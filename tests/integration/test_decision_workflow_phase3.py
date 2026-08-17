from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep, FakeModelAdapter
from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.ai_runtime.contracts import AgentRunStatus, ModelResultKind
from launch_os_v11.ai_runtime.registry import (
    REQUIRED_CONTROLLER_CONTRACT_KEYS,
    default_agent_registry,
)
from launch_os_v11.application.commands import CommandContext, create_business, create_organization
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.application.decision_workflow import (
    DECISION_APPROVAL_ACTION,
    DecisionWorkflowStatus,
    approval_matches_decision,
    approve_decision_for_production,
    get_user_decision_view,
    start_decision_workflow,
)
from launch_os_v11.domain.enums import (
    ApprovalStatus,
    ControllerVerdict,
    EpistemicStatus,
    SourceTrust,
)
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings, get_settings
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.transport import RedisJobQueue
from launch_os_v11.runtime.worker import Worker

pytestmark = [pytest.mark.postgres, pytest.mark.decision_workflow]


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for decision workflow tests")
    return value


def _redis_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_REDIS_URL") or os.environ.get("LAUNCH_OS_REDIS_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_REDIS_URL or LAUNCH_OS_REDIS_URL is required")
    return value


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def test_phase3_governed_decision_workflow_postgresql_redis_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    redis_url = _redis_url()
    config = _alembic_config(database_url, monkeypatch)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    redis_client: Redis = Redis.from_url(redis_url, decode_responses=True)
    queue_name = "launch_os_v11:test:phase3"
    redis_client.delete(queue_name)
    queue = RedisJobQueue(redis_client, queue_name=queue_name)
    clock = FixedClock(datetime(2026, 8, 17, 9, 0, tzinfo=UTC))

    try:
        _assert_phase3_schema(engine)
        seed = _seed_launch(factory)
        workflow_id, initial_job_id = _start_workflow(
            factory,
            seed=seed,
            queue=queue,
            clock=clock,
        )
        assert redis_client.lrange(queue_name, 0, -1) == [initial_job_id]

        adapter = FakeModelAdapter[BaseModel](
            script=_revision_then_pass_script(seed.evidence_id)
        )
        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id="phase3-worker",
            clock=clock,
            handlers=compose_application_handler_registry(
                settings=Settings(),
                queue=queue,
                registry=default_agent_registry(),
                model_router=fake_model_router(adapter),
            ),
        )
        _process_until_workflow_status(
            factory,
            worker=worker,
            workflow_id=workflow_id,
            status=DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL,
        )
        assert adapter.call_count == 18

        _assert_revision_loop_and_materialization(factory, workflow_id=workflow_id)
        _assert_route_trace_and_propagation(factory, workflow_id=workflow_id)
        _assert_no_phase4_or_connector_records(factory)

        redis_client.rpush(queue_name, initial_job_id)
        duplicate = worker.process_one_from_queue(timeout_seconds=1)
        assert duplicate is not None
        assert duplicate.claimed is False
        _assert_no_duplicate_phase3_records(factory)

        approval_id = _approve_final_decision(factory, seed=seed, workflow_id=workflow_id)
        _assert_approval_exact_version_binding(
            factory,
            workflow_id=workflow_id,
            approval_id=approval_id,
        )

        command.downgrade(config, "base")
        assert "decision_workflows" not in set(inspect(engine).get_table_names())
        command.upgrade(config, "head")
        _assert_phase3_schema(engine)
    finally:
        redis_client.delete(queue_name)
        redis_client.close()
        engine.dispose()
        get_settings.cache_clear()


class Seed:
    def __init__(
        self,
        *,
        scope: TenantScope,
        user_id: str,
        launch_id: str,
        evidence_id: str,
    ) -> None:
        self.scope = scope
        self.user_id = user_id
        self.launch_id = launch_id
        self.evidence_id = evidence_id


