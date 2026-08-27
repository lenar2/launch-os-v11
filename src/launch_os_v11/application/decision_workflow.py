from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.context import ContextReference
from launch_os_v11.ai_runtime.contracts import AgentRunStatus
from launch_os_v11.ai_runtime.registry import (
    CHIEF_GROWTH_PRODUCER_CONTRACT_KEY,
    REQUIRED_CONTROLLER_CONTRACT_KEYS,
    SPECIALIST_CONTRACT_KEYS,
    AgentRegistry,
)
from launch_os_v11.ai_runtime.schemas import (
    ControllerReviewOutput,
    DecisionCandidate,
    SpecialistContribution,
)
from launch_os_v11.ai_runtime.service import AgentRunService
from launch_os_v11.application.commands import (
    CommandContext,
    _append_audit,
    _event,
    create_business_snapshot,
)
from launch_os_v11.domain.enums import (
    ApprovalStatus,
    CausalityClass,
    ControllerVerdict,
    ExperimentStatus,
)
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import (
    AgentDefinitionModel,
    AgentRunModel,
    BusinessModel,
    BusinessSnapshotModel,
    ChannelModel,
    ClaimModel,
    ConstraintModel,
    ControllerReviewModel,
    DecisionAlternativeModel,
    DecisionApprovalModel,
    DecisionCandidateModel,
    DecisionModel,
    DecisionWorkflowModel,
    EvidenceModel,
    ExperimentModel,
    ExperimentRuleModel,
    GoalModel,
    HypothesisModel,
    InformationNeedModel,
    JobModel,
    LaunchModel,
    OfferModel,
    ProductModel,
    SpecialistContributionModel,
)
from launch_os_v11.persistence.outbox import append_outbox_event
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_AI_RUN_AGENT,
    JOB_TYPE_AI_RUN_CONTROLLER,
    JOB_TYPE_WORKFLOW_ADVANCE,
    RuntimeJobContext,
)
from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.security import assert_no_secrets
from launch_os_v11.runtime.transport import JobQueue


class DecisionWorkflowStatus(StrEnum):
    SNAPSHOT_READY = "SNAPSHOT_READY"
    SPECIALISTS_RUNNING = "SPECIALISTS_RUNNING"
    SPECIALISTS_READY = "SPECIALISTS_READY"
    CHIEF_RUNNING = "CHIEF_RUNNING"
    DECISION_CANDIDATE_READY = "DECISION_CANDIDATE_READY"
    CONTROLLERS_RUNNING = "CONTROLLERS_RUNNING"
    BLOCKED = "BLOCKED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    CANDIDATE_ACCEPTED = "CANDIDATE_ACCEPTED"
    FINAL_DECISION_MATERIALIZED = "FINAL_DECISION_MATERIALIZED"
    AWAITING_DECISION_APPROVAL = "AWAITING_DECISION_APPROVAL"
    APPROVED_FOR_PRODUCTION = "APPROVED_FOR_PRODUCTION"
    ESCALATED = "ESCALATED"


class DecisionCandidateStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"
    MATERIALIZED = "MATERIALIZED"


DECISION_APPROVAL_ACTION = "approve_decision_for_production"
_PENDING_AGENT_RUN_STATUSES = {
    AgentRunStatus.QUEUED.value,
    AgentRunStatus.RUNNING.value,
    AgentRunStatus.RETRY_WAIT.value,
}
_MAX_CONTROLLER_OUTPUT_ATTEMPTS = 3
_CONTROLLER_TYPE_ALIASES = {
    "evidence": frozenset({"evidence", "evidencecontroller", "evidencecontrollerreview"}),
    "strategy_red_team": frozenset(
        {"strategyredteam", "strategyredteamcontroller", "strategyredteamreview"}
    ),
    "constitutional": frozenset(
        {"constitutional", "constitutionalcontroller", "constitutionalcontrollerreview"}
    ),
    "decision_quality": frozenset(
        {"decisionquality", "decisionqualitycontroller", "decisionqualitycontrollerreview"}
    ),
    "economics": frozenset({"economics", "economicscontroller", "economicscontrollerreview"}),
    "manipulation": frozenset(
        {"manipulation", "manipulationcontroller", "manipulationcontrollerreview"}
    ),
    "anti_analysis_paralysis": frozenset(
        {
            "antianalysisparalysis",
            "antianalysisparalysiscontroller",
            "antianalysisparalysiscontrollerreview",
        }
    ),
}


@dataclass(frozen=True)
class DecisionWorkflowStartResult:
    workflow: DecisionWorkflowModel
    snapshot: BusinessSnapshotModel
    job_id: str


@dataclass(frozen=True)
class UserDecisionView:
    decision: str
    reasons: tuple[str, ...]
    what_happens_now: str
    ready_assets_actions: tuple[str, ...]
    metric_target_current: str | None
    next_checkpoint: str | None
    approval_needed: bool
    status: str


