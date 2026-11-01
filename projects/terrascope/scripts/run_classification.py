"""Run the first land-cover classification (round-2 T3).

Random forest on the winter composite with WorldCover-derived labels,
validated with spatial block CV only. Emits the evaluation JSON, a pickled
model, and an evidence contract that states the weak-label limitation.

    uv run --project projects/terrascope python scripts/run_classification.py [--season winter]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pickle
import sys

from relia.contracts.evidence import (
    EvidenceContract,
    EvidenceRef,
    EvidenceType,
    MethodologyInfo,
    ValidationStatus,
)
from terrascope.config import data_dir
from terrascope.models.classification import ClassificationConfig, classify_composite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="winter", help="composite season directory name")
    args = parser.parse_args()

    root = data_dir()
    season_dir = root / "processed" / "composites" / args.season
    wc_raster = root / "raw" / "esa-worldcover" / "ESA_WorldCover_10m_2021_v200_N12E078_AOI.tif"
    if not wc_raster.is_file():
        print(f"WorldCover subset missing: {wc_raster}")
        return 1

    config = ClassificationConfig()
    print(
        f"classifying {season_dir.name} with RF(config={json.dumps(config.to_dict())}) "
        "under spatial block CV..."
    )
    report, model, feature_names = classify_composite(season_dir, wc_raster, config)

    out_dir = root / "processed" / "classification"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "season": args.season,
        "features": feature_names,
        "config": config.to_dict(),
        "label_source": "ESA WorldCover 2021 v200 dominant-class per 20 m cell (majority >= 0.5)",
        "labels_are_weak": "single-epoch 2021 product applied to 2023/24 imagery; not ground truth",
        "validation": "spatial block CV only (SpatialBlockSplitter; random splits never used)",
        **report.to_dict(),
    }
    report_path = out_dir / f"classification_{args.season}_report.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    model_path = out_dir / f"classification_{args.season}_rf.joblib.pkl"
    with model_path.open("wb") as handle:
        pickle.dump(model, handle)

    print(f"fold accuracy: {report.fold_accuracy}")
    print(f"mean block-CV accuracy: {report.mean_accuracy} +/- {report.sd_accuracy}")
    print(f"class support: {report.class_support}")
    print(f"wrote {report_path}")
    print(f"wrote {model_path}")

    contract = EvidenceContract(
        claim_text=(
            f"A random forest trained on the {args.season} composite features reproduces "
            f"WorldCover-derived labels at {report.mean_accuracy:.1%} mean block-CV accuracy "
            f"({report.sd_accuracy:.1%} sd over {report.n_folds} spatially disjoint 2000 m "
            f"block folds) over {report.n_training_pixels} sampled pixels. This measures "
            "agreement with a weak label product, NOT real-world map accuracy."
        ),
        evidence=[
            EvidenceRef(
                evidence_type=EvidenceType.MODEL_RESULT,
                description=(
                    "Classification evaluation JSON (fold accuracies, confusion matrix, config)"
                ),
                location=str(report_path),
                source="terrascope.models.classification",
            ),
            EvidenceRef(
                evidence_type=EvidenceType.RASTER_STATISTIC,
                description=(
                    "ESA WorldCover 2021 v200 AOI subset (label source, sha256 in manifest)"
                ),
                location="raw/esa-worldcover/ESA_WorldCover_10m_2021_v200_N12E078_AOI.tif",
                source="ESA WorldCover project (CC BY 4.0) via Microsoft Planetary Computer",
            ),
        ],
        methodology=MethodologyInfo(
            name="rf-worldcover-labels-blockcv",
            version="v1",
            parameters={
                **config.to_dict(),
                "features": feature_names,
                "validation": "SpatialBlockSplitter block folds (ADR-0006)",
            },
        ),
        validation_status=ValidationStatus.VALID,
        limitations=[
            "LABELS ARE WEAK: WorldCover 2021 v200 is a single-epoch global product applied "
            "to 2023/24 imagery (temporal mismatch); no surveyed ground truth was used.",
            "Accuracy is agreement with weak labels, not real-world accuracy.",
            "Spatial block CV (2000 m blocks) controls spatial leakage, not label noise.",
            "Per-class support is imbalanced; per-class F1 lives in the evaluation JSON.",
            "Observation only - no causal attribution (ADR-0006).",
        ],
    )
    contract_path = out_dir / f"classification_{args.season}_evidence.json"
    contract_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote {contract_path} ({contract.validation_status.value})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
