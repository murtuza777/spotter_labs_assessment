FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000

# Threads let one worker overlap the slow upstream weather calls. The long timeout covers a
# cold plan (routing + uncached weather) on the free weather tier.
CMD gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WEB_CONCURRENCY:-2} \
    --threads 4 \
    --timeout 120 \
    --access-logfile -
