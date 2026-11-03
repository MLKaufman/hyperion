# Hyperion

A single-container research report portal. Point it at your reports folder and
run Docker Compose. One hostname serves the application and all reports; Caddy,
PI subdomains, a separate database server, and manually generated secrets are
not required.

## Start

```sh
git clone https://github.com/MLKaufman/hyperion.git
cd hyperion
REPORTS_HOST_PATH=/absolute/path/to/reports docker compose up -d --build
```

Open **http://localhost:8000**. For persistent configuration, copy `.env.example`
to `.env` and set `REPORTS_HOST_PATH`, then use `docker compose up -d --build`.
The default sample folder lets you try the app before supplying your own reports.
Docker Compose v2.20+ is required for the optional `compose.local.yaml` alias.

The image automatically:

- Generates a private persistent signing key in `/data/secret-key`.
- Initializes DuckDB and creates `admin` only when the database has no accounts.
- Generates a random initial password, stored with mode 0600 in the data volume.
- Starts one application worker with background report discovery and periodic rescans.
- Serves its own CSS/JavaScript through WhiteNoise.

Read the initial login on the server:

```sh
docker compose exec app cat /data/initial-admin.json
```

Sign in and change the password when prompted. The initial credential file is
removed after that password change. Restarting or upgrading does not reset
accounts or passwords. There is no public first-visitor setup screen and no
shared default password. Use Administration to create accounts and assign PIs.

`./run.sh` is an optional wrapper around Compose; setup lives inside the image,
so plain Compose and `docker run` work equally well. `./run.sh credentials`
displays the initial credentials. `--production` retains the legacy `hyperion`
Compose project name; local mode retains `hyperion-local`.

## Reports folder

```text
reports/
  smith-lab/
    rnaseq-study/
      01-analysis/
        report.html
        report_files/
        figures/volcano.png
        tables/results.csv
      02-revision/
        report.html
  chen-lab/
    another-project/
      01-results/
        report.md
        cells.cloupe
```

The hierarchy is **PI/lab → project → deliverable → report and supporting files**.
Folder/file names provide titles. HTML and Markdown are report documents;
PNG, PDF, CSV, TSV, `.cloupe`, and other supported files are downloadable
supplements. Supplemental-only deliverables are supported. Bundle relative
report assets inside their deliverable. No metadata or publication marker is
required. Symlinks, hidden files, and source code are not published.

The report mount is read-only. Its directories must be traversable and its files
readable by container UID **10001**; grant read/traverse access using your host's
normal permissions or ACLs. An absent mount fails startup instead of silently
creating an empty folder. Put completed reports into place with an atomic rename
from staging. New valid reports are enabled automatically; Administration can
disable projects or individual deliverables.

## One hostname behind Traefik / Cloudflare

The **seq-space repository supplies the full integration**: one Hyperion service,
its volume, hostname label, and trusted proxy network. It builds this repository
locally, so publishing an image to Docker Hub is optional.

For other proxies:

- Set `PUBLIC_URL=https://hyperion.example.com` to the one public origin.
- Attach the app to the proxy's Docker network; route to container port **8000**.
- Set `TRUSTED_PROXY_CIDRS` to the specific proxy addresses. The proxy must
  overwrite or sanitize forwarded headers from untrusted clients.
- Forward `X-Forwarded-Proto` and `X-Forwarded-For`. The application accepts them
  only from trusted peers and finds the client by walking past trusted hops.
- Do not publish the app's port publicly when a proxy handles access.
- Disable caching for authenticated app/report responses. They already send
  `Cache-Control: private, no-store`; avoid rules that override this.
- Keep proxy access logs off for `/content/`, or redact the path and query string.
  Those URLs contain expiring report capabilities. Application logs redact them.

HTTP is supported for local/LAN use by choosing an HTTP `PUBLIC_URL`. Cookie
security and HTTPS redirects follow that URL, independently of `DEBUG`. Public
hosting should use HTTPS. With direct LAN access, set `HYPERION_BIND=0.0.0.0`
and `PUBLIC_URL` to the actual hostname/IP and port visitors use.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_URL` | `http://localhost:8000` | One origin, no path |
| `REPORTS_HOST_PATH` | `./deliverables` | Compose host report directory |
| `HYPERION_PORT` | `8000` | Compose host port |
| `HYPERION_BIND` | `127.0.0.1` | Compose host binding |
| `TRUSTED_PROXY_CIDRS` | empty | Trusted proxy addresses, comma-separated |
| `MAX_DELIVERABLE_BYTES` | `268435456` | Per-deliverable size limit (256 MiB) |
| `SCAN_INTERVAL` | `60` | Seconds between discovery scans |

