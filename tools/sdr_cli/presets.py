"""GUI preset validation and storage (spec section 6). Toolkit-free.

Builtin presets ship in tools/sdr_cli/presets/ (read-only). Local presets live in a writable
directory, one JSON file per preset, and the live/default/auto_switch state in a small state file.
TriggerEngine acts on the live preset's triggers when auto-switch is on.
"""
import json
import os
from pathlib import Path
import re

from . import apex, units
from .events import FLIGHT_KINDS

CARD_TYPES = ('plot', 'number', 'state', 'events', 'map', 'trajectory3d', 'camera', 'waterfall',
              'spectrum', 'constellation', 'link', 'health', 'gps', 'frames')
BUILTIN_DIR = Path(__file__).resolve().parent / 'presets'
FALLBACK = 'flight'
COLS = 12
MAX_CARDS = 40
MAX_TRIGGERS = 20
MAX_BYTES = 64 * 1024
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
CARD_ID_RE = re.compile(r'^[a-z0-9-]{1,24}$')


class PresetError(ValueError):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code
        self.text = text


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value, low, high):
    return isinstance(value, str) and low <= len(value) <= high and value.isprintable()


def _card(card, index):
    where = 'Card {}'.format(index + 1)
    if not isinstance(card, dict):
        raise PresetError('preset_bad_card', '{} must be an object.'.format(where))
    cid = card.get('id')
    if not isinstance(cid, str) or not CARD_ID_RE.match(cid):
        raise PresetError('preset_bad_card', '{} has an invalid id (a-z, 0-9, "-", up to 24).'.format(where))
    where = 'Card "{}"'.format(cid)
    if card.get('type') not in CARD_TYPES:
        raise PresetError('preset_bad_card', '{} has an unknown type {!r}.'.format(where, card.get('type')))
    x, y, w, h = (card.get(k) for k in 'xywh')
    if not all(_int(v) for v in (x, y, w, h)):
        raise PresetError('preset_bad_card', '{} needs integer x, y, w and h.'.format(where))
    if not (x >= 0 and w >= 1 and x + w <= COLS):
        raise PresetError('preset_bad_card', '{} must fit inside the {} columns.'.format(where, COLS))
    if not 0 <= y <= 500:
        raise PresetError('preset_bad_card', '{} y must be 0-500.'.format(where))
    if not 1 <= h <= 24:
        raise PresetError('preset_bad_card', '{} h must be 1-24.'.format(where))
    title = card.get('title')
    if title is not None and not _text(title, 1, 40):
        raise PresetError('preset_bad_card', '{} title must be null or 1-40 printable characters.'.format(where))
    config = card.get('config', {})
    if not isinstance(config, dict):
        raise PresetError('preset_bad_card', '{} config must be an object.'.format(where))
    if card['type'] == 'camera':
        url = config.get('url')
        if url is not None and not (isinstance(url, str) and len(url) <= 500
                                    and re.match(r'^https?://', url, re.IGNORECASE)):
            raise PresetError('preset_bad_url', '{} camera url must be null or an http(s) URL of up to '
                                                '500 characters.'.format(where))
    card_units = config.get('units')
    if card_units is not None:
        if not isinstance(card_units, dict) or not all(
                isinstance(q, str) and isinstance(u, str) and units.is_unit(q, u) for q, u in card_units.items()):
            raise PresetError('preset_bad_unit', '{} has an unknown unit.'.format(where))
    return dict(id=cid, type=card['type'], x=x, y=y, w=w, h=h, title=title, config=config)


def _trigger(trigger):
    if not isinstance(trigger, dict):
        raise PresetError('preset_bad_trigger', 'A trigger must be an object.')
    on, value, target = trigger.get('on'), trigger.get('value'), trigger.get('preset')
    if on == 'phase':
        allowed = apex.PHASES
    elif on == 'event':
        allowed = FLIGHT_KINDS
    else:
        raise PresetError('preset_bad_trigger', 'A trigger "on" must be "phase" or "event".')
    if value not in allowed:
        raise PresetError('preset_bad_trigger', 'Trigger {} value must be one of: {}.'.format(on, ', '.join(allowed)))
    if not isinstance(target, str) or not ID_RE.match(target):
        raise PresetError('preset_bad_trigger', 'A trigger target must be a preset id.')
    return dict(on=on, value=value, preset=target)


