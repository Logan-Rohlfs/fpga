"""Decode one byte source and fan the results out to GUI clients (no web imports).

Each decoded record is encoded once into ``fanout.Outgoing`` objects (spec 2.3, 2.5).
History and the subscribers are updated in the same synchronous step, so a snapshot
taken between two ``feed`` calls never misses or repeats a live row.
"""
import asyncio
from collections import deque
import json
import logging
import time

from . import gui_wire
from . import protocol as p
from .core import ToolError
from .display import WaterfallScale
from .events import EventDeriver
from .fanout import Outgoing
from .history import History
from .receiver_control import profile_for
from .protocol import CHANNELS, LinkState, StreamDecoder, bin_frequency, format_record, power_db

logger = logging.getLogger(__name__)

_LINK_TYPES = (p.STATUS, p.LINK_STATS, p.CONFIG)
_INT16 = (-32768, 32767)


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return gui_wire.json_num(x)


def dumps(msg):
    """Compact JSON with non-finite floats as null, so browsers can always parse it."""
    try:
        return json.dumps(msg, separators=(',', ':'), allow_nan=False)
    except ValueError:
        return json.dumps(_clean(msg), separators=(',', ':'), allow_nan=False)


def _flight_fields(frame):
    """Decoded APEX FLIGHT fields when the frame CRC and length are valid, else None."""
    if not frame or frame.get('kind') != 'FLIGHT' or not frame.get('crc_ok'):
        return None
    fields = frame.get('fields') or {}
    return fields if 'phase' in fields else None   # a wrong length decodes to {body_len}


