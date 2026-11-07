FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY src ./src
# Alembic migrations live alongside the app so they run inside the deployed image, as an explicit
# operator step with a privileged URL (the service's own DATABASE_URL is read-only):
#   docker compose run --rm -e MIGRATION_DATABASE_URL=<admin url> fastapi alembic upgrade head
# The runtime container itself never invokes alembic.
COPY alembic ./alembic
COPY alembic.ini .
# Run as an unprivileged user.
RUN useradd --system --uid 10001 --create-home app
USER app
EXPOSE 8000
# Gunicorn reads its worker count from WEB_CONCURRENCY; override it to suit the host.
ENV WEB_CONCURRENCY=4
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "src.main:app"]
