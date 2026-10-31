# ADR-0001: Monorepo with a uv Workspace

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

Three connected assets (RELIA, TerraScope, FinGuard) share interfaces (evidence contracts,
provider abstraction, data-path utility) and evolve together. Separate repositories would
version shared interfaces awkwardly and duplicate CI.

## Decision

A single Git monorepo managed as a **uv workspace** with three installable members
(`packages/relia`, `projects/terrascope`, `projects/finguard`) and a virtual root project that
pins the shared dev toolchain and depends on all members. One `uv.lock` resolves the whole
graph.

### Structural adaptation

The reference layout listed per-project directories (backend/, pipelines/, …) without a Python
package root. Each project additionally gets a `src/` core package
(`src/terrascope/`, `src/finguard/`) so members are installable, editable by the workspace, and
importable by tests; pipeline directories remain as planned and will import the core package.
This deviation is documented here rather than silently introduced.

## Consequences

- Shared interfaces version atomically with their consumers.
- Dependency changes are visible in one lockfile; AGENTS.md protects `pyproject.toml`/`uv.lock`
  from concurrent edits.
- The repo cannot be published piecemeal; if a standalone RELIA release is ever wanted, extract
  `packages/relia` then (documented before done).
