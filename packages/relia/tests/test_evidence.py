"""Tests for the shared evidence contracts (relia.contracts.evidence)."""

import pytest
from pydantic import ValidationError

from relia.contracts.evidence import (
    SCHEMA_VERSION,
    AbstentionInfo,
    EvidenceContract,
    EvidenceRef,
    EvidenceType,
    MethodologyInfo,
    ValidationStatus,
)


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_type=EvidenceType.SATELLITE_OBSERVATION,
        description="Sentinel-2 L2A scene over the study area",
        location="https://example.com/scene/S2A_44NNA_20240115",
        source="Microsoft Planetary Computer",
        observation_period="2024-01-15",
    )


def test_contract_construction_with_defaults() -> None:
    contract = EvidenceContract(claim_text="Water extent decreased.", evidence=[_evidence()])

    assert contract.schema_version == SCHEMA_VERSION
    assert contract.validation_status is ValidationStatus.UNVALIDATED
    assert contract.abstention.abstained is False
    assert contract.claim_id
    assert contract.evidence[0].evidence_id


def test_valid_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="at least one evidence"):
        EvidenceContract(claim_text="X", validation_status=ValidationStatus.VALID)


def test_valid_claim_with_evidence_passes() -> None:
    contract = EvidenceContract(
        claim_text="X",
        evidence=[_evidence()],
        validation_status=ValidationStatus.VALID,
        methodology=MethodologyInfo(name="ndwi-threshold", version="1.0"),
        confidence=0.93,
    )
    assert contract.methodology is not None
    assert contract.confidence == pytest.approx(0.93)


def test_confidence_bounds_enforced() -> None:
    evidence = [_evidence()]
    with pytest.raises(ValidationError):
        EvidenceContract(claim_text="X", evidence=evidence, confidence=1.5)
    with pytest.raises(ValidationError):
        EvidenceContract(claim_text="X", evidence=evidence, confidence=-0.1)


def test_abstained_claim_requires_reason() -> None:
    with pytest.raises(ValidationError, match="abstention must state a reason"):
        EvidenceContract(claim_text="X", abstention=AbstentionInfo(abstained=True))

    abstained = EvidenceContract(
        claim_text="X",
        abstention=AbstentionInfo(
            abstained=True,
            reason="Cloud-free coverage below the 80% threshold.",
            missing_requirements=["cloud-free composite for 2026-Q3"],
        ),
    )
    assert abstained.validation_status is ValidationStatus.UNVALIDATED
    assert abstained.abstention.missing_requirements


def test_empty_claim_text_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceContract(claim_text="")


def test_json_round_trip() -> None:
    contract = EvidenceContract(
        claim_text="Built-up area increased between 2020 and 2024.",
        evidence=[_evidence()],
        methodology=MethodologyInfo(
            name="ndbi-change",
            parameters={"threshold": 0.1, "compositing": "seasonal-median"},
        ),
        validation_status=ValidationStatus.VALID,
        confidence=0.88,
        limitations=["Classification uncertainty not included in the interval."],
        observation_period="2020-01/2024-12",
    )

    restored = EvidenceContract.model_validate_json(contract.model_dump_json())
    assert restored == contract


def test_evidence_ids_unique_by_default() -> None:
    first, second = _evidence(), _evidence()
    assert first.evidence_id != second.evidence_id


def test_all_evidence_types_reusable() -> None:
    for evidence_type in EvidenceType:
        ref = EvidenceRef(
            evidence_type=evidence_type,
            description="d",
            location="loc",
            source="src",
        )
        assert ref.evidence_type is evidence_type