def _seed_launch(factory: sessionmaker[Session]) -> Seed:
    session = factory()
    try:
        with session.begin():
            organization = create_organization(session, name="Phase 3 Integration Org")
            business = create_business(
                session,
                organization_id=organization.id,
                name="Phase 3 Integration Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="corr-phase3-seed",
            ).record
            scope = TenantScope(organization_id=organization.id, business_id=business.id)
            now = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
            user = models.UserModel(
                id="phase3-user",
                email="phase3@example.test",
                display_name="Owner",
            )
            goal = models.GoalModel(
                id="phase3-goal",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                title="Increase qualified replies",
                target="10 replies",
                metric="qualified_replies",
            )
            product = models.ProductModel(
                id="phase3-product",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                name="Launch Cohort",
                description="Guided launch cohort",
            )
            channel = models.ChannelModel(
                id="phase3-channel",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="manual",
                handle="@launch",
                capabilities={"external_write": False},
            )
            source = models.SourceRecordModel(
                id="phase3-source",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="manual",
                external_id="phase3-source",
                source_type="note",
                trust=SourceTrust.USER_PROVIDED.value,
                payload={"note": "Audience asked for a concise launch offer."},
                ingested_at=now,
            )
            session.add_all([user, goal, product, channel, source])
            session.flush()
            offer = models.OfferModel(
                id="phase3-offer",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                product_id=product.id,
                name="Pilot offer",
                description="Pilot",
                price_descriptor="intro",
            )
            evidence = models.EvidenceModel(
                id="phase3-evidence",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                source_record_id=source.id,
                statement="Audience asked for a concise launch offer.",
                status=EpistemicStatus.FACT.value,
                recorded_at=now,
                conflicts_with_evidence_ids=[],
            )
            campaign = models.CampaignModel(
                id="phase3-campaign",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                name="Phase 3 Campaign",
                goal_id=goal.id,
            )
            session.add_all([offer, evidence, campaign])
            session.flush()
            launch = models.LaunchModel(
                id="phase3-launch",
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                campaign_id=campaign.id,
                offer_id=offer.id,
                goal_id=goal.id,
                channel_id=channel.id,
                snapshot_id=None,
                status="PLANNED",
            )
            session.add(launch)
            session.flush()
            return Seed(
                scope=scope,
                user_id=user.id,
                launch_id=launch.id,
                evidence_id=evidence.id,
            )
    finally:
        session.close()


def _start_workflow(
    factory: sessionmaker[Session],
    *,
    seed: Seed,
    queue: RedisJobQueue,
    clock: FixedClock,
) -> tuple[str, str]:
    session = factory()
    try:
        with session.begin():
            result = start_decision_workflow(
                session,
                context=CommandContext(
                    organization_id=seed.scope.organization_id,
                    business_id=seed.scope.business_id,
                    actor_user_id=seed.user_id,
                    correlation_id="corr-phase3-workflow",
                ),
                queue=queue,
                clock=clock,
                launch_id=seed.launch_id,
                max_revision_rounds=2,
            )
            return result.workflow.id, result.job_id
    finally:
        session.close()


def _process_until_workflow_status(
    factory: sessionmaker[Session],
    *,
    worker: Worker,
    workflow_id: str,
    status: DecisionWorkflowStatus,
) -> None:
    seen: list[tuple[str, str]] = []
    for _ in range(120):
        session = factory()
        try:
            workflow = session.get(models.DecisionWorkflowModel, workflow_id)
            assert workflow is not None
            if workflow.status == status.value:
                return
        finally:
            session.close()
        result = worker.process_one_from_queue(timeout_seconds=1)
        assert result is not None, f"workflow did not reach {status.value}; seen {seen}"
        seen.append((result.job_id, result.status))
    pytest.fail(f"workflow did not reach {status.value}; seen {seen}")


