import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.application.approval_preflight import validate_approval_for_action
from launch_os_v11.domain.entities import Asset, AssetVersion, Decision
from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    DecisionStatus,
    OutboxStatus,
)
from launch_os_v11.domain.exceptions import ApprovalBindingError
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence import models
from launch_os_v11.persistence.repositories import (
    ApprovalRepository,
    AssetVersionRepository,
    AuditLogRepository,
    BusinessEventRepository,
    BusinessSnapshotRepository,
    OutboxEventRepository,
    ScopedRepository,
)


def test_business_snapshot_repository_is_append_only(session: Session) -> None:
    scope = TenantScope("org-snapshot", "biz-snapshot")
    repository = BusinessSnapshotRepository(session, scope, models.BusinessSnapshotModel)
    snapshot = models.BusinessSnapshotModel(
        id="snapshot-1",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        reason="decision context",
        payload={"immutable": True},
        created_at=utc_now(),
    )
    repository.add(snapshot)
    session.commit()

    assert repository.get(snapshot.id) is not None
    assert not hasattr(repository, "update_fields")
    assert not hasattr(repository, "delete")
    method_name = "update_fields"
    with pytest.raises(AttributeError):
        getattr(repository, method_name)(snapshot.id, reason="mutated")


def test_append_only_history_repositories_do_not_expose_update_or_delete(session: Session) -> None:
    scope = TenantScope("org-history", "biz-history")
    repositories = [
        AssetVersionRepository(session, scope, models.AssetVersionModel),
        ApprovalRepository(session, scope, models.ApprovalModel),
        BusinessEventRepository(session, scope, models.BusinessEventModel),
        AuditLogRepository(session, scope, models.AuditLogModel),
        OutboxEventRepository(session, scope, models.OutboxEventModel),
    ]

    for repository in repositories:
        assert not hasattr(repository, "update_fields")
        assert not hasattr(repository, "delete")


def test_published_outbox_event_is_not_overwritten_by_application_repository(
    session: Session,
) -> None:
    scope = TenantScope("org-outbox", "biz-outbox")
    repository = OutboxEventRepository(session, scope, models.OutboxEventModel)
    outbox = models.OutboxEventModel(
        id="outbox-published",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        event_type="event",
        aggregate_type="Aggregate",
        aggregate_id="aggregate",
        payload={},
        status=OutboxStatus.PUBLISHED.value,
        occurred_at=utc_now(),
        correlation_id="corr-outbox",
        created_at=utc_now(),
        published_at=utc_now(),
    )
    repository.add(outbox)
    session.commit()

    loaded = repository.require(outbox.id)

    assert loaded.status == OutboxStatus.PUBLISHED.value
    assert not hasattr(repository, "update_fields")


def test_decision_supersession_persistence_does_not_overwrite_old_record(
    session: Session,
) -> None:
    scope = TenantScope("org-decision-hardening", "biz-decision-hardening")
    old = Decision(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        goal_problem="Improve replies",
        selected_action="Publish original",
        expected_effect="Replies increase",
        reversibility="easy",
        risk_class="low",
        status=DecisionStatus.ACTIVE,
    )
    new = old.supersede_with(
        selected_action="Publish revised",
        reason="checkpoint learning",
    )
    repo = ScopedRepository(session, scope, models.DecisionModel)
    repo.add(
        models.DecisionModel(
            id=old.id,
            organization_id=old.organization_id,
            business_id=old.business_id,
            goal_problem=old.goal_problem,
            selected_action=old.selected_action,
            expected_effect=old.expected_effect,
            reversibility=old.reversibility,
            risk_class=old.risk_class,
            status=old.status.value,
            evidence_ids=[],
            assumption_ids=[],
            known_unknown_ids=[],
        )
    )
    repo.add(
        models.DecisionModel(
            id=new.id,
            organization_id=new.organization_id,
            business_id=new.business_id,
            goal_problem=new.goal_problem,
            selected_action=new.selected_action,
            expected_effect=new.expected_effect,
            reversibility=new.reversibility,
            risk_class=new.risk_class,
            status=new.status.value,
            supersedes_decision_id=old.id,
            evidence_ids=[],
            assumption_ids=[],
            known_unknown_ids=[],
        )
    )
    session.commit()

    decisions = session.execute(select(models.DecisionModel)).scalars().all()

    assert len(decisions) == 2
    assert session.get(models.DecisionModel, old.id).selected_action == "Publish original"  # type: ignore[union-attr]
    assert session.get(models.DecisionModel, new.id).supersedes_decision_id == old.id  # type: ignore[union-attr]


