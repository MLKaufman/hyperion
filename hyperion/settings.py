import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DEBUG', '0') == '1'
DATA_DIR = Path(os.environ.get('DATA_DIR', str(BASE_DIR / 'data')))
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    secret_file = DATA_DIR / 'secret-key'
    if secret_file.exists():
        SECRET_KEY = secret_file.read_text().strip()
    elif DEBUG:
        SECRET_KEY = 'development-only-do-not-use-publicly'
    else:
        raise ImproperlyConfigured('Start the container normally to initialize its persistent secret.')
# PORTAL_ORIGIN remains an alias for existing installations.
PORTAL_ORIGIN = os.environ.get('PUBLIC_URL', os.environ.get('PORTAL_ORIGIN', 'http://localhost:8000')).rstrip('/')
from urllib.parse import urlsplit
origin = urlsplit(PORTAL_ORIGIN)
if origin.scheme not in {'http', 'https'} or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username or origin.password:
    raise ImproperlyConfigured('PUBLIC_URL must be an http(s) origin without a path or credentials.')
PORTAL_HOST = origin.netloc.lower()
PUBLIC_HTTPS = origin.scheme == 'https'
ALLOWED_HOSTS = [origin.hostname, 'app'] + (['testserver'] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = [PORTAL_ORIGIN]
TRUSTED_PROXY_CIDRS = [v.strip() for v in os.environ.get('TRUSTED_PROXY_CIDRS', '').split(',') if v.strip()]
INSTALLED_APPS = ['django.contrib.staticfiles', 'portal']
MIDDLEWARE = [
    'portal.middleware.TrustedProxyMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'portal.middleware.HostBoundaryMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'portal.auth.AuthenticationMiddleware',
    'portal.middleware.PasswordChangeMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'hyperion.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'portal.auth.context', 'portal.assets.context', 'portal.about.context']}}]
WSGI_APPLICATION = 'hyperion.wsgi.application'
# No Django ORM backend: accounts, sessions, discovery and audit all use DuckDB.
DATABASES = {}
DUCKDB_PATH = Path(os.environ.get('DUCKDB_PATH', str(DATA_DIR / 'hyperion.duckdb')))
SCAN_INTERVAL = int(os.environ.get('SCAN_INTERVAL', '60'))
RUN_SCANNER = os.environ.get('RUN_SCANNER', '0') == '1'
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher']
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
SESSION_COOKIE_NAME = 'hyperion_session' if not PUBLIC_HTTPS else '__Host-hyperion_session'
CSRF_COOKIE_NAME = 'csrftoken' if not PUBLIC_HTTPS else '__Host-hyperion_csrf'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = PUBLIC_HTTPS
CSRF_COOKIE_SECURE = PUBLIC_HTTPS
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Only TrustedProxyMiddleware may interpret forwarded headers.
SECURE_PROXY_SSL_HEADER = None
SECURE_SSL_REDIRECT = PUBLIC_HTTPS
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SECURE_HSTS_SECONDS = 31536000 if PUBLIC_HTTPS else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
USE_TZ = True
TIME_ZONE = 'UTC'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
REPORTS_ROOT = Path(os.environ.get('REPORTS_ROOT', str(BASE_DIR / 'sample_reports'))).absolute()
ZIP_CACHE_ROOT = Path(os.environ.get('ZIP_CACHE_ROOT', str(DATA_DIR / 'zip-cache')))
MAX_DELIVERABLE_BYTES = int(os.environ.get('MAX_DELIVERABLE_BYTES', str(256 * 1024 * 1024)))
CONTENT_GRANT_SECONDS = 3600

WHITENOISE_ALLOW_ALL_ORIGINS = False

LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler', 'filters': ['redact_content']}},
    'filters': {'redact_content': {'()': 'hyperion.log_filters.RedactContent'}},
    'loggers': {'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}},
}
