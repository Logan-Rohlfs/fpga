"""Decode one byte source and fan the results out to GUI clients (no web imports)."""
import asyncio
from collections import deque
import logging
import time

from .core import ToolError
from .display import WaterfallScale
from .protocol import CHANNELS, SPECTRUM, LinkState, StreamDecoder, bin_frequency, format_record, power_db

logger = logging.getLogger(__name__)


class Hub:
    RATE_WINDOW_S = 5.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.decoder = StreamDecoder()
        self.link = LinkState()
        self.scales = {ch: WaterfallScale() for ch in CHANNELS}
        self.subscribers = []
        self.arrivals = deque()
        self.active_source = None
        self.source = dict(kind='none', state='starting', detail='', responds_to_tuning=False)

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: self.subscribers.remove(fn)

    def publish(self, msg):
        for fn in list(self.subscribers):
            try:
                fn(msg)
            except Exception:
                logger.exception('GUI subscriber failed')

    def feed(self, data, source=None):
        self.arrivals.append((self.clock(), len(data)))
        records = self.decoder.feed(data)
        self.link.update(records)
        messages = []
        for record in records:
            if source is not None and hasattr(source, 'observe'):
                source.observe(record)
                self.source.update(source.source_state())
            msg = self.message(record)
            if msg['type'] == 'spectrum':
                if source is not None and source.kind == 'sim':
                    from .freqplan import lo_hz
                    state = source.get_tuning()
                    msg['rf_reference'] = dict(lo_hz=lo_hz(state), injection=state.injection)
                else:
                    msg['rf_reference'] = self.source.get('applied')
            messages.append(msg)
        for msg in messages:
            self.publish(msg)
        return messages

    def message(self, r):
        if r.type == SPECTRUM:
            f = r.fields
            db = power_db(f)
            scale = self.scales.setdefault(f['channel'], WaterfallScale())
            scale.update(db)
            return dict(type='spectrum', channel=f['channel'], row=f['row'], t_us=f['t_us'],
                        f0_hz=bin_frequency(f, 0), bin_hz=f['bin_hz'], bins=f['bins'],
                        db10=[int(round(v * 10)) for v in db], low=scale.low, high=scale.high,
                        synthetic=r.synthetic)
        return dict(type='record', record=r.as_json(), text=format_record(r))

    def snapshot(self):
        """Latest slow-changing records, so a new viewer is not blank until the next 1 Hz message."""
        records = [self.link.status, self.link.link_stats, *self.link.metrics.values(), *self.link.iq.values()]
        if self.link.best:
            records.append(self.link.best[-1])
        return [self.message(r) for r in records if r is not None]

    def byte_rate(self):
        now = self.clock()
        while self.arrivals and self.arrivals[0][0] < now - self.RATE_WINDOW_S:
            self.arrivals.popleft()
        return sum(n for _, n in self.arrivals) / self.RATE_WINDOW_S

    def stats_message(self):
        if self.active_source is not None and hasattr(self.active_source, 'source_state'):
            self.source.update(self.active_source.source_state())
        decoder = dict(self.decoder.stats)
        decoder['by_type'] = dict(decoder['by_type'])
        return dict(type='stats', decoder=decoder, rates=self.link.rates(), byte_rate=self.byte_rate(),
                    source=dict(self.source))

    def set_source(self, source, state, detail=''):
        self.active_source = source
        self.source = dict(kind=source.kind, state=state, detail=detail or source.detail,
                           responds_to_tuning=source.responds_to_tuning)
        if hasattr(source, 'source_state'):
            self.source.update(source.source_state())
        self.publish(self.stats_message())

    async def run(self, source):
        """Consume a source until it ends or fails. Link state survives; the decoder restarts."""
        self.decoder = StreamDecoder()
        self.set_source(source, 'running')
        try:
            async for data in source.chunks():
                self.feed(data, source)
        except asyncio.CancelledError:
            self.set_source(source, 'stopped')
            raise
        except (ToolError, OSError) as exc:
            self.set_source(source, 'down', str(exc))
            return
        except Exception as exc:
            logger.exception('GUI source failed')
            self.set_source(source, 'down', str(exc))
            return
        self.set_source(source, 'ended')
