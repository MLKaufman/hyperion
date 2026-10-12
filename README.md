# Hyperion

A read-only Quarto delivery portal with local accounts, PI-level access, and automatically discovered reports and supplemental files.

- **DuckDB** stores accounts, sessions, PI assignments, report indexes, and audit events. No PostgreSQL or SQLite backend is used.
- **uv** manages the environment and dependencies through `pyproject.toml` and `uv.lock`.
- Django provides routing, forms, templates, password hashing, and CSRF protection. The app uses a DuckDB repository and custom account screens rather than Django's ORM/admin.
- Reports stay outside the application, mounted read-only.

See [implementation.md](implementation.md) for the design and remaining production work.

## Run with Docker (recommended)

Start Docker Desktop, then run from this directory:

```sh
./run.sh
./run.sh admin admin
```

The first command builds both images, starts the app and Caddy, and waits for healthy containers. The second prompts for your administrator password; it temporarily stops the app so DuckDB has only one owner, then restarts it even if account creation fails. No default password is created.

Administrator passwords must have at least 12 characters and must not be common or entirely numeric. The command now reports the specific policy failure. If the username already exists, it stops before asking for a password and leaves that account unchanged.

Open [Hyperion locally](http://portal.hyperion.localhost:8080). Local mode binds only to `127.0.0.1` and uses HTTP without certificates. The existing sample report tree is mounted read-only. The launcher creates a private `.env.local` containing a random secret; edit its `REPORTS_HOST_PATH` to use your own reports or `HYPERION_PORT` to change the port, then rerun the launcher. Keep local hostname resolution requirements below in mind.

```sh
./run.sh status
./run.sh logs
./run.sh stop        # Preserves database volumes
./run.sh build       # Build without starting
```

You can invoke the script by its full path from another directory. Local and production use separate Compose project names and volumes. Production requires the existing `.env` and TLS/DNS setup below:

```sh
./run.sh --production
./run.sh --production admin admin
```

Docker with Compose v2 and Bash are required; first-time local setup also uses `openssl`. Host Python and uv are not required for the container workflow.

## Local development

Install uv, then:

```sh
uv sync --locked
export DEBUG=1
uv run python manage.py createadmin admin
uv run python manage.py sync_reports
RUN_SCANNER=1 uv run python manage.py runserver 127.0.0.1:8000 --noreload
```

Open http://portal.hyperion.localhost:8000. Admin-created accounts receive temporary passwords and must change them on first login. Administration manages accounts and their PI assignments; administrators see every PI.

Reports use `pi-<PI UUID>.reports.hyperion.localhost:8000`. The portal and report hostnames must resolve to loopback. Some browsers resolve `.localhost` automatically; others need local DNS or hosts entries for the portal and each PI hostname. Use a common parent site for both hosts, with distinct origins. Do not change only the portal URL to `127.0.0.1` or `localhost`.

Set `REPORTS_ROOT` to an external directory and `DUCKDB_PATH` to the desired database file. Defaults are `sample_reports/` and `data/hyperion.duckdb`. Synthetic fixtures contain no real bioinformatics results, and no default passwords or accounts are supplied.

```sh
DEBUG=1 uv run python manage.py test
```

## One database owner

The application runs **one Gunicorn worker with multiple request threads**. That process owns the DuckDB file. A serialized repository protects database transactions; discovery and cleanup run in a background thread in the same process.

Do not add Gunicorn workers, preload the application, run multiple replicas against the same file, or run database management commands while the server is active. DuckDB rejects another read-write process opening its active file. Use the web administrator screens while the server is running. Stop the app before using `createadmin`, `sync_reports`, or `cleanup_portal` from the command line.

The schema is initialized automatically and explicitly versioned. Django `migrate` and `createsuperuser` are not used. The previous prototype's SQLite file, if present, is left untouched and is not read; existing prototype accounts would need an explicit migration. Folder indexes can simply be rediscovered.

## Automatic discovery

```text
reports/
  smith-lab/
    rnaseq-study/
      01-initial-analysis/
        report.html
        qc.html
        report_files/
        figures/volcano.png
        figures/pathways.svg
        tables/results.csv
        summary.pdf
        cells.cloupe
      02-cell-browser/
        revised-cells.cloupe
```

No metadata file is needed. Folder names provide PI/project/deliverable titles, filenames provide document titles, and natural numeric sorting provides order. The first HTML report opens by default, using natural deliverable and report order. The left sidebar is a flat list of HTML reports; the Files menu in the single compact top bar provides supplemental downloads and supplemental-only packages. HTML under resource directories such as `*_files`, `site_libs`, `libs`, and `assets` is not listed as a primary report. Reports in `figures` or `tables` are also treated as resources.

PNG, PDF, SVG, CSV, TSV, `.cloupe`, and other allowed formats are discovered recursively as supplements. Supporting files in `figures/` and `tables/` are listed; files inside Quarto resource directories remain available to reports and ZIPs without cluttering the sidebar. Extension matching is case-insensitive. A deliverable containing only supplemental files is supported.

`.cloupe` files are downloads for Loupe Browser, not rendered in the web viewer. The portal does not parse or rewrite them. Other supplemental files are likewise available as individual downloads. The allowlist is in `portal/storage.py`; unfamiliar types are excluded until explicitly added.

**Publication:** projects and deliverables are discovered and enabled by default. No `.ready` markers are required; existing markers are ignored. Use Administration to disable or enable visibility. Copy completed folders into place using an atomic rename from a staging directory outside the watched report root. Refresh report folders to scan immediately, or wait for the automatic scan. Validation and PI authorization still apply.

`metadata.json` is reserved for a future optional extension; it is currently ignored and excluded from serving and ZIPs. The early prototype's `deliverable.json` is also ignored/excluded. Hidden files, source code, and symlinks are not published. Relative assets must remain within their deliverable.

Scans run every 60 seconds by default and can be requested from the dashboard. They hash supported files; tune `SCAN_INTERVAL` for large trees. `MAX_DELIVERABLE_BYTES` defaults to 256 MiB and can be raised for larger `.cloupe` packages.

## Access and report isolation

- Each PI has a distinct report hostname. Portal session cookies are host-only; production cookies use the `__Host-` prefix.
- A CSRF-protected POST issues a single-use, 60-second launch ticket. Its redemption sets a one-hour, HTTP-only content cookie scoped to the deliverable.
- Every content request checks the active account, PI membership, parent login session, and publication state. Password changes, logout, account deletion, and admin access changes revoke sessions/grants.
- The sandboxed iframe permits scripts, same-origin resource fetching, and downloads. Report scripts never run on the portal origin. Isolation is per PI; reports within one PI share that PI's origin.
- Downloads from the portal are forced attachments. File paths must appear in the indexed inventory and are opened using directory descriptors with no-follow flags.
- Account and IP login throttles are persisted in DuckDB. Caddy overwrites the trusted client-IP header; the app port must remain private.
- ZIP generation uses disk-backed streaming and a file lock, retaining caches for up to 24 hours. Downloads always pass authorization first.
- Audit events record account actions, access changes, sign-ins, and downloads. Request logs exclude ticket query strings.

Already downloaded data cannot be recalled by revoking access. Bundle trusted report dependencies where practical; external scripts execute with the permissions of their PI's report origin.

## Docker Compose

1. Copy `.env.example` to `.env` and set a long random `SECRET_KEY`.
2. Set portal/report origins and the matching Caddy host variables.
3. Point portal DNS and wildcard report DNS to the server.
4. Obtain the wildcard report certificate with ACME DNS validation. Put `fullchain.pem` and `privkey.pem` in `CERTS_HOST_PATH`. Caddy manages the portal certificate; wildcard certificate renewal is currently external to the app.
5. Set `REPORTS_HOST_PATH` to the external tree, readable by container UID 10001.

Bootstrap before starting the server:

```sh
docker compose build
docker compose run --rm app uv run --no-sync python manage.py createadmin admin
docker compose up -d
```

Compose runs only the app and Caddy. The app stores DuckDB in the persistent `duckdb_data` volume and ZIP caches separately. There is no database server, migration container, or separate scanner process.

```sh
docker compose logs --tail=100 app
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

For offline account recovery, stop the app first, then run `createadmin` with a new username. Do not run database commands using `docker compose exec` while the application owns the file.

## Backup and recovery

Use encrypted host storage and encrypted backups. Back up the external reports, protected configuration/secrets, and the entire DuckDB data directory. Stop the app before copying DuckDB so the database and any WAL file form a consistent set. ZIP caches are disposable.

```sh
docker compose stop app
# Choose a new backup destination each time.
docker compose cp app:/data ./backup-data
docker compose start app
```

For restoration, keep the app stopped, restore the data directory (including any WAL) to its volume, preserve ownership for UID 10001, restore the report tree/configuration, and start one app process. Validate accounts, PI assignments, a report with assets, and a ZIP before exposing the host. Never run `docker compose down -v` when retaining the database matters.

## Verification

51 automated tests pass, covering DuckDB persistence and transaction rollback, account administration, PI isolation, session revocation, ticket concurrency, discovery without metadata, supplemental-only deliveries, `.cloupe` downloads, and a 100 MB ZIP. Locked/offline uv synchronization, Django checks, sample discovery, and Compose configuration validation pass. Both images build successfully; local app and Caddy health checks pass, login/CSS return HTTP 200, and the original 43-test suite also passed inside the Linux app container.

## Remaining release checks

Admin MFA, actual Quarto/browser compatibility, encrypted storage/backups, and a restore drill remain prerequisites for public deployment. Production Django checks may report optional HSTS include-subdomains/preload settings; choose these according to the domain's HTTPS policy. The remaining browser validation work is recorded in `implementation.md`.

### Publication controls and Markdown

Administration has separate Projects and Deliverables tables. Select rows (or select all), then click Enable or Disable to apply the setting immediately. Projects are the immediate folders beneath investigator/lab folders. New items and former Auto settings are enabled by default. Existing Disabled settings remain disabled. A disabled project blocks every deliverable, and a disabled deliverable stays blocked when its project is enabled. Settings persist across scans and restarts; access changes revoke content grants.

Markdown `.md` and `.markdown` files are listed alongside HTML reports. UTF-8 Markdown up to 8 MB renders with headings, tables, lists, code blocks, relative links and images. Raw HTML is escaped and unsafe URL schemes are rejected. Report assets retain the same authenticated PI isolation. ZIPs and file downloads contain the original Markdown. Example: `smith-lab/rnaseq-pilot/01-initial-analysis/03-markdown-example.md`.
