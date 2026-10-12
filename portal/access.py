import time
from django.http import Http404
from portal.db import db
from portal.auth import can_access, session_user, digest as secret_digest
from portal.storage import safe_path, deliverable_relative
from portal.publication import eligible


def published_visible(deliverable):
    if not deliverable or not deliverable.published:
        return False
    try:
        safe_path(deliverable_relative(deliverable))
        return eligible(deliverable.project_id, deliverable.id)
    except (ValueError, OSError):
        return False

def authorized_deliverable(user, pk):
    item = db().deliverable(pk)
    if not published_visible(item) or not can_access(user, item.project.pi):
        raise Http404
    return item

def valid_grant(grant):
    if not grant or not grant.user or not grant.deliverable or grant.expires_at <= time.time():
        return False
    if grant.user.must_change_password or not can_access(grant.user, grant.deliverable.project.pi) or not published_visible(grant.deliverable):
        return False
    user = session_user(grant.session_key)
    return bool(user and user.id == grant.user_id)
