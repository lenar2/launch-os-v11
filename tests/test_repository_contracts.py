from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeAlias

import pytest
from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    CausalityClass,
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
)
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence import models
from launch_os_v11.persistence.repositories import (
    AppendOnlyScopedRepository,
    ScopedRepository,
)

RowFactory: TypeAlias = Callable[[TenantScope, str, dict[str, str]], Any]


def _agent_definition_model(
    scope: TenantScope,
    *,
    suffix: str,
    prefix: str,
) -> models.AgentDefinitionModel:
    contract_key = f"{prefix}.agent.{suffix}"
    return models.AgentDefinitionModel(
        id=f"{prefix}-agent-definition-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name="Reserved",
        mission="Reserved only",
        output_schema={
            "title": "RuntimeProbeOutput",
            "type": "object",
            "additionalProperties": False,
        },
        enabled=False,
        contract_key=contract_key,
        contract_version=1,
        role_name="Reserved",
        model_capability="FAST_STRUCTURED_CLASSIFICATION",
        allowed_context_types=["business"],
        required_context_types=["business"],
        authority_boundaries=[
            "READ_SCOPED_CONTEXT_ONLY",
            "NO_TOOLS",
            "NO_CONNECTORS",
            "NO_EXTERNAL_WRITES",
            "NO_CREDENTIAL_ACCESS",
        ],
        prohibited_actions=[
            "external write",
            "connector access",
            "credential access",
        ],
        required_controller_types=["none_phase2b"],
        abstention_policy="Abstain when scoped context is insufficient.",
        escalation_policy="Escalate without creating domain objects.",
        instruction_version=f"{contract_key}.instructions.v1",
        eval_suite_identifier=f"{contract_key}.eval.v1",
        contract_fingerprint="a" * 64,
        output_schema_name="RuntimeProbeOutput",
        output_schema_version=1,
    )


def _agent_run_model(
    scope: TenantScope,
    *,
    suffix: str,
    prefix: str,
    agent_definition_id: str,
) -> models.AgentRunModel:
    return models.AgentRunModel(
        id=f"{prefix}-agent-run-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        agent_definition_id=agent_definition_id,
        job_id=None,
        payload_schema_version=1,
        agent_contract_key=f"dep.agent.{suffix}",
        agent_contract_version=1,
        agent_contract_fingerprint="a" * 64,
        output_schema_name="RuntimeProbeOutput",
        output_schema_version=1,
        status=JobStatus.QUEUED.value,
        context_refs=[],
        context_manifest={},
        token_usage={},
        safe_trace_metadata={},
    )


