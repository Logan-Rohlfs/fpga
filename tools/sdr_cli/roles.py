# tools/sdr_cli/roles.py
"""GUI roles: every connection is a Viewer; one Admin at a time, unlocked by password.

Over plain HTTP on a LAN this prevents casual or accidental changes; it does not
resist someone sniffing the network. No web framework imports.
"""
import hashlib
import hmac
import os
import secrets
import time

VIEWER, ADMIN = 'viewer', 'admin'
ITERATIONS = 200000


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return 'pbkdf2_sha256${}${}${}'.format(iterations, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        scheme, iterations, salt, digest = stored.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations))
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def clean_label(label):
    text = ''.join(c for c in str(label or '') if c.isprintable()).strip()[:32]
    return text or 'admin'


class RoleManager:
    GRACE_S = 15.0   # a dropped Admin keeps the role this long, so a page reload can resume it

    def __init__(self, password_hash='', clock=time.monotonic, wall=time.time):
        self.password_hash = password_hash
        self.clock = clock
        self.wall = wall
        self.local = {}
        self.admin = None   # dict(client, label, since, token, dropped_at)

    def connect(self, client, local):
        self.local[client] = bool(local)

    def disconnect(self, client):
        self.local.pop(client, None)
        if self.admin and self.admin['client'] == client:
            self.admin['client'] = None
            self.admin['dropped_at'] = self.clock()

    def role(self, client):
        return ADMIN if self.admin and self.admin['client'] == client else VIEWER

    def admin_info(self):
        return None if not self.admin else dict(label=self.admin['label'], since=self.admin['since'])

    def can_login(self, client):
        return bool(self.password_hash) or self.local.get(client, False)

    def login(self, client, password, label, takeover=False):
        if not self.can_login(client):
            return dict(ok=False, code='no_password')
        if self.password_hash and not verify_password(password or '', self.password_hash):
            return dict(ok=False, code='bad_password')
        self.expire()
        if self.admin and self.admin['client'] == client:
            self.admin['label'] = clean_label(label)
            return dict(ok=True, token=self.admin['token'], demoted=None)
        demoted = None
        if self.admin:
            if not takeover:
                return dict(ok=False, code='needs_takeover', held_by=self.admin['label'], since=self.admin['since'])
            demoted = self.admin['client']
        self.admin = dict(client=client, label=clean_label(label), since=self.wall(),
                          token=secrets.token_hex(16), dropped_at=None)
        return dict(ok=True, token=self.admin['token'], demoted=demoted)

    def resume(self, client, token):
        """Rebind a dropped Admin to a new connection that presents its token."""
        self.expire()
        if (self.admin and self.admin['client'] is None and token
                and hmac.compare_digest(self.admin['token'].encode(), str(token).encode('utf-8', 'surrogatepass'))):
            self.admin['client'] = client
            self.admin['dropped_at'] = None
            return True
        return False

    def logout(self, client):
        if self.admin and self.admin['client'] == client:
            self.admin = None
            return True
        return False

    def expire(self):
        """Release an Admin whose connection dropped more than GRACE_S ago."""
        if (self.admin and self.admin['client'] is None
                and self.clock() - self.admin['dropped_at'] > self.GRACE_S):
            self.admin = None
            return True
        return False
