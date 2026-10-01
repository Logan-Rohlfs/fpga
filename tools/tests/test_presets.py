import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from sdr_cli import presets
from sdr_cli.presets import PresetError, PresetStore, TriggerEngine

BUILTIN = Path(presets.__file__).resolve().parent / 'presets'
CARD_TYPES_JSON = Path(presets.__file__).resolve().parents[1] / 'sdr_web/src/lib/cards/card-types.json'


def good():
    return {
        'schema': 1, 'id': 'example', 'name': 'Example', 'revision': 99, 'grid': {'cols': 12},
        'cards': [
            {'id': 'state', 'type': 'state', 'x': 0, 'y': 0, 'w': 3, 'h': 3, 'title': None,
             'config': {'source': 'best'}},
            {'id': 'alt', 'type': 'number', 'x': 3, 'y': 0, 'w': 3, 'h': 3, 'title': 'Altitude',
             'config': {'field': 'alt_agl_m', 'units': {'length': 'ft'}}},
            {'id': 'cam', 'type': 'camera', 'x': 6, 'y': 3, 'w': 6, 'h': 7, 'title': 'Pad camera',
             'config': {'url': 'https://example.com/cam', 'mode': 'mjpeg'}},
        ],
        'triggers': [{'on': 'phase', 'value': 'BOOST', 'preset': 'boost'},
                     {'on': 'event', 'value': 'burnout', 'preset': 'coast-camera'}],
    }


