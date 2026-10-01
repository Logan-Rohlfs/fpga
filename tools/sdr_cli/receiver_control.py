"""Control contract for the sample-driven development receiver, not a PLL driver."""
import struct
from .protocol import crc16_ccitt

CONFIG = 0x02
SAMPLE_RATE_HZ = 1_000_000
BUILD_ID = 0x53445231
APEX_DEMO_BUILD_ID = 0x53445246

PROFILES = {
    BUILD_ID: {'id': 'default', 'label': 'Default receiver profile (ADC test carrier)'},
    APEX_DEMO_BUILD_ID: {
        'id': 'apex_demo', 'label': 'APEX simulated-flight demo (RocketPy, IREC 2026)',
        'rf_label': '441.480 MHz \u00b7 2GFSK \u00b125 kHz \u00b7 10 kbit/s (APEX RF4463 settings; ADC input simulated)',
        # The data is a RocketPy simulation, never a recorded flight; the GUI badge text comes from here.
        'badge': 'SIM FLIGHT \u00b7 SIMULATED ADC',
        'badge_title': ('RocketPy simulation of the IREC 2026 competition flight (Pecos TX) through the real '
                        'receiver; the ADC input is simulated'),
        'badge_title_host': ('RocketPy simulation of the IREC 2026 competition flight (Pecos TX) replayed by the '
                             'host demo source (no FPGA); signal metrics are modelled'),
        # The demo ROM generator fills these FLIGHT fields in because the simulation log lacks them
        # (projects/sdr/host/apex_flight_rom.py EMULATED; a test keeps the lists in step).
        'emulated_fields': ['phase_status', 'health', 'tilt_deg', 'azimuth_deg'],
        'emulated_note': ('Interlock, health, tilt and azimuth fields are emulated by the demo ROM generator '
                          '(absent from the simulation log).'),
        'replay_note': 'Launch to landing; the descent replays at 10x speed.'},
}


def profile_for(build_id):
    """Profile description for a STATUS build_id; unknown builds are labelled, never guessed."""
    profile = PROFILES.get(build_id)
    if profile is not None:
        return {k: list(v) if isinstance(v, list) else v for k, v in profile.items()}
    return {'id': 'unknown', 'label': 'Unknown build 0x%08X' % build_id}


def command(sequence, carrier_ftw, nco_ftw, enable=True):
    if not 0 <= sequence < 255:
        raise ValueError('command sequence must be 0..254')
    body = b'SR' + struct.pack('<BBIIB', 1, sequence, carrier_ftw, nco_ftw, int(enable))
    return body + struct.pack('<H', crc16_ccitt(body))


def tuning_words(state):
    """Return only settings actually supported by the compiled default profile.

    Out-of-band positive IF disables the test transmitter instead of aliasing a
    fictitious carrier through the ADC. Profile changes require a new bitstream.
    """
    from .freqplan import if_hz
    if state.fs_hz != SAMPLE_RATE_HZ:
        raise ValueError('This receiver profile uses 1 MS/s; sample-rate changes require a new bitstream')
    if state.injection != 'low':
        raise ValueError('This receiver profile uses low-side injection; high-side operation requires a matching bit-polarity profile')
    if state.filter_hz != 35_000:
        raise ValueError('The channel filter is compiled into this bitstream; its GUI value must remain 35 kHz')
    if state.target_if_hz != 100_000 or state.window_hz != 35_000:
        raise ValueError('The displayed IF target/window belong to the compiled profile (100 kHz ±35 kHz)')
    signal_if = if_hz(state, state.carrier_hz)
    enabled = 0 < signal_if < SAMPLE_RATE_HZ / 2
    carrier = round(signal_if / SAMPLE_RATE_HZ * 2**32) % 2**32
    nco = round(state.nco_hz / SAMPLE_RATE_HZ * 2**32) % 2**32
    return carrier, nco, enabled