def test_stale_approval_for_old_asset_version_is_rejected(session: Session) -> None:
    now = utc_now()
    scope = TenantScope("org-approval", "biz-approval")
    user = models.UserModel(id="approval-user", email="approval@example.test", display_name="Owner")
    organization = models.OrganizationModel(id=scope.organization_id, name="Approval Org")
    business = models.BusinessModel(
        id=scope.business_id,
        organization_id=scope.organization_id,
        name="Approval Biz",
        timezone="UTC",
    )
    asset = Asset(
        id="asset-approval",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        creative_brief_id="brief",
        asset_type="copy",
        title="Asset",
    )
    v1 = AssetVersion.next_for(
        asset=asset,
        body="Original",
        created_by_user_id=user.id,
        provenance={"origin": "generated"},
    )
    v2 = AssetVersion.next_for(
        asset=asset,
        body="Revised",
        created_by_user_id=user.id,
        previous=v1,
        provenance={"origin": "user_edit"},
    )
    asset_row = models.AssetModel(
        id=asset.id,
        organization_id=asset.organization_id,
        business_id=asset.business_id,
        creative_brief_id=asset.creative_brief_id,
        asset_type=asset.asset_type,
        title=asset.title,
    )
    v1_row = models.AssetVersionModel(
        id=v1.id,
        organization_id=v1.organization_id,
        business_id=v1.business_id,
        asset_id=v1.asset_id,
        version_number=v1.version_number,
        body=v1.body,
        created_by_user_id=v1.created_by_user_id,
        provenance=v1.provenance,
        created_at=now,
    )
    v2_row = models.AssetVersionModel(
        id=v2.id,
        organization_id=v2.organization_id,
        business_id=v2.business_id,
        asset_id=v2.asset_id,
        version_number=v2.version_number,
        body=v2.body,
        created_by_user_id=v2.created_by_user_id,
        provenance=v2.provenance,
        created_at=now,
    )
    action_v1 = models.ActionModel(
        id="action-v1",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_type="publish",
        target_object_type="Asset",
        target_object_id=asset.id,
        target_object_version_id=v1.id,
        target_object_version=v1.version_number,
        status=ActionStatus.APPROVAL_REQUIRED.value,
        idempotency_key="action-v1-key",
    )
    approval_v1 = models.ApprovalModel(
        id="approval-v1",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_id=action_v1.id,
        action_type=action_v1.action_type,
        object_type=action_v1.target_object_type,
        object_id=action_v1.target_object_id,
        object_version_id=action_v1.target_object_version_id,
        object_version=action_v1.target_object_version,
        approved_by_user_id=user.id,
        status=ApprovalStatus.APPROVED.value,
        created_at=now,
    )
    action_v2 = models.ActionModel(
        id="action-v2",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_type="publish",
        target_object_type="Asset",
        target_object_id=asset.id,
        target_object_version_id=v2.id,
        target_object_version=v2.version_number,
        status=ActionStatus.APPROVAL_REQUIRED.value,
        idempotency_key="action-v2-key",
    )
    session.add_all(
        [
            user,
            organization,
            business,
            asset_row,
            v1_row,
            v2_row,
            action_v1,
            approval_v1,
            action_v2,
        ]
    )
    session.commit()

    validate_approval_for_action(approval_v1, action_v1)
    with pytest.raises(ApprovalBindingError):
        validate_approval_for_action(approval_v1, action_v2)

    approval_v2 = models.ApprovalModel(
        id="approval-v2",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_id=action_v2.id,
        action_type=action_v2.action_type,
        object_type=action_v2.target_object_type,
        object_id=action_v2.target_object_id,
        object_version_id=action_v2.target_object_version_id,
        object_version=action_v2.target_object_version,
        approved_by_user_id=user.id,
        status=ApprovalStatus.APPROVED.value,
        created_at=now,
    )

    validate_approval_for_action(approval_v2, action_v2)
    assert v1_row.body == "Original"
    assert v2_row.body == "Revised"
    assert approval_v1.object_version_id != approval_v2.object_version_id
