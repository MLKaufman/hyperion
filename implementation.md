# Hyperion implementation

## Current deployment

One image, one Gunicorn worker with request threads, one hostname. WhiteNoise
serves application static files. The container entrypoint atomically persists a
private signing key, bootstraps a temporary-password administrator only for an
empty database, closes DuckDB, and execs Gunicorn. The worker owns
the database and background scanner. Compose needs only the report mount and a
persistent data volume. The seq-space repository provides Traefik/Cloudflare
routing and stable trusted proxy addresses.

## Authorization and content boundary

Django supplies CSRF protection, forms, templates, and password hashing. DuckDB
stores users, host-only sessions, PI assignments, report indexes, grants, and
audit events; there is no Django ORM backend. Every content request checks a
short-lived capability plus its current parent session and PI/publication
permissions. Capabilities are scoped to one deliverable and redacted from
application logs. Portal sessions alone cannot fetch report content.

Both the iframe attribute and the HTTP CSP apply an opaque-origin sandbox
without allow-same-origin. This replaces the old PI-subdomain architecture.
Report scripts can run and fetch relative assets through capability-only CORS;
they cannot access portal DOM/storage or read authenticated portal responses.
Some widgets depending on origin storage or service workers require adaptation.

## Reports and persistence

The external read-only hierarchy remains PI / project / deliverable. Discovery
uses filenames and natural ordering, excludes unsafe paths/symlinks/source files,
and enables valid new reports without markers. Admin disable controls override
discovery. HTML/Markdown viewers, supplements, project/deliverable ZIP downloads,
publication controls, keyboard shortcuts, and account management are retained.

The existing schema and volume key are retained. No account migration or database
reset is necessary. Old report URLs must be relaunched after upgrade. State and
secret must be backed up together with the app stopped. Do not scale workers or
replicas sharing a DuckDB volume. Administrative MFA remains unimplemented.

## Validation

See README.md for reproducible checks. The single-host work adds tests for
bootstrap idempotency, private persistent secrets, existing-account preservation,
forwarded-header spoof resistance, opaque-origin CORS, and CSRF rejection from
report frames, in addition to the existing authorization and download suite.

The implementation was checked with 73 passing backend tests and three keyboard
JavaScript tests. An isolated Docker deployment verified first login, mandatory
password change, deletion of initial credentials, report assets without cookies,
ZIP downloads, and capability-log redaction. Browser checks verified relative
JavaScript/fetch/CSS and blocked portal DOM, cookie, storage, and CORS access.
An isolated seq-space Compose deployment verified HTTPS through the trusted
tunnel hop and Traefik, secure cookies, and rejection of a spoofed scheme from
an untrusted direct client. No live homelab or existing local deployment was
modified by these tests. Actual report-specific widget compatibility still
requires testing with the user's reports.
