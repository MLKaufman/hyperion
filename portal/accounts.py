import duckdb
from datetime import datetime, timezone
from django import forms
from portal.site_settings import supplemental_limit_bytes, total_limit_bytes, scan_interval_seconds, exclusion_patterns
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect
from django.urls import reverse
from portal.auth import admin_required, create_user, revoke_user
from portal.db import db
from portal.discovery import folder_status, scan_reports, current_projects
from portal.publication import mode
from portal.scan_diagnostics import latest_scan, filter_choices

class SiteSettingsForm(forms.Form):
    max_supplemental_mib = forms.IntegerField(
        label='Maximum supplemental file size (MiB)', min_value=1, max_value=10240,
        help_text='Default: 120 MiB. Files above this size are excluded; originals stay on disk.')

    max_deliverable_mib = forms.IntegerField(
        label='Maximum total deliverable size (MiB)', min_value=1, max_value=102400,
        help_text='Only included files count. A deliverable exceeding this total is not published.')
    scan_interval_seconds = forms.IntegerField(
        label='Automatic scan interval (seconds)', min_value=10, max_value=86400,
        help_text='Delay between scans, from 10 seconds to 24 hours. Changes apply without restarting.')
    exclusion_patterns = forms.CharField(required=False, max_length=20000,
        widget=forms.Textarea(attrs={'rows': 5, 'placeholder': '*.rds\nintermediate/\ntables/private-*'}),
        help_text='One case-sensitive glob per line, relative to each deliverable. Examples: *.rds, intermediate/, tables/private-*. Directory matches exclude all contents.')

    def clean_exclusion_patterns(self):
        patterns = list(dict.fromkeys(line.strip() for line in self.cleaned_data['exclusion_patterns'].splitlines() if line.strip()))
        if len(patterns) > 100:
            raise forms.ValidationError('Use at most 100 patterns.')
        for pattern in patterns:
            if len(pattern) > 200 or pattern.startswith('/') or '\\' in pattern or '..' in pattern.split('/'):
                raise forms.ValidationError('Use relative patterns up to 200 characters, with forward slashes and no .. components.')
        return '\n'.join(patterns)


class AccountForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, label='Temporary password')
    administrator = forms.BooleanField(required=False)
    pis = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label='PI access')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pis'].choices = [(p.id, p.name) for p in db().query('SELECT * FROM pis ORDER BY name')]

class AccessForm(forms.Form):
    active = forms.BooleanField(required=False)
    administrator = forms.BooleanField(required=False)
    pis = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label='PI access')
    temporary_password = forms.CharField(required=False, widget=forms.PasswordInput, help_text='Leave blank to keep the current password.')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pis'].choices = [(p.id, p.name) for p in db().query('SELECT * FROM pis ORDER BY name')]


class ProjectNicknameForm(forms.Form):
    nickname = forms.CharField(max_length=150, required=False, help_text=r'Type \n for a line break. Leave blank to use the folder name.')


@admin_required
def project_edit(request, pk):
    project = db().project(pk)
    if not project:
        raise Http404
    default = project.folder.replace('-', ' ')
    form = ProjectNicknameForm(request.POST if request.method == 'POST' else None,
                               initial={'nickname': project.title if project.title != default else ''})
    if request.method == 'POST' and form.is_valid():
        title = form.cleaned_data['nickname'] or default
        with db().transaction():
            db().execute('UPDATE projects SET title=? WHERE id=?', [title, project.id])
            db().audit(request.user, 'project_renamed', project.id)
        return redirect(reverse('accounts') + '#projects')
    return render(request, 'portal/project_edit.html', {'form': form, 'project': project})


def set_memberships(user_id, pi_ids):
    db().execute('DELETE FROM memberships WHERE user_id=?', [user_id])
    for pi_id in pi_ids:
        db().execute('INSERT INTO memberships VALUES (?, ?)', [user_id, pi_id])