def _seed_dependencies(session: Session, scope: TenantScope, suffix: str) -> dict[str, str]:
    now = utc_now()
    user = models.UserModel(
        id=f"user-{suffix}",
        email=f"{suffix}@example.test",
        display_name=f"User {suffix}",
    )
    organization = models.OrganizationModel(
        id=scope.organization_id,
        name=f"Organization {suffix}",
    )
    business = models.BusinessModel(
        id=scope.business_id,
        organization_id=scope.organization_id,
        name=f"Business {suffix}",
        timezone="UTC",
    )
    goal = models.GoalModel(
        id=f"dep-goal-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        title="Goal",
        target="Target",
    )
    product = models.ProductModel(
        id=f"dep-product-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name="Product",
        description="",
    )
    offer = models.OfferModel(
        id=f"dep-offer-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        product_id=product.id,
        name="Offer",
        description="",
    )
    channel = models.ChannelModel(
        id=f"dep-channel-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="telegram",
        handle="@test",
        capabilities={},
    )
    source = models.SourceRecordModel(
        id=f"dep-source-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="manual",
        external_id=f"external-{suffix}",
        source_type="note",
        trust=SourceTrust.USER_PROVIDED.value,
        payload={},
        ingested_at=now,
    )
    snapshot = models.BusinessSnapshotModel(
        id=f"dep-snapshot-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        reason="test",
        payload={"business": suffix},
        created_at=now,
    )
    campaign = models.CampaignModel(
        id=f"dep-campaign-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name="Campaign",
        goal_id=goal.id,
    )
    launch = models.LaunchModel(
        id=f"dep-launch-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        campaign_id=campaign.id,
        offer_id=offer.id,
        goal_id=goal.id,
        channel_id=channel.id,
        snapshot_id=snapshot.id,
        status=LaunchPhaseStatus.PLANNED.value,
    )
    hypothesis = models.HypothesisModel(
        id=f"dep-hypothesis-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        statement="Hypothesis",
        status=EpistemicStatus.HYPOTHESIS.value,
        evidence_ids=[],
    )
    decision = models.DecisionModel(
        id=f"dep-decision-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        goal_problem="Problem",
        selected_action="Action",
        expected_effect="Effect",
        reversibility="easy",
        risk_class="low",
        status=DecisionStatus.ACTIVE.value,
        snapshot_id=snapshot.id,
        evidence_ids=[],
        assumption_ids=[],
        known_unknown_ids=[],
    )
    experiment = models.ExperimentModel(
        id=f"dep-experiment-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=decision.id,
        hypothesis_id=hypothesis.id,
        metric="replies",
        status=ExperimentStatus.DRAFT.value,
        causality_class=CausalityClass.UNKNOWN.value,
    )
    brief = models.CreativeBriefModel(
        id=f"dep-brief-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=decision.id,
        title="Brief",
        objective="Objective",
        constraints=[],
    )
    asset = models.AssetModel(
        id=f"dep-asset-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        creative_brief_id=brief.id,
        asset_type="copy",
        title="Asset",
    )
    asset_version = models.AssetVersionModel(
        id=f"dep-asset-version-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        asset_id=asset.id,
        version_number=1,
        body="Body",
        created_by_user_id=user.id,
        provenance={},
        created_at=now,
    )
    action = models.ActionModel(
        id=f"dep-action-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_type="publish",
        target_object_type="Asset",
        target_object_id=asset.id,
        target_object_version_id=asset_version.id,
        target_object_version=asset_version.version_number,
        status=ActionStatus.PROPOSED.value,
        idempotency_key=f"action-key-{suffix}",
    )
    approval = models.ApprovalModel(
        id=f"dep-approval-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_id=action.id,
        action_type=action.action_type,
        object_type=action.target_object_type,
        object_id=action.target_object_id,
        object_version_id=action.target_object_version_id,
        object_version=action.target_object_version,
        approved_by_user_id=user.id,
        status=ApprovalStatus.APPROVED.value,
        created_at=now,
    )
    agent_definition = _agent_definition_model(scope, suffix=suffix, prefix="dep")
    session.add_all(
        [
            user,
            organization,
            business,
            goal,
            product,
            offer,
            channel,
            source,
            snapshot,
            campaign,
            launch,
            hypothesis,
            decision,
            experiment,
            brief,
            asset,
            asset_version,
            action,
            approval,
            agent_definition,
        ]
    )
    session.flush()
    return {
        "user": user.id,
        "goal": goal.id,
        "product": product.id,
        "offer": offer.id,
        "channel": channel.id,
        "source": source.id,
        "snapshot": snapshot.id,
        "campaign": campaign.id,
        "launch": launch.id,
        "hypothesis": hypothesis.id,
        "decision": decision.id,
        "experiment": experiment.id,
        "brief": brief.id,
        "asset": asset.id,
        "asset_version": asset_version.id,
        "action": action.id,
        "approval": approval.id,
        "agent_definition": agent_definition.id,
    }


