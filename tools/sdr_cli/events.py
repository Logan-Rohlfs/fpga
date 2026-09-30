"""Server-side derived flight and link events (spec section 10). Toolkit-free.

The link thresholds are display heuristics, not measurements of the radio link.
"""
from collections import deque

from . import protocol as p

LOSS_S = 0.25          # silence on a channel after a good frame before signal_loss
CRC_BURST_N = 3        # CRC-bad frames within CRC_BURST_S make a burst
CRC_BURST_S = 1.0
SWITCH_HOLD = 5        # consecutive BEST frames from a new source before source_switch

FLIGHT_KINDS = ('launch', 'burnout', 'apogee', 'landing')
ALL_KINDS = ('phase', 'launch', 'burnout', 'apogee', 'max_velocity', 'landing', 'flight_reset',
             'signal_loss', 'reacquire', 'crc_burst', 'source_switch', 'source_state')

RESET_TEXT = 'New flight segment (replay loop or flight-computer restart)'
_PRE_LAUNCH = ('IDLE', 'ARMED')
_IN_FLIGHT = ('BOOST', 'COAST', 'DESCENT', 'LANDED')


def _letter(index):
    return 'AB'[index] if index in (0, 1) else None


class EventDeriver:
    def __init__(self):
        self._next_id = 1
        self.segment = 0
        self._synthetic = False
        self._reset_segment_state()
        self._phase = None
        self._good = {}          # channel letter -> (last good t, synthetic)
        self._lost = {}          # channel letter -> (loss t, synthetic) while lost
        self._bad = {}           # channel letter -> deque of CRC-bad times
        self._in_burst = {}
        self._reported = None    # last reported BEST source
        self._candidate = None
        self._count = 0
        self._state = None

    def _reset_segment_state(self):
        self._max_alt = None
        self._max_alt_t = 0.0
        self._max_vel = None
        self._apogee_done = False

    def _event(self, t, kind, text, synthetic, channel=None, value=None, quantity=None):
        ev = dict(id=self._next_id, t=t, kind=kind, text=text, channel=channel, value=value,
                  quantity=quantity, segment=self.segment, synthetic=bool(synthetic))
        self._next_id += 1
        return ev

    # -- public API -------------------------------------------------------------------------

    def feed(self, record):
        self._synthetic = record.synthetic
        out = self._check_loss(record.t)
        if record.type == p.BEST_TELEM:
            out += self._best(record)
        elif record.type == p.CHAN_FRAME:
            out += self._chan(record)
        return out

    def tick(self, now):
        return self._check_loss(now)

    def source_state(self, state, detail, now):
        if state == self._state:
            return []
        self._state = state
        text = '{} ({})'.format(state, detail) if detail else str(state)
        return [self._event(now, 'source_state', 'Source ' + text, self._synthetic)]

    # -- link rules -------------------------------------------------------------------------

    def _check_loss(self, now):
        out = []
        for ch in sorted(self._good):
            last, synth = self._good[ch]
            if ch not in self._lost and now - last > LOSS_S:
                self._lost[ch] = (last, synth)
                out.append(self._event(now, 'signal_loss', 'Signal lost on {}'.format(ch), synth, channel=ch))
        return out

    def _chan(self, record):
        ch = _letter(record.fields.get('channel'))
        if ch is None:
            return []
        t, synth = record.t, record.synthetic
        out = []
        if record.fields.get('crc_ok'):
            if ch in self._lost:
                gap = t - self._lost.pop(ch)[0]
                out.append(self._event(t, 'reacquire', 'Signal reacquired on {} after {:.2f} s'.format(ch, gap),
                                       synth, channel=ch, value=gap))
            self._good[ch] = (t, synth)
            return out
        times = self._bad.setdefault(ch, deque())
        while times and t - times[0] > CRC_BURST_S:
            times.popleft()
        if not times:
            self._in_burst[ch] = False
        times.append(t)
        if len(times) >= CRC_BURST_N and not self._in_burst.get(ch):
            self._in_burst[ch] = True
            out.append(self._event(t, 'crc_burst', 'CRC errors on {} ({} in {:g} s)'.format(
                ch, len(times), CRC_BURST_S), synth, channel=ch))
        return out

    # -- BEST_TELEM: source switch and flight rules ----------------------------------------

    def _best(self, record):
        out = self._switch(record)
        frame = record.fields.get('apex') or {}
        fields = frame.get('fields') or {}
        if frame.get('kind') == 'FLIGHT' and frame.get('crc_ok') and 'phase' in fields:
            out += self._flight(record, fields)
        return out

    def _switch(self, record):
        src = record.fields.get('source')
        if self._reported is None:
            self._reported = src
            return []
        if src == self._reported:
            self._candidate, self._count = None, 0
            return []
        if src == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = src, 1
        if self._count < SWITCH_HOLD:
            return []
        self._reported, self._candidate, self._count = src, None, 0
        ch = _letter(src)
        return [self._event(record.t, 'source_switch', 'Best source switched to {}'.format(
            ch or 'source {}'.format(src)), record.synthetic, channel=ch)]

    def _flight(self, record, f):
        t, synth = record.t, record.synthetic
        new, old = f['phase'], self._phase
        self._phase = new
        out = []
        reset = old in _IN_FLIGHT and new in _PRE_LAUNCH
        if reset:
            self.segment += 1
            self._reset_segment_state()
        alt, vel = f.get('alt_agl_m'), f.get('velocity_mps')
        if alt is not None and (self._max_alt is None or alt > self._max_alt):
            self._max_alt, self._max_alt_t = alt, t
        if vel is not None and (self._max_vel is None or vel > self._max_vel):
            self._max_vel = vel
        if old is None or new == old:
            return out
        ev = lambda *a, **k: self._event(t, *a, synthetic=synth, **k)
        out.append(ev('phase', '{} → {}'.format(old, new)))
        if new == 'BOOST' and old in _PRE_LAUNCH:
            out.append(ev('launch', 'Launch detected'))
        if old == 'BOOST' and new == 'COAST':
            out.append(ev('burnout', 'Motor burnout'))
        if old == 'COAST' and not self._apogee_done:
            self._apogee_done = True
            out.append(self._event(self._max_alt_t, 'apogee', 'Apogee {:.1f} m'.format(self._max_alt), synth,
                                   value=self._max_alt, quantity='length'))
            out.append(ev('max_velocity', 'Max velocity {:.1f} m/s'.format(self._max_vel),
                          value=self._max_vel, quantity='speed'))
        if new == 'LANDED':
            out.append(ev('landing', 'Landing detected'))
        if reset:
            out.append(ev('flight_reset', RESET_TEXT))
        return out
