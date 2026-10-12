"""Public application metadata, separate from private deployment settings."""
from functools import lru_cache
from pathlib import Path
import tomllib


@lru_cache(maxsize=1)
def metadata():
    root = Path(__file__).resolve().parent.parent
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    build_date = root / 'build-date.txt'
    return {
        'app_name': 'Hyperion',
        'app_version': project['version'],
        'app_build_date': build_date.read_text().strip() if build_date.exists() else 'Development checkout (not a container build)',
    }


def context(request):
    return metadata()