def _row_factories() -> list[tuple[type[Any], RowFactory, bool]]:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    return [
        (
            models.BusinessMembershipModel,
            lambda scope, suffix, dep: models.BusinessMembershipModel(
                id=f"row-membership-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                user_id=dep["user"],
                role="owner",
            ),
            True,
        ),
        (
            models.GoalModel,
            lambda scope, suffix, dep: models.GoalModel(
                id=f"row-goal-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                title="Goal",
                target="Target",
            ),
            True,
        ),
        (
            models.ConstraintModel,
            lambda scope, suffix, dep: models.ConstraintModel(
                id=f"row-constraint-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                category="brand",
                rule="No pressure",
            ),
            True,
        ),
        (
            models.ProductModel,
            lambda scope, suffix, dep: models.ProductModel(
                id=f"row-product-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                name="Product",
                description="",
            ),
            True,
        ),
        (
            models.OfferModel,
            lambda scope, suffix, dep: models.OfferModel(
                id=f"row-offer-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                product_id=dep["product"],
                name="Offer",
                description="",
            ),
            True,
        ),
        (
            models.ChannelModel,
            lambda scope, suffix, dep: models.ChannelModel(
                id=f"row-channel-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="telegram",
                handle="@row",
                capabilities={},
            ),
            True,
        ),
        (
            models.SourceRecordModel,
            lambda scope, suffix, dep: models.SourceRecordModel(
                id=f"row-source-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="manual",
                external_id=f"row-source-{suffix}",
                source_type="note",
                trust=SourceTrust.USER_PROVIDED.value,
                payload={},
                ingested_at=now,
            ),
            True,
        ),
        (
            models.EvidenceModel,
            lambda scope, suffix, dep: models.EvidenceModel(
                id=f"row-evidence-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                source_record_id=dep["source"],
                statement="Evidence",
                status=EpistemicStatus.OBSERVATION.value,
                recorded_at=now,
                conflicts_with_evidence_ids=[],
            ),
            True,
        ),
        (
            models.ClaimModel,
            lambda scope, suffix, dep: models.ClaimModel(
                id=f"row-claim-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                statement="Claim",
                status=EpistemicStatus.UNKNOWN.value,
                evidence_ids=[],
            ),
            True,
        ),
        (
            models.HypothesisModel,
            lambda scope, suffix, dep: models.HypothesisModel(
                id=f"row-hypothesis-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                statement="Hypothesis",
                status=EpistemicStatus.HYPOTHESIS.value,
                evidence_ids=[],
            ),
            True,
        ),
        (
            models.InformationNeedModel,
            lambda scope, suffix, dep: models.InformationNeedModel(
                id=f"row-info-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                question="Question?",
                critical=False,
            ),
            True,
        ),
        (
            models.BusinessSnapshotModel,
            lambda scope, suffix, dep: models.BusinessSnapshotModel(
                id=f"row-snapshot-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                reason="Snapshot",
                payload={},
                created_at=now,
            ),
            False,
        ),
        (
            models.CampaignModel,
            lambda scope, suffix, dep: models.CampaignModel(
                id=f"row-campaign-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                name="Campaign",
                goal_id=dep["goal"],
            ),
            True,
        ),
        (
            models.LaunchModel,
            lambda scope, suffix, dep: models.LaunchModel(
                id=f"row-launch-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                campaign_id=dep["campaign"],
                offer_id=dep["offer"],
                goal_id=dep["goal"],
                channel_id=dep["channel"],
                snapshot_id=dep["snapshot"],
                status=LaunchPhaseStatus.PLANNED.value,
            ),
            True,
        ),
        (
            models.LaunchPhaseModel,
            lambda scope, suffix, dep: models.LaunchPhaseModel(
                id=f"row-launch-phase-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                launch_id=dep["launch"],
                name="Phase",
                status=LaunchPhaseStatus.PLANNED.value,
            ),
            True,
        ),
        (
            models.DecisionModel,
            lambda scope, suffix, dep: models.DecisionModel(
                id=f"row-decision-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                goal_problem="Problem",
                selected_action="Action",
                expected_effect="Effect",
                reversibility="easy",
                risk_class="low",
                status=DecisionStatus.ACTIVE.value,
                snapshot_id=dep["snapshot"],
                evidence_ids=[],
                assumption_ids=[],
                known_unknown_ids=[],
            ),
            True,
        ),
        (
            models.DecisionAlternativeModel,
            lambda scope, suffix, dep: models.DecisionAlternativeModel(
                id=f"row-decision-alt-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=dep["decision"],
                action="Alternative",
                rejection_reason="Not now",
            ),
            True,
        ),
        (
            models.ControllerReviewModel,
            lambda scope, suffix, dep: models.ControllerReviewModel(
                id=f"row-review-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=dep["decision"],
                controller_name="Evidence Controller",
                verdict="PASS",
                reason="Ok",
            ),
            True,
        ),
        (
            models.ExperimentModel,
            lambda scope, suffix, dep: models.ExperimentModel(
                id=f"row-experiment-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=dep["decision"],
                hypothesis_id=dep["hypothesis"],
                metric="replies",
                status=ExperimentStatus.DRAFT.value,
                causality_class=CausalityClass.UNKNOWN.value,
            ),
            True,
        ),
        (
            models.ExperimentRuleModel,
            lambda scope, suffix, dep: models.ExperimentRuleModel(
                id=f"row-experiment-rule-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                experiment_id=dep["experiment"],
                baseline="0",
                segment="all",
                treatment="post",
                metric="replies",
                window="24h",
                attribution_method="observational",
                success_threshold="10",
                weak_signal_threshold="3",
                failure_threshold="0",
                next_action_on_success="continue",
                next_action_on_weak_signal="revise",
                next_action_on_failure="stop",
            ),
            True,
        ),
        (
            models.ExperimentResultModel,
            lambda scope, suffix, dep: models.ExperimentResultModel(
                id=f"row-experiment-result-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                experiment_id=dep["experiment"],
                result_class="weak",
                observed_value="3",
                interpreted_at=now,
            ),
            True,
        ),
        (
            models.CreativeBriefModel,
            lambda scope, suffix, dep: models.CreativeBriefModel(
                id=f"row-brief-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=dep["decision"],
                title="Brief",
                objective="Objective",
                constraints=[],
            ),
            True,
        ),
        (
            models.AssetModel,
            lambda scope, suffix, dep: models.AssetModel(
                id=f"row-asset-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                creative_brief_id=dep["brief"],
                asset_type="copy",
                title="Asset",
            ),
            True,
        ),
        (
            models.AssetVersionModel,
            lambda scope, suffix, dep: models.AssetVersionModel(
                id=f"row-asset-version-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                asset_id=dep["asset"],
                version_number=2,
                body="Body",
                created_by_user_id=dep["user"],
                provenance={},
                created_at=now,
            ),
            False,
        ),
        (
            models.PublicationModel,
            lambda scope, suffix, dep: models.PublicationModel(
                id=f"row-publication-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                asset_version_id=dep["asset_version"],
                channel_id=dep["channel"],
                status=PublicationStatus.DRAFT.value,
            ),
            True,
        ),
        (
            models.PermissionPolicyModel,
            lambda scope, suffix, dep: models.PermissionPolicyModel(
                id=f"row-policy-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action_type="publish",
                mode=PermissionMode.EXECUTE_AFTER_APPROVAL.value,
                requires_approval=True,
                public_visibility=True,
            ),
            True,
        ),
        (
            models.ActionModel,
            lambda scope, suffix, dep: models.ActionModel(
                id=f"row-action-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action_type="publish",
                target_object_type="Asset",
                target_object_id=dep["asset"],
                target_object_version_id=dep["asset_version"],
                target_object_version=1,
                status=ActionStatus.PROPOSED.value,
                idempotency_key=f"row-action-key-{suffix}",
            ),
            True,
        ),
        (
            models.ApprovalModel,
            lambda scope, suffix, dep: models.ApprovalModel(
                id=f"row-approval-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action_id=dep["action"],
                action_type="publish",
                object_type="Asset",
                object_id=dep["asset"],
                object_version_id=dep["asset_version"],
                object_version=1,
                approved_by_user_id=dep["user"],
                status=ApprovalStatus.APPROVED.value,
                created_at=now,
            ),
            False,
        ),
        (
            models.ExecutionModel,
            lambda scope, suffix, dep: models.ExecutionModel(
                id=f"row-execution-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action_id=dep["action"],
                approval_id=dep["approval"],
                status=ExecutionStatus.PENDING.value,
                idempotency_key=f"row-execution-key-{suffix}",
            ),
            True,
        ),
        (
            models.BusinessEventModel,
            lambda scope, suffix, dep: models.BusinessEventModel(
                id=f"row-business-event-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                event_type="observed",
                source_record_id=dep["source"],
                occurred_at=now,
                recorded_at=now,
                payload={},
            ),
            False,
        ),
        (
            models.OutboxEventModel,
            lambda scope, suffix, dep: models.OutboxEventModel(
                id=f"row-outbox-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                event_type="event",
                aggregate_type="Aggregate",
                aggregate_id="aggregate",
                payload={},
                status=OutboxStatus.PENDING.value,
                occurred_at=now,
                correlation_id=f"corr-{suffix}",
                created_at=now,
            ),
            False,
        ),
        (
            models.JobModel,
            lambda scope, suffix, dep: models.JobModel(
                id=f"row-job-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                job_type="noop",
                status=JobStatus.QUEUED.value,
                payload={},
                idempotency_key=f"job-key-{suffix}",
            ),
            True,
        ),
        (
            models.AgentDefinitionModel,
            lambda scope, suffix, dep: _agent_definition_model(
                scope,
                suffix=suffix,
                prefix="row",
            ),
            True,
        ),
        (
            models.AgentRunModel,
            lambda scope, suffix, dep: _agent_run_model(
                scope,
                suffix=suffix,
                prefix="row",
                agent_definition_id=dep["agent_definition"],
            ),
            True,
        ),
        (
            models.AuditLogModel,
            lambda scope, suffix, dep: models.AuditLogModel(
                id=f"row-audit-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action="audit",
                object_type="Object",
                object_id="object",
                payload={},
            ),
            False,
        ),
        (
            models.FeatureFlagModel,
            lambda scope, suffix, dep: models.FeatureFlagModel(
                id=f"row-flag-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                key=f"flag-{suffix}",
                enabled=False,
                description="",
            ),
            True,
        ),
        (
            models.LearningModel,
            lambda scope, suffix, dep: models.LearningModel(
                id=f"row-learning-{suffix}",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=dep["decision"],
                experiment_id=dep["experiment"],
                statement="Learning",
                evidence_ids=[],
                causality_class=CausalityClass.UNKNOWN.value,
            ),
            True,
        ),
    ]


