"""Content versions keep browser assets in step with deployed templates."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@lru_cache(maxsize=1)
def versions():
    root = Path(__file__).parent / 'static' / 'portal'
    return {
        f'{name}_version': sha256((root / f'app.{name}').read_bytes()).hexdigest()[:16]
        for name in ('css', 'js')
    }


def context(request):
    return versions()
