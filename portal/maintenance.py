import logging
import threading
import time
from django.conf import settings
from portal.db import db
from portal.discovery import scan_reports
logger = logging.getLogger(__name__)
_started = False
_lock = threading.Lock()

def cleanup():
    now = time.time()
    with db().transaction():
        db().execute('DELETE FROM sessions WHERE expires_at<?', [now])
        db().execute('DELETE FROM grants WHERE expires_at<?', [now])
        db().execute('DELETE FROM attempts WHERE window_start<?', [now - 86400])
    if settings.ZIP_CACHE_ROOT.exists():
        for path in settings.ZIP_CACHE_ROOT.glob('*.zip'):
            if path.stat().st_mtime < now - 86400:
                path.unlink(missing_ok=True)

def start_scanner():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    def work():
        while True:
            try:
                _, errors = scan_reports()
                for error in errors:
                    logger.error('Discovery: %s', error)
                cleanup()
            except Exception:
                logger.exception('Discovery or cleanup failed; retrying on the next interval')
            time.sleep(max(10, settings.SCAN_INTERVAL))
    threading.Thread(target=work, name='report-discovery', daemon=True).start()
