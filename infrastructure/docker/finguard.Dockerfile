# FinGuard investigation service container (same strategy as terrascope.Dockerfile).

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /repo
COPY . .
RUN uv sync --frozen --no-dev --package finguard

ENV PORTFOLIO_DATA_ROOT=/data
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "--package", "finguard", \
     "uvicorn", "finguard.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
