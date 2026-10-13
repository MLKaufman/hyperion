import hmac
import mimetypes
import secrets
import time
import uuid
from urllib.parse import urlencode, quote
from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.password_validation import validate_password
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST
from portal.access import authorized_deliverable, published_visible, valid_grant, secret_digest
from portal.auth import login_required, admin_required, can_access, consume_login_attempt, username_key, digest, set_login, revoke_user
from portal.db import db
from portal.discovery import scan_reports
from portal.downloads import build_zip, build_project_zip, ZipBusy
from portal.report_keyboard import with_keyboard_bridge
from portal.markdown_reports import render_markdown
from portal.storage import deliverable_relative, open_report, natural_key, discover_supplements

class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

class PasswordForm(forms.Form):
    old_password = forms.CharField(widget=forms.PasswordInput)
    new_password = forms.CharField(widget=forms.PasswordInput, min_length=12)
    confirm_password = forms.CharField(widget=forms.PasswordInput)


def sign_in(request):
    form = LoginForm(request.POST or None)
    if request.method == 'POST':
        ip = request.client_ip
        if not consume_login_attempt(request.POST.get('username', ''), ip):
            return HttpResponse('Too many login attempts. Try again in 15 minutes.', status=429, headers={'Retry-After': '900'})
        if form.is_valid():
            username = username_key(form.cleaned_data['username'])
            user = db().one('SELECT * FROM users WHERE username=?', [username])
            # Perform a hash even for unknown users to reduce timing disclosure.
            if user:
                valid = check_password(form.cleaned_data['password'], user.password)
            else:
                make_password(form.cleaned_data['password'])
                valid = False
            if user and valid and user.is_active:
                db().execute('DELETE FROM attempts WHERE id=?', [digest('account:' + username)])
                db().audit(user, 'login')
                target = request.POST.get('next', '/')
                if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=settings.PUBLIC_HTTPS):
                    target = '/'
                return set_login(request, redirect(target), user)
            form.add_error(None, 'Invalid username or password.')
    return render(request, 'portal/login.html', {'form': form, 'next': request.GET.get('next', request.POST.get('next', '/'))})

@login_required
def password_change(request):
    form = PasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            if not check_password(form.cleaned_data['old_password'], request.user.password):
                raise ValidationError('Current password is incorrect.')
            password = form.cleaned_data['new_password']
            if password != form.cleaned_data['confirm_password']:
                raise ValidationError('New passwords do not match.')
            validate_password(password)
            encoded = make_password(password)
            with db().transaction():
                db().execute('UPDATE users SET password=?, must_change_password=false WHERE id=?', [encoded, request.user.id])
                revoke_user(request.user.id)
                db().audit(request.user, 'password_changed')
            from hyperion.startup import remove_initial_credentials
            remove_initial_credentials(request.user.username)
            return set_login(request, redirect('home'), db().user(request.user.id))
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'portal/password.html', {'form': form})

@login_required
@require_POST
def sign_out(request):
    with db().transaction():
        db().execute('DELETE FROM sessions WHERE id=?', [request.session_key])
        db().execute('DELETE FROM grants WHERE session_key=?', [request.session_key])
        db().audit(request.user, 'logout')
    response = redirect('login')
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path='/', samesite='Lax')
    return response
@login_required
def home(request):
    projects = [db().project(row.id) for row in db().query('SELECT id FROM projects')]
    projects = [p for p in projects if can_access(request.user, p.pi)]
    cards = []
    for project in projects:
        deliveries = [d for d in db().deliverables(project.id) if published_visible(d)]
        if deliveries:
            project.count = len(deliveries)
            project.latest = max(d.discovered_at for d in deliveries)
            cards.append(project)
    return render(request, 'portal/home.html', {'projects': cards})

@login_required
def project_view(request, pk):
    project = db().project(pk)
    if not project or not can_access(request.user, project.pi):
        raise Http404
    deliveries = sorted([d for d in db().deliverables(project.id) if published_visible(d)], key=lambda d: natural_key(d.folder))
    documents = []
    for deliverable in deliveries:
        deliverable.documents = []
        for report in deliverable.reports or [{'path': '', 'title': 'Supporting files'}]:
            document = {'deliverable': deliverable, 'path': report['path'], 'title': report['title'], 'url': f'?{urlencode({"deliverable": str(deliverable.pk), "report": report["path"]})}'}
            deliverable.documents.append(document)
            documents.append(document)
    reports = [document for document in documents if document['path']]
    supplemental_deliveries = [document for document in documents if not document['path']]
    if not documents:
        raise Http404
    if request.GET.get('deliverable'):
        selected = next((d for d in documents if str(d['deliverable'].pk) == request.GET['deliverable'] and d['path'] == request.GET.get('report')), None)
        if selected is None:
            raise Http404
    else:
        selected = (reports or documents)[0]
    navigation = reports if selected['path'] else supplemental_deliveries
    index = navigation.index(selected)
    item = selected['deliverable']
    supplements = discover_supplements(item.files)
    return render(request, 'portal/project.html', {'project': project, 'reports': reports, 'supplemental_deliveries': supplemental_deliveries, 'selected': selected, 'previous': navigation[index - 1] if index else None, 'next': navigation[index + 1] if index + 1 < len(navigation) else None, 'supplements': supplements})