@pytest.mark.parametrize(("model_type", "factory", "mutable"), _row_factories())
def test_business_scoped_repository_contracts_for_all_models(
    session: Session,
    model_type: type[Any],
    factory: RowFactory,
    mutable: bool,
) -> None:
    scope_a = TenantScope("org-contract-a", "biz-contract-a")
    scope_b = TenantScope("org-contract-b", "biz-contract-b")
    dependencies_a = _seed_dependencies(session, scope_a, "a")
    dependencies_b = _seed_dependencies(session, scope_b, "b")

    repository_class = ScopedRepository if mutable else AppendOnlyScopedRepository
    repo_a = repository_class(session, scope_a, model_type)
    repo_b = repository_class(session, scope_b, model_type)
    row_a = factory(scope_a, "a", dependencies_a)
    row_b = factory(scope_b, "b", dependencies_b)
    repo_a.add(row_a)
    repo_b.add(row_b)
    session.commit()

    assert repo_a.get(row_a.id) is not None
    assert repo_a.get(row_b.id) is None

    if mutable:
        with pytest.raises(TenantScopeViolation):
            repo_a.update_fields(row_b.id, updated_at=utc_now())
        with pytest.raises(TenantScopeViolation):
            repo_a.delete(row_b.id)
    else:
        assert not hasattr(repo_a, "update_fields")
        assert not hasattr(repo_a, "delete")