@admin_required
def accounts(request):
    editing_settings = request.method == 'POST' and request.POST.get('action') == 'settings'
    settings_form = SiteSettingsForm(request.POST if editing_settings else None,
                                    initial={'max_supplemental_mib': supplemental_limit_bytes() // (1024 * 1024),
                                             'max_deliverable_mib': total_limit_bytes() // (1024 * 1024),
                                             'scan_interval_seconds': scan_interval_seconds(),
                                             'exclusion_patterns': '\n'.join(exclusion_patterns())})
    if editing_settings and settings_form.is_valid():
        with db().transaction():
            for key, value in settings_form.cleaned_data.items():
                db().execute('INSERT INTO site_settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             [key, str(value)])
            db().audit(request.user, 'settings_updated', str(settings_form.cleaned_data))
        from portal.maintenance import settings_changed
        settings_changed.set()
        return redirect(reverse('accounts') + '?settings_saved=1#settings')
    form = AccountForm(request.POST if request.method == 'POST' and not editing_settings else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with db().transaction():
                user = create_user(form.cleaned_data['username'], form.cleaned_data['password'], form.cleaned_data['administrator'])
                set_memberships(user.id, form.cleaned_data['pis'])
                db().audit(request.user, 'account_created', user.id)
            return redirect(reverse('accounts') + '#accounts')
        except ValidationError as exc:
            form.add_error(None, exc)
        except duckdb.ConstraintException:
            form.add_error('username', 'That username already exists.')
    folders, folder_error = folder_status()
    projects = []
    for row in current_projects():
        row.mode = mode('project', row.id)
        row.state = 'Disabled' if row.mode == 'disabled' else 'Enabled'
        projects.append(row)
    account_rows = db().query('''SELECT u.id, u.username, u.is_active, u.is_superuser,
        u.must_change_password, l.last_login FROM users u LEFT JOIN
        (SELECT actor, max(occurred_at) AS last_login FROM audit WHERE action='login' GROUP BY actor) l
        ON l.actor=u.id ORDER BY u.username''')
    memberships = {}
    for membership in db().query('SELECT m.user_id, p.name FROM memberships m JOIN pis p ON p.id=m.pi_id ORDER BY p.name'):
        memberships.setdefault(membership.user_id, []).append(membership.name)
    for account in account_rows:
        account.pi_names = memberships.get(account.id, [])
        account.last_login = datetime.fromtimestamp(account.last_login, timezone.utc) if account.last_login is not None else None
    return render(request, 'portal/accounts.html', {'settings_form': settings_form, 'settings_saved': request.GET.get('settings_saved') == '1', 'diagnostics': filter_choices(latest_scan()), 'form': form, 'folders': folders, 'projects': projects, 'folder_error': folder_error, 'accounts': account_rows})


@admin_required
@require_POST
def publication_update(request, kind, pk):
    return change_publication(request, kind, [str(pk)])


@admin_required
@require_POST
def publication_bulk(request, kind):
    return change_publication(request, kind, list(dict.fromkeys(request.POST.getlist('selected'))))


def change_publication(request, kind, ids):
    if kind not in {'project', 'deliverable'}:
        raise Http404
    if not ids or len(ids) > 1000:
        return HttpResponseBadRequest('Select between 1 and 1000 rows.')
    setting = request.POST.get('mode')
    if setting not in {'enabled', 'disabled'}:
        return HttpResponseBadRequest('Unknown publication setting')
    with db().transaction():
        # Validate the complete selection before changing any row.
        for pk in ids:
            target = db().project(pk) if kind == 'project' else db().deliverable(pk)
            if not target:
                raise Http404
        for pk in ids:
            db().execute('INSERT INTO publication_controls VALUES (?, ?, ?) ON CONFLICT(kind, target_id) DO UPDATE SET mode=excluded.mode', [kind, pk, setting])
            if kind == 'project':
                db().execute('DELETE FROM grants WHERE deliverable_id IN (SELECT id FROM deliverables WHERE project_id=?)', [pk])
            else:
                db().execute('DELETE FROM grants WHERE deliverable_id=?', [pk])
            db().audit(request.user, 'publication_updated', f'{kind}/{pk}: {setting}')
    # Enable validates and indexes immediately; read-time policy also blocks
    # disabled content even while a background scan is finishing.
    scan_reports()
    return redirect(reverse('accounts') + ('#projects' if kind == 'project' else '#deliverables'))

@admin_required
def account_edit(request, pk):
    target = db().user(pk)
    if not target:
        raise Http404
    initial = {'active': target.is_active, 'administrator': target.is_superuser, 'pis': [p.pi_id for p in db().query('SELECT pi_id FROM memberships WHERE user_id=?', [target.id])]}
    form = AccessForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            if target.id == request.user.id:
                form.add_error(None, 'You cannot delete your current administrator account.')
            else:
                with db().transaction():
                    revoke_user(target.id)
                    set_memberships(target.id, [])
                    db().execute('DELETE FROM users WHERE id=?', [target.id])
                    db().audit(request.user, 'account_deleted', target.id)
                return redirect(reverse('accounts') + '#accounts')
        elif form.is_valid():
            try:
                if target.id == request.user.id and (not form.cleaned_data['active'] or not form.cleaned_data['administrator']):
                    raise ValidationError('You cannot disable or demote your current administrator account.')
                password = form.cleaned_data['temporary_password']
                if password:
                    validate_password(password)
                encoded = make_password(password) if password else None
                with db().transaction():
                    db().execute('UPDATE users SET is_active=?, is_superuser=? WHERE id=?', [form.cleaned_data['active'], form.cleaned_data['administrator'], target.id])
                    set_memberships(target.id, form.cleaned_data['pis'])
                    # Every access edit revokes all sessions, including old content grants.
                    revoke_user(target.id)
                    if encoded:
                        db().execute('UPDATE users SET password=?, must_change_password=true WHERE id=?', [encoded, target.id])
                    db().audit(request.user, 'account_updated', target.id)
                return redirect(reverse('accounts') + '#accounts')
            except ValidationError as exc:
                form.add_error(None, exc)
    return render(request, 'portal/account_edit.html', {'form': form, 'account': target})
