"""Seasonality analysis with bootstrap CIs (round-2 T4).

Compares the Ramsar-polygon water fraction (water-series v1, usable dates)
between the NE-monsoon (Oct-Dec) and dry-season (Feb-Apr) windows, with
bootstrap confidence intervals over dates (resampling dates, not pixels —
the dates are the sampling units of the series). Emits a JSON artefact and a
plot under exports/.

    uv run --project projects/terrascope python scripts/seasonality_analysis.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from terrascope.config import data_dir  # noqa: E402

N_BOOTSTRAP = 10000
SEED = 42
MONSOON_MONTHS = (10, 11, 12)  # NE monsoon (Oct-Dec)
DRY_MONTHS = (2, 3, 4)  # dry season (Feb-Apr)


def _bootstrap_ci(values: np.ndarray, rng: np.random.Generator) -> dict:
    n = values.size
    if n == 0:
        return {"mean": None, "ci95_low": None, "ci95_high": None, "n": 0}
    means = np.array(
        [values[rng.integers(0, n, n)].mean() for _ in range(N_BOOTSTRAP)]
    )
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "mean": round(float(values.mean()), 4),
        "ci95_low": round(float(lo), 4),
        "ci95_high": round(float(hi), 4),
        "n": int(n),
    }


def _month_is(dates: np.ndarray, months: tuple[int, ...]) -> np.ndarray:
    month_index = dates.astype("datetime64[M]").astype(int) % 12 + 1  # 1..12
    return np.isin(month_index, months)


def main() -> int:
    root = data_dir()
    report_path = (
        root / "processed" / "water-extent" / "water_extent_2019-04-01_2026-10-31_v1.json"
    )
    observations = json.loads(report_path.read_text(encoding="utf-8"))["observations"]
    usable = [
        o
        for o in observations
        if not o["abstained"] and o["water_fraction_ramsar"] is not None
    ]

    dates = np.array([dt.date.fromisoformat(o["sensing_date"]) for o in usable])
    fractions = np.array([o["water_fraction_ramsar"] for o in usable], dtype=np.float64)

    monsoon = fractions[_month_is(dates, MONSOON_MONTHS)]
    dry = fractions[_month_is(dates, DRY_MONTHS)]
    rng = np.random.default_rng(SEED)
    monsoon_stats = _bootstrap_ci(monsoon, rng)
    dry_stats = _bootstrap_ci(dry, rng)
    diff = monsoon.mean() - dry.mean()
    n_m, n_d = monsoon.size, dry.size
    boot_diffs = np.empty(N_BOOTSTRAP)
    for i in range(N_BOOTSTRAP):
        m = monsoon[rng.integers(0, n_m, n_m)]
        d = dry[rng.integers(0, n_d, n_d)]
        boot_diffs[i] = m.mean() - d.mean()
    dlo, dhi = np.percentile(boot_diffs, [2.5, 97.5])

    payload = {
        "run_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "source_series": str(report_path.name),
        "method": "bootstrap over dates (sampling units = usable scene dates), "
        f"{N_BOOTSTRAP} resamples, seed {SEED}, percentile CIs",
        "monsoon_window_months": list(MONSOON_MONTHS),
        "dry_window_months": list(DRY_MONTHS),
        "monsoon": monsoon_stats,
        "dry": dry_stats,
        "mean_difference_pp": {
            "value": round(float(diff * 100), 2),
            "ci95_low": round(float(dlo * 100), 2),
            "ci95_high": round(float(dhi * 100), 2),
        },
        "interpretation": "positive difference = more MNDWI(>0) water inside the Ramsar "
        "polygon during the NE monsoon than the dry season; observation, not causation",
        "limitations": [
            "unbalanced seasonal sample sizes (see n fields)",
            "water fraction from the calibrated MNDWI threshold (see mndwi_calibration_v1.json)",
            "bootstrap CIs quantify sampling variability over dates, not measurement error",
        ],
    }
    out_dir = root / "exports" / "seasonality"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "seasonality_bootstrap_v1.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    figure, ax = plt.subplots(figsize=(14, 6), dpi=110)
    is_monsoon = _month_is(dates, MONSOON_MONTHS)
    ax.scatter(
        dates[~is_monsoon], fractions[~is_monsoon] * 100,
        s=12, alpha=0.6, label="other dates", color="steelblue",
    )
    ax.scatter(
        dates[is_monsoon], fractions[is_monsoon] * 100,
        s=14, alpha=0.8, label="NE monsoon (Oct-Dec)", color="darkorange",
    )
    for stats, color in (
        (monsoon_stats, "darkorange"),
        (dry_stats, "steelblue"),
    ):
        ax.hlines(
            [stats["mean"] * 100, stats["ci95_low"] * 100, stats["ci95_high"] * 100],
            dates.min(), dates.max(), colors=[color, color, color],
            linestyles=["-", ":", ":"], linewidths=[1.6, 1.0, 1.0], alpha=0.9,
        )
        ax.annotate(
            (
                f"mean {stats['mean'] * 100:.1f}% "
                f"(95% CI {stats['ci95_low'] * 100:.1f}-{stats['ci95_high'] * 100:.1f}%)"
            ),
            xy=(dates.min(), stats["mean"] * 100), xytext=(6, 4), textcoords="offset points",
            fontsize=9, color=color,
        )
    ax.set_title(
        "Pallikaranai Ramsar IN2481 - MNDWI water fraction per usable date (2019-2026)\n"
        f"NE-monsoon vs dry-season bootstrap means (seed {SEED}, {N_BOOTSTRAP} resamples)"
    )
    ax.set_ylabel("water fraction of Ramsar polygon [%]")
    ax.legend(loc="upper right", fontsize=9)
    figure.tight_layout()
    plot_path = out_dir / "seasonality_bootstrap_v1.png"
    figure.savefig(plot_path, bbox_inches="tight")

    print(json.dumps(payload, indent=2))
    print(f"wrote {json_path}")
    print(f"wrote {plot_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
