# Hyperion implementation plan

## Agreed requirements

- Internet-facing portal for dozens of PIs and local accounts.
- External read-only `PI / project / numbered-deliverable` tree.
- Deliverables can be distinct analyses or successive revisions; expected packages around 100 MB, with configurable limits.
- Accounts link to PIs; administrators manage accounts/passwords/access and see all projects.
- Dashboard, report sidebar, home/document title/previous-next navigation, and deliverable ZIP download.
- Preserve interactive Quarto reports and relative dependencies.
- Automatically discover simple supplemental formats: PNG, PDF, SVG, CSV, TSV, `.cloupe`, etc.
- Use DuckDB for every database need and uv for environment/dependency management.
- Reserve optional `metadata.json` for future exceptions; do not require or parse metadata now.

## Architecture

Django 5.2 LTS handles HTTP, forms, CSRF, templates, and password hashing. An explicit parameterized DuckDB repository stores accounts, memberships, sessions, grants, discovery indexes, and audit events. Django's ORM, built-in admin, PostgreSQL, and SQLite are not used. Custom account screens preserve create/delete/disable/password-reset and PI-assignment functions.

`pyproject.toml` and `uv.lock` define the reproducible environment. Containers install dependencies with `uv sync --locked` and execute with `uv run --no-sync`.

One Gunicorn process owns the DuckDB file, serving concurrent request threads and an in-process discovery/cleanup thread. A shared lock serializes database operations and transactions. Do not run a separate scanner, multiple workers/replicas, or database CLI commands against the live file. Offline bootstrap/recovery commands open the same DuckDB file only while the app is stopped.

Compose runs the app and Caddy. DuckDB and ZIP caches occupy separate persistent volumes; reports remain an external read-only mount. Production uses HTTPS, portal DNS, wildcard PI report DNS, and a wildcard report certificate supplied through DNS-based issuance/renewal.

## Discovery and navigation

1. Scan PI/project/deliverable directories, excluding hidden paths and symlinks.
2. Require `.ready` to distinguish completed publication from a partially copied folder. No metadata is required.
3. Identify primary HTML outside resource directories. Use natural sorting and filename-derived titles.
4. Classify supported nontechnical formats as supplemental downloads. Quarto dependencies are served but not listed as supplements.
5. Support supplemental-only deliverables, including `.cloupe` packages.
6. Preserve filenames and relative paths in ZIPs. Future `metadata.json` may override titles/order/relationships; its current presence never controls discovery and it is not public.

Published folders should be immutable; revisions receive new numbered folders. Removing `.ready` immediately revokes content access. The scanner maintains stable IDs across rescans and unpublishes removed/invalid packages.

## Security boundary

Each PI receives a different report origin. Portal sessions use host-only cookies. A CSRF-protected launch endpoint issues a short-lived single-use ticket, redeemed for a deliverable-scoped content cookie. Every asset request checks the active user, current PI membership, parent session, and publication status.

Reports use a sandboxed iframe allowing scripts, same-origin asset access, and downloads. Report JavaScript cannot read the portal or another PI's origin. Same-PI reports share their PI origin. Downloads from the portal are attachments. Safe file-descriptor traversal rejects symlinks and path escapes.

Admin changes revoke account sessions. Passwords are hashed with Argon2. Login throttles, session state, and audit events persist in DuckDB.

## Implemented

- DuckDB repository and versioned schema; local accounts/admin screens.
- uv project/lockfile and uv-based Docker builds.
- Automatic report/supplement discovery without metadata parsing.
- `.cloupe` downloads, case-insensitive extensions, supplemental-only deliverables.
- Dashboard/viewer, per-PI origins, authenticated assets and disk-backed ZIPs.
- In-process scanning and cleanup; simplified Compose.
- Deployment, offline management, and consistent offline backup documentation.

## Validation and remaining work

**51 automated tests pass.** Tests cover authentication, PI isolation, grant replay/concurrency, revocation, CSRF, safe paths, archive contents/100 MB payloads, DuckDB persistence/rollback, account administration, metadata-free discovery, and supplemental-only packages. uv locked/offline synchronization, Django checks, sample discovery, and Compose configuration validation also pass.

Container build/startup is now verified: both local services are healthy, login/static/health HTTP checks pass, and 43 tests pass inside the Linux container. `run.sh` builds, starts, stops, displays logs/status, and safely creates administrators while the app is offline. Local mode binds loopback only and uses separate volumes from production. Full browser/real Quarto compatibility remains open from the first milestone, when embedded-browser local/custom-host connections timed out. Admin MFA, production TLS/DNS setup, encryption/backup provisioning, restore testing, and release security review remain pending.

Confirm whether reports contain identifiable or restricted human-subject data before production hosting decisions. Existing prototype SQLite data is preserved but not automatically migrated; report indexes can be rebuilt from folders, while any real prototype accounts require an explicit migration.

Folder discovery diagnostics now appear in Administration, including missing publication markers. The external sample_reports tree is excluded from Docker image builds.

Projects open the first HTML report in natural deliverable/report order. The sidebar lists only HTML reports, without folder groups; supplemental downloads live in the top-bar Supplemental menu. Previous/next navigation follows the flat report list.

