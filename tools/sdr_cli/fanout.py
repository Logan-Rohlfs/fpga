"""Per-client outbox: subscriptions, slots and role rate budgets (no aiohttp).

Stream overflow: when more than STREAM_MAX live items are queued, the whole
stream queue is cleared and every channel that had queued items is marked for
resync (``take_resync``). Discarding only one channel would leave the queue
near the cap, so it would re-overflow at once. Snapshot items do not count
toward the cap.

Order of delivery from ``Outbox.next()``: control messages (including control
slots), then the stream queue, then any slot that is due.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

CHANNELS = ('flight', 'flight.A', 'flight.B', 'events', 'link', 'frames',
            'spectrum.A', 'spectrum.B', 'iq.A', 'iq.B')

_STREAM_FULL = {'flight': 0, 'flight.A': 0, 'flight.B': 0, 'events': 0}
ROLE_BUDGETS = {
    'admin': dict(_STREAM_FULL, **{
        'spectrum.A': 0, 'spectrum.B': 0, 'iq.A': 0, 'iq.B': 0,
        'link': 0, 'frames': 0, 'stats': 0.5}),
    'viewer': dict(_STREAM_FULL, **{
        'spectrum.A': 0.2, 'spectrum.B': 0.2, 'iq.A': 0.5, 'iq.B': 0.5,
        'link': 0.2, 'frames': 0.1, 'stats': 0.5}),
}
STREAM_MAX = {'admin': 2000, 'viewer': 600}
CONTROL_MAX = 400


@dataclass(frozen=True)
class Outgoing:
    channel: str   # '' for control, 'stats' for stats
    mode: str      # 'stream', 'slot' or 'control'
    key: str
    data: object   # str or bytes


class _Box:
    """A control slot entry; replaced in place by later values."""
    __slots__ = ('data',)

    def __init__(self, data):
        self.data = data


class Outbox:
    def __init__(self, role: str = 'viewer',
                 clock: Callable[[], float] = time.monotonic):
        if role not in ROLE_BUDGETS:
            raise ValueError('unknown role: %s' % role)
        self._role = role
        self._clock = clock
        self._subscribed: frozenset = frozenset()
        self._control: Deque[object] = deque()
        self._control_slots: Dict[str, _Box] = {}
        self._stream: Deque[Tuple[str, object, bool]] = deque()
        self._live = 0  # queued live (non-snapshot) stream items
        self._slots: Dict[str, list] = {}  # key -> [data, channel]
        self._last_sent: Dict[str, float] = {}
        self._last_frames_sent: Optional[float] = None
        self._resync: Set[str] = set()
        self._dropped: Dict[str, int] = {}
        self.overflowed = False
        self.on_ready: Optional[Callable[[], None]] = None

    # -- configuration ---------------------------------------------------
    def set_role(self, role: str) -> None:
        if role not in ROLE_BUDGETS:
            raise ValueError('unknown role: %s' % role)
        self._role = role

    @property
    def subscribed(self) -> frozenset:
        return self._subscribed

    def subscribe(self, channels: Iterable[str]) -> set:
        if isinstance(channels, str):
            raise TypeError('channels must be an iterable of names, not str')
        new = set(channels)
        unknown = sorted(new - set(CHANNELS))
        if unknown:
            raise ValueError('unknown channels: %s' % ', '.join(unknown))
        added = new - self._subscribed
        removed = self._subscribed - new
        self._subscribed = frozenset(new)
        if removed:
            self._stream = deque(i for i in self._stream if i[0] not in removed)
            self._live = sum(1 for i in self._stream if not i[2])
            for key in [k for k, v in self._slots.items() if v[1] in removed]:
                del self._slots[key]
            self._resync -= removed
        return added

    # -- producers -------------------------------------------------------
    def _ready(self) -> None:
        if self.on_ready is not None:
            self.on_ready()

    def _interval(self, name: str) -> float:
        return ROLE_BUDGETS[self._role].get(name, 0)

    def offer(self, out: Outgoing) -> None:
        if out.mode == 'control':
            self.control(out.data)
            return
        if out.mode not in ('stream', 'slot'):
            raise ValueError('unknown mode: %s' % out.mode)
        if out.channel != 'stats' and out.channel not in self._subscribed:
            return
        now = self._clock()
        if out.mode == 'stream':
            if out.channel == 'frames':
                gap = self._interval('frames')
                last = self._last_frames_sent
                if gap and last is not None and now < last + gap:
                    self._dropped['frames'] = self._dropped.get('frames', 0) + 1
                    return
                self._last_frames_sent = now
            self._stream.append((out.channel, out.data, False))
            self._live += 1
            if self._live > STREAM_MAX[self._role]:
                self._resync.update(i[0] for i in self._stream)
                self._stream.clear()
                self._live = 0
                self._ready()
                return
        else:
            slot = self._slots.get(out.key)
            if slot is None:
                self._slots[out.key] = [out.data, out.channel]
            else:
                slot[0] = out.data
        self._ready()

    def control(self, data) -> None:
        self._control.append(data)
        if len(self._control) > CONTROL_MAX:
            self.overflowed = True
        self._ready()

    def control_slot(self, key: str, data) -> None:
        box = self._control_slots.get(key)
        if box is not None:
            box.data = data
        else:
            box = _Box(data)
            self._control_slots[key] = box
            self._control.append(box)
        self._ready()

    def put_snapshot(self, channel: str, items: Iterable) -> None:
        """Queue history items in order, bypassing budgets and the stream cap.

        The caller must already have checked the channel subscription.
        """
        n = 0
        for item in items:
            self._stream.append((channel, item, True))
            n += 1
        if n:
            self._ready()

    # -- consumer --------------------------------------------------------
    def next(self) -> Tuple[Optional[object], Optional[float]]:
        if self._control:
            item = self._control.popleft()
            if isinstance(item, _Box):
                for k, b in list(self._control_slots.items()):
                    if b is item:
                        del self._control_slots[k]
                item = item.data
            return item, None
        if self._stream:
            _, data, snap = self._stream.popleft()
            if not snap:
                self._live -= 1
            return data, None
        now = self._clock()
        wait: Optional[float] = None
        due_key = None
        for key, (_, channel) in self._slots.items():
            last = self._last_sent.get(key)
            due = now if last is None else last + self._interval(channel)
            if now >= due:
                due_key = key
                break
            rem = due - now
            if wait is None or rem < wait:
                wait = rem
        if due_key is not None:
            data = self._slots.pop(due_key)[0]
            self._last_sent[due_key] = now
            return data, None
        return None, wait

    def take_resync(self) -> set:
        out, self._resync = self._resync, set()
        return out

    def take_dropped(self) -> dict:
        out, self._dropped = self._dropped, {}
        return out