def validate(obj):
    """Return a normalized copy (no revision: the store assigns it) or raise PresetError."""
    if not isinstance(obj, dict):
        raise PresetError('preset_bad_schema', 'A preset must be a JSON object.')
    try:
        size = len(json.dumps(obj).encode('utf-8'))
    except (TypeError, ValueError):
        raise PresetError('preset_bad_schema', 'A preset must be plain JSON.')
    if size > MAX_BYTES:
        raise PresetError('preset_too_large', 'A preset may be at most 64 KiB.')
    if obj.get('schema') != 1:
        raise PresetError('preset_bad_schema', 'Unsupported preset schema (expected 1).')
    pid = obj.get('id')
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise PresetError('preset_bad_id', 'Preset id must be 1-40 characters of a-z, 0-9 and "-", '
                                           'starting with a letter or digit.')
    if not _text(obj.get('name'), 1, 40):
        raise PresetError('preset_bad_name', 'Preset name must be 1-40 printable characters.')
    grid = obj.get('grid')
    if not isinstance(grid, dict) or grid.get('cols') != COLS or not _int(grid.get('cols')):
        raise PresetError('preset_bad_grid', 'grid.cols must be {}.'.format(COLS))
    cards = obj.get('cards')
    if not isinstance(cards, list):
        raise PresetError('preset_bad_card', 'cards must be a list.')
    if len(cards) > MAX_CARDS:
        raise PresetError('preset_too_many_cards', 'A preset may have at most {} cards.'.format(MAX_CARDS))
    out_cards, seen = [], set()
    for index, card in enumerate(cards):
        item = _card(card, index)
        if item['id'] in seen:
            raise PresetError('preset_bad_card', 'Duplicate card id "{}".'.format(item['id']))
        seen.add(item['id'])
        for other in out_cards:
            if (item['x'] < other['x'] + other['w'] and other['x'] < item['x'] + item['w']
                    and item['y'] < other['y'] + other['h'] and other['y'] < item['y'] + item['h']):
                raise PresetError('preset_overlap', 'Cards "{}" and "{}" overlap.'.format(other['id'], item['id']))
        out_cards.append(item)
    triggers = obj.get('triggers', [])
    if not isinstance(triggers, list) or len(triggers) > MAX_TRIGGERS:
        raise PresetError('preset_bad_trigger', 'triggers must be a list of at most {}.'.format(MAX_TRIGGERS))
    return dict(schema=1, id=pid, name=obj['name'], grid=dict(cols=COLS), cards=out_cards,
                triggers=[_trigger(t) for t in triggers])


