# TerraScope — Ingestion

**Implemented (M0 step 3).** The ingestion code lives in the importable package at
[`src/terrascope/ingestion/`](../src/terrascope/ingestion/) so it ships in the
wheel and is covered by the test suite (`../tests/test_ingestion_*.py`).

Modules:

| Module | Responsibility |
|---|---|
| `gate.py` | Download-approval gate — every network access must pass it |
| `aoi.py` | Study-area geometry (approximate bbox; authoritative Ramsar RSIS polygon loader ready) |
| `stac_search.py` | Sentinel-2 L2A search on Microsoft Planetary Computer (gated) |
| `scenes.py` | Scene candidates + cloud/date/band filtering (offline logic) |
| `cog_reader.py` | Windowed COG reads + grid-aligned reprojection |
| `masking.py` | SCL masking (classes 0, 1, 3, 8, 9, 10, 11 excluded) |
| `composite.py` | Seasonal grouping + median compositing + valid-count planes |
| `pipeline.py` | `run_download` (gated, cache-aware) and `run_composite` (offline) |
| `__main__.py` | CLI: `status` / `download --approve` / `composite` |

Run it:

```bash
uv run --project projects/terrascope python -m terrascope.ingestion status
# First approved retrieval (owner approval required — AGENTS.md storage rules):
uv run --project projects/terrascope python -m terrascope.ingestion download \
    --start 2024-01-01 --end 2024-03-31 --approve
uv run --project projects/terrascope python -m terrascope.ingestion composite \
    --start 2024-01-01 --end 2024-03-31
```

No satellite data has been downloaded yet; the first retrieval awaits approval.
