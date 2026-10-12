"""DuckDB persistence. One owning process; serialized operations across its threads."""
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
import duckdb
from django.conf import settings

class Record(SimpleNamespace):
    @property
    def pk(self):
        return self.id
    @property
    def is_authenticated(self):
        return getattr(self, 'is_active', False)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS publication_controls (kind VARCHAR NOT NULL, target_id VARCHAR NOT NULL,
 mode VARCHAR NOT NULL, PRIMARY KEY(kind, target_id));
CREATE TABLE IF NOT EXISTS users (id VARCHAR PRIMARY KEY, username VARCHAR UNIQUE NOT NULL,
 password VARCHAR NOT NULL, is_active BOOLEAN NOT NULL, is_superuser BOOLEAN NOT NULL,
 must_change_password BOOLEAN NOT NULL);
CREATE TABLE IF NOT EXISTS pis (id VARCHAR PRIMARY KEY, folder VARCHAR UNIQUE NOT NULL, name VARCHAR NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (user_id VARCHAR, pi_id VARCHAR, PRIMARY KEY(user_id, pi_id));
CREATE TABLE IF NOT EXISTS projects (id VARCHAR PRIMARY KEY, pi_id VARCHAR NOT NULL, folder VARCHAR NOT NULL,
 title VARCHAR NOT NULL, UNIQUE(pi_id, folder));
CREATE TABLE IF NOT EXISTS deliverables (id VARCHAR PRIMARY KEY, project_id VARCHAR NOT NULL,
 folder VARCHAR NOT NULL, title VARCHAR NOT NULL, reports VARCHAR NOT NULL, files VARCHAR NOT NULL,
 fingerprint VARCHAR NOT NULL, published BOOLEAN NOT NULL, discovered_at DOUBLE NOT NULL,
 UNIQUE(project_id, folder));
CREATE TABLE IF NOT EXISTS sessions (id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, expires_at DOUBLE NOT NULL);
CREATE TABLE IF NOT EXISTS grants (id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, deliverable_id VARCHAR NOT NULL,
 session_key VARCHAR NOT NULL, expires_at DOUBLE NOT NULL, secret_hash VARCHAR NOT NULL, ticket_used BOOLEAN NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (id VARCHAR PRIMARY KEY, failures INTEGER NOT NULL, window_start DOUBLE NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id VARCHAR PRIMARY KEY, occurred_at DOUBLE NOT NULL, actor VARCHAR, action VARCHAR NOT NULL, detail VARCHAR NOT NULL);
'''

class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(path))
        # Schema version is explicit; future changes require a migration here.
        with self.transaction():
            self.connection.execute(SCHEMA)
            versions = self.query('SELECT version FROM schema_version')
            if not versions:
                self.execute('INSERT INTO schema_version VALUES (2)')
            elif [x.version for x in versions] == [1]:
                # Version 2 adds publication_controls; existing records are unchanged.
                self.execute('UPDATE schema_version SET version=2')
            elif [x.version for x in versions] != [2]:
                raise RuntimeError('Unsupported DuckDB schema version; upgrade migration required')
    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute('BEGIN TRANSACTION')
            try:
                yield self
                self.connection.execute('COMMIT')
            except BaseException:
                self.connection.execute('ROLLBACK')
                raise
    def execute(self, sql, params=()):
        with self.lock:
            self.connection.execute(sql, list(params))
    def query(self, sql, params=()):
        with self.lock:
            cursor = self.connection.execute(sql, list(params))
            columns = [x[0] for x in cursor.description]
            return [Record(**dict(zip(columns, row))) for row in cursor.fetchall()]
    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None
    def user(self, pk):
        return self.one('SELECT * FROM users WHERE id=?', [str(pk)])
    def project(self, pk):
        project = self.one('SELECT * FROM projects WHERE id=?', [str(pk)])
        if project:
            project.pi = self.one('SELECT * FROM pis WHERE id=?', [project.pi_id])
        return project
    def deliverable(self, pk):
        item = self.one('SELECT * FROM deliverables WHERE id=?', [str(pk)])
        if item:
            item.project = self.project(item.project_id)
            item.reports = json.loads(item.reports)
            item.files = json.loads(item.files)
            item.metadata = {}  # Reserved for optional future metadata.json support.
            item.discovered_at = datetime.fromtimestamp(item.discovered_at, timezone.utc)
        return item
    def deliverables(self, project_id):
        return [self.deliverable(r.id) for r in self.query('SELECT id FROM deliverables WHERE project_id=? AND published', [project_id])]
    def grant(self, pk):
        grant = self.one('SELECT * FROM grants WHERE id=?', [str(pk)])
        if grant:
            grant.user = self.user(grant.user_id)
            grant.deliverable = self.deliverable(grant.deliverable_id)
        return grant
    def audit(self, actor, action, detail=''):
        self.execute('INSERT INTO audit VALUES (?, ?, ?, ?, ?)', [str(uuid.uuid4()), time.time(), getattr(actor, 'id', None), action, str(detail)[:500]])

_store = None
_store_lock = threading.Lock()

def db():
    global _store
    with _store_lock:
        if _store is None:
            _store = Store(settings.DUCKDB_PATH)
        return _store

def close_db():
    global _store
    with _store_lock:
        if _store is not None:
            with _store.lock:
                _store.connection.close()
            _store = None