def test_repository_rejects_reference_to_object_in_another_business(session: Session) -> None:
    scope_a = TenantScope("org-ref-a", "biz-ref-a")
    scope_b = TenantScope("org-ref-b", "biz-ref-b")
    _seed_dependencies(session, scope_a, "ref-a")
    dependencies_b = _seed_dependencies(session, scope_b, "ref-b")
    session.commit()

    repo_a = ScopedRepository(session, scope_a, models.OfferModel)
    offer_with_foreign_product = models.OfferModel(
        id="foreign-offer",
        organization_id=scope_a.organization_id,
        business_id=scope_a.business_id,
        product_id=dependencies_b["product"],
        name="Invalid",
        description="",
    )

    with pytest.raises(TenantScopeViolation):
        repo_a.add(offer_with_foreign_product)


def test_application_facing_repositories_have_no_unscoped_methods(session: Session) -> None:
    scope = TenantScope("org-api", "biz-api")
    mutable_repo = ScopedRepository(session, scope, models.GoalModel)
    append_only_repo = AppendOnlyScopedRepository(session, scope, models.BusinessSnapshotModel)

    forbidden_methods = {
        "get_unscoped",
        "list_unscoped",
        "list_all",
        "update_unscoped",
        "delete_unscoped",
    }
    assert forbidden_methods.isdisjoint(set(dir(mutable_repo)))
    assert forbidden_methods.isdisjoint(set(dir(append_only_repo)))
