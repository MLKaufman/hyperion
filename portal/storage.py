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
    from portal.site_settings import supplemental_limit_bytes, total_limit_bytes, exclusion_patterns, excluded_pattern
    segments = parts(relative)
    relative_file = '/'.join(segments[3:])
    if excluded_pattern(relative_file, exclusion_patterns()):
        raise ValueError('File matches an exclusion pattern')
    limit = file_size_limit(relative_file, supplemental_limit_bytes())
    fd = os.open(settings.REPORTS_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for segment in segments[:-1]:
            child = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(segments[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            os.close(leaf)
            raise ValueError('Not a regular file or exceeds the configured file size limit')
        return os.fdopen(leaf, 'rb')
    finally:
        os.close(fd)

def deliverable_relative(deliverable, path=''):
    prefix = f'{deliverable.project.pi.folder}/{deliverable.project.folder}/{deliverable.folder}'
    return f'{prefix}/{path}' if path else prefix

def inventory(folder, diagnostics=None):
    from portal.site_settings import supplemental_limit_bytes, total_limit_bytes, exclusion_patterns, excluded_pattern
    limit, total_limit, patterns = supplemental_limit_bytes(), total_limit_bytes(), exclusion_patterns()
    folder = folder.resolve(strict=True)
    files, candidates = {}, []
    root = settings.REPORTS_ROOT.resolve()

    def skip(file, reason):
        if diagnostics:
            diagnostics.add(file.relative_to(root).as_posix(), reason)

    def reason(file, relative):
        if file.is_symlink():
            return 'Symbolic link (not followed)'
        if file.name.startswith('.'):
            return 'Hidden file or directory'
        if file.name in INTERNAL:
            return 'Internal analysis file or directory'
        pattern = excluded_pattern(relative, patterns)
        if pattern:
            return f'Matches exclusion pattern: {pattern}'
        return None

    def walk_error(exc):
        raise exc

    for directory, dirs, names in os.walk(folder, followlinks=False, onerror=walk_error):
        kept = []
        for name in sorted(dirs):
            directory_path = Path(directory) / name
            why = reason(directory_path, directory_path.relative_to(folder).as_posix())
            if why:
                skip(directory_path, why + '; entire directory skipped')
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            file = Path(directory) / name
            relative = file.relative_to(folder).as_posix()
            why = reason(file, relative)
            if not why and file.suffix.lower() not in EXTENSIONS:
                why = 'Unsupported file type'
            if not why and not file.is_file():
                why = 'Not a regular file'
            if why:
                skip(file, why)
                continue
            parts(relative)
            size = file.stat().st_size
            cap = file_size_limit(relative, limit)
            if size > cap:
                kind = 'Supplemental' if is_supplement(relative) else 'Report or asset'
                skip(file, f'{kind} file exceeds limit: {size:,} bytes > {cap:,} bytes')
                continue
            candidates.append((file, relative, size))
    total = sum(size for _, _, size in candidates)
    if total > total_limit:
        why = f'Deliverable exceeds total size limit: {total:,} bytes > {total_limit:,} bytes; entire deliverable withheld'
        for file, _, _ in candidates:
            skip(file, why)
        raise ValueError(why)
    for file, relative, size in candidates:
        with open_report(file.relative_to(root).as_posix()) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files[relative] = {'size': size, 'sha256': digest}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return files, fingerprint


def discover_reports(files):
    return [{'path': path, 'title': Path(path).stem.replace('_', ' ').replace('-', ' ')}
            for path in sorted(files, key=natural_key)
            if Path(path).suffix.lower() in {'.html', '.htm', '.md', '.markdown'}
            and not any(x.lower() in RESOURCE_DIRS or x.lower().endswith('_files')
                        for x in PurePosixPath(path).parts[:-1])]


def is_supplement(path):
    # The file format determines presentation; no metadata file is necessary.
    technical = {'.md', '.markdown', '.html', '.htm', '.css', '.js', '.mjs', '.json', '.map', '.wasm',
                 '.woff', '.woff2', '.ttf', '.otf', '.eot', '.ico'}
    return (Path(path).suffix.lower() not in technical
            and not any(x.lower().endswith('_files') or x.lower() in {'site_libs', 'libs', 'assets'}
                        for x in PurePosixPath(path).parts[:-1]))


def discover_supplements(files):
    return [path for path in sorted(files, key=natural_key) if is_supplement(path)]


def file_size_limit(path, supplemental_limit):
    return supplemental_limit if is_supplement(path) else settings.MAX_REPORT_FILE_BYTES
