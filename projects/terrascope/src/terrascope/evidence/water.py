"""Evidence contract for the water-extent observation series.

The claim is deliberately phrased as an **observation** (fraction of valid
pixels classified as water per date range) — never as causation (ADR-0006:
observed change ≠ attributed causation). The AOI fractions use the approximate
study bbox; only the Ramsar-polygon fractions carry an authoritative boundary.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from relia.contracts.evidence import (
    AbstentionInfo,
    EvidenceContract,
    EvidenceRef,
    EvidenceType,
    MethodologyInfo,
    ValidationStatus,
)
from terrascope.features.water_extent import WaterExtentObservation

__all__ = ["water_extent_contract"]


def water_extent_contract(
    observations: list[WaterExtentObservation],
    *,
    start: dt.date,
    end: dt.date,
    report_path: Path,
    threshold: float,
    min_valid_fraction: float,
) -> EvidenceContract:
    """Build the evidence envelope for a water-extent summary claim.

    Fully-abstained series produce an abstaining contract; otherwise the
    claim states the observed range with per-date abstentions in uncertainty.
    """
    abstained = [o for o in observations if o.abstained]
    usable = [o for o in observations if not o.abstained]

    methodology = MethodologyInfo(
        name="mndwi-threshold-water-extent",
        version="v0",
        description=(
            "Per sensing date (deduplicated to the latest processing baseline): "
            "SCL-masked MNDWI water fraction on the fixed 20 m composite grid."
        ),
        parameters={
            "mndwi_threshold": threshold,
            "min_valid_fraction": min_valid_fraction,
            "scl_exclude": sorted({0, 1, 3, 8, 9, 10, 11}),
            "bands": {"green": "B03 (10 m -> 20 m grid)", "swir1": "B11 (20 m)"},
            "grid_crs": "EPSG:32644",
            "scene_dedup": "latest processing baseline per sensing timestamp",
        },
    )

    evidence_refs = [
        EvidenceRef(
            evidence_type=EvidenceType.RASTER_STATISTIC,
            description=(
                "Water-extent observation series JSON (per-date fractions, pixel counts, "
                "abstentions)"
            ),
            location=str(report_path),
            source="terrascope.features.water_extent",
            observation_period=f"{start.isoformat()}/{end.isoformat()}",
        ),
        EvidenceRef(
            evidence_type=EvidenceType.SATELLITE_OBSERVATION,
            description=(
                "As-acquired Sentinel-2 L2A AOI windows with per-file SHA-256 acquisition log"
            ),
            location=(
                "raw/sentinel-2-l2a/acquisition_log.jsonl (under PORTFOLIO_DATA_ROOT/terrascope)"
            ),
            source=(
                "Microsoft Planetary Computer (sentinel-2-l2a); "
                "Contains modified Copernicus Sentinel data"
            ),
            observation_period=f"{start.isoformat()}/{end.isoformat()}",
        ),
    ]

    limitations = [
        (
            "MNDWI > 0 threshold is uncalibrated for turbid marsh water "
            "(v0; revisit with QA histograms)."
        ),
        "AOI water fractions use the APPROXIMATE study bbox boundary; only the Ramsar-polygon "
        "fractions carry an authoritative boundary.",
        (
            "The approximate bbox grid includes a sliver of coastal ocean (MNDWI-positive), which "
            "inflates AOI fractions; the Ramsar-polygon series is the primary measurement."
        ),
        (
            "Single-scene snapshots per date; not continuous monitoring; "
            "no intertidal/tidal correction."
        ),
        "SCL has no dedicated cloud-shadow class; residual shadow can bias fractions either way.",
        "Observation only — no causal attribution for any change (ADR-0006).",
    ]

    if not usable:
        return EvidenceContract(
            claim_text=(
                f"No water-extent claim is made for {start.isoformat()}..{end.isoformat()}: "
                f"all {len(observations)} cached scene dates failed the "
                f"{min_valid_fraction:.0%} valid-fraction gate."
            ),
            evidence=evidence_refs,
            methodology=methodology,
            observation_period=f"{start.isoformat()}/{end.isoformat()}",
            validation_status=ValidationStatus.ABSTAINED,
            limitations=limitations,
            abstention=AbstentionInfo(
                abstained=True,
                reason="Insufficient cloud-free coverage on every cached scene date in the window.",
                missing_requirements=[
                    "additional scenes meeting the valid-fraction gate",
                    "a calibrated water threshold",
                ],
            ),
        )

    aoi_values = [o.water_fraction_aoi for o in usable if o.water_fraction_aoi is not None]
    ramsar_values = [o.water_fraction_ramsar for o in usable if o.water_fraction_ramsar is not None]
    claim_text = (
        f"Between {start.isoformat()} and {end.isoformat()}, the SCL-masked MNDWI(>{threshold:g}) "
        f"water fraction within the approximate Pallikaranai study AOI ranged "
        f"{min(aoi_values):.1%}–{max(aoi_values):.1%} across {len(usable)} usable Sentinel-2 L2A "
        f"scenes ({len(abstained)} of {len(observations)} dates abstained on the "
        f"{min_valid_fraction:.0%} valid-fraction gate). Within the authoritative Ramsar IN2481 "
        f"boundary the water fraction ranged {min(ramsar_values):.1%}–{max(ramsar_values):.1%}. "
        "This is an observation range over the window, not a trend or causal statement."
    )

    return EvidenceContract(
        claim_text=claim_text,
        evidence=evidence_refs,
        methodology=methodology,
        observation_period=f"{start.isoformat()}/{end.isoformat()}",
        validation_status=ValidationStatus.VALID,
        uncertainty={
            "per_date_valid_fractions": {o.sensing_date: o.valid_fraction for o in observations},
            "abstained_dates": {
                o.sensing_date: o.abstention_reason for o in abstained
            },
            "scene_ids": [o.scene_id for o in observations],
        },
        limitations=limitations,
        abstention=AbstentionInfo(abstained=False),
    )


def write_contract(contract: EvidenceContract, out_path: Path) -> Path:
    """Persist a contract as JSON next to its report."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    return out_path
