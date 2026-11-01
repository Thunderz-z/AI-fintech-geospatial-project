# TerraScope API service container.
# Buildable in CI without a local Docker installation (owner preference:
# no Docker Desktop; GitHub Actions builds/pushes images). The container
# mounts the dataset root at runtime — no data is baked into the image.

FROM python:3.13-slim

# Geo stack system libs (rasterio/geopandas wheels bundle their own GDAL/GEOS;
# only runtime extras are needed here).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /repo

# Cache-friendly layering: manifest first, code later.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/relia/pyproject.toml packages/relia/pyproject.toml
COPY projects/terrascope/pyproject.toml projects/terrascope/pyproject.toml
COPY projects/finguard/pyproject.toml projects/finguard/pyproject.toml
RUN uv sync --locked --frozen --no-dev --package terrascope

COPY packages/relia packages/relia
COPY projects/terrascope projects/terrascope
COPY projects/finguard projects/finguard
RUN uv sync --locked --frozen --no-dev --package terrascope

ENV PORTFOLIO_DATA_ROOT=/data
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "--package", "terrascope", \
     "uvicorn", "terrascope.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
