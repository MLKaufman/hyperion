"""Add viewer shortcuts to served HTML only; source files and ZIPs stay intact."""
import json
from functools import lru_cache
from pathlib import Path
from django.conf import settings


@lru_cache(maxsize=1)
def bridge_source():
    return (Path(__file__).parent / 'static/portal/report-keys.js').read_text()


def with_keyboard_bridge(stream):
    try:
        while chunk := stream.read(64 * 1024):
            yield chunk
        origin = json.dumps(settings.PORTAL_ORIGIN).replace('<', '\\u003c')
        yield ('\n<script>' + bridge_source().replace('PORTAL_ORIGIN_VALUE', origin) + '</script>').encode()
    finally:
        stream.close()
