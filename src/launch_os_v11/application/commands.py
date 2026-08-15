from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

from sqlalchemy.orm import Session

from launch_os_v11.domain.entities import (
    Asset,
    AssetVersion,
    BusinessSnapshot,
    Decision,
)
from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    EpistemicStatus,
    SourceTrust,
)
from launch_os_v11.domain.events import DomainEvent
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import (
    ActionModel,
    ApprovalModel,
    AssetModel,
    AssetVersionModel,
    AuditLogModel,
    BusinessEventModel,
    BusinessModel,
    BusinessSnapshotModel,
    DecisionModel,
    EvidenceModel,
    GoalModel,
    OrganizationModel,
    SourceRecordModel,
)
from launch_os_v11.persistence.outbox import append_outbox_event
from launch_os_v11.persistence.repositories import ScopedRepository


@dataclass(frozen=True)
class CommandContext:
    organization_id: str
    business_id: str
    actor_user_id: str | None
    correlation_id: str = field(default_factory=new_id)
    causation_id: str | None = None

    @property
    def scope(self) -> TenantScope:
        return TenantScope(
            organization_id=self.organization_id,
            business_id=self.business_id,
        )


RecordT = TypeVar("RecordT")


@dataclass(frozen=True)
class CommandResult(Generic[RecordT]):
    record: RecordT
    event: DomainEvent


def _append_audit(
    session: Session,
    *,
    context: CommandContext,
    action: str,
    object_type: str,
    object_id: str,
    payload: dict[str, Any] | None = None,
) -> AuditLogModel:
    audit = AuditLogModel(
        organization_id=context.organization_id,
        business_id=context.business_id,
        actor_user_id=context.actor_user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        payload=payload or {},
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
    )
    session.add(audit)
    return audit


def _event(
    context: CommandContext,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        organization_id=context.organization_id,
        business_id=context.business_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
        actor_user_id=context.actor_user_id,
        payload=payload or {},
    )


def create_organization(
    session: Session,
    *,
    name: str,
) -> OrganizationModel:
    organization = OrganizationModel(id=new_id(), name=name)
    session.add(organization)
    # Scalar FK ids do not create ORM object dependencies for later commands.
    session.flush()
    return organization


def create_business(
    session: Session,
    *,
    organization_id: str,
    name: str,
    timezone: str,
    actor_user_id: str | None,
    correlation_id: str | None = None,
) -> CommandResult[BusinessModel]:
    business_id = new_id()
    context = CommandContext(
        organization_id=organization_id,
        business_id=business_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id or new_id(),
    )
    business = BusinessModel(
        id=business_id,
        organization_id=organization_id,
        name=name,
        timezone=timezone,
    )
    session.add(business)
    # Business is the tenant parent for the side-effect rows appended below.
    session.flush()
    event = _event(
        context,
        event_type="business.created",
        aggregate_type="Business",
        aggregate_id=business.id,
        payload={"name": name, "timezone": timezone},
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action="create_business",
        object_type="Business",
        object_id=business.id,
    )
    return CommandResult(record=business, event=event)


def create_goal(
    session: Session,
    *,
    context: CommandContext,
    title: str,
    target: str,
    metric: str | None = None,
) -> CommandResult[GoalModel]:
    goal = GoalModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        title=title,
        target=target,
        metric=metric,
    )
    ScopedRepository(session, context.scope, GoalModel).add(goal)
    event = _event(
        context,
        event_type="goal.created",
        aggregate_type="Goal",
        aggregate_id=goal.id,
        payload={"title": title, "metric": metric},
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action="create_goal",
        object_type="Goal",
        object_id=goal.id,
    )
    return CommandResult(record=goal, event=event)


