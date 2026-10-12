import json
import threading
import time
import uuid
from django.conf import settings
from portal.db import db
from portal.storage import safe_path, inventory, discover_reports, discover_supplements
from portal.publication import eligible, mode

_scan_lock = threading.Lock()

def scan_reports():
    root = settings.REPORTS_ROOT
    if not root.is_dir() or root.is_symlink():
        raise ValueError('REPORTS_ROOT must be an existing real directory')
    seen, errors = [], []
    with _scan_lock:
        for pi_folder in sorted(root.iterdir()):
            if not usable_directory(pi_folder):
                continue
            store = db()
            store.execute('INSERT INTO pis VALUES (?, ?, ?) ON CONFLICT(folder) DO NOTHING', [str(uuid.uuid4()), pi_folder.name, pi_folder.name.replace('-', ' ')])
            pi = store.one('SELECT * FROM pis WHERE folder=?', [pi_folder.name])
            for project_folder in sorted(pi_folder.iterdir()):
                if not usable_directory(project_folder):
                    continue
                store.execute('INSERT INTO projects VALUES (?, ?, ?, ?) ON CONFLICT(pi_id, folder) DO NOTHING', [str(uuid.uuid4()), pi.id, project_folder.name, project_folder.name.replace('-', ' ')])
                project = store.one('SELECT * FROM projects WHERE pi_id=? AND folder=?', [pi.id, project_folder.name])
                for folder in sorted(project_folder.iterdir()):
                    if not usable_directory(folder):
                        continue
                    store.execute('''INSERT INTO deliverables VALUES (?, ?, ?, ?, '[]', '{}', '', false, ?)
                        ON CONFLICT(project_id, folder) DO NOTHING''',
                        [str(uuid.uuid4()), project.id, folder.name, folder.name.replace('-', ' ').replace('_', ' '), time.time()])
                    item = store.one('SELECT id FROM deliverables WHERE project_id=? AND folder=?', [project.id, folder.name])
                    if not eligible(project.id, item.id):
                        continue
                    try:
                        files, fingerprint = inventory(folder)
                        reports = discover_reports(files)
                        if not reports and not discover_supplements(files):
                            raise ValueError('No supported reports or supplements found')
                        # Upsert preserves stable URLs and original discovery date.
                        store.execute('''INSERT INTO deliverables VALUES (?, ?, ?, ?, ?, ?, ?, true, ?)
                            ON CONFLICT(project_id, folder) DO UPDATE SET title=excluded.title,
                            reports=excluded.reports, files=excluded.files, fingerprint=excluded.fingerprint, published=true''',
                            [str(uuid.uuid4()), project.id, folder.name, folder.name.replace('-', ' ').replace('_', ' '), json.dumps(reports), json.dumps(files), fingerprint, time.time()])
                        seen.append(store.one('SELECT id FROM deliverables WHERE project_id=? AND folder=?', [project.id, folder.name]).id)
                    except (ValueError, OSError) as exc:
                        errors.append(f'{folder.relative_to(root)}: {exc}')
        with db().transaction():
            for row in db().query('SELECT id FROM deliverables WHERE published'):
                if row.id not in seen:
                    db().execute('UPDATE deliverables SET published=false WHERE id=?', [row.id])
    return len(seen), errors

def usable_directory(path):
    if not path.is_dir() or path.is_symlink() or path.name.startswith('.'):
        return False
    try:
        safe_path(path.relative_to(settings.REPORTS_ROOT).as_posix())
        return True
    except (ValueError, OSError):
        return False


def folder_status():
    """Lightweight admin diagnostics; never hash report contents on page load."""
    root = settings.REPORTS_ROOT
    if not root.is_dir() or root.is_symlink():
        return [], 'The report directory is unavailable. Check the report mount.'
    indexed = {
        (r.pi_folder, r.project_folder, r.folder): r
        for r in db().query('''SELECT p.folder AS pi_folder, j.folder AS project_folder,
            d.id, d.folder, d.published, j.id AS project_id FROM deliverables d
            JOIN projects j ON j.id=d.project_id JOIN pis p ON p.id=j.pi_id''')
    }
    rows = []
    try:
        for pi in sorted(root.iterdir()):
            if not usable_directory(pi):
                continue
            for project in sorted(pi.iterdir()):
                if not usable_directory(project):
                    continue
                for folder in sorted(project.iterdir()):
                    if not usable_directory(folder):
                        continue
                    record = indexed.get((pi.name, project.name, folder.name))
                    enabled = eligible(record.project_id, record.id) if record else True
                    published = enabled and record is not None and record.published
                    state = 'Published' if published else ('Awaiting scan or validation' if enabled else 'Disabled')
                    setting = mode('deliverable', record.id) if record else 'enabled'
                    rows.append({'pi': pi.name, 'project': project.name, 'folder': folder.name,
                                 'state': state, 'project_id': record.project_id if published else None,
                                 'id': record.id if record else None, 'mode': setting})
    except OSError:
        return rows, 'Some folders could not be read. Check directory permissions and application logs.'
    return rows, ''
