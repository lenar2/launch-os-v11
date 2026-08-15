from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from launch_os_v11.domain.entities import (
    Action,
    Approval,
    Asset,
    AssetVersion,
    BusinessEvent,
    BusinessSnapshot,
    Decision,
    Hypothesis,
)
from launch_os_v11.domain.enums import ApprovalStatus, EpistemicStatus, VerificationBasis
from launch_os_v11.domain.epistemic import transition_epistemic_status
from launch_os_v11.domain.exceptions import ApprovalBindingError, InvalidEpistemicTransition


def test_unknown_does_not_become_fact_without_valid_transition() -> None:
    with pytest.raises(InvalidEpistemicTransition):
        transition_epistemic_status(
            EpistemicStatus.UNKNOWN,
            EpistemicStatus.FACT,
            basis=VerificationBasis.HUMAN_REVIEW,
            evidence_ids=("evidence-1",),
        )


def test_hypothesis_does_not_become_fact_from_model_confidence() -> None:
    hypothesis = Hypothesis(
        organization_id="org-a",
        business_id="biz-a",
        statement="Short hooks may improve replies",
        model_confidence=0.99,
    )

    with pytest.raises(InvalidEpistemicTransition):
        hypothesis.promote_to_fact(
            basis=VerificationBasis.MODEL_CONFIDENCE,
            evidence_ids=("evidence-1",),
        )


def test_business_snapshot_is_immutable_after_creation() -> None:
    snapshot = BusinessSnapshot.create(
        organization_id="org-a",
        business_id="biz-a",
        reason="decision context",
        payload={"goals": [{"title": "launch"}]},
    )

    with pytest.raises(TypeError):
        snapshot.payload["new"] = "not allowed"
    with pytest.raises(TypeError):
        snapshot.payload["goals"][0]["title"] = "mutated"
    with pytest.raises(FrozenInstanceError):
        snapshot.reason = "mutated"  # type: ignore[misc]


def test_decision_supersession_preserves_old_decision_identity() -> None:
    old = Decision(
        organization_id="org-a",
        business_id="biz-a",
        goal_problem="Increase qualified replies",
        selected_action="Publish post A",
        expected_effect="More replies",
        reversibility="easy",
        risk_class="low",
    )

    new = old.supersede_with(
        selected_action="Publish post B",
        reason="checkpoint weak signal",
    )

    assert old.id != new.id
    assert old.supersedes_decision_id is None
    assert new.supersedes_decision_id == old.id
    assert old.selected_action == "Publish post A"


def test_asset_change_creates_new_asset_version() -> None:
    asset = Asset(
        organization_id="org-a",
        business_id="biz-a",
        creative_brief_id="brief-1",
        asset_type="telegram_post",
        title="Launch post",
    )
    v1 = AssetVersion.next_for(
        asset=asset,
        body="Draft one",
        created_by_user_id="user-1",
        provenance={"origin": "generated"},
    )
    v2 = AssetVersion.next_for(
        asset=asset,
        body="Draft two",
        created_by_user_id="user-1",
        previous=v1,
        provenance={"origin": "user_edit"},
    )

    assert v1.id != v2.id
    assert v1.version_number == 1
    assert v2.version_number == 2
    assert v1.body == "Draft one"


def test_approval_is_bound_to_exact_object_version_and_action() -> None:
    action = Action(
        organization_id="org-a",
        business_id="biz-a",
        action_type="publish",
        target_object_type="Asset",
        target_object_id="asset-1",
        target_object_version_id="asset-version-1",
        target_object_version=1,
    )
    approval = Approval(
        organization_id="org-a",
        business_id="biz-a",
        action_id=action.id,
        action_type=action.action_type,
        object_type=action.target_object_type,
        object_id=action.target_object_id,
        object_version_id=action.target_object_version_id,
        object_version=action.target_object_version,
        approved_by_user_id="user-1",
        status=ApprovalStatus.APPROVED,
    )

    assert approval.is_valid_for(
        action_id=action.id,
        action_type="publish",
        object_type="Asset",
        object_id="asset-1",
        object_version_id="asset-version-1",
        object_version=1,
    )
    assert not approval.is_valid_for(
        action_id=action.id,
        action_type="publish",
        object_type="Asset",
        object_id="asset-1",
        object_version_id="asset-version-2",
        object_version=2,
    )
    with pytest.raises(ApprovalBindingError):
        approval.assert_valid_for(
            action_id=action.id,
            action_type="publish",
            object_type="Asset",
            object_id="asset-1",
            object_version_id="asset-version-2",
            object_version=2,
        )


def test_event_time_and_recorded_time_are_distinct_fields() -> None:
    occurred = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    recorded = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    event = BusinessEvent(
        organization_id="org-a",
        business_id="biz-a",
        event_type="telegram.message_observed",
        occurred_at=occurred,
        recorded_at=recorded,
    )

    assert event.occurred_at == occurred
    assert event.recorded_at == recorded
    assert event.occurred_at != event.recorded_at
