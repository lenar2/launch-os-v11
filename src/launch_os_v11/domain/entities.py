from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    CausalityClass,
    ControllerVerdict,
    DecisionStatus,
    EpistemicStatus,
    ExecutionStatus,
    ExperimentStatus,
    JobStatus,
    LaunchPhaseStatus,
    OutboxStatus,
    PermissionMode,
    PublicationStatus,
    SourceTrust,
    VerificationBasis,
)
from launch_os_v11.domain.epistemic import transition_epistemic_status
from launch_os_v11.domain.exceptions import ApprovalBindingError
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass
class VersionedBusinessObject:
    organization_id: str
    business_id: str
    id: str = field(default_factory=new_id)
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class User:
    email: str
    display_name: str
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Business:
    organization_id: str
    name: str
    timezone: str
    id: str = field(default_factory=new_id)
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class BusinessMembership:
    organization_id: str
    business_id: str
    user_id: str
    role: str
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Goal(VersionedBusinessObject):
    title: str = ""
    target: str = ""
    metric: str | None = None
    due_at: datetime | None = None


@dataclass
class Constraint(VersionedBusinessObject):
    category: str = ""
    rule: str = ""


@dataclass
class Product(VersionedBusinessObject):
    name: str = ""
    description: str = ""


@dataclass
class Offer(VersionedBusinessObject):
    product_id: str = ""
    name: str = ""
    description: str = ""
    price_descriptor: str | None = None


@dataclass
class Channel(VersionedBusinessObject):
    provider: str = ""
    handle: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceRecord(VersionedBusinessObject):
    provider: str = ""
    external_id: str = ""
    source_type: str = ""
    trust: SourceTrust = SourceTrust.UNTRUSTED_EXTERNAL
    payload: dict[str, Any] = field(default_factory=dict)
    source_occurred_at: datetime | None = None
    ingested_at: datetime = field(default_factory=utc_now)


@dataclass
class Evidence(VersionedBusinessObject):
    source_record_id: str = ""
    statement: str = ""
    status: EpistemicStatus = EpistemicStatus.OBSERVATION
    confidence: float | None = None
    occurred_at: datetime | None = None
    recorded_at: datetime = field(default_factory=utc_now)
    conflicts_with_evidence_ids: tuple[str, ...] = ()

    def transition_to(
        self,
        target: EpistemicStatus,
        *,
        basis: VerificationBasis,
        evidence_ids: tuple[str, ...] = (),
    ) -> Evidence:
        new_status = transition_epistemic_status(
            self.status,
            target,
            basis=basis,
            evidence_ids=evidence_ids,
        )
        return replace(self, status=new_status, version=self.version + 1, updated_at=utc_now())

    def mark_conflict(self, conflicting_evidence_id: str) -> Evidence:
        conflict_ids = tuple({*self.conflicts_with_evidence_ids, conflicting_evidence_id})
        return replace(
            self,
            status=EpistemicStatus.CONFLICT,
            conflicts_with_evidence_ids=conflict_ids,
            version=self.version + 1,
            updated_at=utc_now(),
        )


@dataclass
class Claim(VersionedBusinessObject):
    statement: str = ""
    status: EpistemicStatus = EpistemicStatus.UNKNOWN
    evidence_ids: tuple[str, ...] = ()

    def transition_to(
        self,
        target: EpistemicStatus,
        *,
        basis: VerificationBasis,
        evidence_ids: tuple[str, ...] = (),
    ) -> Claim:
        new_status = transition_epistemic_status(
            self.status,
            target,
            basis=basis,
            evidence_ids=evidence_ids,
        )
        return replace(
            self,
            status=new_status,
            evidence_ids=tuple({*self.evidence_ids, *evidence_ids}),
            version=self.version + 1,
            updated_at=utc_now(),
        )


@dataclass
class Hypothesis(VersionedBusinessObject):
    statement: str = ""
    status: EpistemicStatus = EpistemicStatus.HYPOTHESIS
    model_confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()

    def promote_to_fact(
        self,
        *,
        basis: VerificationBasis,
        evidence_ids: tuple[str, ...] = (),
    ) -> Claim:
        new_status = transition_epistemic_status(
            self.status,
            EpistemicStatus.FACT,
            basis=basis,
            evidence_ids=evidence_ids,
        )
        return Claim(
            organization_id=self.organization_id,
            business_id=self.business_id,
            statement=self.statement,
            status=new_status,
            evidence_ids=evidence_ids,
        )