class Hub:
    RATE_WINDOW_S = 5.0

    def __init__(self, clock=time.monotonic, wall=time.time):
        self.clock = clock
        self.wall = wall
        self.decoder = StreamDecoder()
        self.link = LinkState()
        self.history = History()
        self.events = EventDeriver()
        self.scales = {ch: WaterfallScale() for ch in CHANNELS}
        self.subscribers = []
        self.arrivals = deque()
        self.active_source = None
        self.on_event = None        # optional callable(event dict), called for each derived event
        self.client_counts = None   # optional callable returning {operators, viewers}
        self.last_error = None      # why the last run() ended 'down', for the source supervisor
        self.source = dict(kind='none', state='starting', detail='', responds_to_tuning=False)

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: self.subscribers.remove(fn)

    def publish(self, out):
        for fn in list(self.subscribers):
            try:
                fn(out)
            except Exception:
                logger.exception('GUI subscriber failed')

    # ---- records
    def feed(self, data, source=None):
        self.arrivals.append((self.clock(), len(data)))
        records = self.decoder.feed(data)
        for record in records:
            record.t = self.wall()
        self.link.update(records)
        published = []
        for record in records:
            if source is not None and hasattr(source, 'observe'):
                source.observe(record)
                self.source.update(source.source_state())
            outs = self._record(record, source) + self._events(self.events.feed(record))
            for out in outs:
                self.publish(out)
            published += outs
        return published

    def tick(self, now_wall):
        """Signal-loss events for channels that went quiet."""
        outs = self._events(self.events.tick(now_wall))
        for out in outs:
            self.publish(out)
        return outs

    def snapshot(self, channel):
        return self.history.snapshot(channel, self.wall())

    def _record(self, r, source):
        f = r.fields
        if r.type == p.STATUS:
            self.source['profile'] = profile_for(f['build_id'])
        if r.type == p.SPECTRUM:
            return [self._spectrum(r, source)] if f.get('channel') in CHANNELS else []
        if r.type in (p.BEST_TELEM, p.CHAN_FRAME):
            return self._frame(r)
        text = dumps(dict(type='record', record=r.as_json(), text=format_record(r)))
        if r.type in _LINK_TYPES:
            key = 'link.' + r.name
        elif r.type == p.CHAN_METRICS and f.get('channel') in CHANNELS:
            key = 'link.CHAN_METRICS.' + f['channel']
            self.history.add_metrics(f['channel'], r.t, f.get('rssi_dbm'), f.get('noise_dbm'), f.get('snr_db'),
                                     f.get('freq_offset_hz'), f.get('crc_good'), f.get('crc_bad'),
                                     f.get('power_unit'))
        elif r.type == p.IQ_SNAPSHOT and f.get('channel') in CHANNELS:
            key = 'iq.' + f['channel']
            self.history.set_latest(key, text)
            return [Outgoing(key, 'slot', key, text)]
        else:
            return []   # unknown message types stay in the decoder stats only
        self.history.set_latest(key, text)
        return [Outgoing('link', 'slot', key, text)]

    def _frame(self, r):
        f = r.fields
        text = dumps(dict(type='record', record=r.as_json(), text=format_record(r)))
        self.history.add_frame(text)
        outs = []
        fields = _flight_fields(f.get('apex'))
        if fields is not None:
            if r.type == p.BEST_TELEM:
                origin, best_from = 'best', gui_wire.BEST_FROM.get(f.get('source'))
            elif f.get('crc_ok') and f.get('channel') in CHANNELS:
                origin, best_from = f['channel'], None
            else:
                origin = None
            if origin is not None:
                row = gui_wire.encode_flight_row(r.t, fields, r.synthetic, best_from)
                self.history.add_flight(origin, r.t, row)
                channel = 'flight' if origin == 'best' else 'flight.' + origin
                outs.append(Outgoing(channel, 'stream', channel, gui_wire.pack_flight(origin, [row])))
        outs.append(Outgoing('frames', 'stream', 'frames', text))
        return outs

    def _spectrum(self, r, source):
        f = r.fields
        db = power_db(f)
        scale = self.scales.setdefault(f['channel'], WaterfallScale())
        scale.update(db)
        if source is not None and source.kind == 'sim':
            from .freqplan import lo_hz
            state = source.get_tuning()
            reference = dict(lo_hz=lo_hz(state), injection=state.injection)
        else:
            reference = self.source.get('applied')
        db10 = [min(max(int(round(v * 10)), _INT16[0]), _INT16[1]) for v in db]
        data = gui_wire.encode_spectrum(f['channel'], f['row'], r.t, bin_frequency(f, 0), f['bin_hz'],
                                        scale.low, scale.high, db10, r.synthetic, reference)
        self.history.add_spectrum(f['channel'], data)
        key = 'spectrum.' + f['channel']
        return Outgoing(key, 'slot', key, data)

    def _events(self, events):
        if not events:
            return []
        for event in events:
            self.history.add_event(event)
            if self.on_event is not None:
                try:
                    self.on_event(event)
                except Exception:
                    logger.exception('GUI event callback failed')
        return [Outgoing('events', 'stream', 'events', dumps(dict(type='events', items=events, reset=False)))]

    # ---- stats and source state
    def byte_rate(self):
        now = self.clock()
        while self.arrivals and self.arrivals[0][0] < now - self.RATE_WINDOW_S:
            self.arrivals.popleft()
        return sum(n for _, n in self.arrivals) / self.RATE_WINDOW_S

    def stats_message(self, clients=None):
        if self.active_source is not None and hasattr(self.active_source, 'source_state'):
            self.source.update(self.active_source.source_state())
        decoder = dict(self.decoder.stats)
        decoder['by_type'] = dict(decoder['by_type'])
        if clients is None and self.client_counts is not None:
            clients = self.client_counts()
        msg = dict(type='stats', decoder=decoder, rates=self.link.rates(self.wall()), byte_rate=self.byte_rate(),
                   source=dict(self.source))
        if clients is not None:
            msg['clients'] = dict(clients)
        return msg

    def stats_outgoing(self, clients=None):
        return Outgoing('stats', 'slot', 'stats', dumps(self.stats_message(clients)))

    def set_source(self, source, state, detail='', retry_in_s=None):
        """Record the source state; ``source`` None means no source could be opened.

        A source with a ``port`` (serial) reports it; ``retry_in_s`` is the delay before the
        supervisor's next open attempt. Events come only from state changes (EventDeriver dedups).
        """
        profile = self.source.get('profile')
        self.active_source = source
        if source is None:
            self.source = dict(kind='none', state=state, detail=detail, responds_to_tuning=False)
        else:
            self.source = dict(kind=source.kind, state=state, detail=detail or source.detail,
                               responds_to_tuning=source.responds_to_tuning)
        if profile is not None:
            self.source['profile'] = profile
        if getattr(source, 'port', None):
            self.source['port'] = source.port
        if retry_in_s is not None:
            self.source['retry_in_s'] = retry_in_s
        if source is not None and hasattr(source, 'source_state'):
            self.source.update(source.source_state())
        self.publish(self.stats_outgoing())
        for out in self._events(self.events.source_state(state, self.source['detail'], self.wall())):
            self.publish(out)

    async def run(self, source):
        """Consume a source until it ends or fails. Link state survives; the decoder restarts."""
        self.decoder = StreamDecoder()
        self.last_error = None
        self.set_source(source, 'running')
        try:
            async for data in source.chunks():
                self.feed(data, source)
        except asyncio.CancelledError:
            self.set_source(source, 'stopped')
            raise
        except (ToolError, OSError) as exc:
            self.last_error = exc
            self.set_source(source, 'down', str(exc))
            return
        except Exception as exc:
            logger.exception('GUI source failed')
            self.last_error = exc
            self.set_source(source, 'down', str(exc))
            return
        self.set_source(source, 'ended')
