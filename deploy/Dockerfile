# B18: one image for the api, the worker and the one-shot migration (TRD AD-01: one package, two
# entry points). Build context: the repository root (deploy/compose.yml sets it).
# Python as in backend/pyproject.toml (>=3.12,<3.13). Runtime dependencies only, no dev extras.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# The pinned runtime dependencies of pyproject.toml, installed before the code for layer caching.
COPY backend/pyproject.toml /app/backend/pyproject.toml
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
EOF
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The package is run from its source tree (PYTHONPATH), so paths relative to the source such as the
# recorded QuickBooks fixtures (backend/fixtures) resolve as they do locally.
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY backend/src /app/backend/src
COPY backend/fixtures /app/backend/fixtures
COPY backend/scripts /app/backend/scripts
COPY deploy/migrate.py /app/deploy/migrate.py
ENV PYTHONPATH=/app/backend/src

# Non-root user. /data/blobs is the file store (named volume matchdesk_blobs); creating it here gives
# a new volume this owner. No .env file is in the image: settings come from the environment.
RUN groupadd --system --gid 10001 matchdesk \
    && useradd --system --uid 10001 --gid matchdesk --home-dir /app --no-create-home matchdesk \
    && mkdir -p /data/blobs /tmp/play \
    && chown matchdesk:matchdesk /data/blobs /tmp/play
USER matchdesk

ENV MATCHDESK_API_HOST=0.0.0.0 \
    MATCHDESK_API_PORT=8101 \
    MATCHDESK_BLOB_BACKEND=local \
    MATCHDESK_BLOB_ROOT=/data/blobs

EXPOSE 8101
CMD ["python", "-m", "matchdesk.api"]