The report view uses one 44-pixel, non-wrapping horizontal top bar for home, sidebar toggle, document name, previous/next, reload, Supplemental, ZIP, and account actions. Dropdowns and actionable status notices overlay the report instead of reducing its height.

CSS and JavaScript URLs include content hashes so browser caches cannot pair old assets with updated templates. Rebuilt both local containers and verified the horizontal toolbar in Chrome; all 51 automated tests pass.

Toolbar actions are ordered Supplemental, Download ZIP, previous/next, reload. ZIP and individual supplemental links open a native Save As picker when supported; other browsers use normal downloads and their location preferences. Downloads stream to the chosen file. Cancellation never initiates a fallback download, and error/sign-in responses are not written. Verified both native dialogs in Chrome and cancelled them; 51 Python tests and 5 JavaScript download tests pass (`node --test tests/downloads.test.cjs`). The built-in browser now reaches the local login page successfully.

The sidebar includes Download report beneath the project title. The project ZIP preserves project/deliverable paths and includes all published result files and assets, using the existing publication exclusions and PI authorization. Archive cache keys incorporate all included deliverable fingerprints; unpublished/withdrawn deliverables are excluded even when a previous ZIP is cached. Browser-owned Save As permission warnings cannot be customized; normal attachment downloads with the browser’s ask-for-location setting are the alternative.

The project download label is Download Project. ArrowLeft/ArrowRight follow the existing previous/next report links; ArrowUp/ArrowDown page the embedded report by 90% of its viewport. A small bridge is appended only to served report HTML, with exact origin/source checks in both directions; downloaded files remain original. Inputs, editable elements, interactive widgets, modifier combinations and already-handled events retain their own behavior. Nested embedded widgets or reports with a restrictive script CSP may retain their own keyboard behavior. Validated with 54 Python tests and 8 JavaScript tests.

Download regression fix: removed the custom File System Access Save As handler and restored standard browser attachment downloads for deliverable ZIPs, project ZIPs, and supplemental files. Save location follows the browser’s download preferences. Layout and keyboard shortcuts are unchanged.

Runtime recovery: Docker’s 59 GB disk reached 100%, causing DuckDB WAL writes to fail during report grant creation, downloads and logout. Reclaimed 2.463 GB of unused build cache without deleting images or persistent volumes, restarted the app, and verified database-backed login-attempt writes succeed again. Both containers are healthy. Monitor Docker disk space when repeatedly building images; application liveness alone did not detect this write failure.

The account menu includes About, opening an accessible modal with app name, package version, UTC container build timestamp, a description and shortcut help. Build time is recorded in the image rather than derived from startup time. Close, Escape and backdrop clicks dismiss it; report navigation shortcuts are suspended while it is open.

A clearly labeled Home button is available in the report toolbar and the shared header used by all other pages. It returns to the project dashboard.

Project `.ready` markers now enable descendant deliverables. Persistent admin Auto/Enabled/Disabled controls are available in separate project and deliverable tables, with disabled parent precedence and immediate grant revocation. Schema version 2 adds publication_controls without modifying account data. Unpublished folders are indexed as inactive records so admins can enable them. Markdown rendering uses markdown-it-py with raw HTML disabled and the existing isolated report origin/keyboard bridge. A synthetic Markdown example is included in smith-lab/rnaseq-pilot.

Validation: 59 Python tests (including marker inheritance, grant revocation, admin CSRF/authorization, Markdown rendering/original downloads, and schema migration) and 3 keyboard JavaScript tests pass. Admin tables and Markdown example were visually checked in the built-in browser using synthetic data. The live database was backed up before migration; schema v2 and example discovery were confirmed, and both containers are healthy.

Administration now uses Projects, Deliverables and Accounts tabs. Tab state is linked by URL fragments, and publication changes, refreshes, account saves and validation errors retain the relevant section. Tabs support arrow-key/Home/End navigation and accessible tab/panel semantics. Without JavaScript, all sections remain visible.

Project identity remains Investigator/Lab → Project → Deliverable. Admin project/deliverable tables now use row checkboxes, select-all with mixed state, a selection count, and immediate bulk Enable/Disable/Auto actions. Every selected ID is validated before an atomic settings update; grants are revoked per affected row and one scan follows the batch. All 61 backend tests pass, including bulk authorization/CSRF/atomic validation and project hierarchy. Selection behavior verified in the built-in browser; containers rebuilt and healthy.

Supplemental now uses a yellow button treatment. Accounts tab places Create account first, followed by a table of username, role, active status, assigned investigator/lab access, password-change requirement, last successful login (UTC), and Edit links to the existing account editor. Last-login dates derive from existing login audit events, with No login recorded when absent; no account schema change is needed. 62 backend tests pass.

Publication update (2026-09-28): removed all .ready-based visibility checks and the Auto action/marker column. New projects and deliverables, and legacy Auto settings, default to enabled after normal validation. Explicit admin Disabled settings remain effective across scans and restarts, including parent-project overrides. Existing .ready files are ignored and need not be removed from mounted report folders. Enable/Disable are the only publication actions. Updated documentation and 62 passing backend tests cover marker-free discovery and access revocation.

Administration tables now omit the redundant Publication column. Disabled projects, deliverables (including those hidden by a disabled parent), and accounts use a light red row background while retaining their textual status.