@dataclass
class InformationNeed(VersionedBusinessObject):
    question: str = ""
    critical: bool = False
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class BusinessSnapshot:
    organization_id: str
    business_id: str
    reason: str
    payload: Any
    id: str = field(default_factory=new_id)
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        organization_id: str,
        business_id: str,
        reason: str,
        payload: dict[str, Any],
    ) -> BusinessSnapshot:
        return cls(
            organization_id=organization_id,
            business_id=business_id,
            reason=reason,
            payload=_freeze_value(payload),
        )


@dataclass
class Campaign(VersionedBusinessObject):
    name: str = ""
    goal_id: str | None = None


@dataclass
class Launch(VersionedBusinessObject):
    campaign_id: str = ""
    offer_id: str = ""
    goal_id: str = ""
    channel_id: str = ""
    snapshot_id: str | None = None
    status: LaunchPhaseStatus = LaunchPhaseStatus.PLANNED


@dataclass
class LaunchPhase(VersionedBusinessObject):
    launch_id: str = ""
    name: str = ""
    status: LaunchPhaseStatus = LaunchPhaseStatus.PLANNED
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@dataclass
class Decision(VersionedBusinessObject):
    goal_problem: str = ""
    selected_action: str = ""
    expected_effect: str = ""
    confidence: float | None = None
    reversibility: str = ""
    risk_class: str = ""
    status: DecisionStatus = DecisionStatus.ACTIVE
    snapshot_id: str | None = None
    supersedes_decision_id: str | None = None
    next_checkpoint: str | None = None
    evidence_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    known_unknown_ids: tuple[str, ...] = ()

    def supersede_with(
        self,
        *,
        selected_action: str,
        goal_problem: str | None = None,
        expected_effect: str | None = None,
        reason: str,
    ) -> Decision:
        if not selected_action:
            msg = "a superseding decision must include selected_action"
            raise ValueError(msg)
        return Decision(
            organization_id=self.organization_id,
            business_id=self.business_id,
            goal_problem=goal_problem or self.goal_problem,
            selected_action=selected_action,
            expected_effect=expected_effect or self.expected_effect,
            confidence=self.confidence,
            reversibility=self.reversibility,
            risk_class=self.risk_class,
            snapshot_id=self.snapshot_id,
            supersedes_decision_id=self.id,
            next_checkpoint=reason,
            evidence_ids=self.evidence_ids,
            assumption_ids=self.assumption_ids,
            known_unknown_ids=self.known_unknown_ids,
        )


@dataclass
class DecisionAlternative(VersionedBusinessObject):
    decision_id: str = ""
    action: str = ""
    rejection_reason: str = ""


@dataclass
class ControllerReview(VersionedBusinessObject):
    decision_id: str | None = None
    asset_version_id: str | None = None
    controller_name: str = ""
    verdict: ControllerVerdict = ControllerVerdict.PASS
    reason: str = ""


@dataclass
class Experiment(VersionedBusinessObject):
    decision_id: str = ""
    hypothesis_id: str | None = None
    metric: str = ""
    status: ExperimentStatus = ExperimentStatus.DRAFT
    causality_class: CausalityClass = CausalityClass.UNKNOWN


@dataclass
class ExperimentRule(VersionedBusinessObject):
    experiment_id: str = ""
    baseline: str = ""
    segment: str = ""
    treatment: str = ""
    metric: str = ""
    window: str = ""
    attribution_method: str = ""
    success_threshold: str = ""
    weak_signal_threshold: str = ""
    failure_threshold: str = ""
    next_action_on_success: str = ""
    next_action_on_weak_signal: str = ""
    next_action_on_failure: str = ""


@dataclass
class ExperimentResult(VersionedBusinessObject):
    experiment_id: str = ""
    result_class: str = ""
    observed_value: str = ""
    interpreted_at: datetime = field(default_factory=utc_now)


@dataclass
class CreativeBrief(VersionedBusinessObject):
    decision_id: str = ""
    title: str = ""
    objective: str = ""
    constraints: tuple[str, ...] = ()


@dataclass
class Asset(VersionedBusinessObject):
    creative_brief_id: str = ""
    asset_type: str = ""
    title: str = ""


