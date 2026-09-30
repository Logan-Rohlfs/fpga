"""The frontend's event-kind lists (lib/events.ts) must equal sdr_cli/events.py."""
import os
import re
import unittest

from sdr_cli import events

TS = os.path.join(os.path.dirname(__file__), '..', 'sdr_web', 'src', 'lib', 'events.ts')


def ts_list(source, name):
    match = re.search(r'export const ' + name + r'\s*=\s*\[(.*?)\]', source, re.S)
    if not match:
        raise AssertionError('{} not found in events.ts'.format(name))
    return tuple(re.findall(r"'([^']*)'", match.group(1)))


class EventKindSyncTest(unittest.TestCase):
    def setUp(self):
        with open(TS, encoding='utf-8') as stream:
            self.source = stream.read()

    def test_flight_category_kinds(self):
        self.assertEqual(ts_list(self.source, 'FLIGHT_CATEGORY_KINDS'), events.FLIGHT_CATEGORY_KINDS)

    def test_link_kinds(self):
        self.assertEqual(ts_list(self.source, 'LINK_KINDS'), events.LINK_KINDS)

    def test_all_kinds_is_the_concatenation(self):
        self.assertEqual(events.ALL_KINDS, events.FLIGHT_CATEGORY_KINDS + events.LINK_KINDS)
        self.assertIn('ALL_EVENT_KINDS = [...FLIGHT_CATEGORY_KINDS, ...LINK_KINDS]', self.source)


if __name__ == '__main__':
    unittest.main()
