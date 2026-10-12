import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hyperion.settings')
application = get_wsgi_application()
from django.conf import settings
if settings.RUN_SCANNER:
    from portal.maintenance import start_scanner
    start_scanner()