Inside the image, `/reports` is the read-only report mount and `/data` stores the
secret, database, and disposable ZIP cache. Advanced overrides include
`DATA_DIR`, `DUCKDB_PATH`, `ZIP_CACHE_ROOT`, and `REPORTS_ROOT`. `PORTAL_ORIGIN`
remains an alias for `PUBLIC_URL`. An explicitly supplied `SECRET_KEY` is
persisted on first boot; subsequent starts reject a different supplied key.

For `docker run`, after building the image:

```sh
docker build -t hyperion:local .
docker run -d --name hyperion -p 127.0.0.1:8000:8000 \
  --mount type=bind,src=/absolute/path/to/reports,dst=/reports,readonly \
  --mount type=volume,src=hyperion-data,dst=/data \
  hyperion:local
docker exec hyperion cat /data/initial-admin.json
```

## Report isolation on one hostname

Accounts and PI assignments still control every report, asset, and download.
A CSRF-protected launch creates a one-time ticket, redeemed for an unpredictable,
per-deliverable URL valid for one hour. Each request rechecks the parent session,
PI membership, publication state, and account status. Logout and access changes
revoke it. Portal cookies do not authorize content URLs.

Reports execute in an **opaque-origin sandbox**: scripts and downloads are
allowed, but access to the portal DOM, cookies, and browser storage is blocked.
A response-level sandbox also applies when someone opens a report URL directly.
Only authorized report assets accept CORS from the sandbox's `null` origin.
Portal pages never grant CORS to reports. The keyboard bridge checks the sending
window and opaque origin; the only parent-to-report message is a scroll command.

Relative scripts, styles, images, and `fetch()` resources work. Reports relying
on localStorage, service workers, parent-frame DOM access, popups, or credentialed
cross-origin requests may need adaptation. Do not add `allow-same-origin` to
work around this: it would remove the separation from account pages. Original
files remain available in downloads. Test your actual Quarto widgets before
sharing a new report format.

## Upgrade an existing two-container installation

Back up the existing data first. Keep the **same Compose project name** and
`duckdb_data` volume to retain accounts and PI assignments. The new Compose file
retains that volume key. Stop the old app before the new one opens its database:

```sh
docker compose -p hyperion stop app caddy
docker compose -p hyperion up -d --build --remove-orphans
```

Use `-p hyperion-local` instead for the old local launcher deployment. Set the
new `PUBLIC_URL` (and matching port) in `.env` or `.env.local`. If preserving an
explicit old signing key, temporarily add `SECRET_KEY` to the app's environment
on its first startup; it will then live in `/data/secret-key`. Existing accounts
are retained even when a new signing key is generated. Old report tickets/URLs
are invalid; reload the viewer. Old Caddy/cache volumes can remain untouched.

## Administration, backup, and recovery

One Gunicorn worker owns DuckDB. Do not scale replicas/workers against the same
volume. The startup script closes its bootstrap database connection before
starting the server; no manual bootstrap ordering is needed.

For offline recovery, `./run.sh admin NEW_USERNAME` stops the app, prompts for a
new administrator password, and restarts the app. Use `--production` when
appropriate. Do not use Django `migrate` or `createsuperuser`.

Back up your reports and all of `/data`, including the secret and any DuckDB WAL.
Stop the app while copying the database; never use `docker compose down -v` when
retaining data matters. Preserve UID 10001 ownership when restoring.

```sh
docker compose stop app
docker compose cp app:/data ./backup-data
docker compose start app
```

Use encrypted storage/backups appropriate to your reports. Administrative MFA
is not implemented. Access revocation cannot recall previously downloaded data.

## Development checks

```sh
DEBUG=1 RUN_SCANNER=0 uv run --locked python manage.py test
node --test tests/keyboard.test.cjs
docker compose config --quiet
```

