from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.ai_runtime.adapters.base import ModelAdapter
from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep, FakeModelAdapter
from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.ai_runtime.contracts import (
    AgentAuthority,
    ModelCapability,
    ModelRequest,
    ModelResult,
    ModelResultKind,
    ProviderMetadata,
)
from launch_os_v11.ai_runtime.errors import AIContractError
from launch_os_v11.ai_runtime.registry import (
    REQUIRED_CONTROLLER_CONTRACT_KEYS,
    AgentRegistry,
    chief_growth_producer_contract,
    controller_contracts,
    specialist_contracts,
)
from launch_os_v11.application.commands import CommandContext, create_business, create_organization
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.application.decision_workflow import (
    DECISION_APPROVAL_ACTION,
    DecisionWorkflowStatus,
    approval_matches_decision,
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
from launch_os_v11.platform.config import Settings
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.transport import JobQueue
from launch_os_v11.runtime.worker import Worker


class ListJobQueue:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.messages.append(job_id)

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        del timeout_seconds
        if not self.messages:
            return None
        return self.messages.pop(0)


class MismatchedTraceAdapter(ModelAdapter[BaseModel]):
    provider_name = "fake"

    def invoke(self, request: ModelRequest[BaseModel]) -> ModelResult[BaseModel]:
        return ModelResult(
            kind=ModelResultKind.PARSED,
            parsed_output=request.output_type.model_validate(_specialist_payload("mismatch", "e1")),
            refusal=None,
            incomplete_reason=None,
            invalid_output_reason=None,
            metadata=ProviderMetadata(
                provider_name="other-provider",
                model_name=request.selected_model_name,
                response_id="mismatch",
                token_usage={},
                latency_ms=0,
                started_at=_now(),
                completed_at=_now(),
            ),
        )


def test_phase3_registry_uses_positive_typed_authority_allowlist() -> None:
    specialist = specialist_contracts()[0]
    chief = chief_growth_producer_contract()
    controller = controller_contracts()[0]

    assert AgentAuthority.READ_CONTEXT in specialist.authority_boundaries
    assert AgentAuthority.PROPOSE_RECOMMENDATION in specialist.authority_boundaries
    assert AgentAuthority.PROPOSE_DECISION_CANDIDATE not in specialist.authority_boundaries
    assert AgentAuthority.PROPOSE_DECISION_CANDIDATE in chief.authority_boundaries
    assert AgentAuthority.REVIEW_DECISION_CANDIDATE not in chief.authority_boundaries
    assert AgentAuthority.REVIEW_DECISION_CANDIDATE in controller.authority_boundaries
    assert AgentAuthority.PROPOSE_RECOMMENDATION not in controller.authority_boundaries

    with pytest.raises(AIContractError):
        AgentRegistry(
            [
                replace(
                    specialist,
                    authority_boundaries=(
                        AgentAuthority.READ_CONTEXT,
                        AgentAuthority.PROPOSE_DECISION_CANDIDATE,
                    ),
                )
            ]
        )
    with pytest.raises(AIContractError):
        AgentRegistry(
            [
                replace(
                    chief,
                    authority_boundaries=(
                        AgentAuthority.READ_CONTEXT,
                        AgentAuthority.REVIEW_DECISION_CANDIDATE,
                    ),
                )
            ]
        )
    with pytest.raises(AIContractError):
        AgentRegistry(
            [
                replace(
                    controller,
                    authority_boundaries=(
                        AgentAuthority.READ_CONTEXT,
                        AgentAuthority.PROPOSE_RECOMMENDATION,
                    ),
                )
            ]
        )


def test_model_router_rejects_capability_mismatch() -> None:
    adapter = FakeModelAdapter[BaseModel]()
    from launch_os_v11.ai_runtime.errors import AIConfigurationError
    from launch_os_v11.ai_runtime.router import ModelRoute, ModelRouter

    with pytest.raises(AIConfigurationError):
        ModelRouter(
            routes={
                ModelCapability.DEEP_REASONING: ModelRoute(
                    capability=ModelCapability.FAST_STRUCTURED_CLASSIFICATION,
                    provider_name=adapter.provider_name,
                    model_name=adapter.model_name,
                )
            },
            adapters={adapter.provider_name: adapter},
        )


def test_start_workflow_creates_immutable_business_snapshot(session: Session) -> None:
    scope = _seed_business_graph(session, suffix="snapshot")
    queue = ListJobQueue()
    context = CommandContext(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        actor_user_id=None,
        correlation_id="corr-snapshot",
    )

    result = start_decision_workflow(
        session,
        context=context,
        queue=queue,
        clock=FixedClock(_now()),
    )
    original_name = result.snapshot.payload["business"]["name"]
    business = session.get(models.BusinessModel, scope.business_id)
    assert business is not None
    business.name = "Mutated after snapshot"
    session.flush()

    persisted = session.get(models.BusinessSnapshotModel, result.snapshot.id)
    assert persisted is not None
    assert persisted.payload["business"]["name"] == original_name
    assert persisted.payload["business"]["name"] != business.name


def test_route_trace_mismatch_fails_without_domain_write(engine) -> None:
    factory = create_session_factory(engine)
    scope = _seed_business_graph_in_factory(factory, suffix="trace")
    queue = ListJobQueue()
    clock = FixedClock(_now())
    session = factory()
    try:
        with session.begin():
            context = CommandContext(
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                actor_user_id=None,
                correlation_id="corr-trace",
            )
            workflow = start_decision_workflow(
                session,
                context=context,
                queue=queue,
                clock=clock,
            ).workflow
            workflow_id = workflow.id
    finally:
        session.close()

    worker = Worker(
        session_factory=factory,
        queue=queue,
        worker_id="phase3-trace-worker",
        clock=clock,
        handlers=compose_application_handler_registry(
            settings=Settings(),
            queue=queue,
            model_router=fake_model_router(MismatchedTraceAdapter()),
        ),
    )

    assert worker.process_one_from_queue() is not None
    result = worker.process_one_from_queue()
    assert result is not None
    assert result.status == "FAILED"
    session = factory()
    try:
        workflow = session.get(models.DecisionWorkflowModel, workflow_id)
        assert workflow is not None
        assert workflow.status == DecisionWorkflowStatus.SPECIALISTS_RUNNING.value
        assert session.scalar(select(func.count()).select_from(models.DecisionModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.ActionModel)) == 0
    finally:
        session.close()


def test_controller_block_prevents_final_decision_materialization(engine) -> None:
    factory = create_session_factory(engine)
    scope = _seed_business_graph_in_factory(factory, suffix="block")
    queue = ListJobQueue()
    clock = FixedClock(_now())
    evidence_id = "evidence-block"
    script = [
        *[
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_specialist_payload(role, evidence_id),
            )
            for role in ("Audience Intelligence", "Revenue/Funnel Strategist", "Launch Strategist")
        ],
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_candidate_payload(
                evidence_id,
                selected_action="Tell buyers low sales prove they are not ready.",
            ),
        ),
        *[
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_controller_payload(
                    contract_key.removeprefix("ai.controller."),
                    evidence_id,
                    verdict=ControllerVerdict.BLOCK
                    if contract_key.endswith(".constitutional")
                    else ControllerVerdict.PASS,
                    issues=["Maps business performance to human readiness"]
                    if contract_key.endswith(".constitutional")
                    else [],
                ),
            )
            for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS
        ],
    ]
    workflow_id = _start_workflow_in_factory(factory, scope=scope, queue=queue, clock=clock)
    worker = _phase3_worker(factory=factory, queue=queue, clock=clock, script=script)
    _process_all(worker, queue)

    session = factory()
    try:
        workflow = session.get(models.DecisionWorkflowModel, workflow_id)
        assert workflow is not None
        assert workflow.status == DecisionWorkflowStatus.BLOCKED.value
        candidate = session.scalar(select(models.DecisionCandidateModel))
        assert candidate is not None
        assert candidate.status == "BLOCKED"
        assert session.scalar(select(func.count()).select_from(models.DecisionModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.ActionModel)) == 0
        assert session.scalar(select(func.count()).select_from(models.ExecutionModel)) == 0
    finally:
        session.close()


