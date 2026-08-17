from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from launch_os_v11.domain.enums import ControllerVerdict, EpistemicStatus


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskClass(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class EvidenceReference(StrictOutputModel):
    evidence_id: str = Field(min_length=1)
    epistemic_status: EpistemicStatus
    note: str = Field(min_length=1)


class FactUsage(StrictOutputModel):
    statement: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    epistemic_status: EpistemicStatus

    @model_validator(mode="after")
    def _must_be_fact_like(self) -> FactUsage:
        allowed = {
            EpistemicStatus.OBSERVATION,
            EpistemicStatus.FACT,
            EpistemicStatus.DERIVED_FACT,
        }
        if self.epistemic_status not in allowed:
            msg = "facts_used cannot contain hypothesis, unknown, conflict, or rejected status"
            raise ValueError(msg)
        return self


class HypothesisStatement(StrictOutputModel):
    statement: str = Field(min_length=1)
    evidence_ref: str | None = None
    confidence: float = Field(ge=0, le=1)


class AssumptionStatement(StrictOutputModel):
    statement: str = Field(min_length=1)
    evidence_ref: str | None = None
    confidence: float = Field(ge=0, le=1)


class UnknownStatement(StrictOutputModel):
    question: str = Field(min_length=1)
    critical: bool = False


class ConflictStatement(StrictOutputModel):
    statement: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class SpecialistContribution(StrictOutputModel):
    schema_name: Literal["SpecialistContribution"] = "SpecialistContribution"
    schema_version: Literal[1] = 1
    role: str = Field(min_length=1)
    observations: list[str] = Field(min_length=1)
    facts_used: list[FactUsage] = Field(default_factory=list)
    hypotheses: list[HypothesisStatement] = Field(default_factory=list)
    assumptions: list[AssumptionStatement] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[UnknownStatement] = Field(default_factory=list)
    conflicts: list[ConflictStatement] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_refs_cover_facts(self) -> SpecialistContribution:
        if self.facts_used and not self.evidence_refs:
            raise ValueError("facts_used requires explicit evidence_refs")
        declared = {item.evidence_id for item in self.evidence_refs}
        missing = [
            fact.evidence_ref for fact in self.facts_used if fact.evidence_ref not in declared
        ]
        if missing:
            raise ValueError("facts_used references must be present in evidence_refs")
        return self


class DecisionAlternativeOutput(StrictOutputModel):
    action: str = Field(min_length=1)
    rejection_reason: str = Field(min_length=1)


class ExperimentProposal(StrictOutputModel):
    hypothesis: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    segment: str = Field(min_length=1)
    treatment: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    window: str = Field(min_length=1)
    attribution_method: str = Field(min_length=1)
    success_threshold: str = Field(min_length=1)
    weak_signal_threshold: str = Field(min_length=1)
    failure_threshold: str = Field(min_length=1)
    next_action_on_success: str = Field(min_length=1)
    next_action_on_weak_signal: str = Field(min_length=1)
    next_action_on_failure: str = Field(min_length=1)


class DecisionCandidate(StrictOutputModel):
    schema_name: Literal["DecisionCandidate"] = "DecisionCandidate"
    schema_version: Literal[1] = 1
    goal: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    selected_action: str = Field(min_length=1)
    why: list[str] = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    alternatives: list[DecisionAlternativeOutput] = Field(min_length=1)
    why_alternatives_not_selected: list[str] = Field(default_factory=list)
    hypotheses: list[HypothesisStatement] = Field(default_factory=list)
    assumptions: list[AssumptionStatement] = Field(default_factory=list)
    unknowns: list[UnknownStatement] = Field(default_factory=list)
    expected_effect: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    reversibility: str = Field(min_length=1)
    risk_class: RiskClass
    experiment_proposal: ExperimentProposal | None = None
    required_assets: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    next_checkpoint: str = Field(min_length=1)


class ControllerReviewOutput(StrictOutputModel):
    schema_name: Literal["ControllerReview"] = "ControllerReview"
    schema_version: Literal[1] = 1
    controller_type: str = Field(min_length=1)
    verdict: ControllerVerdict
    issues: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    severity: RiskClass
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)


class RuntimeProbeOutput(StrictOutputModel):
    schema_name: Literal["RuntimeProbeOutput"] = "RuntimeProbeOutput"
    schema_version: Literal[1] = 1
    message: str = Field(min_length=1)
    facts_used: list[FactUsage] = Field(default_factory=list)
    hypotheses: list[HypothesisStatement] = Field(default_factory=list)
    unknowns: list[UnknownStatement] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ContentStrategyProposal(StrictOutputModel):
    schema_name: Literal["ContentStrategyProposal"] = "ContentStrategyProposal"
    schema_version: Literal[1] = 1
    objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    content_job: str = Field(min_length=1)
    core_message: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    message_mechanism: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    cta_intent: str = Field(min_length=1)
    channel_format: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    allowed_claims: list[str] = Field(default_factory=list)
    forbidden_or_unsupported_claims: list[str] = Field(default_factory=list)
    brand_constraints: list[str] = Field(default_factory=list)
    production_constraints: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[UnknownStatement] = Field(default_factory=list)


class ClaimInventoryItem(StrictOutputModel):
    text: str = Field(min_length=1)
    claim_type: Literal[
        "FACTUAL",
        "QUANTITATIVE",
        "TESTIMONIAL",
        "RESULT",
        "PROMOTIONAL",
    ]
    requires_evidence: bool
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _requires_evidence_ref(self) -> ClaimInventoryItem:
        if self.requires_evidence and not self.evidence_ref:
            raise ValueError("evidence-backed claim requires evidence_ref")
        return self


class RightsProvenanceDeclaration(StrictOutputModel):
    origin: Literal["GENERATED", "USER_PROVIDED", "LICENSED", "DERIVED"]
    related_source_asset_ids: list[str] = Field(default_factory=list)
    permission_scope: str | None = None
    customer_content_consent_ref: str | None = None
    publication_restrictions: list[str] = Field(default_factory=list)
    license_expires_at: str | None = None


class AssetDraftProposal(StrictOutputModel):
    schema_name: Literal["AssetDraftProposal"] = "AssetDraftProposal"
    schema_version: Literal[1] = 1
    body: str = Field(min_length=1)
    opening: str | None = None
    cta: str = Field(min_length=1)
    claim_inventory: list[ClaimInventoryItem] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    content_notes: list[str] = Field(default_factory=list)
    rights: RightsProvenanceDeclaration

    @model_validator(mode="after")
    def _claims_reference_declared_evidence(self) -> AssetDraftProposal:
        declared = {item.evidence_id for item in self.evidence_refs}
        missing = [
            claim.evidence_ref
            for claim in self.claim_inventory
            if claim.evidence_ref is not None and claim.evidence_ref not in declared
        ]
        if missing:
            raise ValueError("claim evidence_ref must be present in evidence_refs")
        return self
