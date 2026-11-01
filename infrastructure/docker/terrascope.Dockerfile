# TerraScope API service container.
# Built by CI (no local Docker — ADR-0007). The dataset root is mounted at
# runtime; nothing is baked into the image.

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /repo
COPY . .
RUN uv sync --frozen --no-dev --package terrascope

ENV PORTFOLIO_DATA_ROOT=/data
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "--package", "terrascope", \
     "uvicorn", "terrascope.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
