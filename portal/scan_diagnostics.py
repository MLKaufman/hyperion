"""Bounded, persistent summary of the latest scan, visible only to admins."""
import json
from datetime import datetime, timezone
from portal.db import db


class ScanDiagnostics:
    def __init__(self):
        self.data = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'Running',
                     'entries': [], 'count': 0, 'omitted': 0, 'published': 0}

    def add(self, path, reason):
        self.data['count'] += 1
        if len(self.data['entries']) < 2000:
            self.data['entries'].append({'path': str(path), 'reason': str(reason)})
        else:
            self.data['omitted'] += 1

    def save(self):
        db().execute('INSERT INTO site_settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     ['last_scan_diagnostics', json.dumps(self.data)])

    def finish(self, status, published=0):
        self.data.update(status=status, published=published,
                         finished_at=datetime.now(timezone.utc).isoformat())
        self.save()


def latest_scan():
    row = db().one('SELECT value FROM site_settings WHERE key=?', ['last_scan_diagnostics'])
    if not row:
        return None
    data = json.loads(row.value)
    for key in ('started_at', 'finished_at'):
        if key in data:
            data[key] = datetime.fromisoformat(data[key])
    return data


def reason_category(reason):
    """Group variable messages (sizes and patterns) into useful filter choices."""
    if 'exceeds total size limit' in reason:
        return 'Deliverable size limit'
    if 'exceeds limit' in reason or 'file size limit' in reason:
        return 'File size limit'
    if reason.startswith('Matches exclusion pattern:'):
        return 'Exclusion pattern'
    if reason.startswith('Hidden, unsafe,'):
        return 'Invalid folder'
    if reason.startswith('Hidden'):
        return 'Hidden files'
    if reason.startswith('Internal'):
        return 'Internal files'
    if reason.startswith('Unsupported file type'):
        return 'Unsupported file type'
    if reason.startswith('Symbolic link'):
        return 'Symbolic links'
    if reason.startswith('Project or deliverable disabled'):
        return 'Disabled'
    if reason.startswith('No supported reports'):
        return 'No supported content'
    return 'Other errors'


def filter_choices(data):
    """Enrich stored snapshots too, so filters work without another scan."""
    if not data:
        return None
    pis, projects, reasons = set(), set(), set()
    for entry in data['entries']:
        parts = entry['path'].split('/') if entry['path'] != '(scan)' else []
        entry['pi'] = parts[0] if parts else ''
        entry['project'] = '/'.join(parts[:2]) if len(parts) >= 2 else ''
        entry['category'] = reason_category(entry['reason'])
        if entry['pi']:
            pis.add(entry['pi'])
        if entry['project']:
            projects.add((entry['pi'], entry['project']))
        reasons.add(entry['category'])
    data['pi_choices'] = sorted(pis)
    data['project_choices'] = [{'pi': pi, 'value': project} for pi, project in sorted(projects)]
    data['reason_choices'] = sorted(reasons)
    data['retained_count'] = len(data['entries'])
    return data
