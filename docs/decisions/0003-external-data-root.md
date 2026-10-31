# ADR-0003: External Data Root via PORTFOLIO_DATA_ROOT (No Silent Fallback)

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

The internal SSD is small (~60 GB free); datasets must live on the external drive
(`D:\GITHUB\AI-Portfolio\Portfolio data`, which contains spaces in the path). Hardcoded paths
break portability and CI; silent fallbacks to the internal drive cause exactly the disk
exhaustion this architecture must prevent.

## Decision

1. The single source of truth is the **`PORTFOLIO_DATA_ROOT` environment variable**, with a
   fallback to the repository's local `.env` (gitignored). `.env.example` documents it.
2. `relia.config.paths` implements resolution + validation: existence, directory check,
   **writability probe** (real temp-file probe; `os.access` is unreliable on Windows), project
   subdirectory resolution with a known-projects whitelist (guards path traversal), and a
   non-raising `check_data_root` diagnostic snapshot for the CLI.
3. **No silent fallback**: a missing/unusable root raises typed errors
   (`DataRootNotConfiguredError`, `DataRootUnavailableError`); pipelines stop and report.
4. Deployment portability: production can repoint the variable at object storage or a mounted
   volume without code changes.

Machine configuration on the development machine: local `.env` **and** a persistent user
variable (`setx`) — user-approved.

## Consequences

- CI has no dataset root by design; tests always use temporary roots via env vars — which also
  proves the configuration path.
- Every dataset-consuming module funnels through this utility; grep for
  `PORTFOLIO_DATA_ROOT`/`paths` to audit data access.
