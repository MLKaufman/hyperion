import io
import json
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from portal.db import db, close_db
from portal.auth import create_user, digest
import time
from portal.storage import open_report

@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, PORTAL_HOST='localhost:8000', PORTAL_ORIGIN='http://localhost:8000', REPORT_HOST_TEMPLATE='pi-{pi}.reports.localhost:8000', REPORT_ORIGIN_TEMPLATE='http://pi-{pi}.reports.localhost:8000', ALLOWED_HOSTS=['localhost', '.reports.localhost', 'app'], PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PortalTests(SimpleTestCase):
    def setUp(self):
        close_db()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'reports'
        self.root.mkdir()
        self.cache = Path(self.temp.name) / 'cache'
        self.config = override_settings(REPORTS_ROOT=self.root, ZIP_CACHE_ROOT=self.cache, DUCKDB_PATH=Path(self.temp.name) / 'test.duckdb')
        self.config.enable()
        self.addCleanup(self.config.disable)
        self.addCleanup(close_db)
        for pi in ['alpha', 'beta']:
            folder = self.root / pi / 'project' / '01-analysis'
            folder.mkdir(parents=True)
            (folder / 'report.html').write_text('<html><script src="assets/main.js"></script><h1>Report</h1></html>')
            (folder / 'table.csv').write_text('gene,value\nA,2\n')
            (folder / '.secret').write_text('private')
            (folder / 'analysis.qmd').write_text('source')
            (folder / 'assets').mkdir()
            (folder / 'assets/main.js').write_text('window.reportLoaded = true;')
            (folder / 'assets/widget.html').write_text('<p>Embedded</p>')
            (folder / 'metadata.json').write_text('{reserved for future use}')
        self.scan()
        self.alpha = db().one('SELECT * FROM pis WHERE folder=?', ['alpha'])
        self.beta = db().one('SELECT * FROM pis WHERE folder=?', ['beta'])
        self.a = db().deliverable(db().one('SELECT d.id FROM deliverables d JOIN projects p ON p.id=d.project_id WHERE p.pi_id=?', [self.alpha.id]).id)
        self.b = db().deliverable(db().one('SELECT d.id FROM deliverables d JOIN projects p ON p.id=d.project_id WHERE p.pi_id=?', [self.beta.id]).id)
        self.user = create_user('alice', 'test-password-123', temporary=False)
        db().execute('INSERT INTO memberships VALUES (?, ?)', [self.user.id, self.alpha.id])
        self.client = Client(HTTP_HOST='localhost:8000')
        self.login(self.client)
        self.content_client = Client()
    def login(self, client):
        response = client.post('/login/', {'username': 'alice', 'password': 'test-password-123'})
        self.assertEqual(response.status_code, 302)

    def scan(self):
        call_command('sync_reports', stdout=io.StringIO(), stderr=io.StringIO())
    def launch(self, item=None):
        item = item or self.a
        response = self.client.post(reverse('launch', args=[item.pk]), {'path': 'report.html'})
        self.assertEqual(response.status_code, 200)
        return urlsplit(response.json()['url'])
    def redeem(self, item=None):
        parsed = self.launch(item)
        response = self.content_client.get(parsed.path + '?' + parsed.query, HTTP_HOST=parsed.netloc)
        self.assertEqual(response.status_code, 302)
        return parsed.netloc, response['Location'], parsed
    def read_content(self, host, path):
        return self.content_client.get(path, HTTP_HOST=host)
    def test_dashboard_only_assigned_pi(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(self.a.project.pk))
        self.assertNotContains(response, str(self.b.project.pk))
    def test_project_and_download_boundaries(self):
        for name in ['project', 'download_project', 'launch', 'download_zip']:
            pk = self.b.project.pk if name in {'project', 'download_project'} else self.b.pk
            response = self.client.post(reverse(name, args=[pk])) if name == 'launch' else self.client.get(reverse(name, args=[pk]))
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse('download_file', args=[self.b.pk, 'table.csv'])).status_code, 404)

    def test_project_archive_contents_and_publication_changes(self):
        folder = self.root / 'alpha' / 'project' / '02-results'
        folder.mkdir()
        (folder / 'results.csv').write_text('gene,value\nB,3\n')
        self.scan()
        url = reverse('download_project', args=[self.a.project.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('project.zip', response['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            self.assertIn('project/01-analysis/report.html', archive.namelist())
            self.assertIn('project/01-analysis/assets/main.js', archive.namelist())
            self.assertEqual(archive.read('project/02-results/results.csv'), b'gene,value\nB,3\n')
            self.assertFalse(any('.secret' in name or '.qmd' in name for name in archive.namelist()))
        response.close()
        item = db().one("SELECT id FROM deliverables WHERE project_id=? AND folder='02-results'", [self.a.project.id])
        db().execute('INSERT INTO publication_controls VALUES (?, ?, ?)', ['deliverable', item.id, 'disabled'])
        response = self.client.get(url)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
            self.assertNotIn('project/02-results/results.csv', archive.namelist())
        response.close()
        db().execute('DELETE FROM memberships WHERE user_id=?', [self.user.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_project_archive_rejects_changed_files(self):
        (self.root / 'alpha/project/01-analysis/table.csv').write_text('changed')
        response = self.client.get(reverse('download_project', args=[self.a.project.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(list(self.cache.glob('*.partial')))

    def test_keyboard_bridge_only_changes_served_report(self):
        host, path, _ = self.redeem()
        response = self.read_content(host, path)
        content = b''.join(response.streaming_content)
        self.assertIn(b'hyperion-keyboard', content)
        self.assertIn(b'http://localhost:8000', content)
        self.assertNotIn(b'PORTAL_ORIGIN_VALUE', content)
        response.close()
        original = (self.root / 'alpha/project/01-analysis/report.html').read_bytes()
        response = self.client.get(reverse('download_file', args=[self.a.pk, 'report.html']))
        self.assertEqual(b''.join(response.streaming_content), original)
        response.close()
    def test_viewer_lists_reports_without_widget_html(self):
        response = self.client.get(reverse('project', args=[self.a.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '01 analysis')
        self.assertNotContains(response, 'widget.html')
    def test_launch_redeem_assets_and_replay(self):
        host, path, parsed = self.redeem()
        response = self.read_content(host, path)
        self.assertEqual(response.status_code, 200)
        self.assertIn('sandbox allow-scripts allow-same-origin allow-downloads', response['Content-Security-Policy'])
        response.close()
        response = self.read_content(host, f'/content/{self.a.pk}/assets/main.js')
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.content_client.get(parsed.path + '?' + parsed.query, HTTP_HOST=host).status_code, 404)
    def test_report_hosts_cannot_serve_portal(self):
        host = f'pi-{self.alpha.pk}.reports.localhost:8000'
        for path in ['/', '/login/', '/admin/', reverse('launch', args=[self.a.pk])]:
            self.assertEqual(self.client.get(path, HTTP_HOST=host).status_code, 404)
        self.assertEqual(self.client.get(f'/content/{self.a.pk}/report.html').status_code, 404)
    def test_no_content_without_grant(self):
        host = f'pi-{self.alpha.pk}.reports.localhost:8000'
        self.assertEqual(self.content_client.get(f'/content/{self.a.pk}/report.html', HTTP_HOST=host).status_code, 404)
    def test_wrong_pi_host_and_deliverable(self):
        host, path, _ = self.redeem()
        self.assertEqual(self.read_content(f'pi-{self.beta.pk}.reports.localhost:8000', path).status_code, 404)
        self.assertEqual(self.read_content(host, f'/content/{self.b.pk}/report.html').status_code, 404)
    def test_membership_revocation(self):
        host, path, _ = self.redeem()
        db().execute('DELETE FROM memberships WHERE user_id=?', [self.user.id])
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_disabled_account(self):
        host, path, _ = self.redeem()
        db().execute('UPDATE users SET is_active=false WHERE id=?', [self.user.id])
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_password_change_revokes_content(self):
        host, path, _ = self.redeem()
        from portal.auth import revoke_user
        revoke_user(self.user.id)
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_logout_revokes_content(self):
        host, path, _ = self.redeem()
        self.client.post(reverse('logout'))
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_expired_parent_session(self):
        host, path, _ = self.redeem()
        db().execute('UPDATE sessions SET expires_at=?', [time.time() - 1])
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_expired_grant(self):
        host, path, _ = self.redeem()
        db().execute('UPDATE grants SET expires_at=?', [time.time() - 1])
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_expired_ticket(self):
        from unittest.mock import patch
        from django.core import signing
        parsed = self.launch()
        with patch('portal.views.signing.loads', side_effect=signing.SignatureExpired):
            self.assertEqual(self.content_client.get(parsed.path + '?' + parsed.query, HTTP_HOST=parsed.netloc).status_code, 404)
    def test_admin_disable_is_immediate(self):
        host, path, _ = self.redeem()
        db().execute('INSERT INTO publication_controls VALUES (?, ?, ?) ON CONFLICT DO NOTHING', ['deliverable', self.a.id, 'disabled'])
        self.assertEqual(self.read_content(host, path).status_code, 404)
        self.assertEqual(self.client.get(reverse('download_zip', args=[self.a.pk])).status_code, 404)
        self.scan()
        self.a = db().deliverable(self.a.id)
        self.assertFalse(self.a.published)
    def test_zip_contents(self):
        response = self.client.get(reverse('download_zip', args=[self.a.pk]))
        self.assertEqual(response.status_code, 200)
        data = b''.join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()), {'report.html', 'table.csv', 'assets/main.js', 'assets/widget.html'})
            self.assertEqual(archive.read('table.csv'), b'gene,value\nA,2\n')
    def test_changed_files_reject_new_zip(self):
        (self.root / 'alpha/project/01-analysis/table.csv').write_text('changed')
        self.assertEqual(self.client.get(reverse('download_zip', args=[self.a.pk])).status_code, 409)
    def test_hidden_files_and_traversal_denied(self):
        host, _, _ = self.redeem()
        for path in ['.secret', 'analysis.qmd', 'metadata.json', 'deliverable.json', '../report.html', '/etc/passwd']:
            self.assertEqual(self.read_content(host, f'/content/{self.a.pk}/{path}').status_code, 404)
        with self.assertRaises(ValueError):
            open_report('../outside')
    def test_symlink_replacement_denied(self):
        host, path, _ = self.redeem()
        file = self.root / 'alpha/project/01-analysis/report.html'
        file.unlink()
        file.symlink_to(self.root / 'beta/project/01-analysis/report.html')
        self.assertEqual(self.read_content(host, path).status_code, 404)
    def test_symlink_directory_denied(self):
        host, _, _ = self.redeem()
        assets = self.root / 'alpha/project/01-analysis/assets'
        import shutil
        shutil.rmtree(assets)
        assets.symlink_to(self.root / 'beta/project/01-analysis/assets', target_is_directory=True)
        self.assertEqual(self.read_content(host, f'/content/{self.a.pk}/assets/main.js').status_code, 404)
    def test_auto_discovery_and_metadata_ignored(self):
        folder = self.root / 'alpha/project/02-draft'
        folder.mkdir()
        (folder / 'report.html').write_text('draft')
        self.scan()
        self.assertEqual(db().one('SELECT count(*) AS n FROM deliverables WHERE published').n, 3)
        self.assertTrue(db().one("SELECT published FROM deliverables WHERE folder='02-draft'").published)
        (self.root / 'alpha/project/01-analysis/metadata.json').write_text('{broken')
        self.scan()
        self.assertTrue(db().deliverable(self.a.id).published)
    def test_force_password_change(self):
        db().execute('UPDATE users SET must_change_password=true WHERE id=?', [self.user.id])
        self.assertRedirects(self.client.get('/'), '/password/', fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse('launch', args=[self.a.pk]), {'path': 'report.html'}).status_code, 302)
    def test_login_rate_limit_and_admin_login(self):
        client = Client(HTTP_HOST='localhost:8000')
        for _ in range(10):
            response = client.post('/login/', {'username': 'alice', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(client.post('/admin/login/', {'username': 'alice', 'password': 'wrong'}).status_code, 429)
    def test_csrf_required_for_launch(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost:8000')
        client.cookies[settings.SESSION_COOKIE_NAME] = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(client.post(reverse('launch', args=[self.a.pk]), {'path': 'report.html'}).status_code, 403)
    def test_portal_download_forces_attachment(self):
        response = self.client.get(reverse('download_file', args=[self.a.pk, 'report.html']))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        self.assertIn('sandbox', response['Content-Security-Policy'])
        response.close()
    def test_admin_sees_all_projects(self):
        db().execute('UPDATE users SET is_superuser=true WHERE id=?', [self.user.id])
        response = self.client.get('/')
        self.assertContains(response, str(self.a.project.pk))
        self.assertContains(response, str(self.b.project.pk))
    def test_size_limit(self):
        with override_settings(MAX_DELIVERABLE_BYTES=1), self.assertRaises(CommandError):
            self.scan()
        self.assertEqual(db().one('SELECT count(*) AS n FROM deliverables WHERE published').n, 0)

    def test_malformed_content_cookie_returns_404(self):
        self.content_client.cookies['hyperion_content'] = 'invalid-uuid:secret'
        host = f'pi-{self.alpha.pk}.reports.localhost:8000'
        self.assertEqual(self.read_content(host, f'/content/{self.a.pk}/report.html').status_code, 404)

    def test_large_deliverable_zip(self):
        # Exercise the expected 100 MB size using bounded writes and reads.
        path = self.root / 'alpha/project/01-analysis/large.tsv'
        block = b'GENE_A\t12.34\n' * 8192
        size = 100 * 1024 * 1024
        with path.open('wb') as output:
            remaining = size
            while remaining:
                chunk = block[:min(len(block), remaining)]
                output.write(chunk)
                remaining -= len(chunk)
        self.scan()
        response = self.client.get(reverse('download_zip', args=[self.a.pk]))
        self.assertEqual(response.status_code, 200)
        for _ in response.streaming_content:
            pass
        response.close()
        with zipfile.ZipFile(next(self.cache.glob('*.zip'))) as archive:
            self.assertEqual(archive.getinfo('large.tsv').file_size, size)
            self.assertIsNone(archive.testzip())

    def test_simple_supplement_formats_are_automatic(self):
        folder = self.root / 'alpha/project/01-analysis'
        (folder / 'figures').mkdir()
        for file in ['figures/plot.png', 'figures/plot.svg', 'figures/report.pdf', 'cells.cloupe', 'UPPER.CLOUPE']:
            (folder / file).write_bytes(b'synthetic fixture')
        self.scan()
        response = self.client.get(reverse('project', args=[self.a.project.id]))
        for file in ['figures/plot.png', 'figures/plot.svg', 'figures/report.pdf', 'cells.cloupe', 'UPPER.CLOUPE']:
            self.assertContains(response, file)
        self.assertNotContains(response, 'assets/main.js')
        response = self.client.get(reverse('download_file', args=[self.a.id, 'cells.cloupe']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'synthetic fixture')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        archive_response = self.client.get(reverse('download_zip', args=[self.a.id]))
        with zipfile.ZipFile(io.BytesIO(b''.join(archive_response.streaming_content))) as archive:
            self.assertIn('cells.cloupe', archive.namelist())
            self.assertNotIn('metadata.json', archive.namelist())

    def test_supplement_only_deliverable(self):
        folder = self.root / 'alpha/project/02-cell-browser'
        folder.mkdir()
        (folder / 'cells.cloupe').write_bytes(b'demo')
        self.scan()
        response = self.client.get(reverse('project', args=[self.a.project.id]))
        self.assertEqual(response.context['selected']['deliverable'].id, self.a.id)
        self.assertContains(response, '02 cell browser')
        package = response.context['supplemental_deliveries'][0]
        response = self.client.get(reverse('project', args=[self.a.project.id]) + package['url'])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cells.cloupe')
        self.assertContains(response, 'This deliverable contains supplemental files')
        self.assertNotContains(response, 'id="report-frame"')

    def test_persistence_across_reopen_and_stable_discovery(self):
        original = self.a.id
        close_db()
        self.assertEqual(db().user(self.user.id).username, 'alice')
        self.scan()
        self.assertEqual(db().deliverable(original).project.pi.id, self.alpha.id)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_storage_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with db().transaction():
                db().execute('DELETE FROM users WHERE id=?', [self.user.id])
                raise RuntimeError('simulate failure')
        self.assertIsNotNone(db().user(self.user.id))

    def test_parallel_ticket_redemption_is_single_use(self):
        from concurrent.futures import ThreadPoolExecutor
        parsed = self.launch()
        def consume(_):
            return Client().get(parsed.path + '?' + parsed.query, HTTP_HOST=parsed.netloc).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(consume, range(2))), [302, 404])

    def test_member_cannot_manage_accounts(self):
        self.assertEqual(self.client.get('/admin/').status_code, 404)
        self.assertEqual(self.client.post(reverse('account_edit', args=[self.user.id]), {'action': 'delete'}).status_code, 404)
        self.assertIsNotNone(db().user(self.user.id))

    def make_admin(self):
        admin = create_user('administrator', 'secure-admin-password-8723', admin=True, temporary=False)
        client = Client(HTTP_HOST='localhost:8000')
        self.assertEqual(client.post('/login/', {'username': 'administrator', 'password': 'secure-admin-password-8723'}).status_code, 302)
        return admin, client

    def test_admin_create_account_and_pi_access(self):
        _, client = self.make_admin()
        response = client.post('/admin/', {'username': 'collaborator', 'password': 'temporary-secret-2384', 'pis': [self.beta.id]})
        self.assertEqual(response.status_code, 302)
        user = db().one('SELECT * FROM users WHERE username=?', ['collaborator'])
        self.assertTrue(user.must_change_password)
        self.assertIsNotNone(db().one('SELECT 1 FROM memberships WHERE user_id=? AND pi_id=?', [user.id, self.beta.id]))
        self.assertEqual(client.get('/admin/').status_code, 200)
        self.assertEqual(client.get(reverse('account_edit', args=[user.id])).status_code, 200)

    def test_admin_access_edit_revokes_sessions(self):
        host, path, _ = self.redeem()
        _, admin = self.make_admin()
        response = admin.post(reverse('account_edit', args=[self.user.id]), {'action': 'save', 'active': 'on', 'pis': [self.beta.id]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.read_content(host, path).status_code, 404)
        self.login(self.client)
        self.assertNotContains(self.client.get('/'), str(self.a.project.id))
        self.assertContains(self.client.get('/'), str(self.b.project.id))

    def test_admin_reset_and_delete(self):
        host, path, _ = self.redeem()
        _, admin = self.make_admin()
        response = admin.post(reverse('account_edit', args=[self.user.id]), {'action': 'save', 'active': 'on', 'pis': [self.alpha.id], 'temporary_password': 'new-temporary-secret-9324'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db().user(self.user.id).must_change_password)
        self.assertEqual(self.read_content(host, path).status_code, 404)
        response = admin.post(reverse('account_edit', args=[self.user.id]), {'action': 'delete'})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db().user(self.user.id))
        self.assertTrue((self.root / 'alpha/project/01-analysis/report.html').exists())

    def test_actual_password_change_revokes_prior_sessions(self):
        host, path, _ = self.redeem()
        other = Client(HTTP_HOST='localhost:8000')
        self.login(other)
        response = self.client.post('/password/', {'old_password': 'test-password-123', 'new_password': 'updated-password-8291', 'confirm_password': 'updated-password-8291'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(other.get('/').status_code, 302)
        self.assertEqual(self.read_content(host, path).status_code, 404)

    def test_admin_cannot_delete_self_or_accept_invalid_pi(self):
        admin, client = self.make_admin()
        response = client.post(reverse('account_edit', args=[admin.id]), {'action': 'delete'})
        self.assertContains(response, 'cannot delete')
        self.assertIsNotNone(db().user(admin.id))
        response = client.post('/admin/', {'username': 'invalid', 'password': 'temporary-secret-2340', 'pis': ['missing-pi']})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db().one('SELECT * FROM users WHERE username=?', ['invalid']))

    def test_admin_csrf_protection(self):
        _, admin = self.make_admin()
        client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost:8000')
        client.cookies[settings.SESSION_COOKIE_NAME] = admin.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(client.post(reverse('account_edit', args=[self.user.id]), {'action': 'delete'}).status_code, 403)

    def test_login_rejects_external_redirect(self):
        response = Client(HTTP_HOST='localhost:8000').post('/login/', {'username': 'alice', 'password': 'test-password-123', 'next': 'https://attacker.example/'})
        self.assertEqual(response['Location'], '/')

    def test_stale_password_cannot_create_new_session(self):
        from django.contrib.auth.hashers import make_password
        from django.test import RequestFactory
        from django.http import HttpResponse
        from portal.auth import set_login, revoke_user
        stale_user = db().user(self.user.id)
        with db().transaction():
            db().execute('UPDATE users SET password=? WHERE id=?', [make_password('replacement-secret-8923'), self.user.id])
            revoke_user(self.user.id)
        request = RequestFactory().post('/login/')
        response = set_login(request, HttpResponse(), stale_user)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(db().one('SELECT count(*) AS n FROM sessions WHERE user_id=?', [self.user.id]).n, 0)

    def test_createadmin_existing_username_does_not_prompt_or_modify(self):
        from unittest.mock import patch
        original = db().user(self.user.id).password
        with patch('portal.management.commands.createadmin.getpass') as prompt:
            with self.assertRaisesMessage(CommandError, 'Account "alice" already exists'):
                call_command('createadmin', ' ALICE ', stdout=io.StringIO())
            prompt.assert_not_called()
        self.assertEqual(db().user(self.user.id).password, original)
        self.assertFalse(db().user(self.user.id).is_superuser)

    def test_createadmin_short_password_reports_policy(self):
        from unittest.mock import patch
        with patch('portal.management.commands.createadmin.getpass', side_effect=['Abc!9x', 'Abc!9x']):
            with self.assertRaisesMessage(CommandError, 'at least 12 characters'):
                call_command('createadmin', 'new-admin', stdout=io.StringIO())
        self.assertIsNone(db().one('SELECT id FROM users WHERE username=?', ['new-admin']))

    def test_createadmin_numeric_password_reports_policy(self):
        from unittest.mock import patch
        password = '9357204816390527'
        with patch('portal.management.commands.createadmin.getpass', side_effect=[password, password]):
            with self.assertRaisesMessage(CommandError, 'entirely numeric'):
                call_command('createadmin', 'new-admin', stdout=io.StringIO())
        self.assertIsNone(db().one('SELECT id FROM users WHERE username=?', ['new-admin']))

    def test_createadmin_mismatch_does_not_create_account(self):
        from unittest.mock import patch
        with patch('portal.management.commands.createadmin.getpass', side_effect=['one', 'two']):
            with self.assertRaisesMessage(CommandError, 'Passwords do not match'):
                call_command('createadmin', 'new-admin', stdout=io.StringIO())
        self.assertIsNone(db().one('SELECT id FROM users WHERE username=?', ['new-admin']))

    def test_createadmin_success(self):
        from unittest.mock import patch
        from django.contrib.auth.hashers import check_password
        password = 'A-long-admin-test-passphrase-729!'
        with patch('portal.management.commands.createadmin.getpass', side_effect=[password, password]):
            call_command('createadmin', 'new-admin', stdout=io.StringIO())
        user = db().one('SELECT * FROM users WHERE username=?', ['new-admin'])
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.must_change_password)
        self.assertTrue(check_password(password, user.password))

    def test_admin_shows_pending_and_published_folders(self):
        folder = self.root / 'alpha/project/02-new-deliverable'
        folder.mkdir()
        (folder / 'report.html').write_text('<h1>New report</h1>')
        _, admin = self.make_admin()
        response = admin.get('/admin/')
        self.assertContains(response, '02-new-deliverable')
        self.assertContains(response, 'Awaiting scan or validation')
        self.assertContains(response, 'Published')
        self.assertNotContains(self.client.get(reverse('project', args=[self.a.project.id])), '02-new-deliverable')
        response = admin.post('/refresh/', {'return_to': 'admin'})
        self.assertEqual(response['Location'], '/admin/')
        response = admin.get('/admin/')
        self.assertNotContains(response, 'Awaiting scan or validation')
        self.assertEqual(len(self.client.get(reverse('project', args=[self.a.project.id])).context['reports']), 2)

    def test_admin_folder_status_handles_missing_mount(self):
        _, admin = self.make_admin()
        with override_settings(REPORTS_ROOT=self.root / 'missing'):
            self.assertContains(admin.get('/admin/'), 'report directory is unavailable')

    def test_project_opens_first_report_and_flat_navigation(self):
        folder = self.root / 'alpha/project/02-followup'
        folder.mkdir()
        (folder / 'followup.html').write_text('<h1>Follow-up</h1>')
        self.scan()
        url = reverse('project', args=[self.a.project.id])
        response = self.client.get(url)
        self.assertEqual(response.context['selected']['deliverable'].id, self.a.id)
        self.assertIsNone(response.context['previous'])
        sidebar = response.content.decode().split('<aside', 1)[1].split('</aside>', 1)[0]
        self.assertNotIn('<details', sidebar)
        self.assertNotIn('02 followup', sidebar)
        self.assertNotIn('table.csv', sidebar)
        self.assertIn('followup', sidebar)
        next_report = response.context['next']
        response = self.client.get(url + next_report['url'])
        self.assertEqual(response.context['selected']['path'], 'followup.html')
        self.assertIsNone(response.context['next'])
        self.assertEqual(response.context['previous']['deliverable'].id, self.a.id)

    def test_legacy_markers_and_auto_settings_do_not_control_visibility(self):
        from portal.publication import mode
        marker = self.root / 'alpha/project/.ready'
        marker.touch()
        marker.unlink()
        marker.symlink_to(self.root / 'nonexistent')
        db().execute('INSERT INTO publication_controls VALUES (?, ?, ?)', ['project', self.a.project.id, 'auto'])
        self.scan()
        self.assertEqual(mode('project', self.a.project.id), 'enabled')
        host, path, _ = self.redeem()
        self.assertEqual(self.read_content(host, path).status_code, 200)
        marker.unlink()
        self.assertEqual(self.read_content(host, path).status_code, 200)

    def test_publication_overrides_and_revocation(self):
        _, admin = self.make_admin()
        host, path, _ = self.redeem()
        project_url = reverse('publication_update', args=['project', self.a.project.id])
        delivery_url = reverse('publication_update', args=['deliverable', self.a.id])
        self.assertEqual(self.client.post(project_url, {'mode': 'disabled'}).status_code, 404)
        self.assertEqual(admin.get(project_url).status_code, 405)
        self.assertEqual(admin.post(project_url, {'mode': 'invalid'}).status_code, 400)
        admin.post(project_url, {'mode': 'disabled'})
        self.scan()
        self.assertEqual(self.read_content(host, path).status_code, 404)
        self.assertEqual(self.client.get(reverse('download_project', args=[self.a.project.id])).status_code, 404)
        admin.post(delivery_url, {'mode': 'enabled'})
        self.assertEqual(self.client.post(reverse('launch', args=[self.a.id]), {'path': 'report.html'}).status_code, 404)
        admin.post(project_url, {'mode': 'enabled'})
        self.assertTrue(db().deliverable(self.a.id).published)
        self.assertEqual(self.read_content(host, path).status_code, 404)  # Old grants stay revoked.
        admin.post(delivery_url, {'mode': 'disabled'})
        (self.root / 'alpha/project/.ready').touch()
        self.scan()
        self.assertFalse(db().deliverable(self.a.id).published)
        admin.post(delivery_url, {'mode': 'enabled'})
        self.assertTrue(db().deliverable(self.a.id).published)
        page = admin.get('/admin/')
        self.assertContains(page, 'Projects</h3>')
        self.assertContains(page, 'Deliverables</h3>')

    def test_admin_enable_unmarked_folder_and_csrf(self):
        folder = self.root / 'alpha/project/02-draft'
        folder.mkdir()
        (folder / 'report.html').write_text('<h1>Draft</h1>')
        self.scan()
        item = db().one("SELECT id FROM deliverables WHERE folder='02-draft'")
        _, admin = self.make_admin()
        url = reverse('publication_update', args=['deliverable', item.id])
        protected = Client(enforce_csrf_checks=True, HTTP_HOST='localhost:8000')
        protected.cookies = admin.cookies
        self.assertEqual(protected.post(url, {'mode': 'enabled'}).status_code, 403)
        self.assertEqual(admin.post(url, {'mode': 'enabled'}).status_code, 302)
        self.assertTrue(db().deliverable(item.id).published)
        admin.post(url, {'mode': 'disabled'})
        self.assertFalse(db().deliverable(item.id).published)

    def test_markdown_report_rendering_and_original_download(self):
        folder = self.root / 'alpha/project/01-analysis'
        markdown = '# Example\n\n| Sample | Value |\n| --- | --- |\n| A | 2 |\n\n[Results](table.csv)\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n'
        (folder / 'notes.MD').write_text(markdown)
        self.scan()
        page = self.client.get(reverse('project', args=[self.a.project.id]))
        self.assertIn('notes.MD', [r['path'] for r in page.context['reports']])
        self.assertNotIn('notes.MD', page.context['supplements'])
        launched = self.client.post(reverse('launch', args=[self.a.id]), {'path': 'notes.MD'})
        parsed = urlsplit(launched.json()['url'])
        redeemed = self.content_client.get(parsed.path + '?' + parsed.query, HTTP_HOST=parsed.netloc)
        response = self.read_content(parsed.netloc, redeemed['Location'])
        html = b''.join(response.streaming_content).decode()
        response.close()
        self.assertIn('<h1>Example</h1>', html)
        self.assertIn('<table>', html)
        self.assertIn('href="table.csv"', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('hyperion-keyboard', html)
        download = self.client.get(reverse('download_file', args=[self.a.id, 'notes.MD']))
        self.assertEqual(b''.join(download.streaming_content).decode(), markdown)
        download.close()

    def test_publication_schema_upgrade_preserves_accounts(self):
        db().execute('DROP TABLE publication_controls')
        db().execute('UPDATE schema_version SET version=1')
        close_db()
        self.assertEqual(db().one('SELECT version FROM schema_version').version, 2)
        self.assertEqual(db().user(self.user.id).username, 'alice')
        self.assertEqual(db().query('SELECT * FROM publication_controls'), [])

    def test_bulk_publication_validates_selection_and_applies_together(self):
        _, admin = self.make_admin()
        url = reverse('publication_bulk', args=['project'])
        ids = [self.a.project.id, self.b.project.id]
        self.assertEqual(self.client.post(url, {'selected': ids, 'mode': 'disabled'}).status_code, 404)
        self.assertEqual(admin.post(url, {'mode': 'disabled'}).status_code, 400)
        self.assertEqual(admin.post(url, {'selected': [ids[0], 'missing'], 'mode': 'disabled'}).status_code, 404)
        self.assertEqual(db().query('SELECT * FROM publication_controls'), [])
        protected = Client(enforce_csrf_checks=True, HTTP_HOST='localhost:8000')
        protected.cookies = admin.cookies
        self.assertEqual(protected.post(url, {'selected': ids, 'mode': 'disabled'}).status_code, 403)
        response = admin.post(url, {'selected': ids, 'mode': 'disabled'})
        self.assertEqual(response['Location'], '/admin/#projects')
        self.assertFalse(db().deliverable(self.a.id).published)
        self.assertFalse(db().deliverable(self.b.id).published)
        admin.post(url, {'selected': ids, 'mode': 'enabled'})
        self.assertTrue(db().deliverable(self.a.id).published)
        self.assertTrue(db().deliverable(self.b.id).published)
        url = reverse('publication_bulk', args=['deliverable'])
        response = admin.post(url, {'selected': [self.a.id, self.b.id, self.a.id], 'mode': 'disabled'})
        self.assertEqual(response['Location'], '/admin/#deliverables')
        self.assertEqual(db().one('SELECT count(*) AS n FROM deliverables WHERE published').n, 0)

    def test_projects_are_immediate_children_of_pi(self):
        nested = self.root / 'alpha/project/01-analysis/nested'
        nested.mkdir()
        (nested / 'report.html').write_text('<h1>Nested report</h1>')
        other = self.root / 'alpha/second-project/01-deliverable'
        other.mkdir(parents=True)
        (other / 'report.html').write_text('<h1>Another project</h1>')
        self.scan()
        folders = {p.folder for p in db().query('SELECT folder FROM projects WHERE pi_id=?', [self.alpha.id])}
        self.assertEqual(folders, {'project', 'second-project'})

    def test_account_table_last_login_and_details(self):
        _, admin = self.make_admin()
        create_user('never-signed-in', 'another-long-test-password', temporary=False)
        self.client.post('/login/', {'username': 'alice', 'password': 'incorrect'})
        response = admin.get('/admin/')
        alice = next(account for account in response.context['accounts'] if account.id == self.user.id)
        expected = db().one("SELECT max(occurred_at) AS at FROM audit WHERE actor=? AND action='login'", [self.user.id]).at
        self.assertAlmostEqual(alice.last_login.timestamp(), expected, places=5)
        self.assertEqual(alice.pi_names, ['alpha'])
        never = next(account for account in response.context['accounts'] if account.username == 'never-signed-in')
        self.assertIsNone(never.last_login)
        self.assertContains(response, 'Last login (UTC)')
        self.assertContains(response, 'No login recorded')
        self.assertContains(response, 'aria-label="Edit alice"')
        html = response.content.decode()
        self.assertLess(html.index('<h2>Create account</h2>'), html.index('<h2>Accounts</h2>'))
