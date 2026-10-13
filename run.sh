#!/usr/bin/env bash
# Convenience wrapper; the container performs setup even without this script.
set -Eeuo pipefail
cd -- "$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mode=local
if [[ "${1:-}" == --production ]]; then mode=production; shift; fi
command_name="${1:-up}"
if [[ $# -gt 0 ]]; then shift; fi
compose=(docker compose --project-name hyperion-local -f compose.yaml)
if [[ "$mode" == production ]]; then
    compose=(docker compose --project-name hyperion -f compose.yaml)
elif [[ -f .env.local ]]; then
    compose+=(--env-file .env.local)
fi
case "$command_name" in
    up)
        "${compose[@]}" up --build -d --wait --wait-timeout 300
        echo 'Hyperion is ready at PUBLIC_URL (default http://localhost:8000).'
        echo 'First login: ./run.sh credentials (add --production for production mode).'
        ;;
    credentials) "${compose[@]}" exec app cat /data/initial-admin.json ;;
    build) "${compose[@]}" build app ;;
    stop) "${compose[@]}" down ;;
    status) "${compose[@]}" ps ;;
    logs) "${compose[@]}" logs --follow --tail=100 app ;;
    admin)
        [[ $# -eq 1 && -t 0 ]] || { echo 'Usage: ./run.sh [--production] admin USER (interactive terminal)' >&2; exit 2; }
        running=$("${compose[@]}" ps --status running --services)
        restore_app() { if [[ "$running" == *app* ]]; then "${compose[@]}" up -d app; fi; }
        trap restore_app EXIT
        "${compose[@]}" stop app
        "${compose[@]}" run --rm --no-deps app python manage.py createadmin "$1"
        ;;
    help|-h|--help) echo 'Usage: ./run.sh [--production] [up|build|stop|status|logs|credentials|admin USER]' ;;
    *) echo 'Unknown command. Run ./run.sh help.' >&2; exit 2 ;;
esac