def _write_json(path, obj):
    """Atomic write: a temporary file in the same directory, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def _read(path):
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        item = validate(obj)
        revision = obj.get('revision')
        if not _int(revision) or revision < 1 or item['id'] != path.stem:
            return None
        item['revision'] = revision
        return item
    except (OSError, ValueError):
        return None


class PresetStore:
    def __init__(self, builtin_dir, local_dir, state_path):
        self.builtin_dir = Path(builtin_dir)
        self.local_dir = Path(local_dir)
        self.state_path = Path(state_path)

    # ---- reading
    def _builtins(self):
        return [item for item in map(_read, sorted(self.builtin_dir.glob('*.json'))) if item]

    def _locals(self, taken):
        found = []
        if self.local_dir.is_dir():
            for path in self.local_dir.glob('*.json'):
                item = _read(path)
                if item and item['id'] not in taken:
                    found.append(item)
        return sorted(found, key=lambda i: (i['name'], i['id']))

    def all(self):
        builtins = self._builtins()
        return builtins + self._locals({i['id'] for i in builtins})

    def get(self, pid):
        return next((i for i in self.all() if i['id'] == pid), None)

    def _is_builtin(self, pid):
        return any(i['id'] == pid for i in self._builtins())

    # ---- state
    def _raw_state(self):
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def state(self):
        raw = self._raw_state()
        ids = {i['id'] for i in self.all()}
        default = raw.get('default') if raw.get('default') in ids else FALLBACK
        live = raw.get('live') if raw.get('live') in ids else default
        return dict(live=live, default=default, auto_switch=raw.get('auto_switch') is True)

    def _save_state(self, **changes):
        state = self.state()
        state.update(changes)
        _write_json(self.state_path, state)

    def _need(self, pid):
        if not isinstance(pid, str) or not ID_RE.match(pid) or self.get(pid) is None:
            raise PresetError('preset_missing', 'No such preset.')

    def set_live(self, pid):
        self._need(pid)
        self._save_state(live=pid)

    def set_default(self, pid):
        self._need(pid)
        self._save_state(default=pid)

    def set_auto_switch(self, enabled):
        self._save_state(auto_switch=bool(enabled))

    # ---- writing
    def save(self, preset, base_revision):
        item = validate(preset)
        pid = item['id']
        if self._is_builtin(pid):
            raise PresetError('preset_readonly', 'Builtin presets are read-only; save a copy under a new name.')
        if base_revision is not None and not _int(base_revision):
            raise PresetError('preset_bad_revision', 'base_revision must be null or an integer.')
        stored = self.get(pid)
        if base_revision is None:
            if stored is not None:
                raise PresetError('preset_exists', 'A preset with that id already exists.')
            revision = 1
        elif stored is None:
            raise PresetError('preset_missing', 'That preset no longer exists.')
        elif stored['revision'] != base_revision:
            raise PresetError('preset_conflict', 'The preset changed since you loaded it; reload and retry.')
        else:
            revision = stored['revision'] + 1
        item['revision'] = revision
        _write_json(self.local_dir / '{}.json'.format(pid), item)
        return item

    def delete(self, pid):
        if not isinstance(pid, str) or not ID_RE.match(pid):
            raise PresetError('preset_missing', 'No such preset.')
        if self._is_builtin(pid):
            raise PresetError('preset_readonly', 'Builtin presets cannot be deleted.')
        if self.get(pid) is None:
            raise PresetError('preset_missing', 'No such preset.')
        state = self.state()
        if state['default'] == pid:
            raise PresetError('preset_in_use', 'Choose another default first.')
        (self.local_dir / '{}.json'.format(pid)).unlink()
        if state['live'] == pid:
            self._save_state(live=state['default'])

    def message(self):
        builtin = {i['id'] for i in self._builtins()}
        items = [dict(i, builtin=i['id'] in builtin) for i in self.all()]
        return dict(type='presets', items=items, **self.state())


class TriggerEngine:
    """Switch the live preset on flight events (spec section 6). Toolkit-free.

    Only flight-category events count. A phase trigger matches a ``phase`` event whose text ends
    with "-> <value>"; an event trigger matches the event kind (one of FLIGHT_KINDS).
    """

    def __init__(self, store):
        self.store = store
        self.last = None   # (target id, description) of the most recent switch, for the notice

    def on_event(self, event):
        """Return the new live preset id when this event switched it, else None."""
        kind = event.get('kind')
        if event.get('category') != 'flight' or not (kind == 'phase' or kind in FLIGHT_KINDS):
            return None
        state = self.store.state()
        if not state['auto_switch']:
            return None
        live = self.store.get(state['live'])
        if live is None:
            return None
        text = event.get('text')
        for trigger in live.get('triggers', []):
            if trigger['on'] == 'phase':
                hit = kind == 'phase' and isinstance(text, str) and text.endswith(' \u2192 ' + trigger['value'])
            else:
                hit = trigger['value'] == kind
            target = trigger['preset']
            if not hit or target == state['live'] or self.store.get(target) is None:
                continue
            self.store.set_live(target)
            self.last = (target, '{} {}'.format(trigger['on'], trigger['value']))
            return target
        return None
