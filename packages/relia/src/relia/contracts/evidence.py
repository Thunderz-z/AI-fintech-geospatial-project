"""Evidence contracts: machine-verifiable support for generated claims.

Every important system-generated claim in the portfolio (environmental
findings in TerraScope, suspicious-activity narratives in FinGuard,
evaluation answers in RELIA) is packaged as an :class:`EvidenceContract`
that binds the claim to its concrete evidence, methodology, uncertainty
and limitations — or records an explicit abstention.

Design notes live in ``docs/decisions/0002-evidence-contracts.md``. The
contract is deliberately domain-agnostic: domain data structures stay in
the applications; only the verification envelope is shared.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.0.0"


class ValidationStatus(StrEnum):
    """Lifecycle state of a claim's validation."""

    UNVALIDATED = "unvalidated"
    VALID = "valid"
    INVALID = "invalid"
    ABSTAINED = "abstained"


class EvidenceType(StrEnum):
    """Kind of artefact an :class:`EvidenceRef` points at.

    The list covers the known portfolio domains; ``OTHER`` keeps the
    schema open without forcing new domains to fork the contract.
    """

    SATELLITE_OBSERVATION = "satellite_observation"
    RASTER_STATISTIC = "raster_statistic"
    TRANSACTION_RECORD = "transaction_record"
    GRAPH_MOTIF = "graph_motif"
    MODEL_RESULT = "model_result"
    DOCUMENT_EXCERPT = "document_excerpt"
    EVALUATION_RESULT = "evaluation_result"
    EXECUTION_TRACE = "execution_trace"
    OTHER = "other"


class EvidenceRef(BaseModel):
    """Reference to one concrete piece of supporting data or artefact."""

    evidence_id: str = Field(default_factory=lambda: uuid4().hex)
    evidence_type: EvidenceType
    description: str = Field(min_length=1)
    location: str = Field(
        min_length=1,
        description="How to reach the artefact: URI, path, scene ID, table key, ...",
    )
    source: str = Field(min_length=1, description="Producing system or provider (provenance).")
    observation_period: str | None = Field(
        default=None,
        description="ISO 8601 date or interval the evidence covers.",
    )
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MethodologyInfo(BaseModel):
    """How the claim was produced, at a reproducibility level."""

    name: str = Field(min_length=1)
    version: str | None = None
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class AbstentionInfo(BaseModel):
    """Explicit refusal to assert a claim, with what is missing to answer."""

    abstained: bool = False
    reason: str | None = None
    missing_requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reason_required_when_abstaining(self) -> AbstentionInfo:
        if self.abstained and not (self.reason and self.reason.strip()):
            raise ValueError("An abstention must state a reason.")
        return self


class EvidenceContract(BaseModel):
    """Verification envelope binding a claim to its evidence.

    Invariants enforced here:

    * An abstained claim must carry an abstention reason.
    * A claim marked ``VALID`` must reference at least one evidence item.
    * ``confidence``, when present, is a probability in [0, 1].
    """

    schema_version: str = SCHEMA_VERSION
    claim_id: str = Field(default_factory=lambda: uuid4().hex)
    claim_text: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    methodology: MethodologyInfo | None = None
    observation_period: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    uncertainty: dict[str, Any] | None = Field(
        default=None,
        description="Free-form uncertainty statement, e.g. a bootstrap interval.",
    )
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    limitations: list[str] = Field(default_factory=list)
    abstention: AbstentionInfo = Field(default_factory=AbstentionInfo)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _check_grounding(self) -> EvidenceContract:
        if self.abstention.abstained and not self.abstention.reason:
            raise ValueError("An abstained claim must carry an abstention reason.")
        if self.validation_status is ValidationStatus.VALID and not self.evidence:
            raise ValueError(
                "A claim marked valid must reference at least one evidence item."
            )
        return self
