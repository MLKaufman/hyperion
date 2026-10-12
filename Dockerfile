FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN date -u '+%Y-%m-%d %H:%M UTC' > /app/build-date.txt && DEBUG=1 uv run --no-sync python manage.py collectstatic --noinput && useradd --uid 10001 --create-home portal && mkdir -p /data /var/cache/hyperion && chown portal:portal /data /var/cache/hyperion
USER portal
EXPOSE 8000
# DuckDB has one owning process. Threads and the scanner share a serialized Store.
CMD ["uv", "run", "--no-sync", "gunicorn", "hyperion.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(h)s %(m)s %(U)s %(s)s %(L)s"]
