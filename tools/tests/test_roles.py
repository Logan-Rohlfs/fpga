# tools/tests/test_roles.py
import unittest

from sdr_cli import roles as r


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PasswordTest(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = r.hash_password('rocket', iterations=1000)
        self.assertTrue(stored.startswith('pbkdf2_sha256$1000$'))
        self.assertTrue(r.verify_password('rocket', stored))
        self.assertFalse(r.verify_password('Rocket', stored))
        self.assertNotEqual(stored, r.hash_password('rocket', iterations=1000))   # salted
        for junk in ('', 'x$y', 'md5$1$00$00', None, 'pbkdf2_sha256$1$zz$00'):
            self.assertFalse(r.verify_password('rocket', junk))

    def test_label_is_cleaned(self):
        self.assertEqual(r.clean_label('  \x07gs\n '), 'gs')
        self.assertEqual(r.clean_label(''), 'admin')
        self.assertEqual(len(r.clean_label('x' * 50)), 32)


class RoleTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.roles = r.RoleManager(r.hash_password('pw', iterations=1000), clock=self.clock,
                                   wall=lambda: 1700000000.0)
        for client in ('a', 'b'):
            self.roles.connect(client, local=False)

    def test_everyone_starts_as_viewer(self):
        self.assertEqual((self.roles.role('a'), self.roles.role('b')), (r.VIEWER, r.VIEWER))
        self.assertIsNone(self.roles.admin_info())
        self.assertTrue(self.roles.can_login('a'))

    def test_bad_password(self):
        self.assertEqual(self.roles.login('a', 'nope', 'gs'), dict(ok=False, code='bad_password'))
        self.assertEqual(self.roles.role('a'), r.VIEWER)

    def test_single_admin_needs_confirmed_takeover(self):
        first = self.roles.login('a', 'pw', 'groundstation')
        self.assertTrue(first['ok'])
        self.assertIsNone(first['demoted'])
        held = self.roles.login('b', 'pw', 'phone')
        self.assertEqual(held, dict(ok=False, code='needs_takeover', held_by='groundstation', since=1700000000.0))
        self.assertEqual(self.roles.role('a'), r.ADMIN)
        taken = self.roles.login('b', 'pw', 'phone', takeover=True)
        self.assertTrue(taken['ok'])
        self.assertEqual(taken['demoted'], 'a')
        self.assertEqual((self.roles.role('a'), self.roles.role('b')), (r.VIEWER, r.ADMIN))
        self.assertEqual(self.roles.admin_info(), dict(label='phone', since=1700000000.0))

    def test_drop_keeps_admin_through_grace_and_resume(self):
        token = self.roles.login('a', 'pw', 'gs')['token']
        self.roles.disconnect('a')
        self.clock.t += 10
        self.assertFalse(self.roles.expire())
        self.roles.connect('a2', local=False)
        self.assertFalse(self.roles.resume('a2', 'wrong'))
        self.assertTrue(self.roles.resume('a2', token))
        self.assertEqual(self.roles.role('a2'), r.ADMIN)

    def test_drop_releases_after_grace(self):
        self.roles.login('a', 'pw', 'gs')
        self.roles.disconnect('a')
        self.clock.t += 16
        self.assertTrue(self.roles.expire())
        self.assertIsNone(self.roles.admin_info())
        self.assertTrue(self.roles.login('b', 'pw', 'x')['ok'])

    def test_logout(self):
        self.roles.login('a', 'pw', 'gs')
        self.assertFalse(self.roles.logout('b'))
        self.assertTrue(self.roles.logout('a'))
        self.assertEqual(self.roles.role('a'), r.VIEWER)

    def test_no_password_allows_only_localhost(self):
        roles = r.RoleManager('', clock=self.clock)
        roles.connect('lan', local=False)
        roles.connect('here', local=True)
        self.assertFalse(roles.can_login('lan'))
        self.assertTrue(roles.can_login('here'))
        self.assertEqual(roles.login('lan', '', 'x')['code'], 'no_password')
        self.assertTrue(roles.login('here', '', 'x')['ok'])

    def test_resume_rejects_non_ascii_token(self):
        token = self.roles.login('a', 'pw', 'gs')['token']
        self.roles.disconnect('a')
        self.roles.connect('a2', local=False)
        self.assertFalse(self.roles.resume('a2', 'é'))
        self.assertTrue(self.roles.resume('a2', token))