def _assert_revision_loop_and_materialization(
    factory: sessionmaker[Session],
    *,
    workflow_id: str,
) -> None:
    session = factory()
    try:
        workflow = session.get(models.DecisionWorkflowModel, workflow_id)
        assert workflow is not None
        assert workflow.revision_count == 1
        assert workflow.final_decision_id is not None
        assert workflow.final_approval_id is None
        candidates = session.scalars(
            select(models.DecisionCandidateModel)
            .where(models.DecisionCandidateModel.workflow_id == workflow_id)
            .order_by(models.DecisionCandidateModel.version_number)
        ).all()
        assert [candidate.version_number for candidate in candidates] == [1, 2]
        assert candidates[1].previous_candidate_id == candidates[0].id
        assert candidates[0].selected_action == "Draft concise offer v1"
        assert candidates[1].selected_action == "Draft concise offer v2 with risk checkpoint"
        assert candidates[0].status == "REVISION_REQUIRED"
        assert candidates[1].status == "MATERIALIZED"
        decision = session.get(models.DecisionModel, workflow.final_decision_id)
        assert decision is not None
        assert decision.source_candidate_id == candidates[1].id
        assert decision.selected_action == candidates[1].selected_action
        assert decision.status == "AWAITING_DECISION_APPROVAL"
        assert decision.required_actions == ["owner approval"]
        assert decision.experiment_proposal["metric"] == "qualified_replies"
        assert (
            session.scalar(select(func.count()).select_from(models.SpecialistContributionModel))
            == 3
        )
        assert session.scalar(select(func.count()).select_from(models.ControllerReviewModel)) == 14
        assert (
            session.scalar(select(func.count()).select_from(models.DecisionAlternativeModel))
            == 1
        )
        assert session.scalar(select(func.count()).select_from(models.ExperimentModel)) == 1
        assert session.scalar(select(func.count()).select_from(models.ExperimentRuleModel)) == 1
        view = get_user_decision_view(
            session,
            scope=workflow_scope(workflow),
            decision_id=decision.id,
        )
        assert view.approval_needed
        assert view.decision == decision.selected_action
    finally:
        session.close()


def _assert_route_trace_and_propagation(
    factory: sessionmaker[Session],
    *,
    workflow_id: str,
) -> None:
    session = factory()
    try:
        workflow = session.get(models.DecisionWorkflowModel, workflow_id)
        assert workflow is not None
        runs = session.scalars(select(models.AgentRunModel)).all()
        assert len(runs) == 18
        assert {run.status for run in runs} == {AgentRunStatus.SUCCEEDED.value}
        assert {run.correlation_id for run in runs} == {"corr-phase3-workflow"}
        for run in runs:
            trace = run.safe_trace_metadata
            assert trace["selected_provider_name"] == "fake"
            assert trace["actual_provider_name"] == "fake"
            assert trace["selected_model_name"] == "fake-structured-model"
            assert trace["actual_model_name"] == "fake-structured-model"
        controller_runs = [
            run for run in runs if run.agent_contract_key.startswith("ai.controller.")
        ]
        candidate_ids = {
            candidate.id
            for candidate in session.scalars(
                select(models.DecisionCandidateModel).where(
                    models.DecisionCandidateModel.workflow_id == workflow_id
                )
            )
        }
        assert {run.causation_id for run in controller_runs}.issubset(candidate_ids)
    finally:
        session.close()


def _assert_no_phase4_or_connector_records(factory: sessionmaker[Session]) -> None:
    session = factory()
    try:
        assert session.scalar(select(func.count()).select_from(models.ActionModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.ExecutionModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.CreativeBriefModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.AssetModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.PublicationModel)) == 0
    finally:
        session.close()


def _assert_no_duplicate_phase3_records(factory: sessionmaker[Session]) -> None:
    session = factory()
    try:
        assert (
            session.scalar(select(func.count()).select_from(models.SpecialistContributionModel))
            == 3
        )
        assert session.scalar(select(func.count()).select_from(models.DecisionCandidateModel)) == 2
        assert session.scalar(select(func.count()).select_from(models.ControllerReviewModel)) == 14
        assert session.scalar(select(func.count()).select_from(models.DecisionModel)) == 1
    finally:
        session.close()


