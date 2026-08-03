FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --no-dev

COPY . .
RUN uv sync --no-dev

RUN chmod +x docker-entrypoint.sh docker-entrypoint-worker.sh

RUN groupadd --system marketplace \
    && useradd --system --gid marketplace --home-dir /app --shell /usr/sbin/nologin marketplace \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R marketplace:marketplace /app

ENV PATH="/app/.venv/bin:$PATH"

USER marketplace

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