Tests cover PI authorization, grant replay/expiry/revocation, safe paths, ZIPs,
publication controls, automatic bootstrap, persistent secrets, proxy trust, and
single-host report isolation. The image serves `/health/` and includes its own
Docker health check. No live database is used by the test suite.

### Project nicknames and file size exclusions

In **Administration → Projects**, select **Edit nickname** to set a project's
name on dashboard buttons and in the report sidebar. The original folder name
remains visible in administration. Clearing the nickname restores the name
derived from the folder. Scans preserve nicknames; paths and URLs do not change.

By default, individual files larger than **120 MiB (125,829,120 bytes)** are automatically
excluded from scanning, report lists, supplemental files, and ZIP downloads.
Files exactly at the limit are included. Excluded files remain on disk, and other
files in the same deliverable can still be published. The existing 256 MiB total
per-deliverable limit counts only included files. Reports that depend on excluded
assets may have missing content. Use **Refresh report folders** to update existing
inventories immediately after deployment.

Administration lists only current project folders directly beneath each PI and
current deliverable folders beneath those projects. Removed folders disappear
from the admin lists on page reload. The next scan (normally every 60 seconds,
or **Refresh report folders**) unpublishes removed deliverables. Stored records
are retained so restoring the same folder path preserves its nickname, IDs, and
visibility settings. Renaming or moving a folder creates a new identity.

Project nicknames support literal `\n` for line breaks, for example
`scRNAseq\nJanuary 2025`. Breaks appear on project buttons, in the sidebar,
and in the administration nickname column. Edit fields retain the `\n` text.

### Administration settings

**Administration → Settings** persists these options in DuckDB across restarts:

| Setting | Default | Allowed range |
| --- | --- | --- |
| Maximum supplemental file size | 120 MiB | 1–10,240 MiB |
| Maximum total deliverable size | `MAX_DELIVERABLE_BYTES` (normally 256 MiB) | 1–102,400 MiB |
| Automatic scan interval | `SCAN_INTERVAL` (normally 60 seconds) | 10–86,400 seconds |
| Exclusion patterns | None | Up to 100 patterns, 200 characters each |

Saved values override environment defaults. The scan interval is the delay after
one scan finishes before the next begins. Saving settings wakes the automatic
scanner and requests a new scan without a container restart. With automatic
scanning disabled, use **Refresh report folders** or **Scan now** instead.

Exclusions use case-sensitive shell wildcards, one per line, relative to each
deliverable. A pattern without a slash matches a filename or directory name at
any depth. A pattern with a slash matches the relative path (`*` can span slashes).
Directory matches exclude all descendants. Examples:

```text
*.rds
intermediate/
tables/private-*
```

Blank lines are ignored. Clearing the field removes custom exclusions. Built-in
exclusions for hidden/internal files, unsupported types, and symlinks remain.
Excluding a report asset can cause missing content in the rendered report.

The supplemental limit uses the same classification as the Supplemental menu.
HTML/Markdown reports and embedded assets retain the separate 120 MiB limit.
Only included files count toward the total deliverable size; exceeding that
total withholds the entire deliverable. Files exactly at a limit are accepted.
Restrictions apply immediately to access and downloads, including cached ZIPs.
Newly eligible files appear after scanning. Originals are never deleted.

**Administration → Scan diagnostics** shows the latest scan's start/end times,
status, published-deliverable count, and skipped paths with reasons. It includes
size and pattern exclusions, hidden/internal files, unsupported types, symbolic
links, disabled folders, and validation or filesystem errors. Directory entries
represent their full subtree. The latest snapshot persists across restarts;
up to 2,000 entries are retained with a count of omitted entries. Refresh the
page to see a background scan's results, or use **Scan now**. Diagnostics are
administrator-only and are replaced by the next scan rather than accumulating.

Schema version 3 adds the settings table automatically while preserving accounts,
access rules, and project nicknames.

Scan diagnostics can be filtered by PI/lab, project, and skip-reason category.
Filters combine, update immediately, and apply to the retained snapshot entries.
Project choices narrow to the selected PI; **Clear filters** restores all entries.
Scan-wide errors remain visible with All PIs / All projects selected.