def _approve_final_decision(
    factory: sessionmaker[Session],
    *,
    seed: Seed,
    workflow_id: str,
) -> str:
    session = factory()
    try:
        with session.begin():
            approval = approve_decision_for_production(
                session,
                context=CommandContext(
                    organization_id=seed.scope.organization_id,
                    business_id=seed.scope.business_id,
                    actor_user_id=seed.user_id,
                    correlation_id="corr-phase3-approval",
                ),
                workflow_id=workflow_id,
                approved_by_user_id=seed.user_id,
            )
            repeated = approve_decision_for_production(
                session,
                context=CommandContext(
                    organization_id=seed.scope.organization_id,
                    business_id=seed.scope.business_id,
                    actor_user_id=seed.user_id,
                    correlation_id="corr-phase3-approval",
                ),
                workflow_id=workflow_id,
                approved_by_user_id=seed.user_id,
            )
            assert repeated.id == approval.id
            return approval.id
    finally:
        session.close()


def _assert_approval_exact_version_binding(
    factory: sessionmaker[Session],
    *,
    workflow_id: str,
    approval_id: str,
) -> None:
    session = factory()
    try:
        workflow = session.get(models.DecisionWorkflowModel, workflow_id)
        approval = session.get(models.DecisionApprovalModel, approval_id)
        assert workflow is not None
        assert approval is not None
        assert workflow.status == DecisionWorkflowStatus.APPROVED_FOR_PRODUCTION.value
        assert workflow.final_approval_id == approval.id
        decision = session.get(models.DecisionModel, approval.decision_id)
        assert decision is not None
        assert decision.status == "APPROVED_FOR_PRODUCTION"
        assert approval.action_type == DECISION_APPROVAL_ACTION
        assert approval.object_type == "Decision"
        assert approval.object_id == decision.id
        assert approval.object_version_id == decision.id
        assert approval.object_version == decision.version
        assert approval.status == ApprovalStatus.APPROVED.value
        assert approval_matches_decision(approval, decision)

        stale_target = models.DecisionModel(
            id="phase3-decision-v2",
            organization_id=decision.organization_id,
            business_id=decision.business_id,
            version=decision.version + 1,
            goal_problem=decision.goal_problem,
            selected_action="Superseding candidate requires its own approval",
            expected_effect=decision.expected_effect,
            confidence=decision.confidence,
            reversibility=decision.reversibility,
            risk_class=decision.risk_class,
            status="AWAITING_DECISION_APPROVAL",
            snapshot_id=decision.snapshot_id,
            supersedes_decision_id=decision.id,
            evidence_ids=list(decision.evidence_ids),
            assumption_ids=list(decision.assumption_ids),
            known_unknown_ids=list(decision.known_unknown_ids),
        )
        assert not approval_matches_decision(approval, stale_target)
    finally:
        session.close()


def _assert_phase3_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"decision_workflows", "specialist_contributions", "decision_candidates"}.issubset(
        tables
    )
    assert "decision_approvals" in tables
    agent_run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    assert "idempotency_key" in agent_run_columns
    workflow_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("decision_workflows")
    }
    assert "ck_decision_workflows_status_phase3" in workflow_checks
    candidate_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("decision_candidates")
    }
    assert ("workflow_id", "version_number") in candidate_uniques
    assert ("chief_agent_run_id",) in candidate_uniques


def _revision_then_pass_script(evidence_id: str) -> list[FakeAdapterScriptStep]:
    return [
        *[
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_specialist_payload(role, evidence_id),
            )
            for role in ("Audience Intelligence", "Revenue/Funnel Strategist", "Launch Strategist")
        ],
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_candidate_payload(evidence_id, selected_action="Draft concise offer v1"),
        ),
        *[
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_controller_payload(
                    contract_key.removeprefix("ai.controller."),
                    evidence_id,
                    verdict=ControllerVerdict.REVISE
                    if contract_key.endswith(".strategy_red_team")
                    else ControllerVerdict.PASS,
                ),
            )
            for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS
        ],
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_candidate_payload(
                evidence_id,
                selected_action="Draft concise offer v2 with risk checkpoint",
            ),
        ),
        *[
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_controller_payload(
                    contract_key.removeprefix("ai.controller."),
                    evidence_id,
                    verdict=ControllerVerdict.PASS_WITH_CONDITIONS
                    if contract_key.endswith(".economics")
                    else ControllerVerdict.PASS,
                ),
            )
            for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS
        ],
    ]


