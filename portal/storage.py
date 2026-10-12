import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from django.conf import settings

EXTENSIONS = {'.md', '.markdown', '.html', '.htm', '.css', '.js', '.mjs', '.json', '.map', '.wasm', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.eot', '.cloupe', '.pdf', '.csv', '.tsv', '.txt', '.xlsx', '.xls', '.zip', '.gz', '.parquet', '.feather', '.rds', '.rdata', '.bed', '.vcf', '.fasta', '.fa', '.fastq', '.fq', '.mp4', '.webm', '.mp3', '.ogg'}
INTERNAL = {'metadata.json', 'deliverable.json', '__pycache__', 'node_modules', 'renv', '_freeze', '_quarto.yml'}
RESOURCE_DIRS = {'site_libs', 'libs', 'assets', 'figures', 'tables'}

def natural_key(value):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', value)]

def parts(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '\\' in value or any(x in {'', '.', '..'} or x.startswith('.') or x in INTERNAL for x in value.split('/')):
        raise ValueError('Unsafe path')
    return p.parts

def safe_path(relative):
    segments = parts(relative)
    root = settings.REPORTS_ROOT.resolve(strict=True)
    path = root
    for segment in segments:
        path = path / segment
        if path.is_symlink():
            raise ValueError('Symlinks are not published')
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('Path escapes report root')
    return resolved

def open_report(relative):
    # Walk using directory descriptors, refusing symlinks at every component.
    # This also prevents a path replacement between validation and opening.
    segments = parts(relative)
    fd = os.open(settings.REPORTS_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for segment in segments[:-1]:
            child = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(segments[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        if not stat.S_ISREG(os.fstat(leaf).st_mode):
            os.close(leaf)
            raise ValueError('Not a regular file')
        return os.fdopen(leaf, 'rb')
    finally:
        os.close(fd)

def deliverable_relative(deliverable, path=''):
    prefix = f'{deliverable.project.pi.folder}/{deliverable.project.folder}/{deliverable.folder}'
    return f'{prefix}/{path}' if path else prefix

def inventory(folder):
    folder = folder.resolve(strict=True)
    files = {}
    total = 0
    for directory, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in INTERNAL and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            file = Path(directory) / name
            relative = file.relative_to(folder).as_posix()
            if name.startswith('.') or name in INTERNAL or file.is_symlink() or file.suffix.lower() not in EXTENSIONS or not file.is_file():
                continue
            parts(relative)
            total += file.stat().st_size
            if total > settings.MAX_DELIVERABLE_BYTES:
                raise ValueError('Deliverable exceeds configured size limit')
            root_relative = file.relative_to(settings.REPORTS_ROOT.resolve()).as_posix()
            with open_report(root_relative) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            files[relative] = {'size': file.stat().st_size, 'sha256': digest}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return files, fingerprint

def discover_reports(files):
    return [{'path': path, 'title': Path(path).stem.replace('_', ' ').replace('-', ' ')}
            for path in sorted(files, key=natural_key)
            if Path(path).suffix.lower() in {'.html', '.htm', '.md', '.markdown'}
            and not any(x.lower() in RESOURCE_DIRS or x.lower().endswith('_files')
                        for x in PurePosixPath(path).parts[:-1])]


def discover_supplements(files):
    # The file format determines presentation; no metadata file is necessary.
    technical = {'.md', '.markdown', '.html', '.htm', '.css', '.js', '.mjs', '.json', '.map', '.wasm',
                 '.woff', '.woff2', '.ttf', '.otf', '.eot', '.ico'}
    return [path for path in sorted(files, key=natural_key)
            if Path(path).suffix.lower() not in technical
            and not any(x.lower().endswith('_files') or x.lower() in {'site_libs', 'libs', 'assets'}
                        for x in PurePosixPath(path).parts[:-1])]
