from portal.db import db


def mode(kind, pk):
    row = db().one('SELECT mode FROM publication_controls WHERE kind=? AND target_id=?', [kind, str(pk)])
    # Legacy Auto settings now mean enabled, just like newly discovered folders.
    return 'disabled' if row and row.mode == 'disabled' else 'enabled'


def eligible(project_id, deliverable_id):
    return mode('project', project_id) != 'disabled' and mode('deliverable', deliverable_id) != 'disabled'