def start_decision_workflow(
    session: Session,
    *,
    context: CommandContext,
    queue: JobQueue,
    clock: Clock,
    launch_id: str | None = None,
    snapshot_id: str | None = None,
    max_revision_rounds: int = 2,
) -> DecisionWorkflowStartResult:
    snapshot = (
        _snapshot(session, scope=context.scope, snapshot_id=snapshot_id)
        if snapshot_id is not None
        else create_business_snapshot(
            session,
            context=context,
            reason="phase3.decision_workflow",
            payload=_snapshot_payload(session, scope=context.scope, launch_id=launch_id),
        ).record
    )
    if launch_id is not None:
        launch = session.get(LaunchModel, launch_id)
        if launch is None:
            raise PermanentJobError("Launch not found for decision workflow")
        context.scope.assert_matches(
            organization_id=launch.organization_id,
            business_id=launch.business_id,
        )
    existing = session.scalar(
        select(DecisionWorkflowModel).where(
            DecisionWorkflowModel.organization_id == context.organization_id,
            DecisionWorkflowModel.business_id == context.business_id,
            DecisionWorkflowModel.snapshot_id == snapshot.id,
        )
    )
    if existing is not None:
        job = _enqueue_workflow_advance(
            session,
            workflow=existing,
            queue=queue,
            clock=clock,
            suffix=f"resume:{existing.status}:{existing.revision_count}",
        )
        return DecisionWorkflowStartResult(workflow=existing, snapshot=snapshot, job_id=job.id)

    workflow = DecisionWorkflowModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        launch_id=launch_id,
        snapshot_id=snapshot.id,
        status=DecisionWorkflowStatus.SNAPSHOT_READY.value,
        revision_count=0,
        max_revision_rounds=max_revision_rounds,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
    )
    session.add(workflow)
    session.flush()
    event = _event(
        context,
        event_type="decision_workflow.started",
        aggregate_type="DecisionWorkflow",
        aggregate_id=workflow.id,
        payload={"snapshot_id": snapshot.id, "launch_id": launch_id},
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action="start_decision_workflow",
        object_type="DecisionWorkflow",
        object_id=workflow.id,
        payload={"snapshot_id": snapshot.id},
    )
    job = _enqueue_workflow_advance(
        session,
        workflow=workflow,
        queue=queue,
        clock=clock,
        suffix="start",
    )
    return DecisionWorkflowStartResult(workflow=workflow, snapshot=snapshot, job_id=job.id)


class DecisionWorkflowAdvanceHandler:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        queue: JobQueue,
    ) -> None:
        self._registry = registry
        self._queue = queue

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        assert_no_secrets(payload)
        workflow_id = _workflow_id(payload)
        workflow = session.get(DecisionWorkflowModel, workflow_id)
        if workflow is None:
            raise PermanentJobError(f"DecisionWorkflow not found: {workflow_id}")
        context.scope.assert_matches(
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
        )
        _advance_workflow(
            session,
            workflow=workflow,
            queue=self._queue,
            clock=clock,
            registry=self._registry,
        )


def approve_decision_for_production(
    session: Session,
    *,
    context: CommandContext,
    workflow_id: str,
    approved_by_user_id: str,
) -> DecisionApprovalModel:
    workflow = session.get(DecisionWorkflowModel, workflow_id)
    if workflow is None:
        raise PermanentJobError("DecisionWorkflow not found")
    context.scope.assert_matches(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )
    if workflow.status == DecisionWorkflowStatus.APPROVED_FOR_PRODUCTION.value:
        if workflow.final_approval_id is None:
            raise PermanentJobError("Approved DecisionWorkflow has no approval binding")
        existing_approval = session.get(DecisionApprovalModel, workflow.final_approval_id)
        if existing_approval is None:
            raise PermanentJobError("DecisionWorkflow approval binding is missing")
        return existing_approval
    if workflow.status != DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value:
        raise PermanentJobError("DecisionWorkflow is not awaiting decision approval")
    if workflow.final_decision_id is None:
        raise PermanentJobError("DecisionWorkflow has no final Decision")
    decision = session.get(DecisionModel, workflow.final_decision_id)
    if decision is None or decision.source_candidate_id is None:
        raise PermanentJobError("Final Decision provenance is incomplete")
    context.scope.assert_matches(
        organization_id=decision.organization_id,
        business_id=decision.business_id,
    )
    existing = session.scalar(
        select(DecisionApprovalModel).where(
            DecisionApprovalModel.decision_id == decision.id,
            DecisionApprovalModel.action_type == DECISION_APPROVAL_ACTION,
            DecisionApprovalModel.object_version_id == decision.id,
        )
    )
    if existing is not None:
        return existing
    approval = DecisionApprovalModel(
        id=new_id(),
        organization_id=context.organization_id,
        business_id=context.business_id,
        workflow_id=workflow.id,
        decision_id=decision.id,
        candidate_id=decision.source_candidate_id,
        action_type=DECISION_APPROVAL_ACTION,
        object_type="Decision",
        object_id=decision.id,
        object_version_id=decision.id,
        object_version=decision.version,
        approved_by_user_id=approved_by_user_id,
        status=ApprovalStatus.APPROVED.value,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
        created_at=utc_now(),
    )
    session.add(approval)
    session.flush()
    decision.status = "APPROVED_FOR_PRODUCTION"
    workflow.final_approval_id = approval.id
    workflow.status = DecisionWorkflowStatus.APPROVED_FOR_PRODUCTION.value
    event = _event(
        context,
        event_type="decision.approved_for_production",
        aggregate_type="Decision",
        aggregate_id=decision.id,
        payload={
            "approval_id": approval.id,
            "object_version_id": approval.object_version_id,
            "action_type": approval.action_type,
        },
    )
    append_outbox_event(session, event)
    _append_audit(
        session,
        context=context,
        action=DECISION_APPROVAL_ACTION,
        object_type="Decision",
        object_id=decision.id,
        payload={"object_version_id": approval.object_version_id},
    )
    session.flush()
    return approval


def approval_matches_decision(approval: DecisionApprovalModel, decision: DecisionModel) -> bool:
    return (
        approval.object_type == "Decision"
        and approval.object_id == decision.id
        and approval.object_version_id == decision.id
        and approval.object_version == decision.version
        and approval.action_type == DECISION_APPROVAL_ACTION
        and approval.status == ApprovalStatus.APPROVED.value
    )