def create_source_record(
    session: Session,
    *,
    context: CommandContext,
    provider: str,
    external_id: str,
    source_type: str,
    payload: dict[str, Any],
    trust: SourceTrust = SourceTrust.UNTRUSTED_EXTERNAL,
) -> CommandResult[SourceRecordModel]:
    now = utc_now()
    source_record = SourceRecordModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        provider=provider,
        external_id=external_id,
        source_type=source_type,
        trust=trust.value,
        payload=payload,
        source_occurred_at=now,
        ingested_at=now,
    )
    ScopedRepository(session, context.scope, SourceRecordModel).add(source_record)
    event = _event(
        context,
        event_type="source_record.created",
        aggregate_type="SourceRecord",
        aggregate_id=source_record.id,
        payload={"provider": provider, "external_id": external_id},
    )
    append_outbox_event(session, event)
    return CommandResult(record=source_record, event=event)


def create_evidence(
    session: Session,
    *,
    context: CommandContext,
    source_record_id: str,
    statement: str,
    status: EpistemicStatus,
    confidence: float | None = None,
) -> CommandResult[EvidenceModel]:
    evidence = EvidenceModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        source_record_id=source_record_id,
        statement=statement,
        status=status.value,
        confidence=confidence,
        recorded_at=utc_now(),
        conflicts_with_evidence_ids=[],
    )
    ScopedRepository(session, context.scope, EvidenceModel).add(evidence)
    event = _event(
        context,
        event_type="evidence.created",
        aggregate_type="Evidence",
        aggregate_id=evidence.id,
        payload={"status": status.value},
    )
    append_outbox_event(session, event)
    return CommandResult(record=evidence, event=event)


def create_business_snapshot(
    session: Session,
    *,
    context: CommandContext,
    reason: str,
    payload: dict[str, Any],
) -> CommandResult[BusinessSnapshotModel]:
    snapshot = BusinessSnapshot.create(
        organization_id=context.organization_id,
        business_id=context.business_id,
        reason=reason,
        payload=payload,
    )
    row = BusinessSnapshotModel(
        id=snapshot.id,
        organization_id=snapshot.organization_id,
        business_id=snapshot.business_id,
        version=snapshot.version,
        reason=snapshot.reason,
        payload=payload,
        created_at=snapshot.created_at,
    )
    session.add(row)
    event = _event(
        context,
        event_type="business_snapshot.created",
        aggregate_type="BusinessSnapshot",
        aggregate_id=row.id,
        payload={"reason": reason},
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action="create_business_snapshot",
        object_type="BusinessSnapshot",
        object_id=row.id,
    )
    return CommandResult(record=row, event=event)


def persist_decision(
    session: Session,
    *,
    context: CommandContext,
    decision: Decision,
) -> CommandResult[DecisionModel]:
    context.scope.assert_matches(
        organization_id=decision.organization_id,
        business_id=decision.business_id,
    )
    row = DecisionModel(
        id=decision.id,
        organization_id=decision.organization_id,
        business_id=decision.business_id,
        version=decision.version,
        goal_problem=decision.goal_problem,
        selected_action=decision.selected_action,
        expected_effect=decision.expected_effect,
        confidence=decision.confidence,
        reversibility=decision.reversibility,
        risk_class=decision.risk_class,
        status=decision.status.value,
        snapshot_id=decision.snapshot_id,
        supersedes_decision_id=decision.supersedes_decision_id,
        next_checkpoint=decision.next_checkpoint,
        evidence_ids=list(decision.evidence_ids),
        assumption_ids=list(decision.assumption_ids),
        known_unknown_ids=list(decision.known_unknown_ids),
    )
    ScopedRepository(session, context.scope, DecisionModel).add(row)
    event = _event(
        context,
        event_type="decision.created",
        aggregate_type="Decision",
        aggregate_id=row.id,
        payload={"supersedes_decision_id": row.supersedes_decision_id},
    )
    append_outbox_event(session, event)
    return CommandResult(record=row, event=event)