class ValidateTest(unittest.TestCase):
    def reject(self, code, mutate):
        obj = good()
        mutate(obj)
        with self.assertRaises(PresetError) as ctx:
            presets.validate(obj)
        self.assertEqual(ctx.exception.code, code)
        self.assertTrue(ctx.exception.text)

    def test_valid_preset_normalizes_and_ignores_input_revision(self):
        original = good()
        out = presets.validate(original)
        self.assertEqual(original, good())   # input untouched
        self.assertNotIn('revision', out)
        self.assertEqual(out['id'], 'example')
        self.assertEqual(out['triggers'], good()['triggers'])
        self.assertEqual(out['cards'][0]['title'], None)

    def test_defaults_for_optional_fields(self):
        obj = good()
        del obj['triggers']
        del obj['cards'][0]['title']
        del obj['cards'][0]['config']
        out = presets.validate(obj)
        self.assertEqual(out['triggers'], [])
        self.assertEqual(out['cards'][0]['config'], {})
        self.assertIsNone(out['cards'][0]['title'])

    def test_each_rule_rejects(self):
        cases = [
            ('preset_bad_schema', lambda o: o.update(schema=2)),
            ('preset_bad_id', lambda o: o.update(id='Bad_ID')),
            ('preset_bad_id', lambda o: o.update(id='-x')),
            ('preset_bad_name', lambda o: o.update(name='x' * 41)),
            ('preset_bad_name', lambda o: o.update(name='')),
            ('preset_bad_grid', lambda o: o['grid'].update(cols=11)),
            ('preset_too_many_cards', lambda o: o.update(cards=[
                {'id': 'c{}'.format(i), 'type': 'state', 'x': 0, 'y': i, 'w': 1, 'h': 1, 'config': {}}
                for i in range(41)])),
            ('preset_bad_card', lambda o: o['cards'][1].update(id='state')),
            ('preset_bad_card', lambda o: o['cards'][1].update(type='hologram')),
            ('preset_bad_card', lambda o: o['cards'][1].update(x=10)),
            ('preset_bad_card', lambda o: o['cards'][1].update(h=25)),
            ('preset_bad_card', lambda o: o['cards'][1].update(w=0)),
            ('preset_bad_card', lambda o: o['cards'][1].update(y=501)),
            ('preset_bad_card', lambda o: o['cards'][1].update(x=True)),
            ('preset_bad_card', lambda o: o['cards'][1].update(title='')),
            ('preset_bad_card', lambda o: o['cards'][1].update(config=[])),
            ('preset_overlap', lambda o: o['cards'][1].update(x=2)),
            ('preset_bad_url', lambda o: o['cards'][2]['config'].update(url='javascript:alert(1)')),
            ('preset_bad_url', lambda o: o['cards'][2]['config'].update(url='https://x/' + 'a' * 500)),
            ('preset_bad_unit', lambda o: o['cards'][1]['config'].update(units={'length': 'furlong'})),
            ('preset_bad_trigger', lambda o: o['triggers'][0].update(value='FLYING')),
            ('preset_bad_trigger', lambda o: o['triggers'][1].update(value='phase')),
            ('preset_bad_trigger', lambda o: o['triggers'][1].update(on='clock')),
            ('preset_bad_trigger', lambda o: o['triggers'][1].update(preset='Bad Id')),
            ('preset_bad_trigger', lambda o: o.update(triggers=[o['triggers'][0]] * 21)),
            ('preset_too_large', lambda o: o['cards'][0]['config'].update(blob='x' * 70000)),
        ]
        for code, mutate in cases:
            with self.subTest(code=code):
                self.reject(code, mutate)

    def test_forty_cards_is_allowed(self):
        obj = good()
        obj['cards'] = [{'id': 'c{}'.format(i), 'type': 'state', 'x': i % 12, 'y': i // 12, 'w': 1, 'h': 1,
                         'config': {}} for i in range(40)]
        self.assertEqual(len(presets.validate(obj)['cards']), 40)

    def test_non_object_is_rejected(self):
        for bad in (None, [], 'x', 3):
            with self.assertRaises(PresetError):
                presets.validate(bad)

    def test_card_types_match_json(self):
        self.assertEqual(list(presets.CARD_TYPES), json.loads(CARD_TYPES_JSON.read_text())['types'])

    def test_shipped_presets_validate(self):
        files = sorted(BUILTIN.glob('*.json'))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                obj = json.loads(path.read_text())
                self.assertEqual(obj['id'], path.stem)
                presets.validate(obj)

    def test_default_flight_preset_card_types(self):
        obj = json.loads((BUILTIN / 'flight.json').read_text())
        self.assertEqual(obj['id'], 'flight')
        types = {c['type'] for c in obj['cards']}
        self.assertTrue({'state', 'number', 'plot', 'map', 'trajectory3d', 'events', 'link', 'waterfall'} <= types)


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.local = self.dir / 'presets'
        self.state_path = self.dir / 'preset_state.json'
        self.store = self.make()

    def make(self):
        return PresetStore(BUILTIN, self.local, self.state_path)

    def code(self, fn, *args):
        with self.assertRaises(PresetError) as ctx:
            fn(*args)
        return ctx.exception.code

    def test_defaults_and_listing(self):
        self.assertEqual(self.store.state(), {'live': 'flight', 'default': 'flight', 'auto_switch': False})
        self.assertEqual([p['id'] for p in self.store.all()], ['flight'])

    def test_save_create_then_update_bumps_revision(self):
        saved = self.store.save(good(), None)
        self.assertEqual(saved['revision'], 1)
        saved = self.store.save(good(), 1)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(self.store.get('example')['revision'], 2)
        self.assertEqual(json.loads((self.local / 'example.json').read_text())['revision'], 2)

    def test_listing_order_builtins_first_then_local_by_name(self):
        for pid, name in (('zz', 'Alpha'), ('aa', 'Zulu')):
            obj = good()
            obj.update(id=pid, name=name)
            self.store.save(obj, None)
        self.assertEqual([p['id'] for p in self.store.all()], ['flight', 'zz', 'aa'])

    def test_builtin_is_readonly(self):
        obj = good()
        obj['id'] = 'flight'
        self.assertEqual(self.code(self.store.save, obj, None), 'preset_readonly')
        self.assertEqual(self.code(self.store.save, obj, 1), 'preset_readonly')
        self.assertFalse((self.local / 'flight.json').exists())

    def test_create_existing_is_rejected(self):
        self.store.save(good(), None)
        self.assertEqual(self.code(self.store.save, good(), None), 'preset_exists')

    def test_stale_base_revision_conflicts_and_keeps_file(self):
        self.store.save(good(), None)
        self.store.save(good(), 1)
        self.assertEqual(self.code(self.store.save, good(), 1), 'preset_conflict')
        self.assertEqual(json.loads((self.local / 'example.json').read_text())['revision'], 2)

    def test_numeric_base_for_unknown_id_is_missing(self):
        self.assertEqual(self.code(self.store.save, good(), 1), 'preset_missing')

    def test_bad_base_revision_type(self):
        self.assertEqual(self.code(self.store.save, good(), 'one'), 'preset_bad_revision')
        self.assertEqual(self.code(self.store.save, good(), True), 'preset_bad_revision')

    def test_invalid_preset_is_not_written(self):
        obj = good()
        obj['grid']['cols'] = 3
        self.assertEqual(self.code(self.store.save, obj, None), 'preset_bad_grid')
        self.assertFalse(self.local.exists() and list(self.local.iterdir()))

    def test_write_is_atomic_and_leaves_no_tmp(self):
        self.store.save(good(), None)
        self.store.set_live('example')
        self.assertEqual([p.name for p in self.local.iterdir()], ['example.json'])
        json.loads((self.local / 'example.json').read_text())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['preset_state.json', 'presets'])
        json.loads(self.state_path.read_text())

    def test_delete_rules(self):
        self.store.save(good(), None)
        self.store.set_default('example')
        self.assertEqual(self.code(self.store.delete, 'example'), 'preset_in_use')
        self.assertEqual(self.code(self.store.delete, 'flight'), 'preset_readonly')
        self.assertEqual(self.code(self.store.delete, 'nope'), 'preset_missing')
        self.assertEqual(self.code(self.store.delete, '../x'), 'preset_missing')
        self.store.set_default('flight')
        self.store.set_live('example')
        self.store.delete('example')
        self.assertFalse((self.local / 'example.json').exists())
        self.assertEqual(self.store.state()['live'], 'flight')

    def test_deleting_live_resets_live_to_default(self):
        other = good()
        other.update(id='other')
        self.store.save(good(), None)
        self.store.save(other, None)
        self.store.set_default('other')
        self.store.set_live('example')
        self.store.delete('example')
        self.assertEqual(self.store.state()['live'], 'other')

    def test_set_live_and_default_need_existing_id(self):
        self.assertEqual(self.code(self.store.set_live, 'nope'), 'preset_missing')
        self.assertEqual(self.code(self.store.set_default, 'nope'), 'preset_missing')
        self.store.save(good(), None)
        self.store.set_live('example')
        self.store.set_default('example')
        self.store.set_auto_switch(True)
        fresh = self.make()
        self.assertEqual(fresh.state(), {'live': 'example', 'default': 'example', 'auto_switch': True})

    def test_missing_or_corrupt_state_falls_back_to_flight(self):
        self.assertEqual(self.store.state()['live'], 'flight')
        self.state_path.write_text('{not json')
        self.assertEqual(self.make().state(), {'live': 'flight', 'default': 'flight', 'auto_switch': False})
        self.state_path.write_text(json.dumps({'live': 'gone', 'default': 'gone', 'auto_switch': 'yes'}))
        self.assertEqual(self.make().state(), {'live': 'flight', 'default': 'flight', 'auto_switch': False})
        self.state_path.write_text('[1]')
        self.assertEqual(self.make().state()['live'], 'flight')

    def test_triggers_stored_and_returned_unchanged(self):
        self.store.save(good(), None)
        self.assertEqual(self.store.get('example')['triggers'], good()['triggers'])
        self.assertEqual(self.make().get('example')['triggers'], good()['triggers'])

    def test_message_shape(self):
        self.store.save(good(), None)
        msg = self.store.message()
        self.assertEqual(msg['type'], 'presets')
        self.assertEqual((msg['live'], msg['default'], msg['auto_switch']), ('flight', 'flight', False))
        self.assertEqual([i['id'] for i in msg['items']], ['flight', 'example'])
        self.assertEqual([i['builtin'] for i in msg['items']], [True, False])

    def test_corrupt_or_shadowing_local_files_are_ignored(self):
        self.local.mkdir()
        (self.local / 'broken.json').write_text('{oops')
        shadow = good()
        shadow.update(id='flight', revision=7)
        (self.local / 'flight.json').write_text(json.dumps(shadow))
        listing = self.store.all()
        self.assertEqual([p['id'] for p in listing], ['flight'])
        self.assertEqual(listing[0]['revision'], 1)


