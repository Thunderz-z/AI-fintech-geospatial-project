# ADR-0004: Shared Utilities Live in RELIA

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

The data-path utility (and future small shared helpers) is needed by all three packages. The
reference architecture names only one shared package (`packages/relia`), whose identity is
reliability/evaluation infrastructure.

## Decision

Shared utilities are colocated in RELIA (`relia.config.paths`) rather than creating a fourth
workspace member (e.g. `portfolio-common`) at this stage.

## Alternatives considered

- *A separate `packages/common`* — cleaner conceptual separation, but adds workspace member,
  release and coordination overhead for one module. Revisit **if** the count of non-reliability
  shared modules exceeds a handful.

## Consequences

- TerraScope/FinGuard already depend on RELIA, so no new edges appear.
- RELIA's package identity is documented as "reliability infrastructure + portfolio shared
  foundation" in its docstring; if the shared surface grows, the split (extracting `common`)
  becomes a documented refactor rather than an emergency.
