# tools/sdr_cli/sources.py
"""Byte sources for the GUI hub: live UART, a recorded capture, or a host-side simulator.

Every source yields raw link bytes, so all of them go through the one StreamDecoder
in hub.py. Serial tuning is enabled only after a receiver CONFIG capability report.
"""
import asyncio
import errno
import math
from pathlib import Path
import random
import time

from . import apex, freqplan, protocol as p
from .core import ToolError

LINK_BYTES_PER_S = 100000   # 1 Mbaud, 8N1

_MISSING_ERRNOS = (errno.ENOENT, errno.ENXIO)
# EAGAIN: pyserial's exclusive flock fails this way when another ./sdr process holds the port.
_BUSY_ERRNOS = (errno.EBUSY, errno.EACCES, errno.EPERM, errno.EAGAIN)
# pyserial on Windows reports these as message text only, without an errno. serial_io's
# 'auto' port resolution reports an absent board as "Cannot select a unique Basys 3 UART".
_MISSING_TEXT = ('No such file', 'cannot find the file', 'Cannot select a unique')
_BUSY_TEXT = ('Resource busy', 'Access is denied', 'Could not exclusively lock')


class Backoff:
    """Serial retry delays (spec 18): 0.5, 1, 2, 4, 8 s, then every 8 s until reset()."""

    def __init__(self, initial=0.5, maximum=8.0):
        self.initial, self.maximum = initial, maximum
        self._delay = initial

    def next(self):
        delay = self._delay
        self._delay = min(self._delay * 2, self.maximum)
        return delay

    def reset(self):
        self._delay = self.initial


def classify_open_error(exc):
    """'missing', 'busy' or 'other' for a failed port open, from the errno or text of exc and its causes."""
    chain = []
    while exc is not None and exc not in chain:
        chain.append(exc)
        exc = exc.__cause__
    for item in chain:
        code = getattr(item, 'errno', None)
        if code in _MISSING_ERRNOS:
            return 'missing'
        if code in _BUSY_ERRNOS:
            return 'busy'
    text = ' '.join(str(item) for item in chain)
    if any(t in text for t in _MISSING_TEXT):
        return 'missing'
    if any(t in text for t in _BUSY_TEXT):
        return 'busy'
    return 'other'


class SerialSource:
    kind = 'serial'
    responds_to_tuning = False

    def __init__(self, config, session_factory=None, get_tuning=None):
        if session_factory is None:
            from .serial_io import Session as session_factory
        self.session = session_factory(config)
        from .receiver_control import TuningController
        self.control = TuningController(get_tuning, self.session.send, time.monotonic) if get_tuning else None

    def observe(self, record):
        if self.control:
            self.control.observe(record)
            self.responds_to_tuning = self.control.capable

    def source_state(self):
        return self.control.snapshot() if self.control else {}

    @property
    def port(self):
        return self.session.port or self.session.config['port']

    @property
    def detail(self):
        return '{} @ {} baud'.format(self.port, self.session.config['baud'])

    def open(self):
        """Open the port now (raises ToolError); chunks() then reuses the open session."""
        self.session.connect()

    def close(self):
        self.session.close()

    async def chunks(self):
        self.session.connect()
        try:
            while True:
                if self.control:
                    self.control.tick()
                data = self.session.read()   # non-blocking: the port opens with timeout=0
                if data:
                    yield data
                else:
                    await asyncio.sleep(0.01)
        finally:
            self.session.close()


class ReplaySource:
    kind = 'replay'
    responds_to_tuning = False

    def __init__(self, path, speed=1.0, loop=False, chunk=512):
        self.path = Path(path).expanduser()
        if not self.path.is_file():
            raise ToolError('Replay file not found: {}'.format(path))
        if loop and self.path.stat().st_size == 0:
            raise ToolError('Cannot loop an empty replay file.')
        if not math.isfinite(speed) or speed < 0:
            raise ToolError('Replay speed must be 0 (as fast as possible) or positive.')
        self.speed, self.loop, self.chunk = speed, loop, chunk
        self.detail = self.path.name + (' (looping)' if loop else '')

    async def chunks(self):
        data = self.path.read_bytes()
        if not data:
            return
        while True:
            for offset in range(0, len(data), self.chunk):
                part = data[offset:offset + self.chunk]
                yield part
                await asyncio.sleep(len(part) / (LINK_BYTES_PER_S * self.speed) if self.speed else 0)
            if not self.loop:
                return