def test_decision_approval_binds_exact_decision_version() -> None:
    decision = models.DecisionModel(
        id="decision-v1",
        organization_id="org",
        business_id="biz",
        version=1,
        goal_problem="Problem",
        selected_action="Action v1",
        expected_effect="Effect",
        confidence=0.7,
        reversibility="easy",
        risk_class="LOW",
        status="AWAITING_DECISION_APPROVAL",
        evidence_ids=[],
        assumption_ids=[],
        known_unknown_ids=[],
    )
    approval = models.DecisionApprovalModel(
        id="approval-v1",
        organization_id="org",
        business_id="biz",
        workflow_id="workflow",
        decision_id=decision.id,
        candidate_id="candidate",
        action_type=DECISION_APPROVAL_ACTION,
        object_type="Decision",
        object_id=decision.id,
        object_version_id=decision.id,
        object_version=decision.version,
        approved_by_user_id="user",
        status=ApprovalStatus.APPROVED.value,
        created_at=_now(),
    )
    new_decision = models.DecisionModel(
        id="decision-v2",
        organization_id="org",
        business_id="biz",
        version=2,
        goal_problem="Problem",
        selected_action="Action v2",
        expected_effect="Effect",
        confidence=0.8,
        reversibility="easy",
        risk_class="LOW",
        status="AWAITING_DECISION_APPROVAL",
        supersedes_decision_id=decision.id,
        evidence_ids=[],
        assumption_ids=[],
        known_unknown_ids=[],
    )

    assert approval_matches_decision(approval, decision)
    assert not approval_matches_decision(approval, new_decision)


