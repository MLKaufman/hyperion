"""Administrator preferences persisted in the application's DuckDB volume."""
from django.conf import settings
from portal.db import db


def supplemental_limit_bytes():
    row = db().one('SELECT value FROM site_settings WHERE key=?', ['max_supplemental_mib'])
    return int(row.value) * 1024 * 1024 if row else settings.MAX_REPORT_FILE_BYTES


def total_limit_bytes():
    row = db().one('SELECT value FROM site_settings WHERE key=?', ['max_deliverable_mib'])
    return int(row.value) * 1024 * 1024 if row else settings.MAX_DELIVERABLE_BYTES


def scan_interval_seconds():
    row = db().one('SELECT value FROM site_settings WHERE key=?', ['scan_interval_seconds'])
    return int(row.value) if row else max(10, settings.SCAN_INTERVAL)


def exclusion_patterns():
    row = db().one('SELECT value FROM site_settings WHERE key=?', ['exclusion_patterns'])
    return row.value.splitlines() if row else []


def excluded_pattern(path, patterns):
    """Case-sensitive shell globs; match paths and their ancestor directories."""
    from fnmatch import fnmatchcase
    pieces = path.strip('/').split('/')
    candidates = ['/'.join(pieces[:i]) for i in range(1, len(pieces) + 1)]
    for pattern in patterns:
        pattern = pattern.rstrip('/')
        if any(fnmatchcase(candidate if '/' in pattern else candidate.rsplit('/', 1)[-1], pattern)
               for candidate in candidates):
            return pattern
    return None


def policy_key():
    import hashlib
    import json
    return hashlib.sha256(json.dumps([supplemental_limit_bytes(), total_limit_bytes(),
                                     exclusion_patterns(), settings.MAX_REPORT_FILE_BYTES]).encode()).hexdigest()
