"""Run water change detection between two composite epochs (M3).

Post-classification comparison of the calibrated MNDWI water masks of two
seasonal composite epochs — observed transitions only, never causation.
Emits the report JSON, the change/uncertainty rasters and an evidence
contract stating threshold, validity gate, margins and limitations.

    uv run --project projects/terrascope python scripts/run_change_detection.py \
        --epoch-a winter_2019-20 --epoch-b winter
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from relia.contracts.evidence import (
    EvidenceContract,
    EvidenceRef,
    EvidenceType,
    MethodologyInfo,
    ValidationStatus,
)
from terrascope.config import data_dir
from terrascope.features.change import ChangeConfig, change_report_payload, compare_epochs
from terrascope.features.indices import build_season_indices


def _ensure_indices(epoch_dir: Path) -> None:
    if not (epoch_dir / "mndwi_median.tif").is_file():
        build_season_indices(epoch_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-a", required=True, help="composite dir name of the earlier epoch")
    parser.add_argument("--epoch-b", required=True, help="composite dir name of the later epoch")
    parser.add_argument("--season", default="winter", help="season label for artefact names")
    args = parser.parse_args()

    root = data_dir()
    composites = root / "processed" / "composites"
    epoch_a = composites / args.epoch_a
    epoch_b = composites / args.epoch_b
    for epoch in (epoch_a, epoch_b):
        if not (epoch / "provenance.json").is_file():
            print(f"Epoch composite missing: {epoch} (run the composite stage first)")
            return 1
        _ensure_indices(epoch)

    config = ChangeConfig()
    print(
        f"comparing {epoch_a.name} vs {epoch_b.name} "
        f"(threshold {config.mndwi_threshold}, min valid obs {config.min_valid_obs})..."
    )
    report, map_path, uncertainty_path = compare_epochs(
        epoch_a, epoch_b, config=config, out_dir=root / "processed" / "change-detection",
        season=args.season,
    )

    out_dir = root / "processed" / "change-detection"
    payload = change_report_payload(report, config)
    report_path = out_dir / f"change_{args.season}_{epoch_a.name}_vs_{epoch_b.name}.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    contract = EvidenceContract(
        claim_text=(
            f"Between composite epochs {epoch_a.name} and {epoch_b.name} ({args.season}), "
            f"the MNDWI>{config.mndwi_threshold} water fraction over comparably observed "
            f"pixels moved from {report.water_fraction_a:.1%} to {report.water_fraction_b:.1%}: "
            f"{report.transition_matrix['gained_water']:.2%} of compared pixels gained water and "
            f"{report.transition_matrix['lost_water']:.2%} lost water. This is an observed "
            "post-classification comparison — not a causal or class-level land-cover statement."
        ),
        evidence=[
            EvidenceRef(
                evidence_type=EvidenceType.RASTER_STATISTIC,
                description="Water transition report (transition matrix, fractions, margins)",
                location=str(report_path),
                source="TerraScope change detection (terrascope.features.change)",
            ),
            EvidenceRef(
                evidence_type=EvidenceType.RASTER_STATISTIC,
                description="Per-pixel change map (legend in sidecar JSON)",
                location=str(map_path),
                source="TerraScope change detection",
            ),
            EvidenceRef(
                evidence_type=EvidenceType.RASTER_STATISTIC,
                description="Uncertainty map: block-mean observation agreement + margin caveat",
                location=str(uncertainty_path),
                source="TerraScope change detection",
            ),
            EvidenceRef(
                evidence_type=EvidenceType.SATELLITE_OBSERVATION,
                description="Epoch provenance sidecars (scene IDs, dates, SCL config, grid)",
                location=str(epoch_a / "provenance.json"),
                source="Microsoft Planetary Computer sentinel-2-l2a",
            ),
        ],
        methodology=MethodologyInfo(
            name="mndwi-post-classification-change",
            version="v1",
            parameters=config.to_dict(),
        ),
        validation_status=ValidationStatus.VALID,
        confidence=None,
        limitations=report.limitations
        + [
            "single-epoch MNDWI calibration reference (WorldCover 2021) applies to both epochs",
        ],
        uncertainty={
            "ambiguous_margin_fraction": report.ambiguous_margin_fraction,
            "median_abs_margin": report.median_abs_margin,
            "agreement_uncertainty": report.agreement_uncertainty,
            "valid_fraction_of_grid": report.valid_fraction_of_grid,
        },
        observation_period=f"{epoch_a.name} vs {epoch_b.name}",
    )
    contract_path = out_dir / (
        f"change_{args.season}_{epoch_a.name}_vs_{epoch_b.name}.evidence.json"
    )
    contract_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")

    print(f"compared pixels: {report.compared_pixels}")
    print(f"water fraction: {report.water_fraction_a:.2%} -> {report.water_fraction_b:.2%}")
    print(
        f"transitions: gained {report.transition_matrix['gained_water']:.2%}, "
        f"lost {report.transition_matrix['lost_water']:.2%}"
    )
    print(f"wrote {report_path}")
    print(f"wrote {contract_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