def _phase3_worker(
    *,
    factory: sessionmaker[Session],
    queue: JobQueue,
    clock: FixedClock,
    script: list[FakeAdapterScriptStep],
) -> Worker:
    adapter = FakeModelAdapter[BaseModel](script=script)
    return Worker(
        session_factory=factory,
        queue=queue,
        worker_id="phase3-worker",
        clock=clock,
        handlers=compose_application_handler_registry(
            settings=Settings(),
            queue=queue,
            model_router=fake_model_router(adapter),
        ),
    )


def _process_all(worker: Worker, queue: ListJobQueue, *, limit: int = 80) -> None:
    for _ in range(limit):
        if not queue.messages:
            return
        result = worker.process_one_from_queue()
        assert result is not None
    pytest.fail(f"queue was not drained: {queue.messages}")


def _start_workflow_in_factory(
    factory: sessionmaker[Session],
    *,
    scope: TenantScope,
    queue: ListJobQueue,
    clock: FixedClock,
) -> str:
    session = factory()
    try:
        with session.begin():
            context = CommandContext(
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                actor_user_id=None,
                correlation_id="corr-phase3",
            )
            return start_decision_workflow(
                session,
                context=context,
                queue=queue,
                clock=clock,
            ).workflow.id
    finally:
        session.close()


def _seed_business_graph_in_factory(
    factory: sessionmaker[Session],
    *,
    suffix: str,
) -> TenantScope:
    session = factory()
    try:
        with session.begin():
            return _seed_business_graph(session, suffix=suffix)
    finally:
        session.close()


def _seed_business_graph(session: Session, *, suffix: str) -> TenantScope:
    organization = create_organization(session, name=f"Phase 3 Org {suffix}")
    business = create_business(
        session,
        organization_id=organization.id,
        name=f"Phase 3 Business {suffix}",
        timezone="UTC",
        actor_user_id=None,
        correlation_id=f"corr-seed-{suffix}",
    ).record
    scope = TenantScope(organization_id=organization.id, business_id=business.id)
    now = _now()
    user = models.UserModel(
        id=f"user-{suffix}",
        email=f"{suffix}@example.test",
        display_name="Owner",
    )
    goal = models.GoalModel(
        id=f"goal-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        title="Increase qualified replies",
        target="10 replies",
        metric="qualified_replies",
    )
    product = models.ProductModel(
        id=f"product-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name="Cohort",
        description="Guided launch cohort",
    )
    offer = models.OfferModel(
        id=f"offer-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        product_id=product.id,
        name="Pilot offer",
        description="Pilot",
        price_descriptor="intro",
    )
    channel = models.ChannelModel(
        id=f"channel-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="manual",
        handle="@launch",
        capabilities={"post": False},
    )
    source = models.SourceRecordModel(
        id=f"source-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="manual",
        external_id=f"source-{suffix}",
        source_type="note",
        trust=SourceTrust.USER_PROVIDED.value,
        payload={"note": "Audience asked for a concise launch offer."},
        ingested_at=now,
    )
    evidence = models.EvidenceModel(
        id=f"evidence-{suffix}",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement="Audience asked for a concise launch offer.",
        status=EpistemicStatus.FACT.value,
        recorded_at=now,
        conflicts_with_evidence_ids=[],
    )
    session.add_all([user, goal, product, offer, channel, source, evidence])
    session.flush()
    return scope


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
    issues: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_name": "ControllerReview",
        "schema_version": 1,
        "controller_type": controller_type,
        "verdict": verdict.value,
        "issues": issues or [],
        "required_changes": ["Revise candidate"] if verdict == ControllerVerdict.REVISE else [],
        "severity": "LOW" if verdict == ControllerVerdict.PASS else "HIGH",
        "evidence_refs": [_evidence_ref(evidence_id)],
    }


def _now() -> datetime:
    return datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
