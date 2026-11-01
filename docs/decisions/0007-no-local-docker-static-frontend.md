# ADR-0007: No Local Docker; Static Frontend v0; CI-Built Images

- Status: Accepted
- Date: 2026-11-01
- Deciders: portfolio owner

## Context

The owner will not install Docker Desktop on the development machine. Both
services still need containerization for deployment credibility, and the
master plan calls for map/investigation UIs.

## Decision

1. **No local Docker.** Docker artifacts (Dockerfiles, compose, CI build job)
   are written and verified in GitHub Actions (ubuntu runners have a daemon);
   nothing container-related runs locally. Local development is
   `uvicorn`/`uv run` against the external data root.
2. **Datasets stay external to images.** Containers mount the data root at
   runtime (`PORTFOLIO_DATA_ROOT=/data`); TerraScope mounts read-only,
   FinGuard read-write (queue persistence). No data is baked in.
3. **Frontend v0 is build-less.** Single-file HTML/JS clients (MapLibre via
   CDN for TerraScope) served by the FastAPI apps behind an optional
   `static_dir` mount. Rationale: the deliverable is the engineering, not a
   build pipeline; a React/Vite SPA is deferred until v1 needs state
   management beyond two screens. No npm/node dependency is introduced.

## Consequences

- CI gained a `docker` job building both images on every push (honest
  "buildable" claims, verified by CI not by hope).
- Deploying is: build in CI → run with a mounted volume; documented in
  `docs/architecture/deployment.md`.
- The `static_dir` mount stays optional; the API works without a frontend.
