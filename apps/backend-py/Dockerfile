FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Build stage
FROM base AS builder
WORKDIR /app

COPY apps/backend-py/pyproject.toml apps/backend-py/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY apps/backend-py .
RUN uv sync --frozen --no-dev

# Production stage
FROM base AS runner
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app /app

EXPOSE 3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
