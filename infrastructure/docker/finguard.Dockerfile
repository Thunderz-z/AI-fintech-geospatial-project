# FinGuard investigation service container (same strategy as terrascope.Dockerfile).

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /repo

COPY pyproject.toml uv.lock .python-version ./
COPY packages/relia/pyproject.toml packages/relia/pyproject.toml
COPY projects/terrascope/pyproject.toml projects/terrascope/pyproject.toml
COPY projects/finguard/pyproject.toml projects/finguard/pyproject.toml
RUN uv sync --locked --frozen --no-dev --package finguard

COPY packages/relia packages/relia
COPY projects/terrascope projects/terrascope
COPY projects/finguard projects/finguard
RUN uv sync --locked --frozen --no-dev --package finguard

ENV PORTFOLIO_DATA_ROOT=/data
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "--package", "finguard", \
     "uvicorn", "finguard.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
