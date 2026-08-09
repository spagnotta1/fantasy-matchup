# One image, five services.
#
# The API, the ETL cron, the projection job, the cache warmer and the provider
# feeds all run from this image with different start commands. That is not
# frugality — it is the only way to guarantee the projection a job writes and
# the projection the API serves were produced by the same code. Separate images
# drift the first time one is rebuilt and the other is not, and the symptom is
# a response shape that no single commit explains.
#
# The default command is the API, because that is the service that must come up
# by itself after a platform restart. Every other service overrides it in its
# railway.*.json.
#
# The frontend is built in a first stage and its output copied into the runtime
# image, so the API serves the app from its own origin. That is what lets the
# client call a relative `/api/v1` with no CORS exchange and no absolute base
# URL baked into the bundle. Node does not survive into the final image — only
# the static files it produced.

FROM node:22-slim AS web

WORKDIR /web

# Lockfile first, so a source edit does not reinstall the dependency tree.
# `npm ci` rather than `npm install`: it installs exactly the lockfile and fails
# when the two disagree, which is the behaviour a reproducible build needs.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# Runs `tsc -b` before Vite, so a type error fails the image build rather than
# shipping. The frontend needs no build-time configuration: every environment
# it can be deployed into is same-origin by construction.
RUN npm run build


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code edits don't invalidate the layer.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./

# The built frontend. Set explicitly rather than discovered: the package is
# installed into site-packages, so the repository-relative fallback in
# nflfp.api.spa cannot find `web/dist` from there. An image built without this
# stage — or a worker container that ignores the variable — simply serves the
# API, which is the correct behaviour for every service that is not the API.
COPY --from=web /web/dist ./web/dist
ENV WEB_DIST_DIR=/app/web/dist

# DuckDB downloads the httpfs and postgres extensions on first use. Baking them
# into the image keeps the cron run from depending on extension-CDN uptime.
RUN python -c "import duckdb; c = duckdb.connect(); \
    c.execute('INSTALL httpfs'); c.execute('INSTALL postgres')"

# Run as a non-root user. Nothing here writes to the filesystem — the warehouse
# is Postgres and the DuckDB file is a local-development convenience that is
# deliberately not deployed — so there is no reason to hold write access to the
# image at runtime.
RUN useradd --create-home --uid 10001 nflfp && chown -R nflfp:nflfp /app
USER nflfp

# Railway injects PORT; pg.dsn() adds sslmode=require for remote hosts.
ENV PORT=8000
EXPOSE 8000

# Not the platform health check — that is configured in railway.api.json and
# points at /api/v1/health/live. This one exists for `docker run` and for any
# orchestrator that reads it, and uses the liveness endpoint for the same
# reason: a container must not be killed because Postgres failed over.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request as u; \
    u.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/api/v1/health/live\", timeout=2)"

CMD ["sh", "-c", "python -m nflfp.api --host 0.0.0.0 --port ${PORT:-8000}"]
