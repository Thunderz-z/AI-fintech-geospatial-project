# TerraScope Evaluation — Water-Extent Seasonality v1 (bootstrap CIs)

Status: **implemented and run** (round-2 T4). Agent 2 (TerraScope), 2026-11-01.
Artefacts: `exports/seasonality/seasonality_bootstrap_v1.{json,png}` on the data root
(`PORTFOLIO_DATA_ROOT/terrascope`); source series: `processed/water-extent/water_extent_2019-04-01_2026-10-31_v1.json`.

## Question

Does the MNDWI(>0) water fraction inside the authoritative Ramsar IN2481 polygon differ
between the NE-monsoon (Oct–Dec) and dry-season (Feb–Apr) windows, and by how much — with an
uncertainty statement that does not overstate the evidence?

## Method

- Series: water-series **v1** (calibrated threshold 0.0; reference: ESA WorldCover 2021 v200
  permanent-water class, mean Cohen's κ = 0.45; see
  `processed/water-extent/mndwi_calibration_v1.json`). 137 usable dates of 195 (58 abstained
  on the 80% valid-fraction gate).
- **Bootstrap over dates** (the dates are the sampling units): 10,000 resamples with
  replacement per season, seed 42, percentile 95% CIs for each seasonal mean and for the
  difference in means. Unbalanced n (monsoon 20, dry 68) is handled by resampling within
  season; it is recorded as a limitation, not hidden.

## Result

| Window | n | mean | 95% CI |
|---|---|---|---|
| NE monsoon (Oct–Dec) | 20 | 19.5% | 14.4–25.0% |
| Dry season (Feb–Apr) | 68 | 10.4% | 9.6–11.2% |
| **Difference** | — | **+9.1 pp** | **+4.0 to +14.9 pp** |

The difference CI excludes zero: more MNDWI-positive water inside the Ramsar polygon during
the NE monsoon than the dry season, robust over date resampling.

Event sanity check: the three highest monsoon dates (39.6%, 43.6%, 48.1%) fall in **Nov–Dec
2021**, matching the December 2021 Chennai floods — the series captures a real, independently
documented hydrological event. This is a consistency observation, not a validation.

## Reproduce

```bash
uv run --project projects/terrascope python -m terrascope.ingestion water \
    --start 2019-04-01 --end 2026-10-31 \
    --calibration "D:/GITHUB/AI-Portfolio/Portfolio data/terrascope/processed/water-extent/mndwi_calibration_v1.json"
uv run --project projects/terrascope python projects/terrascope/scripts/seasonality_analysis.py
```

## Limitations

- Absolute water levels are threshold-dependent; the calibrated threshold is stated in the
  series and contract. The seasonal *contrast* was robust across the whole threshold sweep in
  M0's sensitivity artefact.
- Bootstrap CIs quantify sampling variability over dates, not measurement error or label
  noise (weak reference; QA points 7/12, see the calibration artefact).
- Unbalanced seasonal sample sizes (20 vs 68); resampling is within season.
- Observation only — no causal attribution (ADR-0006).
