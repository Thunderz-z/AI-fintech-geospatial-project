# Codebase Memory MCP — Working Setup

Status: configured and verified during initialization (2026-10-31). This document records the
exact working configuration so future sessions can re-establish it.

## What it is

[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) provides a continuously
updated structural knowledge graph of this repository, queried through MCP tools
(`search_code`, `search_graph`, `trace_path`, `get_architecture`, …).

## Verified state (initialization)

- MCP server reachable from ZCode; project auto-registered as
  `C-Github-My-portfolio-and-resume-projects-AI-fintech-geospatial-project` rooted at the repo.
- Watcher: **active**, strategy `git`, poll interval 5000 ms (`index_status.watch.watched: true`).
- Initial index covered the pre-scaffolding tree (2 files); a full re-index runs after the
  foundation scaffolding and coverage is checked with `check_index_coverage`.

## Configuration commands used (verify keys against the installed version)

```
codebase-memory-mcp config get
codebase-memory-mcp config set auto_index true
codebase-memory-mcp config set auto_watch true
codebase-memory-mcp config set watcher_enabled true
```

Watcher settings are read when the daemon starts; after changing them:
`codebase-memory-mcp daemon stop`, then reconnect the MCP integration. Do not invent
unsupported commands — check `codebase-memory-mcp --help` first.

## Operating rules (see AGENTS.md)

1. Indexing is driven through the MCP session (`index_repository`, async + status polling), not
   just the CLI, so watching registers for the session.
2. The watcher is polling-based (~5 s), not instantaneous; after substantial structural
   changes, verify with `index_status` / `check_index_coverage`.
3. Watching is tied to active MCP sessions — if all owning sessions close, auto-updates stop
   until a session reconnects and re-registers.
4. Multiple agents must confirm they share the same repository path and Codebase Memory
   project.
5. `.codebase-memory/` local artifacts are gitignored; never commit them.
