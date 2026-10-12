import fcntl
import hashlib
import json
import os
import tempfile
import zipfile
from django.conf import settings
from portal.storage import deliverable_relative, open_report

class ZipBusy(Exception):
    pass

def build_zip(deliverable):
    entries = ((path, deliverable_relative(deliverable, path), expected)
               for path, expected in deliverable.files.items())
    return _build_archive(f'{deliverable.pk}-{deliverable.fingerprint}', entries)


def build_project_zip(project, deliverables):
    deliverables = sorted(deliverables, key=lambda item: item.folder)
    fingerprint = hashlib.sha256(json.dumps([
        (item.pk, item.folder, item.fingerprint) for item in deliverables
    ]).encode()).hexdigest()
    entries = ((f'{project.folder}/{item.folder}/{path}', deliverable_relative(item, path), expected)
               for item in deliverables for path, expected in item.files.items())
    return _build_archive(f'project-{project.pk}-{fingerprint}', entries)


def _build_archive(key, entries):
    cache = settings.ZIP_CACHE_ROOT
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache / f'{key}.zip'
    # One generator per deployment host; other downloads can use completed caches.
    if target.exists():
        return target
    with (cache / 'generation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ZipBusy
        if target.exists():
            return target
        fd, temporary = tempfile.mkstemp(dir=cache, suffix='.partial')
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for path, source_path, expected in entries:
                    digest = hashlib.sha256()
                    total = 0
                    with open_report(source_path) as source, archive.open(path, 'w', force_zip64=True) as dest:
                        while chunk := source.read(1024 * 1024):
                            digest.update(chunk)
                            total += len(chunk)
                            if total > expected['size']:
                                raise ValueError('Published files changed; rescan required')
                            dest.write(chunk)
                    if digest.hexdigest() != expected['sha256'] or total != expected['size']:
                        raise ValueError('Published files changed; rescan required')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return target