def get_user_decision_view(
    session: Session,
    *,
    scope: TenantScope,
    decision_id: str,
) -> UserDecisionView:
    decision = session.get(DecisionModel, decision_id)
    if decision is None:
        raise PermanentJobError("Decision not found")
    scope.assert_matches(organization_id=decision.organization_id, business_id=decision.business_id)
    candidate_payload: dict[str, Any] = {}
    if decision.source_candidate_id is not None:
        candidate = session.get(DecisionCandidateModel, decision.source_candidate_id)
        if candidate is not None:
            candidate_payload = candidate.payload
    reasons = tuple((candidate_payload.get("why") or [])[:3])
    ready_actions = tuple(decision.required_actions or [])
    experiment = decision.experiment_proposal or {}
    metric = experiment.get("metric")
    target = experiment.get("success_threshold")
    metric_target = (
        f"{metric} / {target}" if isinstance(metric, str) and isinstance(target, str) else None
    )
    return UserDecisionView(
        decision=decision.selected_action,
        reasons=reasons,
        what_happens_now=(
            "Await owner approval before production."
            if decision.status == "AWAITING_DECISION_APPROVAL"
            else "Decision approved for Phase 4 production."
        ),
        ready_assets_actions=ready_actions,
        metric_target_current=metric_target,
        next_checkpoint=decision.next_checkpoint,
        approval_needed=decision.status == "AWAITING_DECISION_APPROVAL",
        status=decision.status,
    )


