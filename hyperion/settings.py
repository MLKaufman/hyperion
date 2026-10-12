import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DEBUG', '0') == '1'
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY is required outside development.')
    SECRET_KEY = 'development-only-do-not-use-publicly'
PORTAL_ORIGIN = os.environ.get('PORTAL_ORIGIN', 'http://portal.hyperion.localhost:8000').rstrip('/')
REPORT_ORIGIN_TEMPLATE = os.environ.get('REPORT_ORIGIN_TEMPLATE', 'http://pi-{pi}.reports.hyperion.localhost:8000').rstrip('/')
from urllib.parse import urlsplit
PORTAL_HOST = urlsplit(PORTAL_ORIGIN).netloc
REPORT_HOST_TEMPLATE = urlsplit(REPORT_ORIGIN_TEMPLATE).netloc
if '{pi}' not in REPORT_HOST_TEMPLATE:
    raise ImproperlyConfigured('REPORT_ORIGIN_TEMPLATE must contain {pi} in its hostname.')
if not DEBUG and (not PORTAL_ORIGIN.startswith('https://') or not REPORT_ORIGIN_TEMPLATE.startswith('https://')):
    raise ImproperlyConfigured('Production origins must use HTTPS.')
report_suffix = urlsplit(REPORT_ORIGIN_TEMPLATE.replace('{pi}', 'placeholder')).hostname.split('.', 1)[1]
ALLOWED_HOSTS = [urlsplit(PORTAL_ORIGIN).hostname, '.' + report_suffix, 'testserver', 'app'] if DEBUG else [urlsplit(PORTAL_ORIGIN).hostname, '.' + report_suffix, 'app']
CSRF_TRUSTED_ORIGINS = [PORTAL_ORIGIN]
INSTALLED_APPS = ['django.contrib.staticfiles', 'portal']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'portal.middleware.HostBoundaryMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'portal.auth.AuthenticationMiddleware', 'portal.middleware.PasswordChangeMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'hyperion.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'portal.auth.context', 'portal.assets.context', 'portal.about.context']}}]
WSGI_APPLICATION = 'hyperion.wsgi.application'
# No Django ORM backend: accounts, sessions, discovery and audit all use DuckDB.
DATABASES = {}
DUCKDB_PATH = Path(os.environ.get('DUCKDB_PATH', str(BASE_DIR / 'data' / 'hyperion.duckdb')))
SCAN_INTERVAL = int(os.environ.get('SCAN_INTERVAL', '60'))
RUN_SCANNER = os.environ.get('RUN_SCANNER', '0') == '1'
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher']
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
SESSION_COOKIE_NAME = 'hyperion_session' if DEBUG else '__Host-hyperion_session'
CSRF_COOKIE_NAME = 'csrftoken' if DEBUG else '__Host-hyperion_csrf'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
USE_TZ = True
TIME_ZONE = 'UTC'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
REPORTS_ROOT = Path(os.environ.get('REPORTS_ROOT', str(BASE_DIR / 'sample_reports'))).absolute()
ZIP_CACHE_ROOT = Path(os.environ.get('ZIP_CACHE_ROOT', str(BASE_DIR / '.zip-cache')))
MAX_DELIVERABLE_BYTES = int(os.environ.get('MAX_DELIVERABLE_BYTES', str(256 * 1024 * 1024)))
CONTENT_GRANT_SECONDS = 3600