def _evidence_ref(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "epistemic_status": EpistemicStatus.FACT.value,
        "note": "Seeded fact",
    }


def _specialist_payload(role: str, evidence_id: str) -> dict[str, object]:
    return {
        "schema_name": "SpecialistContribution",
        "schema_version": 1,
        "role": role,
        "observations": [f"{role} observed a concise offer signal."],
        "facts_used": [
            {
                "statement": "Audience asked for a concise launch offer.",
                "evidence_ref": evidence_id,
                "epistemic_status": EpistemicStatus.FACT.value,
            }
        ],
        "hypotheses": [
            {
                "statement": "A concise offer may increase replies.",
                "evidence_ref": evidence_id,
                "confidence": 0.55,
            }
        ],
        "assumptions": [
            {
                "statement": "Audience intent remains stable this week.",
                "evidence_ref": evidence_id,
                "confidence": 0.5,
            }
        ],
        "recommendations": ["Test a concise offer"],
        "risks": ["Signal may be narrow"],
        "unknowns": [{"question": "Will replies convert?", "critical": False}],
        "conflicts": [
            {
                "statement": "No blocking conflict in current evidence set.",
                "evidence_refs": [evidence_id],
            }
        ],
        "confidence": 0.65,
        "evidence_refs": [_evidence_ref(evidence_id)],
    }


def _candidate_payload(evidence_id: str, *, selected_action: str) -> dict[str, object]:
    return {
        "schema_name": "DecisionCandidate",
        "schema_version": 1,
        "goal": "Increase qualified replies",
        "problem": "Launch motion is not validated",
        "selected_action": selected_action,
        "why": ["Uses a verified audience signal", "Keeps the next step reversible"],
        "evidence_refs": [_evidence_ref(evidence_id)],
        "alternatives": [{"action": "Wait", "rejection_reason": "No signal would be learned"}],
        "why_alternatives_not_selected": ["Waiting does not improve evidence"],
        "hypotheses": [
            {
                "statement": "Concise offer wording increases reply rate.",
                "evidence_ref": evidence_id,
                "confidence": 0.55,
            }
        ],
        "assumptions": [
            {
                "statement": "Audience segment remains reachable.",
                "evidence_ref": evidence_id,
                "confidence": 0.5,
            }
        ],
        "unknowns": [{"question": "Exact conversion rate after replies?", "critical": False}],
        "expected_effect": "More qualified replies",
        "confidence": 0.64,
        "reversibility": "easy",
        "risk_class": "LOW",
        "experiment_proposal": {
            "hypothesis": "Concise offer wording increases reply rate.",
            "baseline": "Current long-form offer",
            "segment": "warm audience",
            "treatment": "Concise offer",
            "metric": "qualified_replies",
            "window": "7d",
            "attribution_method": "manual tagged replies",
            "success_threshold": "10 replies",
            "weak_signal_threshold": "3 replies",
            "failure_threshold": "0 replies",
            "next_action_on_success": "prepare production assets",
            "next_action_on_weak_signal": "revise offer",
            "next_action_on_failure": "stop and inspect evidence",
        },
        "required_assets": ["offer copy draft"],
        "required_actions": ["owner approval"],
        "next_checkpoint": "Review reply count after seven days",
    }


def _controller_payload(
    controller_type: str,
    evidence_id: str,
    *,
    verdict: ControllerVerdict,
) -> dict[str, object]:
    return {
        "schema_name": "ControllerReview",
        "schema_version": 1,
        "controller_type": controller_type,
        "verdict": verdict.value,
        "issues": ["Needs revision"] if verdict == ControllerVerdict.REVISE else [],
        "required_changes": ["Add risk checkpoint"] if verdict == ControllerVerdict.REVISE else [],
        "severity": "MEDIUM" if verdict == ControllerVerdict.REVISE else "LOW",
        "evidence_refs": [_evidence_ref(evidence_id)],
    }


def workflow_scope(workflow: models.DecisionWorkflowModel) -> TenantScope:
    return TenantScope(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )
