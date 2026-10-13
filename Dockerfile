FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_DOWNLOADS=never
ENV DATA_DIR=/data REPORTS_ROOT=/reports RUN_SCANNER=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN date -u '+%Y-%m-%d %H:%M UTC' > /app/build-date.txt && DEBUG=1 RUN_SCANNER=0 uv run --no-sync python manage.py collectstatic --noinput && useradd --uid 10001 --create-home portal && mkdir -p /data /var/cache/hyperion && chown portal:portal /data /var/cache/hyperion
USER portal
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://localhost:8000/health/', headers={'Host': 'app'}), timeout=5)"
ENTRYPOINT ["python", "-m", "hyperion.startup"]
