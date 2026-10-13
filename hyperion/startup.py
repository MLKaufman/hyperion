"""Container entrypoint: persistent secrets and first-run account, then one worker."""
import json
import os
from pathlib import Path
import secrets
import tempfile


def private_file(path, contents):
    """Publish a complete mode-0600 file once, never overwrite existing state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.initial-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    return path.read_text()


def prepare_secret(data_dir):
    path = data_dir / 'secret-key'
    supplied = os.environ.get('SECRET_KEY', '')
    value = private_file(path, (supplied or secrets.token_urlsafe(64)) + '\n').strip()
    if supplied and supplied != value:
        raise RuntimeError('SECRET_KEY differs from the persisted /data/secret-key; keep the existing key when upgrading.')
    if len(value) < 32:
        raise RuntimeError('The persistent SECRET_KEY must contain at least 32 characters.')
    os.environ['SECRET_KEY'] = value


def bootstrap_admin(data_dir):
    from portal.auth import create_user
    from portal.db import db
    path = data_dir / 'initial-admin.json'
    if not db().one('SELECT id FROM users LIMIT 1'):
        credentials = json.loads(private_file(path, json.dumps({
            'username': 'admin', 'password': secrets.token_urlsafe(24)
        }, indent=2) + '\n'))
        with db().transaction():
            create_user(credentials['username'], credentials['password'], admin=True, temporary=True)
    if path.exists():
        credentials = json.loads(path.read_text())
        user = db().one('SELECT must_change_password FROM users WHERE username=?', [credentials['username']])
        if user and user.must_change_password:
            print('Initial administrator ready. Read /data/initial-admin.json inside this container; change the password at first login.', flush=True)
        else:
            path.unlink()


def remove_initial_credentials(username):
    from django.conf import settings
    path = settings.DATA_DIR / 'initial-admin.json'
    try:
        if path.exists() and json.loads(path.read_text())['username'] == username:
            path.unlink()
    except (OSError, ValueError, KeyError):
        # Password changes must succeed even when optional credential cleanup fails.
        import logging
        logging.getLogger(__name__).warning('Could not remove initial-admin.json; remove it from the data volume.')


def main():
    import sys
    os.umask(0o077)
    data_dir = Path(os.environ.setdefault('DATA_DIR', '/data'))
    data_dir.mkdir(parents=True, exist_ok=True)
    prepare_secret(data_dir)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hyperion.settings')
    if sys.argv[1:]:
        os.execvp(sys.argv[1], sys.argv[1:])
    import django
    django.setup()
    from django.conf import settings
    from portal.db import close_db
    if not settings.REPORTS_ROOT.is_dir() or not os.access(settings.REPORTS_ROOT, os.R_OK | os.X_OK):
        raise RuntimeError('Mount a readable reports folder at /reports (container UID 10001).')
    settings.ZIP_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        bootstrap_admin(data_dir)
    finally:
        close_db()
    os.execvp('gunicorn', ['gunicorn', 'hyperion.wsgi:application', '--bind', '0.0.0.0:8000',
        '--workers', '1', '--threads', '4', '--timeout', '120', '--forwarded-allow-ips=',
        '--logger-class', 'hyperion.logging.RedactingLogger', '--access-logfile', '-',
        '--access-logformat', '%(h)s %(m)s %(U)s %(s)s %(L)s'])


if __name__ == '__main__':
    main()
