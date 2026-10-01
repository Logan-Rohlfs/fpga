"""Capped GUI history and per-channel snapshots (spec 3.5).

Stores hold encoded bytes or JSON strings, so a snapshot is never re-encoded.
"""
import json
from collections import deque

from . import gui_wire

FULL_RES_S = 120.0
DECIMATE = 20
BATCH = 4096

_LINK_LATEST = ('link.STATUS', 'link.LINK_STATS', 'link.CONFIG',
                'link.CHAN_METRICS.A', 'link.CHAN_METRICS.B')
_METRIC_COLUMNS = ('t', 'rssi', 'noise', 'snr', 'df', 'crc_good', 'crc_bad', 'synthetic')
_FLIGHT_CHANNELS = {'flight': 'best', 'flight.A': 'A', 'flight.B': 'B'}


def _clean(x):
    """Deep copy with non-finite floats mapped to None, so the JSON is always valid."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return gui_wire.json_num(x)


def _marker(channel, count):
    return json.dumps({'type': 'history', 'channel': channel, 'count': count}, separators=(',', ':'), allow_nan=False)


class History:
    def __init__(self, flight_cap=36000, event_cap=2000, spectrum_cap=120, metrics_cap=600, frames_cap=200):
        self._flight = {o: deque(maxlen=flight_cap) for o in gui_wire.ORIGINS}
        self._events = deque(maxlen=event_cap)
        self._spectrum = {c: deque(maxlen=spectrum_cap) for c in ('A', 'B')}
        self._latest = {}
        self._metrics = {c: deque(maxlen=metrics_cap) for c in ('A', 'B')}
        self._power_unit = {}
        self._frames = deque(maxlen=frames_cap)

    def add_flight(self, origin, t, row_bytes):
        self._flight[origin].append((t, row_bytes))

    def add_event(self, event):
        self._events.append(_clean(event))

    def add_spectrum(self, channel, row_bytes):
        self._spectrum[channel].append(row_bytes)

    def set_latest(self, key, json_str):
        self._latest[key] = json_str

    def add_metrics(self, channel, t, rssi, noise, snr, df, crc_good, crc_bad, power_unit, synthetic=False):
        self._metrics[channel].append(tuple(gui_wire.json_num(v) for v in (t, rssi, noise, snr, df, crc_good, crc_bad))
                                      + (bool(synthetic),))
        self._power_unit[channel] = power_unit

    def add_frame(self, json_str):
        self._frames.append(json_str)

    def snapshot(self, channel, now):
        if channel in _FLIGHT_CHANNELS:
            return self._flight_snapshot(channel, _FLIGHT_CHANNELS[channel], now)
        if channel == 'events':
            return [json.dumps({'type': 'events', 'items': list(self._events), 'reset': True},
                               separators=(',', ':'), allow_nan=False)]
        kind, _, sub = channel.partition('.')
        if kind == 'spectrum' and sub in self._spectrum:
            rows = list(self._spectrum[sub])
            return [_marker(channel, len(rows))] + rows
        if kind == 'iq' and sub in ('A', 'B'):
            latest = self._latest.get(channel)
            return [] if latest is None else [latest]
        if channel == 'link':
            return self._link_snapshot()
        if channel == 'frames':
            frames = list(self._frames)
            return [_marker(channel, len(frames))] + frames
        raise KeyError(channel)

    def _flight_snapshot(self, channel, origin, now):
        cutoff = now - FULL_RES_S
        rows = self._flight[origin]
        older = [r for t, r in rows if t < cutoff]
        chosen = older[::DECIMATE] + [r for t, r in rows if t >= cutoff]
        out = [_marker(channel, len(chosen))]
        for i in range(0, len(chosen), BATCH):
            out.append(gui_wire.pack_flight(origin, chosen[i:i + BATCH]))
        return out

    def _link_snapshot(self):
        out = [self._latest[k] for k in _LINK_LATEST if k in self._latest]
        for ch in ('A', 'B'):
            if not self._metrics[ch]:
                continue
            cols = list(zip(*self._metrics[ch]))
            msg = {'type': 'metrics_history', 'channel': ch}
            msg.update({name: list(col) for name, col in zip(_METRIC_COLUMNS, cols)})
            msg['power_unit'] = self._power_unit.get(ch)
            out.append(json.dumps(msg, separators=(',', ':'), allow_nan=False))
        return out