def flight_event(kind, text='x', category='flight'):
    return dict(kind=kind, text=text, category=category)


def phase(old, new):
    return flight_event('phase', '{} \u2192 {}'.format(old, new))


class TriggerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.store = PresetStore(BUILTIN, self.dir / 'presets', self.dir / 'state.json')
        self.engine = TriggerEngine(self.store)
        self.save('start', [{'on': 'phase', 'value': 'BOOST', 'preset': 'boost'}])
        self.save('boost', [{'on': 'event', 'value': 'burnout', 'preset': 'coast'},
                            {'on': 'event', 'value': 'landing', 'preset': 'ghost'}])
        self.save('coast', [])
        self.store.set_live('start')

    def save(self, pid, triggers):
        obj = good()
        obj.update(id=pid, name=pid, triggers=triggers)
        self.store.save(obj, None)

    def test_off_means_no_switch(self):
        self.assertIsNone(self.engine.on_event(phase('ARMED', 'BOOST')))
        self.assertEqual(self.store.state()['live'], 'start')

    def test_phase_then_event_triggers_chain(self):
        self.store.set_auto_switch(True)
        self.assertIsNone(self.engine.on_event(phase('IDLE', 'ARMED')))
        self.assertEqual(self.engine.on_event(phase('ARMED', 'BOOST')), 'boost')
        self.assertEqual(self.store.state()['live'], 'boost')
        self.assertEqual(self.engine.last, ('boost', 'phase BOOST'))
        self.assertEqual(self.engine.on_event(flight_event('burnout')), 'coast')
        self.assertEqual(self.store.state()['live'], 'coast')

    def test_missing_target_and_same_target_are_ignored(self):
        self.store.set_auto_switch(True)
        self.store.set_live('boost')
        self.assertIsNone(self.engine.on_event(flight_event('landing')))
        self.assertEqual(self.store.state()['live'], 'boost')

    def test_only_flight_category_and_matching_text(self):
        self.store.set_auto_switch(True)
        self.store.set_live('boost')
        self.assertIsNone(self.engine.on_event(flight_event('burnout', category='link')))
        self.store.set_live('start')
        self.assertIsNone(self.engine.on_event(phase('BOOST', 'COAST')))
        self.assertIsNone(self.engine.on_event(flight_event('phase', 'ARMED \u2192 XBOOST')))
        self.assertIsNone(self.engine.on_event(flight_event('signal_loss', category='link')))
        self.assertEqual(self.store.state()['live'], 'start')

    def test_demo_loop_reset_does_not_switch_back(self):
        self.store.set_auto_switch(True)
        self.store.set_live('coast')
        for ev in (phase('LANDED', 'IDLE'), flight_event('flight_reset')):
            self.assertIsNone(self.engine.on_event(ev))
        self.assertEqual(self.store.state()['live'], 'coast')


if __name__ == '__main__':
    unittest.main()
