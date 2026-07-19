# Pinned, not :slim or :latest. The delivery hour depends on the image carrying
# zoneinfo data (Debian slim does); a base that drifts to one without it would
# fall back to UTC and just send the digest at the wrong time.
FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first, as their own layer: source edits then rebuild in seconds
# instead of re-resolving the whole tree.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_URL="sqlite:////data/ogoh.db"

# The database is the only thing worth keeping; the image stays disposable.
RUN mkdir -p /data && useradd --system --uid 1000 ogoh && chown ogoh:ogoh /data
USER ogoh

CMD ["ogoh-bot"]