def create_asset_version(
    session: Session,
    *,
    context: CommandContext,
    asset_row: AssetModel,
    body: str,
    created_by_user_id: str,
    previous_version: AssetVersionModel | None = None,
    provenance: dict[str, Any] | None = None,
) -> CommandResult[AssetVersionModel]:
    asset = Asset(
        id=asset_row.id,
        organization_id=asset_row.organization_id,
        business_id=asset_row.business_id,
        version=asset_row.version,
        created_at=asset_row.created_at,
        updated_at=asset_row.updated_at,
        creative_brief_id=asset_row.creative_brief_id,
        asset_type=asset_row.asset_type,
        title=asset_row.title,
    )
    previous = None
    if previous_version is not None:
        previous = AssetVersion(
            id=previous_version.id,
            organization_id=previous_version.organization_id,
            business_id=previous_version.business_id,
            asset_id=previous_version.asset_id,
            version_number=previous_version.version_number,
            body=previous_version.body,
            created_by_user_id=previous_version.created_by_user_id,
            provenance=previous_version.provenance,
            created_at=previous_version.created_at,
        )
    new_version = AssetVersion.next_for(
        asset=asset,
        body=body,
        created_by_user_id=created_by_user_id,
        previous=previous,
        provenance=provenance,
    )
    row = AssetVersionModel(
        id=new_version.id,
        organization_id=new_version.organization_id,
        business_id=new_version.business_id,
        asset_id=new_version.asset_id,
        version_number=new_version.version_number,
        body=new_version.body,
        created_by_user_id=new_version.created_by_user_id,
        provenance=new_version.provenance,
        created_at=new_version.created_at,
    )
    context.scope.assert_matches(organization_id=row.organization_id, business_id=row.business_id)
    session.add(row)
    event = _event(
        context,
        event_type="asset_version.created",
        aggregate_type="AssetVersion",
        aggregate_id=row.id,
        payload={"asset_id": row.asset_id, "version_number": row.version_number},
    )
    append_outbox_event(session, event)
    return CommandResult(record=row, event=event)


def approve_action(
    session: Session,
    *,
    context: CommandContext,
    action: ActionModel,
    approved_by_user_id: str,
) -> CommandResult[ApprovalModel]:
    context.scope.assert_matches(
        organization_id=action.organization_id,
        business_id=action.business_id,
    )
    approval = ApprovalModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        action_id=action.id,
        action_type=action.action_type,
        object_type=action.target_object_type,
        object_id=action.target_object_id,
        object_version_id=action.target_object_version_id,
        object_version=action.target_object_version,
        approved_by_user_id=approved_by_user_id,
        status=ApprovalStatus.APPROVED.value,
        created_at=utc_now(),
    )
    session.add(approval)
    action.status = ActionStatus.APPROVED.value
    event = _event(
        context,
        event_type="approval.created",
        aggregate_type="Approval",
        aggregate_id=approval.id,
        payload={
            "action_id": action.id,
            "action_type": approval.action_type,
            "object_type": approval.object_type,
            "object_id": approval.object_id,
            "object_version_id": approval.object_version_id,
            "object_version": approval.object_version,
        },
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action="approve_action",
        object_type=approval.object_type,
        object_id=approval.object_id,
        payload={"object_version": approval.object_version},
    )
    return CommandResult(record=approval, event=event)


def create_business_event(
    session: Session,
    *,
    context: CommandContext,
    event_type: str,
    occurred_at: datetime,
    recorded_at: datetime,
    payload: dict[str, Any] | None = None,
) -> CommandResult[BusinessEventModel]:
    row = BusinessEventModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        event_type=event_type,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        payload=payload or {},
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
    )
    ScopedRepository(session, context.scope, BusinessEventModel).add(row)
    event = _event(
        context,
        event_type="business_event.recorded",
        aggregate_type="BusinessEvent",
        aggregate_id=row.id,
        payload={"business_event_type": event_type},
    )
    append_outbox_event(session, event)
    return CommandResult(record=row, event=event)
