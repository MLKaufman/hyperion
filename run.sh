#!/usr/bin/env bash
# Build/run Hyperion from any working directory. Local mode binds loopback only.
set -Eeuo pipefail
cd -- "$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'HELP'
Usage: ./run.sh [--production] [COMMAND]

Commands:
  up             Build and start containers; wait for health (default)
  build          Build both images
  stop           Stop/remove containers, preserving database and cache volumes
  status         Show container status
  logs           Follow recent logs (Ctrl-C exits logs only)
  admin USER     Create an administrator interactively; briefly stop the app
  help           Show this help

Local mode uses .env.local (created automatically), sample_reports by default,
and http://portal.hyperion.localhost:8080. Edit .env.local to change the reports
path or port. Local mode binds to 127.0.0.1; no TLS certificates are required.
Production uses .env, compose.yaml, and the TLS/DNS setup described in README.md.
HELP
}

mode=local
if [[ "${1:-}" == --production ]]; then
    mode=production
    shift
fi
command_name="${1:-up}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command_name" in
    help|-h|--help) usage; exit 0 ;;
    up|build|stop|status|logs) [[ $# -eq 0 ]] || { usage >&2; exit 2; } ;;
    admin) [[ $# -eq 1 ]] || { usage >&2; exit 2; } ;;
    *) usage >&2; exit 2 ;;
esac
command -v docker >/dev/null 2>&1 || { echo 'Install Docker with Compose first.' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo 'Docker Compose v2 is required.' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Docker is unavailable. Start Docker Desktop (or the Docker daemon), then retry.' >&2; exit 1; }

if [[ "$mode" == production ]]; then
    [[ -f .env ]] || { echo 'Copy .env.example to .env and configure production DNS, paths, secret, and certificates first. See README.md.' >&2; exit 1; }
    compose=(docker compose --project-name hyperion --env-file .env -f compose.yaml)
else
    if [[ ! -f .env.local ]]; then
        command -v openssl >/dev/null 2>&1 || { echo 'openssl is required to generate the initial local secret.' >&2; exit 1; }
        secret=$(openssl rand -hex 48)
        # noclobber protects against two launchers creating this file concurrently.
        (umask 077; set -o noclobber; {
            printf 'SECRET_KEY=%s\n' "$secret"
            printf '%s\n' 'HYPERION_PORT=8080' 'REPORTS_HOST_PATH=./sample_reports' 'MAX_DELIVERABLE_BYTES=268435456' 'SCAN_INTERVAL=60'
        } > .env.local) || { echo 'Could not create .env.local; check its permissions and retry.' >&2; exit 1; }
        unset secret
        echo 'Created .env.local. Edit it to use your own report directory.'
    fi
    compose=(docker compose --project-name hyperion-local --env-file .env.local -f compose.local.yaml)
fi
"${compose[@]}" config --quiet

case "$command_name" in
    build) "${compose[@]}" build ;;
    up)
        if ! "${compose[@]}" up --build -d --wait --wait-timeout 180; then
            "${compose[@]}" ps >&2
            "${compose[@]}" logs --tail=50 >&2
            exit 1
        fi
        if [[ "$mode" == local ]]; then
            address=$("${compose[@]}" port caddy 80)
            printf '\nHyperion is running: http://portal.hyperion.localhost:%s\n' "${address##*:}"
            printf 'Create your first account: ./run.sh admin admin\n'
        else
            printf '\nHyperion is running. Open the PORTAL_ORIGIN configured in .env.\n'
            printf 'Create an account if needed: ./run.sh --production admin admin\n'
        fi
        ;;
    stop) "${compose[@]}" down; echo 'Stopped. Database and cache volumes were preserved.' ;;
    status) "${compose[@]}" ps ;;
    logs) "${compose[@]}" logs --follow --tail=100 ;;
    admin)
        [[ -t 0 ]] || { echo 'Run the admin command in an interactive terminal to enter the password.' >&2; exit 1; }
        "${compose[@]}" build app
        running=$("${compose[@]}" ps --status running --services)
        restart_app=false
        if [[ " ${running//$'\n'/ } " == *' app '* ]]; then
            restart_app=true
            "${compose[@]}" stop app
        fi
        restore_app() {
            if [[ "$restart_app" == true ]]; then
                "${compose[@]}" up -d --wait --wait-timeout 180 app || echo 'App restart failed; run the launcher again.' >&2
            fi
        }
        trap restore_app EXIT
        "${compose[@]}" run --rm --no-deps app uv run --no-sync python manage.py createadmin "$1"
        ;;
esac