class TuningController:
    """Bounded stop-and-wait control; writes never establish applied state."""
    TIMEOUT_S = 1.0
    MAX_ATTEMPTS = 3

    def __init__(self, get_tuning, send, clock):
        self.get_tuning, self.send, self.clock = get_tuning, send, clock
        self.capable = False
        self.applied = None
        self.pending = None
        self.last_command = None
        self.last_requested = None
        self.sequence = 0
        self.state = 'detecting'
        self.error = ''

    def snapshot(self):
        return dict(control_state=self.state, control_error=self.error,
                    applied=dict(self.applied) if self.applied else None,
                    responds_to_tuning=self.capable)

    def observe(self, record):
        if record.type != CONFIG:
            return
        f = record.fields
        if f['enable'] not in (0, 1):
            return
        if f['status'] == 0:
            self.capable = True
        words = (f['carrier_ftw'], f['nco_ftw'], bool(f['enable']))
        pending = self.pending
        if pending and f['command_seq'] == pending['seq']:
            if f['status'] != 0:
                self.pending = None
                self.state, self.error = 'rejected', 'Receiver rejected tuning'
            elif words == pending['words']:
                self.applied = dict(pending['reference'], carrier_ftw=words[0], nco_ftw=words[1],
                                    enabled=words[2], inferred=False, confirmed_by='ack')
                self.pending = None
                self.state, self.error = 'applied', ''
        elif f['command_seq'] == 255 and f['status'] == 0:
            # A report establishes acquisition settings independently of command
            # success. It must never masquerade as the missing matching ACK.
            last = self.last_command
            previous_words = ((self.applied['carrier_ftw'], self.applied['nco_ftw'], self.applied['enabled'])
                              if self.applied else (last['words'] if last else None))
            if pending and words != pending['words']:
                # An in-flight command may apply after this older report.
                self.applied = None
                return
            if last and words == last['words']:
                reference = dict(last['reference'], inferred=False)
            else:
                nominal = self.get_tuning().carrier_hz
                reference = dict(lo_hz=nominal-words[0]*SAMPLE_RATE_HZ/2**32,
                                 injection='low', inferred=True)
            self.applied = dict(reference, carrier_ftw=words[0], nco_ftw=words[1],
                                enabled=words[2], confirmed_by='report')
            if not pending:
                if previous_words is not None and words != previous_words:
                    # A reboot or another controller changed acquisition settings.
                    # Restore the desired profile once; identical periodic reports
                    # must not restart commands or defeat bounded retry behavior.
                    self.state, self.error = 'out_of_sync', 'Receiver settings changed; restoring requested tuning'
                    self.last_requested = None
                elif self.state == 'detecting':
                    self.state = 'reported'
                elif self.state == 'timeout':
                    self.error = 'Command acknowledgement missing; acquisition settings established by a later receiver report'

    def tick(self):
        if not self.capable:
            return
        from .freqplan import lo_hz
        state = self.get_tuning()
        try:
            words = tuning_words(state)
        except ValueError as exc:
            self.state, self.error = 'unsupported', str(exc)
            return
        requested = (words, lo_hz(state), state.injection)
        now = self.clock()
        if self.pending:
            if now-self.pending['sent_at'] < self.TIMEOUT_S:
                return
            if self.pending['attempts'] >= self.MAX_ATTEMPTS:
                self.pending = None
                self.applied = None
                self.state, self.error = 'timeout', 'No matching receiver acknowledgement; application unknown and RF reference unavailable'
                return
            self.send(self.pending['wire'])
            self.pending['attempts'] += 1
            self.pending['sent_at'] = now
            return
        if requested == self.last_requested:
            return
        seq = self.sequence
        self.sequence = (seq+1) % 255
        wire = command(seq, *words)
        self.send(wire)
        self.pending = dict(seq=seq, words=words, wire=wire, attempts=1, sent_at=now,
                            reference=dict(lo_hz=lo_hz(state), injection=state.injection))
        self.last_command = self.pending
        self.applied = None  # A lost ACK can hide the moment new samples start.
        self.last_requested = requested
        self.state, self.error = 'pending', ''