def _advance_workflow(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    status = DecisionWorkflowStatus(workflow.status)
    if status == DecisionWorkflowStatus.SNAPSHOT_READY:
        _ensure_specialist_runs(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        workflow.status = DecisionWorkflowStatus.SPECIALISTS_RUNNING.value
        _enqueue_workflow_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix="after-specialists",
        )
        return
    if status == DecisionWorkflowStatus.SPECIALISTS_RUNNING:
        _materialize_specialist_contributions(session, workflow=workflow)
        workflow.status = DecisionWorkflowStatus.SPECIALISTS_READY.value
        _ensure_chief_run(session, workflow=workflow, queue=queue, clock=clock, registry=registry)
        workflow.status = DecisionWorkflowStatus.CHIEF_RUNNING.value
        _enqueue_workflow_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix=f"after-chief:{_next_candidate_version(session, workflow)}",
        )
        return
    if status == DecisionWorkflowStatus.CHIEF_RUNNING:
        candidate = _materialize_candidate(session, workflow=workflow)
        workflow.status = DecisionWorkflowStatus.DECISION_CANDIDATE_READY.value
        _ensure_controller_runs(
            session,
            workflow=workflow,
            candidate=candidate,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        candidate.status = DecisionCandidateStatus.UNDER_REVIEW.value
        workflow.status = DecisionWorkflowStatus.CONTROLLERS_RUNNING.value
        _enqueue_workflow_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix=f"after-controllers:{candidate.version_number}",
        )
        return
    if status == DecisionWorkflowStatus.CONTROLLERS_RUNNING:
        candidate = _latest_candidate(session, workflow)
        not_ready_controller_runs = _ensure_controller_runs(
            session,
            workflow=workflow,
            candidate=candidate,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        if not_ready_controller_runs:
            generation = _controller_run_generation(session, workflow, candidate)
            _enqueue_workflow_advance(
                session,
                workflow=workflow,
                queue=queue,
                clock=clock,
                suffix=(
                    f"after-controllers:{candidate.version_number}:"
                    f"controller-output-retry:{generation}"
                ),
            )
            return
        reviews = _materialize_controller_reviews(session, workflow=workflow, candidate=candidate)
        outcome = _controller_outcome(reviews)
        if outcome == ControllerVerdict.BLOCK:
            candidate.status = DecisionCandidateStatus.BLOCKED.value
            workflow.status = DecisionWorkflowStatus.BLOCKED.value
            session.flush()
            return
        if outcome == ControllerVerdict.REVISE:
            candidate.status = DecisionCandidateStatus.REVISION_REQUIRED.value
            if workflow.revision_count >= workflow.max_revision_rounds:
                workflow.status = DecisionWorkflowStatus.ESCALATED.value
                session.flush()
                return
            workflow.revision_count += 1
            workflow.status = DecisionWorkflowStatus.REVISION_REQUIRED.value
            _ensure_chief_run(
                session,
                workflow=workflow,
                queue=queue,
                clock=clock,
                registry=registry,
                previous_candidate=candidate,
                reviews=reviews,
            )
            workflow.status = DecisionWorkflowStatus.CHIEF_RUNNING.value
            _enqueue_workflow_advance(
                session,
                workflow=workflow,
                queue=queue,
                clock=clock,
                suffix=f"after-chief:{_next_candidate_version(session, workflow)}",
            )
            return
        candidate.status = DecisionCandidateStatus.ACCEPTED.value
        workflow.status = DecisionWorkflowStatus.CANDIDATE_ACCEPTED.value
        _materialize_final_decision(session, workflow=workflow, candidate=candidate)
        workflow.status = DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value
        return


def _ensure_specialist_runs(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    scope = TenantScope(organization_id=workflow.organization_id, business_id=workflow.business_id)
    for contract_key in SPECIALIST_CONTRACT_KEYS:
        service.create_agent_run(
            session,
            scope=scope,
            contract_key=contract_key,
            contract_version=1,
            input_ref=f"decision_workflow:{workflow.id}:specialist:{contract_key}",
            context_refs=(
                ContextReference(
                    object_type="business_snapshot",
                    object_id=workflow.snapshot_id,
                ),
            ),
            correlation_id=workflow.correlation_id,
            causation_id=workflow.id,
            job_type=JOB_TYPE_AI_RUN_AGENT,
            idempotency_key=f"decision_workflow:{workflow.id}:specialist:{contract_key}",
        )


def _ensure_chief_run(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
    previous_candidate: DecisionCandidateModel | None = None,
    reviews: tuple[ControllerReviewModel, ...] = (),
) -> None:
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    scope = TenantScope(organization_id=workflow.organization_id, business_id=workflow.business_id)
    refs = [ContextReference(object_type="business_snapshot", object_id=workflow.snapshot_id)]
    refs.extend(
        ContextReference(object_type="specialist_contribution", object_id=row.id)
        for row in _specialist_contributions(session, workflow)
    )
    if previous_candidate is not None:
        refs.append(
            ContextReference(
                object_type="decision_candidate",
                object_id=previous_candidate.id,
            )
        )
    refs.extend(
        ContextReference(object_type="controller_review", object_id=review.id)
        for review in reviews
    )
    version = _next_candidate_version(session, workflow)
    service.create_agent_run(
        session,
        scope=scope,
        contract_key=CHIEF_GROWTH_PRODUCER_CONTRACT_KEY,
        contract_version=1,
        input_ref=f"decision_workflow:{workflow.id}:chief:v{version}",
        context_refs=tuple(refs),
        correlation_id=workflow.correlation_id,
        causation_id=workflow.id,
        job_type=JOB_TYPE_AI_RUN_AGENT,
        idempotency_key=f"decision_workflow:{workflow.id}:chief:v{version}",
    )


def _ensure_controller_runs(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> int:
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    scope = TenantScope(organization_id=workflow.organization_id, business_id=workflow.business_id)
    refs = (
        ContextReference(object_type="business_snapshot", object_id=workflow.snapshot_id),
        ContextReference(object_type="decision_candidate", object_id=candidate.id),
    )
    not_ready_count = 0
    for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS:
        controller_type = contract_key.removeprefix("ai.controller.")
        run_state = _controller_run_state(
            session,
            workflow=workflow,
            candidate=candidate,
            contract_key=contract_key,
            controller_type=controller_type,
        )
        if run_state == "ready":
            continue
        not_ready_count += 1
        if run_state == "pending":
            continue
        idempotency_key = _next_controller_run_idempotency_key(
            session,
            workflow=workflow,
            candidate=candidate,
            contract_key=contract_key,
        )
        if idempotency_key is None:
            continue
        input_ref = _controller_run_input_ref(
            workflow=workflow,
            candidate=candidate,
            contract_key=contract_key,
        )
        service.create_agent_run(
            session,
            scope=scope,
            contract_key=contract_key,
            contract_version=1,
            input_ref=input_ref,
            context_refs=refs,
            correlation_id=workflow.correlation_id,
            causation_id=candidate.id,
            job_type=JOB_TYPE_AI_RUN_CONTROLLER,
            idempotency_key=idempotency_key,
        )
    return not_ready_count


def _materialize_specialist_contributions(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
) -> None:
    for contract_key in SPECIALIST_CONTRACT_KEYS:
        existing = _specialist_contribution(session, workflow=workflow, contract_key=contract_key)
        if existing is not None:
            continue
        run = _agent_run_by_idempotency(
            session,
            workflow,
            f"decision_workflow:{workflow.id}:specialist:{contract_key}",
        )
        if run.status != AgentRunStatus.SUCCEEDED.value or run.output_data is None:
            raise TransientJobError(f"specialist run is not ready: {contract_key}")
        try:
            output = SpecialistContribution.model_validate(run.output_data)
        except ValidationError as exc:
            raise PermanentJobError("specialist output failed schema validation") from exc
        _validate_evidence_refs(session, workflow=workflow, run=run, refs=output.evidence_refs)
        definition = _definition_for_run(session, run)
        row = SpecialistContributionModel(
            id=new_id(),
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
            workflow_id=workflow.id,
            snapshot_id=workflow.snapshot_id,
            agent_run_id=run.id,
            contract_key=run.agent_contract_key,
            contract_version=run.agent_contract_version,
            instruction_version=definition.instruction_version,
            schema_version=output.schema_version,
            role=output.role,
            payload=output.model_dump(mode="json"),
            evidence_refs=[ref.model_dump(mode="json") for ref in output.evidence_refs],
            context_hash=_required(run, "context_hash"),
            context_manifest=run.context_manifest,
            correlation_id=run.correlation_id,
            causation_id=run.causation_id,
            created_at=utc_now(),
        )
        session.add(row)
        session.flush()


def _materialize_candidate(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
) -> DecisionCandidateModel:
    version = _next_candidate_version(session, workflow)
    existing = session.scalar(
        select(DecisionCandidateModel).where(
            DecisionCandidateModel.workflow_id == workflow.id,
            DecisionCandidateModel.version_number == version,
        )
    )
    if existing is not None:
        return existing
    run = _agent_run_by_idempotency(
        session,
        workflow,
        f"decision_workflow:{workflow.id}:chief:v{version}",
    )
    if run.status != AgentRunStatus.SUCCEEDED.value or run.output_data is None:
        raise TransientJobError("chief run is not ready")
    try:
        output = DecisionCandidate.model_validate(run.output_data)
    except ValidationError as exc:
        raise PermanentJobError("DecisionCandidate output failed schema validation") from exc
    if not output.selected_action.strip():
        raise PermanentJobError("DecisionCandidate selected_action is required")
    _validate_evidence_refs(session, workflow=workflow, run=run, refs=output.evidence_refs)
    previous = _latest_candidate_or_none(session, workflow)
    contribution_ids = [row.id for row in _specialist_contributions(session, workflow)]
    row = DecisionCandidateModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        workflow_id=workflow.id,
        snapshot_id=workflow.snapshot_id,
        chief_agent_run_id=run.id,
        previous_candidate_id=previous.id if previous is not None else None,
        version_number=version,
        revision_round=workflow.revision_count,
        status=DecisionCandidateStatus.CANDIDATE.value,
        schema_version=output.schema_version,
        selected_action=output.selected_action,
        payload=output.model_dump(mode="json"),
        evidence_refs=[ref.model_dump(mode="json") for ref in output.evidence_refs],
        specialist_contribution_ids=contribution_ids,
        controller_review_ids=[],
        context_hash=_required(run, "context_hash"),
        context_manifest=run.context_manifest,
        correlation_id=run.correlation_id,
        causation_id=run.causation_id,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _materialize_controller_reviews(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
) -> tuple[ControllerReviewModel, ...]:
    reviews: list[ControllerReviewModel] = []
    for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS:
        controller_type = contract_key.removeprefix("ai.controller.")
        existing = session.scalar(
            select(ControllerReviewModel).where(
                ControllerReviewModel.decision_candidate_id == candidate.id,
                ControllerReviewModel.controller_type == controller_type,
            )
        )
        if existing is not None:
            reviews.append(existing)
            continue
        run = _controller_agent_run(
            session,
            workflow=workflow,
            candidate=candidate,
            contract_key=contract_key,
            controller_type=controller_type,
        )
        if run.status != AgentRunStatus.SUCCEEDED.value or run.output_data is None:
            raise TransientJobError(f"controller run is not ready: {controller_type}")
        try:
            output = ControllerReviewOutput.model_validate(run.output_data)
        except ValidationError as exc:
            raise PermanentJobError("ControllerReview output failed schema validation") from exc
        _assert_controller_type_matches_contract(
            expected_controller_type=controller_type,
            output_controller_type=output.controller_type,
        )
        _validate_evidence_refs(session, workflow=workflow, run=run, refs=output.evidence_refs)
        _validate_controller_verdict(
            controller_type=controller_type,
            candidate=candidate,
            output=output,
        )
        definition = _definition_for_run(session, run)
        row = ControllerReviewModel(
            id=new_id(),
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
            decision_id=None,
            asset_version_id=None,
            controller_name=output.controller_type,
            verdict=output.verdict.value,
            reason="; ".join(output.issues or output.required_changes or [output.verdict.value]),
            decision_candidate_id=candidate.id,
            agent_run_id=run.id,
            snapshot_id=workflow.snapshot_id,
            controller_type=controller_type,
            contract_key=run.agent_contract_key,
            contract_version=run.agent_contract_version,
            instruction_version=definition.instruction_version,
            output_schema_version=output.schema_version,
            context_hash=_required(run, "context_hash"),
            context_manifest=run.context_manifest,
            severity=output.severity.value,
            issues=list(output.issues),
            required_changes=list(output.required_changes),
            evidence_refs=[ref.model_dump(mode="json") for ref in output.evidence_refs],
            conditions=list(output.required_changes)
            if output.verdict == ControllerVerdict.PASS_WITH_CONDITIONS
            else [],
            correlation_id=run.correlation_id,
            causation_id=run.causation_id,
        )
        session.add(row)
        session.flush()
        reviews.append(row)
    candidate.controller_review_ids = [review.id for review in reviews]
    session.flush()
    return tuple(reviews)


def _next_controller_run_idempotency_key(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    contract_key: str,
) -> str:
    runs = _controller_agent_runs(
        session,
        workflow=workflow,
        candidate=candidate,
        contract_key=contract_key,
    )
    base_key = _controller_run_input_ref(
        workflow=workflow,
        candidate=candidate,
        contract_key=contract_key,
    )
    if not runs:
        return base_key
    return f"{base_key}:retry:{len(runs) + 1}"


def _controller_run_state(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    contract_key: str,
    controller_type: str,
) -> str:
    runs = _controller_agent_runs(
        session,
        workflow=workflow,
        candidate=candidate,
        contract_key=contract_key,
    )
    if any(run.status in _PENDING_AGENT_RUN_STATUSES for run in runs):
        return "pending"
    if any(
        _controller_run_can_materialize(
            session,
            workflow=workflow,
            candidate=candidate,
            run=run,
            controller_type=controller_type,
        )
        for run in runs
    ):
        return "ready"
    if len(runs) >= _MAX_CONTROLLER_OUTPUT_ATTEMPTS:
        raise PermanentJobError("ControllerReview output retry limit exceeded")
    return "create"


def _controller_agent_run(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    contract_key: str,
    controller_type: str,
) -> AgentRunModel:
    runs = _controller_agent_runs(
        session,
        workflow=workflow,
        candidate=candidate,
        contract_key=contract_key,
    )
    for run in runs:
        if _controller_run_can_materialize(
            session,
            workflow=workflow,
            candidate=candidate,
            run=run,
            controller_type=controller_type,
        ):
            return run
    if any(run.status in _PENDING_AGENT_RUN_STATUSES for run in runs):
        raise TransientJobError(f"controller run is not ready: {controller_type}")
    if len(runs) >= _MAX_CONTROLLER_OUTPUT_ATTEMPTS:
        raise PermanentJobError("ControllerReview output retry limit exceeded")
    raise TransientJobError(f"controller run is not ready: {controller_type}")


def _controller_agent_runs(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    contract_key: str,
) -> tuple[AgentRunModel, ...]:
    input_ref = _controller_run_input_ref(
        workflow=workflow,
        candidate=candidate,
        contract_key=contract_key,
    )
    return tuple(
        session.scalars(
            select(AgentRunModel)
            .where(
                AgentRunModel.organization_id == workflow.organization_id,
                AgentRunModel.business_id == workflow.business_id,
                AgentRunModel.agent_contract_key == contract_key,
                AgentRunModel.agent_contract_version == 1,
                AgentRunModel.input_ref == input_ref,
            )
            .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
        )
    )


def _controller_run_generation(
    session: Session,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
) -> int:
    input_refs = [
        _controller_run_input_ref(
            workflow=workflow,
            candidate=candidate,
            contract_key=contract_key,
        )
        for contract_key in REQUIRED_CONTROLLER_CONTRACT_KEYS
    ]
    return int(
        session.scalar(
            select(func.count())
            .select_from(AgentRunModel)
            .where(
                AgentRunModel.organization_id == workflow.organization_id,
                AgentRunModel.business_id == workflow.business_id,
                AgentRunModel.input_ref.in_(input_refs),
            )
        )
        or 0
    )


def _controller_run_input_ref(
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    contract_key: str,
) -> str:
    return f"decision_workflow:{workflow.id}:candidate:{candidate.version_number}:{contract_key}"


def _controller_run_can_materialize(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
    run: AgentRunModel,
    controller_type: str,
) -> bool:
    if run.status != AgentRunStatus.SUCCEEDED.value or run.output_data is None:
        return False
    try:
        output = ControllerReviewOutput.model_validate(run.output_data)
        _assert_controller_type_matches_contract(
            expected_controller_type=controller_type,
            output_controller_type=output.controller_type,
        )
        _validate_evidence_refs(session, workflow=workflow, run=run, refs=output.evidence_refs)
        _validate_controller_verdict(
            controller_type=controller_type,
            candidate=candidate,
            output=output,
        )
    except (PermanentJobError, ValidationError):
        return False
    return True


def _materialize_final_decision(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    candidate: DecisionCandidateModel,
) -> DecisionModel:
    if workflow.final_decision_id is not None:
        existing = session.get(DecisionModel, workflow.final_decision_id)
        if existing is None:
            raise PermanentJobError("Workflow final_decision_id points to missing Decision")
        return existing
    output = DecisionCandidate.model_validate(candidate.payload)
    if not output.selected_action.strip():
        raise PermanentJobError("accepted candidate has no selected_action")
    context = CommandContext(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        actor_user_id=None,
        correlation_id=workflow.correlation_id or new_id(),
        causation_id=candidate.id,
    )
    decision = DecisionModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        version=1,
        goal_problem=f"{output.goal}: {output.problem}",
        selected_action=output.selected_action,
        expected_effect=output.expected_effect,
        confidence=output.confidence,
        reversibility=output.reversibility,
        risk_class=output.risk_class.value,
        status="AWAITING_DECISION_APPROVAL",
        snapshot_id=workflow.snapshot_id,
        supersedes_decision_id=None,
        next_checkpoint=output.next_checkpoint,
        evidence_ids=[ref.evidence_id for ref in output.evidence_refs],
        assumption_ids=[assumption.statement for assumption in output.assumptions],
        known_unknown_ids=[unknown.question for unknown in output.unknowns],
        source_candidate_id=candidate.id,
        why_alternatives_not_selected=list(output.why_alternatives_not_selected),
        hypotheses=[item.model_dump(mode="json") for item in output.hypotheses],
        assumptions=[item.model_dump(mode="json") for item in output.assumptions],
        experiment_proposal=output.experiment_proposal.model_dump(mode="json")
        if output.experiment_proposal is not None
        else {},
        required_assets=list(output.required_assets),
        required_actions=list(output.required_actions),
    )
    session.add(decision)
    session.flush()
    for alternative in output.alternatives:
        session.add(
            DecisionAlternativeModel(
                id=new_id(),
                organization_id=workflow.organization_id,
                business_id=workflow.business_id,
                decision_id=decision.id,
                action=alternative.action,
                rejection_reason=alternative.rejection_reason,
            )
        )
    if output.experiment_proposal is not None:
        experiment = ExperimentModel(
            id=new_id(),
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
            decision_id=decision.id,
            hypothesis_id=None,
            metric=output.experiment_proposal.metric,
            status=ExperimentStatus.DRAFT.value,
            causality_class=CausalityClass.UNKNOWN.value,
        )
        session.add(experiment)
        session.flush()
        session.add(
            ExperimentRuleModel(
                id=new_id(),
                organization_id=workflow.organization_id,
                business_id=workflow.business_id,
                experiment_id=experiment.id,
                baseline=output.experiment_proposal.baseline,
                segment=output.experiment_proposal.segment,
                treatment=output.experiment_proposal.treatment,
                metric=output.experiment_proposal.metric,
                window=output.experiment_proposal.window,
                attribution_method=output.experiment_proposal.attribution_method,
                success_threshold=output.experiment_proposal.success_threshold,
                weak_signal_threshold=output.experiment_proposal.weak_signal_threshold,
                failure_threshold=output.experiment_proposal.failure_threshold,
                next_action_on_success=output.experiment_proposal.next_action_on_success,
                next_action_on_weak_signal=output.experiment_proposal.next_action_on_weak_signal,
                next_action_on_failure=output.experiment_proposal.next_action_on_failure,
            )
        )
    for review in _controller_reviews(session, candidate):
        review.decision_id = decision.id
    candidate.status = DecisionCandidateStatus.MATERIALIZED.value
    workflow.final_decision_id = decision.id
    workflow.status = DecisionWorkflowStatus.FINAL_DECISION_MATERIALIZED.value
    append_outbox_event(
        session,
        _event(
            context,
            event_type="decision.materialized",
            aggregate_type="Decision",
            aggregate_id=decision.id,
            payload={"source_candidate_id": candidate.id},
        ),
    )
    _append_audit(
        session,
        context=context,
        action="materialize_decision",
        object_type="Decision",
        object_id=decision.id,
        payload={"candidate_id": candidate.id},
    )
    session.flush()
    return decision


def _controller_outcome(reviews: tuple[ControllerReviewModel, ...]) -> ControllerVerdict:
    verdicts = {ControllerVerdict(review.verdict) for review in reviews}
    if ControllerVerdict.BLOCK in verdicts:
        return ControllerVerdict.BLOCK
    if ControllerVerdict.REVISE in verdicts:
        return ControllerVerdict.REVISE
    if ControllerVerdict.PASS_WITH_CONDITIONS in verdicts:
        return ControllerVerdict.PASS_WITH_CONDITIONS
    return ControllerVerdict.PASS


def _assert_controller_type_matches_contract(
    *,
    expected_controller_type: str,
    output_controller_type: str,
) -> None:
    aliases = _CONTROLLER_TYPE_ALIASES.get(expected_controller_type)
    if aliases is None:
        raise PermanentJobError("unknown controller contract type")
    if _controller_type_token(output_controller_type) not in aliases:
        raise PermanentJobError("ControllerReview controller_type does not match contract")


def _controller_type_token(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _validate_controller_verdict(
    *,
    controller_type: str,
    candidate: DecisionCandidateModel,
    output: ControllerReviewOutput,
) -> None:
    if (
        controller_type == "constitutional"
        and _contains_human_worth_violation(candidate.payload)
        and output.verdict != ControllerVerdict.BLOCK
    ):
        raise PermanentJobError("Constitutional Controller must BLOCK human-worth violations")
    if controller_type == "evidence" and not output.evidence_refs:
        raise PermanentJobError("Evidence Controller must include evidence_refs")


def _contains_human_worth_violation(payload: dict[str, Any]) -> bool:
    text = " ".join(_strings(payload)).lower()
    business_terms = ("sales", "conversion", "price", "non-purchase", "discipline", "revenue")
    worth_terms = ("human value", "worth", "rank", "not ready", "readiness", "correctness")
    return any(term in text for term in business_terms) and any(
        term in text for term in worth_terms
    )


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def _validate_evidence_refs(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    run: AgentRunModel,
    refs: Sequence[Any],
) -> None:
    expected_status_by_ref = _agent_run_evidence_ref_statuses(
        session,
        workflow=workflow,
        run=run,
    )
    for ref in refs:
        evidence_id = ref.evidence_id
        expected_status = expected_status_by_ref.get(evidence_id)
        if expected_status is None:
            raise PermanentJobError(f"unsupported evidence reference: {evidence_id}")
        if expected_status != ref.epistemic_status.value:
            raise PermanentJobError("evidence reference epistemic status mismatch")


def _agent_run_evidence_ref_statuses(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    run: AgentRunModel,
) -> dict[str, str]:
    _scope(workflow).assert_matches(
        organization_id=run.organization_id,
        business_id=run.business_id,
    )
    statuses = _manifest_evidence_ref_statuses(run.context_manifest)
    if f"business_snapshot:{workflow.snapshot_id}" in statuses:
        statuses.update(_snapshot_evidence_ref_statuses(session, workflow=workflow))
    return statuses


def _manifest_evidence_ref_statuses(manifest: object) -> dict[str, str]:
    if not isinstance(manifest, dict):
        return {}
    items = manifest.get("items")
    if not isinstance(items, list):
        return {}
    statuses: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        epistemic_status = item.get("epistemic_status")
        if not isinstance(epistemic_status, str):
            continue
        provenance_ref = item.get("provenance_ref")
        if isinstance(provenance_ref, str):
            statuses[provenance_ref] = epistemic_status
        source_object_type = item.get("source_object_type")
        source_object_id = item.get("source_object_id")
        if source_object_type == "evidence" and isinstance(source_object_id, str):
            statuses[source_object_id] = epistemic_status
    return statuses


def _snapshot_evidence_ref_statuses(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
) -> dict[str, str]:
    snapshot = _snapshot(session, scope=_scope(workflow), snapshot_id=workflow.snapshot_id)
    items = snapshot.payload.get("evidence", [])
    if not isinstance(items, list):
        return {}
    statuses: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("id")
        epistemic_status = item.get("status")
        if isinstance(evidence_id, str) and isinstance(epistemic_status, str):
            statuses[evidence_id] = epistemic_status
    return statuses


def _snapshot_payload(
    session: Session,
    *,
    scope: TenantScope,
    launch_id: str | None,
) -> dict[str, Any]:
    business = session.get(BusinessModel, scope.business_id)
    if business is None:
        raise PermanentJobError("Business not found for snapshot")
    scope.assert_matches(organization_id=business.organization_id, business_id=business.id)
    payload: dict[str, Any] = {
        "schema_name": "Phase3BusinessSnapshotPayload",
        "schema_version": 1,
        "business": {
            "id": business.id,
            "name": business.name,
            "timezone": business.timezone,
            "version": business.version,
        },
        "launch": None,
        "goals": [],
        "constraints": [],
        "products": [],
        "offers": [],
        "channels": [],
        "claims": [],
        "hypotheses": [],
        "information_needs": [],
        "evidence": [],
        "conflicts": [],
    }
    if launch_id is not None:
        launch = session.get(LaunchModel, launch_id)
        if launch is not None:
            scope.assert_matches(
                organization_id=launch.organization_id,
                business_id=launch.business_id,
            )
            payload["launch"] = {
                "id": launch.id,
                "campaign_id": launch.campaign_id,
                "offer_id": launch.offer_id,
                "goal_id": launch.goal_id,
                "channel_id": launch.channel_id,
                "status": launch.status,
            }
    payload["goals"] = [
        {"id": row.id, "title": row.title, "target": row.target, "metric": row.metric}
        for row in session.scalars(
            _scoped_select(GoalModel, scope).order_by(GoalModel.created_at, GoalModel.id)
        )
    ]
    payload["constraints"] = [
        {"id": row.id, "category": row.category, "rule": row.rule}
        for row in session.scalars(
            _scoped_select(ConstraintModel, scope).order_by(
                ConstraintModel.created_at,
                ConstraintModel.id,
            )
        )
    ]
    payload["products"] = [
        {"id": row.id, "name": row.name, "description": row.description}
        for row in session.scalars(
            _scoped_select(ProductModel, scope).order_by(ProductModel.created_at, ProductModel.id)
        )
    ]
    payload["offers"] = [
        {
            "id": row.id,
            "product_id": row.product_id,
            "name": row.name,
            "description": row.description,
            "price_descriptor": row.price_descriptor,
        }
        for row in session.scalars(
            _scoped_select(OfferModel, scope).order_by(OfferModel.created_at, OfferModel.id)
        )
    ]
    payload["channels"] = [
        {
            "id": row.id,
            "provider": row.provider,
            "handle": row.handle,
            "capabilities": row.capabilities,
        }
        for row in session.scalars(
            _scoped_select(ChannelModel, scope).order_by(ChannelModel.created_at, ChannelModel.id)
        )
    ]
    payload["claims"] = [
        {
            "id": row.id,
            "statement": row.statement,
            "status": row.status,
            "evidence_ids": row.evidence_ids,
        }
        for row in session.scalars(
            _scoped_select(ClaimModel, scope).order_by(ClaimModel.created_at, ClaimModel.id)
        )
    ]
    payload["hypotheses"] = [
        {
            "id": row.id,
            "statement": row.statement,
            "status": row.status,
            "model_confidence": row.model_confidence,
            "evidence_ids": row.evidence_ids,
        }
        for row in session.scalars(
            _scoped_select(HypothesisModel, scope).order_by(
                HypothesisModel.created_at,
                HypothesisModel.id,
            )
        )
    ]
    payload["information_needs"] = [
        {"id": row.id, "question": row.question, "critical": row.critical}
        for row in session.scalars(
            _scoped_select(InformationNeedModel, scope).order_by(
                InformationNeedModel.created_at,
                InformationNeedModel.id,
            )
        )
    ]
    evidence_rows = session.scalars(
        _scoped_select(EvidenceModel, scope).order_by(EvidenceModel.recorded_at, EvidenceModel.id)
    )
    for row in evidence_rows:
        item = {
            "id": row.id,
            "source_record_id": row.source_record_id,
            "statement": row.statement,
            "status": row.status,
            "confidence": row.confidence,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "recorded_at": row.recorded_at.isoformat(),
            "conflicts_with_evidence_ids": row.conflicts_with_evidence_ids,
        }
        payload["evidence"].append(item)
        if row.conflicts_with_evidence_ids:
            payload["conflicts"].append(
                {"evidence_id": row.id, "conflicts_with": row.conflicts_with_evidence_ids}
            )
    assert_no_secrets(payload)
    return payload


def _scoped_select(model_type: type[Any], scope: TenantScope) -> Select[Any]:
    model = cast(Any, model_type)
    return select(model_type).where(
        model.organization_id == scope.organization_id,
        model.business_id == scope.business_id,
    )


def _snapshot(
    session: Session,
    *,
    scope: TenantScope,
    snapshot_id: str | None,
) -> BusinessSnapshotModel:
    if snapshot_id is None:
        raise PermanentJobError("snapshot_id is required")
    snapshot = session.get(BusinessSnapshotModel, snapshot_id)
    if snapshot is None:
        raise PermanentJobError("BusinessSnapshot not found")
    scope.assert_matches(organization_id=snapshot.organization_id, business_id=snapshot.business_id)
    return snapshot


def _workflow_id(payload: Mapping[str, object]) -> str:
    if payload.get("payload_schema_version") != 1:
        raise PermanentJobError("workflow.advance payload_schema_version must be 1")
    workflow_id = payload.get("workflow_id")
    if not isinstance(workflow_id, str):
        raise PermanentJobError("workflow_id is required")
    return workflow_id


def _enqueue_workflow_advance(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    suffix: str,
) -> JobModel:
    job = create_job(
        session,
        scope=_scope(workflow),
        job_type=JOB_TYPE_WORKFLOW_ADVANCE,
        payload={"workflow_id": workflow.id, "payload_schema_version": 1},
        payload_schema_version=1,
        idempotency_key=f"decision_workflow:{workflow.id}:advance:{suffix}",
        clock=clock,
        max_attempts=5,
        correlation_id=workflow.correlation_id,
        causation_id=workflow.id,
    )
    queue.enqueue(job.id)
    return job


def _agent_run_by_idempotency(
    session: Session,
    workflow: DecisionWorkflowModel,
    idempotency_key: str,
) -> AgentRunModel:
    run = session.scalar(
        select(AgentRunModel).where(
            AgentRunModel.organization_id == workflow.organization_id,
            AgentRunModel.business_id == workflow.business_id,
            AgentRunModel.idempotency_key == idempotency_key,
        )
    )
    if run is None:
        raise TransientJobError(f"AgentRun is not created yet: {idempotency_key}")
    return run


def _specialist_contribution(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    contract_key: str,
) -> SpecialistContributionModel | None:
    return session.scalar(
        select(SpecialistContributionModel).where(
            SpecialistContributionModel.workflow_id == workflow.id,
            SpecialistContributionModel.contract_key == contract_key,
            SpecialistContributionModel.contract_version == 1,
        )
    )


def _specialist_contributions(
    session: Session,
    workflow: DecisionWorkflowModel,
) -> tuple[SpecialistContributionModel, ...]:
    return tuple(
        session.scalars(
            select(SpecialistContributionModel)
            .where(SpecialistContributionModel.workflow_id == workflow.id)
            .order_by(SpecialistContributionModel.contract_key)
        )
    )


def _latest_candidate(
    session: Session,
    workflow: DecisionWorkflowModel,
) -> DecisionCandidateModel:
    candidate = _latest_candidate_or_none(session, workflow)
    if candidate is None:
        raise TransientJobError("DecisionCandidate is not ready")
    return candidate


def _latest_candidate_or_none(
    session: Session,
    workflow: DecisionWorkflowModel,
) -> DecisionCandidateModel | None:
    return session.scalar(
        select(DecisionCandidateModel)
        .where(DecisionCandidateModel.workflow_id == workflow.id)
        .order_by(DecisionCandidateModel.version_number.desc())
        .limit(1)
    )


def _next_candidate_version(session: Session, workflow: DecisionWorkflowModel) -> int:
    value = session.scalar(
        select(func.max(DecisionCandidateModel.version_number)).where(
            DecisionCandidateModel.workflow_id == workflow.id
        )
    )
    return int(value or 0) + 1


def _controller_reviews(
    session: Session,
    candidate: DecisionCandidateModel,
) -> tuple[ControllerReviewModel, ...]:
    return tuple(
        session.scalars(
            select(ControllerReviewModel)
            .where(ControllerReviewModel.decision_candidate_id == candidate.id)
            .order_by(ControllerReviewModel.controller_type)
        )
    )


def _scope(workflow: DecisionWorkflowModel) -> TenantScope:
    return TenantScope(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )


def _required(run: AgentRunModel, field_name: str) -> str:
    value = getattr(run, field_name)
    if not isinstance(value, str) or not value:
        raise PermanentJobError(f"AgentRun missing required {field_name}")
    return value


def _definition_for_run(session: Session, run: AgentRunModel) -> AgentDefinitionModel:
    definition = session.get(AgentDefinitionModel, run.agent_definition_id)
    if definition is None:
        raise PermanentJobError("AgentRun missing AgentDefinition")
    return definition