@login_required
@require_POST
def launch(request, pk):
    item = authorized_deliverable(request.user, pk)
    path = request.POST.get('path', '')
    if path not in {r['path'] for r in item.reports}:
        raise Http404
    grant_id = str(uuid.uuid4())
    db().execute('INSERT INTO grants VALUES (?, ?, ?, ?, ?, ?, false)', [grant_id, request.user.id, item.id, request.session_key, time.time() + settings.CONTENT_GRANT_SECONDS, ''])
    ticket = signing.dumps({'grant': grant_id, 'path': path}, salt='report-launch')
    origin = settings.PORTAL_ORIGIN
    return JsonResponse({'url': f'{origin}/content/launch/?{urlencode({"ticket": ticket})}'})

@xframe_options_exempt
def redeem(request):
    try:
        data = signing.loads(request.GET.get('ticket', ''), salt='report-launch', max_age=60)
        with db().transaction():
            grant = db().grant(data['grant'])
            if not valid_grant(grant) or grant.ticket_used or data['path'] not in {r['path'] for r in grant.deliverable.reports}:
                raise Http404
            secret = secrets.token_urlsafe(32)
            db().execute('UPDATE grants SET secret_hash=?, ticket_used=true WHERE id=?', [secret_digest(secret), grant.id])
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise Http404
    prefix = f'/content/{grant.deliverable_id}/{grant.id}/{secret}/'
    response = HttpResponseRedirect(prefix + quote(data['path'], safe='/'))
    response['Content-Security-Policy'] = f"frame-ancestors {settings.PORTAL_ORIGIN}"
    return response

@xframe_options_exempt
def content(request, pk, grant_id, secret, path):
    try:
        grant = db().grant(grant_id)
        if not valid_grant(grant) or not grant.ticket_used or grant.deliverable_id != str(pk) or not hmac.compare_digest(grant.secret_hash, secret_digest(secret)):
            raise Http404
    except ValueError:
        raise Http404
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        return HttpResponse(status=405)
    item = grant.deliverable
    if path not in item.files:
        raise Http404
    if request.method == 'OPTIONS':
        response = HttpResponse(status=204)
        response['Access-Control-Allow-Origin'] = 'null'
        response['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        return response
    try:
        stream = open_report(deliverable_relative(item, path))
    except (OSError, ValueError):
        raise Http404
    media_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    if path.lower().endswith(('.js', '.mjs')):
        media_type = 'text/javascript'
    if path.lower().endswith(('.md', '.markdown')):
        try:
            stream = render_markdown(stream, path)
        except (ValueError, UnicodeError):
            return HttpResponse('Markdown must be UTF-8 and no larger than 8 MB. Download the original file to read it.', status=422)
        media_type = 'text/html; charset=utf-8'
    if path in {report['path'] for report in item.reports}:
        response = StreamingHttpResponse(with_keyboard_bridge(stream), content_type=media_type)
    else:
        response = FileResponse(stream, content_type=media_type)
    response['Content-Security-Policy'] = f"frame-ancestors {settings.PORTAL_ORIGIN}; sandbox allow-scripts allow-downloads"
    # Sandboxed reports have Origin: null. Only this authorized capability URL
    # permits CORS; portal pages never do, and no cookies are needed for assets.
    response['Access-Control-Allow-Origin'] = 'null'
    return response

@login_required
def download_file(request, pk, path):
    item = authorized_deliverable(request.user, pk)
    if path not in item.files:
        raise Http404
    try:
        stream = open_report(deliverable_relative(item, path))
    except (OSError, ValueError):
        raise Http404
    db().audit(request.user, 'file_download', f'{pk}/{path}')
    response = FileResponse(stream, as_attachment=True, filename=path.rsplit('/', 1)[-1], content_type='application/octet-stream')
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response

@login_required
def download_project(request, pk):
    project = db().project(pk)
    if not project or not can_access(request.user, project.pi):
        raise Http404
    deliveries = [item for item in db().deliverables(project.pk) if published_visible(item)]
    if not deliveries:
        raise Http404
    try:
        path = build_project_zip(project, deliveries)
    except ZipBusy:
        return HttpResponse('Another archive is being prepared. Retry shortly.', status=503, headers={'Retry-After': '5'})
    except (ValueError, OSError):
        return HttpResponse('Archive unavailable; ask the administrator to refresh this project.', status=409)
    db().audit(request.user, 'project_zip_download', str(pk))
    return FileResponse(path.open('rb'), as_attachment=True, filename=f'{project.folder}.zip', content_type='application/zip')


@login_required
def download_zip(request, pk):
    item = authorized_deliverable(request.user, pk)
    try:
        path = build_zip(item)
    except ZipBusy:
        return HttpResponse('Another archive is being prepared. Retry shortly.', status=503, headers={'Retry-After': '5'})
    except (ValueError, OSError):
        return HttpResponse('Archive unavailable; ask the administrator to refresh this deliverable.', status=409)
    db().audit(request.user, 'zip_download', pk)
    return FileResponse(path.open('rb'), as_attachment=True, filename=f'{item.project.folder}-{item.folder}.zip', content_type='application/zip')

@admin_required
@require_POST
def refresh(request):
    try:
        count, errors = scan_reports()
    except ValueError as exc:
        return HttpResponse(str(exc), status=503, content_type='text/plain')
    db().audit(request.user, 'reports_refreshed', f'{count} indexed; {len(errors)} errors')
    if errors:
        return HttpResponse('\n'.join(errors), status=409, content_type='text/plain')
    if request.POST.get('return_to') == 'admin':
        tab = request.POST.get('return_tab', '')
        return redirect(reverse('accounts') + ('#' + tab if tab in {'projects', 'deliverables'} else ''))
    return redirect('home')

def health(request):
    db().query('SELECT 1')
    return JsonResponse({'status': 'ok', 'database': 'duckdb'})
