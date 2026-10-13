import hashlib
import secrets
import time
import unicodedata
import uuid
from functools import wraps
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.http import Http404
from django.shortcuts import redirect
from django.middleware.csrf import rotate_token
from portal.db import db, Record


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def username_key(username):
    return unicodedata.normalize('NFKC', username).strip().casefold()

def create_user(username, password, admin=False, temporary=True):
    username = username_key(username)
    if not username or len(username) > 150:
        raise ValidationError('Username must contain 1–150 characters.')
    validate_password(password)
    user_id = str(uuid.uuid4())
    db().execute('INSERT INTO users VALUES (?, ?, ?, true, ?, ?)', [user_id, username, make_password(password), admin, temporary])
    return db().user(user_id)

def can_access(user, pi):
    return bool(user and user.is_active and (user.is_superuser or db().one('SELECT 1 FROM memberships WHERE user_id=? AND pi_id=?', [user.id, pi.id])))

def session_user(session_id):
    session = db().one('SELECT * FROM sessions WHERE id=? AND expires_at>?', [session_id, time.time()])
    if not session:
        return None
    user = db().user(session.user_id)
    return user if user and user.is_active else None

def set_login(request, response, user):
    token = secrets.token_urlsafe(32)
    with db().transaction():
        current = db().user(user.id)
        if not current or not current.is_active or current.password != user.password:
            return redirect('login')
        old = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        if old:
            db().execute('DELETE FROM sessions WHERE id=?', [digest(old)])
        db().execute('INSERT INTO sessions VALUES (?, ?, ?)', [digest(token), user.id, time.time() + settings.SESSION_COOKIE_AGE])
    rotate_token(request)
    response.set_cookie(settings.SESSION_COOKIE_NAME, token, httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite='Lax', path='/')
    return response

def revoke_user(user_id):
    # Caller holds a transaction when combining this with account changes.
    db().execute('DELETE FROM sessions WHERE user_id=?', [user_id])
    db().execute('DELETE FROM grants WHERE user_id=?', [user_id])

def login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from urllib.parse import urlencode
            return redirect('/login/?' + urlencode({'next': request.get_full_path()}))
        return view(request, *args, **kwargs)
    return wrapped

def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)
    return wrapped

def consume_login_attempt(username, ip):
    now = time.time()
    keys = [(digest('account:' + username_key(username)), 10), (digest('ip:' + ip), 60)]
    with db().transaction():
        for key, limit in keys:
            attempt = db().one('SELECT * FROM attempts WHERE id=?', [key])
            if attempt and attempt.window_start > now - 900 and attempt.failures >= limit:
                return False
        for key, _ in keys:
            attempt = db().one('SELECT * FROM attempts WHERE id=?', [key])
            if not attempt or attempt.window_start <= now - 900:
                db().execute('INSERT INTO attempts VALUES (?, 1, ?) ON CONFLICT(id) DO UPDATE SET failures=1, window_start=excluded.window_start', [key, now])
            else:
                db().execute('UPDATE attempts SET failures=failures+1 WHERE id=?', [key])
    return True

class AuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        token = request.COOKIES.get(settings.SESSION_COOKIE_NAME, '')
        request.session_key = digest(token) if token and not request.is_report else ''
        request.user = session_user(request.session_key) if request.session_key else None
        request.user = request.user or Record(id=None, is_active=False, is_superuser=False, must_change_password=False)
        return self.get_response(request)

def context(request):
    return {'user': request.user}
