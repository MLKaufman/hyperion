import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings, RequestFactory
from django.http import HttpResponse
from django.contrib.auth.hashers import check_password
from hyperion.startup import prepare_secret, bootstrap_admin, remove_initial_credentials
from portal.db import db, close_db
from portal.auth import create_user
from portal.middleware import TrustedProxyMiddleware


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StartupTests(SimpleTestCase):
    def setUp(self):
        close_db()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = override_settings(DATA_DIR=self.root, DUCKDB_PATH=self.root / 'hyperion.duckdb')
        config.enable()
        self.addCleanup(config.disable)
        self.addCleanup(close_db)

    def test_secret_is_private_stable_and_rejects_accidental_rotation(self):
        with patch.dict(os.environ, {}, clear=True):
            prepare_secret(self.root)
            first = os.environ['SECRET_KEY']
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual((self.root / 'secret-key').stat().st_mode & 0o777, 0o600)
            os.environ.pop('SECRET_KEY')
            prepare_secret(self.root)
            self.assertEqual(os.environ['SECRET_KEY'], first)
            os.environ['SECRET_KEY'] = 'different-' * 10
            with self.assertRaises(RuntimeError):
                prepare_secret(self.root)
            self.assertEqual((self.root / 'secret-key').read_text().strip(), first)

    def test_bootstrap_is_idempotent_and_requires_password_change(self):
        output = io.StringIO()
        with redirect_stdout(output):
            bootstrap_admin(self.root)
            credentials = json.loads((self.root / 'initial-admin.json').read_text())
            first = db().one('SELECT * FROM users')
            self.assertTrue(first.is_superuser and first.must_change_password)
            self.assertTrue(check_password(credentials['password'], first.password))
            close_db()
            bootstrap_admin(self.root)
        self.assertEqual(db().one('SELECT count(*) AS n FROM users').n, 1)
        self.assertEqual(db().one('SELECT * FROM users').password, first.password)
        self.assertNotIn(credentials['password'], output.getvalue())
        self.assertEqual((self.root / 'initial-admin.json').stat().st_mode & 0o777, 0o600)
        remove_initial_credentials(first.username)
        self.assertFalse((self.root / 'initial-admin.json').exists())
        with redirect_stdout(io.StringIO()):
            bootstrap_admin(self.root)
        self.assertEqual(db().one('SELECT count(*) AS n FROM users').n, 1)
        self.assertFalse((self.root / 'initial-admin.json').exists())

    def test_existing_accounts_are_not_replaced(self):
        user = create_user('existing-admin', 'an-existing-long-password', admin=True, temporary=False)
        bootstrap_admin(self.root)
        self.assertEqual(db().one('SELECT count(*) AS n FROM users').n, 1)
        self.assertEqual(db().one('SELECT * FROM users').password, user.password)
        self.assertFalse((self.root / 'initial-admin.json').exists())

    def test_supplied_legacy_key_is_persisted(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'legacy-secret-' * 5}):
            prepare_secret(self.root)
            self.assertEqual((self.root / 'secret-key').read_text().strip(), 'legacy-secret-' * 5)


@override_settings(TRUSTED_PROXY_CIDRS=['172.30.85.2/32', '172.30.85.3/32'])
class ProxyTests(SimpleTestCase):
    def request(self, peer, forwarded):
        request = RequestFactory().get('/', REMOTE_ADDR=peer,
            HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_FOR=forwarded)
        TrustedProxyMiddleware(lambda r: HttpResponse())(request)
        return request

    def test_cloudflare_chain_preserves_scheme_and_client(self):
        request = self.request('172.30.85.3', '203.0.113.9, 172.30.85.2')
        self.assertEqual(request.client_ip, '203.0.113.9')
        self.assertTrue(request.is_secure())

    def test_untrusted_peer_cannot_spoof_headers(self):
        request = self.request('192.0.2.8', '203.0.113.9')
        self.assertEqual(request.client_ip, '192.0.2.8')
        self.assertFalse(request.is_secure())

    def test_untrusted_intermediate_stops_spoofed_leftmost_ip(self):
        request = self.request('172.30.85.3', '203.0.113.9, 192.0.2.8')
        self.assertEqual(request.client_ip, '192.0.2.8')

    def test_malformed_forwarded_address_falls_back_to_peer(self):
        request = self.request('172.30.85.3', 'bad address')
        self.assertEqual(request.client_ip, '172.30.85.3')