@dataclass(frozen=True)
class AssetVersion:
    organization_id: str
    business_id: str
    asset_id: str
    version_number: int
    body: str
    created_by_user_id: str
    provenance: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def next_for(
        cls,
        *,
        asset: Asset,
        body: str,
        created_by_user_id: str,
        previous: AssetVersion | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> AssetVersion:
        version_number = 1 if previous is None else previous.version_number + 1
        return cls(
            organization_id=asset.organization_id,
            business_id=asset.business_id,
            asset_id=asset.id,
            version_number=version_number,
            body=body,
            created_by_user_id=created_by_user_id,
            provenance=provenance or {},
        )


@dataclass
class Publication(VersionedBusinessObject):
    asset_version_id: str = ""
    channel_id: str = ""
    status: PublicationStatus = PublicationStatus.DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None


@dataclass
class PermissionPolicy(VersionedBusinessObject):
    action_type: str = ""
    mode: PermissionMode = PermissionMode.EXECUTE_AFTER_APPROVAL
    requires_approval: bool = True
    public_visibility: bool = True


@dataclass
class Action(VersionedBusinessObject):
    action_type: str = ""
    target_object_type: str = ""
    target_object_id: str = ""
    target_object_version_id: str = ""
    target_object_version: int = 1
    status: ActionStatus = ActionStatus.PROPOSED
    idempotency_key: str = field(default_factory=new_id)


@dataclass(frozen=True)
class Approval:
    organization_id: str
    business_id: str
    action_id: str
    action_type: str
    object_type: str
    object_id: str
    object_version_id: str
    object_version: int
    approved_by_user_id: str
    status: ApprovalStatus = ApprovalStatus.APPROVED
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def assert_valid_for(
        self,
        *,
        action_id: str,
        action_type: str,
        object_type: str,
        object_id: str,
        object_version_id: str,
        object_version: int,
    ) -> None:
        if (
            self.status != ApprovalStatus.APPROVED
            or self.action_id != action_id
            or self.action_type != action_type
            or self.object_type != object_type
            or self.object_id != object_id
            or self.object_version_id != object_version_id
            or self.object_version != object_version
        ):
            msg = "approval is bound to a different object/version/action"
            raise ApprovalBindingError(msg)

    def is_valid_for(
        self,
        *,
        action_id: str,
        action_type: str,
        object_type: str,
        object_id: str,
        object_version_id: str,
        object_version: int,
    ) -> bool:
        try:
            self.assert_valid_for(
                action_id=action_id,
                action_type=action_type,
                object_type=object_type,
                object_id=object_id,
                object_version_id=object_version_id,
                object_version=object_version,
            )
        except ApprovalBindingError:
            return False
        return True


@dataclass
class Execution(VersionedBusinessObject):
    action_id: str = ""
    approval_id: str | None = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    idempotency_key: str = field(default_factory=new_id)
    external_reference: str | None = None


@dataclass
class BusinessEvent(VersionedBusinessObject):
    event_type: str = ""
    source_record_id: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    recorded_at: datetime = field(default_factory=utc_now)
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass
class OutboxEvent(VersionedBusinessObject):
    event_type: str = ""
    aggregate_type: str = ""
    aggregate_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    occurred_at: datetime = field(default_factory=utc_now)
    correlation_id: str = field(default_factory=new_id)
    causation_id: str | None = None


@dataclass
class Job(VersionedBusinessObject):
    job_type: str = ""
    status: JobStatus = JobStatus.QUEUED
    payload: dict[str, Any] = field(default_factory=dict)
    run_after: datetime | None = None


@dataclass
class AgentDefinition(VersionedBusinessObject):
    name: str = ""
    mission: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = False


@dataclass
class AgentRun(VersionedBusinessObject):
    agent_definition_id: str = ""
    status: JobStatus = JobStatus.PENDING
    input_ref: str | None = None
    output_ref: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass
class AuditLog(VersionedBusinessObject):
    actor_user_id: str | None = None
    action: str = ""
    object_type: str = ""
    object_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass
class FeatureFlag(VersionedBusinessObject):
    key: str = ""
    enabled: bool = False
    description: str = ""


@dataclass
class Learning(VersionedBusinessObject):
    decision_id: str | None = None
    experiment_id: str | None = None
    statement: str = ""
    evidence_ids: tuple[str, ...] = ()
    causality_class: CausalityClass = CausalityClass.UNKNOWN
    confidence: float | None = None
