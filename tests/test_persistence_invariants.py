from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from launch_os_v11.application.commands import (
    CommandContext,
    create_business,
    create_business_event,
    create_evidence,
    create_goal,
    create_organization,
    create_source_record,
    persist_decision,
)
from launch_os_v11.domain.entities import Decision
from launch_os_v11.domain.enums import DecisionStatus, EpistemicStatus
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    BusinessEventModel,
    BusinessModel,
    DecisionModel,
    EvidenceModel,
    GoalModel,
    OutboxEventModel,
)
from launch_os_v11.persistence.repositories import ScopedRepository


def test_tenant_a_cannot_read_or_modify_tenant_b_object(session: Session) -> None:
    scope_a = TenantScope(organization_id="org-a", business_id="biz-a")
    scope_b = TenantScope(organization_id="org-b", business_id="biz-b")
    goal_a = GoalModel(
        id="goal-a",
        organization_id=scope_a.organization_id,
        business_id=scope_a.business_id,
        title="A",
        target="A target",
    )
    goal_b = GoalModel(
        id="goal-b",
        organization_id=scope_b.organization_id,
        business_id=scope_b.business_id,
        title="B",
        target="B target",
    )
    session.add_all([goal_a, goal_b])
    session.commit()

    repo_a = ScopedRepository(session, scope_a, GoalModel)

    assert repo_a.get("goal-a") is not None
    assert repo_a.get("goal-b") is None
    with pytest.raises(TenantScopeViolation):
        repo_a.update_fields("goal-b", title="cross-tenant write")


def test_conflicting_evidence_records_are_preserved(session: Session) -> None:
    context = CommandContext(
        organization_id="org-a",
        business_id="biz-a",
        actor_user_id="user-a",
        correlation_id="corr-evidence",
    )
    source_1 = create_source_record(
        session,
        context=context,
        provider="telegram",
        external_id="message-1",
        source_type="message",
        payload={"text": "12 replies"},
    ).record
    source_2 = create_source_record(
        session,
        context=context,
        provider="manual",
        external_id="note-1",
        source_type="note",
        payload={"text": "not 12 replies"},
    ).record
    evidence_1 = create_evidence(
        session,
        context=context,
        source_record_id=source_1.id,
        statement="Post received 12 replies",
        status=EpistemicStatus.OBSERVATION,
    ).record
    evidence_2 = create_evidence(
        session,
        context=context,
        source_record_id=source_2.id,
        statement="Post did not receive 12 replies",
        status=EpistemicStatus.CONFLICT,
    ).record
    evidence_2.conflicts_with_evidence_ids = [evidence_1.id]
    session.commit()

    records = (
        session.execute(select(EvidenceModel).order_by(EvidenceModel.statement))
        .scalars()
        .all()
    )

    assert len(records) == 2
    assert {record.status for record in records} == {
        EpistemicStatus.OBSERVATION.value,
        EpistemicStatus.CONFLICT.value,
    }


def test_domain_event_and_outbox_event_are_atomic(session: Session) -> None:
    organization = create_organization(session, name="Org A")
    session.commit()

    with pytest.raises(RuntimeError), session.begin():
        create_business(
            session,
            organization_id=organization.id,
            name="Business A",
            timezone="Asia/Barnaul",
            actor_user_id="user-a",
            correlation_id="corr-atomic",
        )
        raise RuntimeError("force rollback")

    assert session.scalar(select(func.count()).select_from(BusinessModel)) == 0
    assert session.scalar(select(func.count()).select_from(OutboxEventModel)) == 0
    session.rollback()

    with session.begin():
        result = create_business(
            session,
            organization_id=organization.id,
            name="Business A",
            timezone="Asia/Barnaul",
            actor_user_id="user-a",
            correlation_id="corr-atomic",
        )

    assert session.get(BusinessModel, result.record.id) is not None
    outbox = session.get(OutboxEventModel, result.event.id)
    assert outbox is not None
    assert outbox.aggregate_id == result.record.id
    assert outbox.correlation_id == "corr-atomic"


def test_correlation_id_and_causation_id_flow_through_chain(session: Session) -> None:
    organization = create_organization(session, name="Org A")
    business_result = create_business(
        session,
        organization_id=organization.id,
        name="Business A",
        timezone="Asia/Barnaul",
        actor_user_id="user-a",
        correlation_id="corr-chain",
    )
    goal_context = CommandContext(
        organization_id=organization.id,
        business_id=business_result.record.id,
        actor_user_id="user-a",
        correlation_id=business_result.event.correlation_id,
        causation_id=business_result.event.id,
    )
    goal_result = create_goal(
        session,
        context=goal_context,
        title="First launch",
        target="Validate offer",
    )
    session.commit()

    assert goal_result.event.correlation_id == "corr-chain"
    assert goal_result.event.causation_id == business_result.event.id
    outbox = session.get(OutboxEventModel, goal_result.event.id)
    assert outbox is not None
    assert outbox.correlation_id == "corr-chain"
    assert outbox.causation_id == business_result.event.id


def test_decision_supersession_persists_both_versions(session: Session) -> None:
    context = CommandContext(
        organization_id="org-a",
        business_id="biz-a",
        actor_user_id="user-a",
        correlation_id="corr-decision",
    )
    old = Decision(
        organization_id=context.organization_id,
        business_id=context.business_id,
        goal_problem="Increase replies",
        selected_action="Publish A",
        expected_effect="More replies",
        reversibility="easy",
        risk_class="low",
        status=DecisionStatus.ACTIVE,
    )
    new = old.supersede_with(selected_action="Publish B", reason="weak checkpoint")
    persist_decision(session, context=context, decision=old)
    persist_decision(session, context=context, decision=new)
    session.commit()

    decisions = (
        session.execute(select(DecisionModel).order_by(DecisionModel.selected_action))
        .scalars()
        .all()
    )

    assert len(decisions) == 2
    assert decisions[0].supersedes_decision_id is None
    assert decisions[1].supersedes_decision_id == old.id


def test_business_event_time_distinguishes_occurred_and_recorded(session: Session) -> None:
    occurred = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    recorded = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    context = CommandContext(
        organization_id="org-a",
        business_id="biz-a",
        actor_user_id="user-a",
        correlation_id="corr-time",
    )
    result = create_business_event(
        session,
        context=context,
        event_type="telegram.message_observed",
        occurred_at=occurred,
        recorded_at=recorded,
    )
    session.commit()

    row = session.get(BusinessEventModel, result.record.id)

    assert row is not None
    assert row.occurred_at != row.recorded_at
    assert row.correlation_id == "corr-time"


def test_repository_rejects_wrong_scope_on_add(session: Session) -> None:
    repo = ScopedRepository(
        session,
        TenantScope(organization_id="org-a", business_id="biz-a"),
        GoalModel,
    )
    wrong_goal = GoalModel(
        id=new_id(),
        organization_id="org-b",
        business_id="biz-b",
        title="Wrong",
        target="Wrong",
    )

    with pytest.raises(TenantScopeViolation):
        repo.add(wrong_goal)