BENCH_OFFSET_HZ = 10.4e3          # TX crystal offset seen on the bench (module map)
TICK_S = 0.05
SPEC_BINS, SPEC_BIN_HZ = 256, 390.625
DB_REF, DB_STEP = -120.0, 0.5
FSK_DEVIATION_HZ = 25e3
CHANNEL_MODEL = {
    0: dict(peak_db=-50.0, noise_db=-105.0, rssi_offset=0.0, fail_every=11, radius=26000),
    1: dict(peak_db=-56.0, noise_db=-104.0, rssi_offset=-6.0, fail_every=7, radius=13000),
}


def _i16(v):
    return max(-32767, min(32767, int(round(v))))


class SimSource:
    """Host-side stand-in producer whose spectrum and metrics follow the tuning state.

    A toy model for developing the Tune page without hardware: 2-GFSK lobes at
    ±25 kHz around the carrier IF; "lock" needs the signal inside the XADC window
    and the lobes mostly inside the channel filter. Rates match rtl/link_test_sources.sv.
    Everything is flagged SYNTHETIC.
    """
    kind = 'sim'
    responds_to_tuning = True
    detail = 'host simulator'

    def __init__(self, get_tuning, seed=None):
        self.get_tuning = get_tuning
        self.rng = random.Random(seed)
        self.tick = 0
        self.seq = 0
        self.apex_seq = 0
        self.frames = {0: 0, 1: 0}
        self.good = {0: 0, 1: 0}
        self.bad = {0: 0, 1: 0}
        self.rows = {0: 0, 1: 0}
        self.link = dict(from_a=0, from_b=0, both_ok=0, neither_ok=0, best_sent=0)

    def _msg(self, mtype, fields):
        data = p.encode_message(mtype, p.build_payload(mtype, fields), seq=self.seq)
        self.seq = (self.seq + 1) & 0xFF
        return data

    def channel(self):
        """(state, signal IF, offset from NCO, locked) for the current tuning."""
        s = self.get_tuning()
        sig = freqplan.if_hz(s, s.carrier_hz + BENCH_OFFSET_HZ)
        df = sig - s.nco_hz
        if not (-2**31 <= df <= 2**31 - 1 and 0 < s.target_if_hz <= 2**31 - 1):
            raise ToolError('Simulator IF or offset exceeds the signed 32-bit wire format. '
                            'Adjust tuning, then reconnect the source.')
        locked = abs(sig - s.target_if_hz) <= s.window_hz and abs(df) <= max(0.0, s.filter_hz - 17e3)
        return s, sig, df, locked

    def step(self):
        """Bytes for one 50 ms tick."""
        t_us = int(round(self.tick * TICK_S * 1e6)) & 0xFFFFFFFF
        s, sig, df, locked = self.channel()
        out, ok = [], {0: False, 1: False}
        self.apex_seq = (self.apex_seq + 1) & 0xFF
        if locked:
            for ch in (0, 1):
                model = CHANNEL_MODEL[ch]
                self.frames[ch] += 1
                ok[ch] = self.frames[ch] % model['fail_every'] != 0
                if ok[ch]:
                    self.good[ch] += 1
                else:
                    self.bad[ch] += 1
                rssi = -78.0 + model['rssi_offset'] + self.rng.gauss(0, 0.8)
                out.append(self._msg(p.CHAN_FRAME, dict(
                    channel=ch, crc_ok=int(ok[ch]), t_us=t_us, rssi_dbm_x10=int(round(rssi * 10)),
                    quality=200 if ok[ch] else 90, freq_offset_hz=int(round(df)),
                    raw=apex.build_test_frame(self.apex_seq, ok[ch]))))
        if ok[0] or ok[1]:
            out.append(self._msg(p.BEST_TELEM, dict(t_us=t_us, source=0 if ok[0] else 1,
                                                    raw=apex.build_test_frame(self.apex_seq))))
            self.link['best_sent'] += 1
        if ok[0]:
            self.link['from_a'] += 1
        elif ok[1]:
            self.link['from_b'] += 1
        else:
            self.link['neither_ok'] += 1
        if ok[0] and ok[1]:
            self.link['both_ok'] += 1
        if self.tick % 2 == 0:
            for ch in (0, 1):
                out.append(self._metrics(ch, df, locked))
                out.append(self._spectrum(ch, t_us, s, sig))
        if self.tick % 4 == 0:
            for ch in (0, 1):
                out.append(self._iq(ch, t_us, locked))
        if self.tick % 20 == 0:
            out.append(self._msg(p.STATUS, dict(version=p.PROTOCOL_VERSION, channels=3,
                                                uptime_ms=int(self.tick * TICK_S * 1000), build_id=0, dropped=0)))
            out.append(self._msg(p.LINK_STATS, dict(self.link)))
        self.tick += 1
        return b''.join(out)

    def _metrics(self, ch, df, locked):
        model = CHANNEL_MODEL[ch]
        noise = -112.0 + self.rng.gauss(0, 0.4)
        rssi = (-78.0 + model['rssi_offset'] if locked else -112.0) + self.rng.gauss(0, 0.6)
        return self._msg(p.CHAN_METRICS, dict(
            channel=ch, rssi_dbm_x10=int(round(rssi * 10)), noise_dbm_x10=int(round(noise * 10)),
            snr_db_x10=int(round((rssi - noise) * 10)), freq_offset_hz=int(round(df)),
            sync_hits=self.frames[ch], crc_good=self.good[ch], crc_bad=self.bad[ch]))

    def _spectrum(self, ch, t_us, s, sig, present=True):
        model = CHANNEL_MODEL[ch]
        center = int(round(s.target_if_hz))
        peak = 10 ** (model['peak_db'] / 10) if present else 0.0
        power = []
        for k in range(SPEC_BINS):
            f = center + (k - SPEC_BINS // 2) * SPEC_BIN_HZ
            linear = 10 ** ((model['noise_db'] + self.rng.gauss(0, 2.2)) / 10)
            for deviation in (-FSK_DEVIATION_HZ, FSK_DEVIATION_HZ):
                linear += peak * math.exp(-0.5 * ((f - sig - deviation) / 1.6e3) ** 2)
            db = 10 * math.log10(linear)
            power.append(max(0, min(255, int(round((db - DB_REF) / DB_STEP)))))
        row = self.rows[ch]
        self.rows[ch] = (row + 1) & 0xFFFF
        return self._msg(p.SPECTRUM, dict(
            channel=ch, averages=1, row=row, t_us=t_us, center_hz=center, bin_mhz=int(SPEC_BIN_HZ * 1000),
            db_ref_x10=int(DB_REF * 10), db_step_x100=int(DB_STEP * 100), power=power))

    def _iq(self, ch, t_us, locked):
        radius = CHANNEL_MODEL[ch]['radius'] if locked else 2000
        pairs = []
        for _ in range(64):
            angle = self.rng.uniform(0, 2 * math.pi)
            pairs.append((_i16(radius * math.cos(angle) + self.rng.gauss(0, 2200)),
                          _i16(radius * math.sin(angle) + self.rng.gauss(0, 2200))))
        return self._msg(p.IQ_SNAPSHOT, dict(channel=ch, t_us=t_us, sample_rate_hz=100000, iq=pairs))

    async def chunks(self):
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            yield self.step()
            await asyncio.sleep(max(0.0, start + self.tick * TICK_S - loop.time()))


# Demo bitstream profile (rtl/receiver_link_sources.sv, DEMO_FLIGHT=1); tools/tests/test_sources.py
# checks these against the RTL constants.
DEMO_ROM = Path(__file__).resolve().parents[2] / 'projects/sdr/rom/apex_flight.mem'
DEMO_GAP_SLOTS = 20
DEMO_LOSS = {'A': (60, 69), 'B': (228, 237)}
DEMO_BUILD_ID = 0x53445246
DEMO_DBFS = dict(A=dict(rssi=-21.0, noise=-58.0), B=dict(rssi=-24.0, noise=-58.0))


class DemoSource(SimSource):
    """Host stand-in for the demo bitstream (./sdr build --demo) when no board is attached.

    Sends the checked-in replay ROM (projects/sdr/rom/apex_flight.mem) as FLIGHT frames on the
    demo schedule: one ROM frame per 50 ms slot, DEMO_GAP_SLOTS silent slots, then the loop, with
    the same per-antenna loss windows as the RTL. STATUS carries the demo BUILD_ID, so the GUI
    uses the apex_demo profile. No receiver runs here: signal, noise, spectrum and I/Q are a
    modelled stand-in in relative dBFS, and every record is flagged SYNTHETIC. Tuning is ignored.
    """
    kind = 'demo'
    responds_to_tuning = False
    detail = 'host demo replay (no FPGA)'

    def __init__(self, get_tuning=None, seed=None, rom_path=DEMO_ROM):
        from .freqplan import TuningState
        super().__init__(lambda: TuningState(), seed=seed)
        self.rom = [apex.with_crc(frame) for frame in apex.read_rom_frames(rom_path)]

    def channel(self):
        s = self.get_tuning()
        return s, s.target_if_hz, 0.0, True

    def _lost(self, ch, slot):
        first, last = DEMO_LOSS[p.CHANNELS[ch]]
        return first <= slot <= last

    def _dbfs_msg(self, mtype, fields):
        data = p.encode_message(mtype, p.build_payload(mtype, fields), seq=self.seq,
                                flags=p.FLAG_SYNTHETIC | p.FLAG_DBFS)
        self.seq = (self.seq + 1) & 0xFF
        return data

    def step(self):
        """Bytes for one 50 ms slot."""
        t_us = int(round(self.tick * TICK_S * 1e6)) & 0xFFFFFFFF
        slot = self.tick % (len(self.rom) + DEMO_GAP_SLOTS)
        s, sig, _, _ = self.channel()
        out, ok = [], {0: False, 1: False}
        if slot < len(self.rom):
            raw = self.rom[slot]
            for ch in (0, 1):
                if self._lost(ch, slot):
                    continue
                ok[ch] = True
                self.frames[ch] += 1
                self.good[ch] += 1
                rssi = DEMO_DBFS[p.CHANNELS[ch]]['rssi'] + self.rng.gauss(0, 0.5)
                out.append(self._dbfs_msg(p.CHAN_FRAME, dict(
                    channel=ch, crc_ok=1, t_us=t_us, rssi_dbm_x10=int(round(rssi * 10)), quality=220 - 20 * ch,
                    freq_offset_hz=0, raw=raw)))
            if ok[0] or ok[1]:
                out.append(self._msg(p.BEST_TELEM, dict(t_us=t_us, source=0 if ok[0] else 1, raw=raw)))
                self.link['best_sent'] += 1
            if ok[0]:
                self.link['from_a'] += 1
            elif ok[1]:
                self.link['from_b'] += 1
            else:
                self.link['neither_ok'] += 1
            if ok[0] and ok[1]:
                self.link['both_ok'] += 1
        if self.tick % 2 == 0:
            for ch in (0, 1):
                present = slot < len(self.rom) and not self._lost(ch, slot)
                model = DEMO_DBFS[p.CHANNELS[ch]]
                noise = model['noise'] + self.rng.gauss(0, 0.4)
                rssi = (model['rssi'] if present else model['noise']) + self.rng.gauss(0, 0.5)
                out.append(self._dbfs_msg(p.CHAN_METRICS, dict(
                    channel=ch, rssi_dbm_x10=int(round(rssi * 10)), noise_dbm_x10=int(round(noise * 10)),
                    snr_db_x10=int(round((rssi - noise) * 10)), freq_offset_hz=0,
                    sync_hits=self.frames[ch], crc_good=self.good[ch], crc_bad=self.bad[ch])))
                out.append(self._spectrum(ch, t_us, s, sig, present))
        if self.tick % 4 == 0:
            for ch in (0, 1):
                out.append(self._iq(ch, t_us, slot < len(self.rom) and not self._lost(ch, slot)))
        if self.tick % 20 == 0:
            out.append(self._msg(p.STATUS, dict(version=p.PROTOCOL_VERSION, channels=3,
                                                uptime_ms=int(self.tick * TICK_S * 1000), build_id=DEMO_BUILD_ID,
                                                dropped=0)))
            out.append(self._msg(p.LINK_STATS, dict(self.link)))
        self.tick += 1
        return b''.join(out)


def from_args(config, kind, file=None, speed=1.0, loop=False):
    """Validate the choice now; return a factory taking get_tuning() and building a fresh source."""
    if kind == 'sim':
        return lambda get_tuning: SimSource(get_tuning)
    if kind == 'demo':
        return lambda get_tuning: DemoSource(get_tuning)
    if kind == 'replay':
        if not file:
            raise ToolError('--source replay needs --file CAPTURE.bin')
        ReplaySource(file, speed=speed, loop=loop)   # raises ToolError early for a bad path/speed
        return lambda get_tuning: ReplaySource(file, speed=speed, loop=loop)
    if kind == 'serial':
        return lambda get_tuning: SerialSource(config, get_tuning=get_tuning)
    raise ToolError('Unknown source {!r}: use serial, replay, sim or demo.'.format(kind))
