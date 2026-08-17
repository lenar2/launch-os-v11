from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.contracts import AgentRunStatus
from launch_os_v11.application.decision_workflow import approval_matches_decision
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    ActionModel,
    AgentRunModel,
    AssetVersionModel,
    DecisionApprovalModel,
    DecisionModel,
    EvidenceModel,
    ExecutionModel,
    JobModel,
    PublicationModel,
)
from launch_os_v11.persistence.production_models import (
    AssetRightsProvenanceModel,
    ContentStrategyModel,
    ProductionWorkflowModel,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import JOB_TYPE_WORKFLOW_ADVANCE
from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.transport import JobQueue

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _assert_decision_binding(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> None:
    decision = _decision(session, workflow)
    if decision.version != workflow.decision_version:
        raise PermanentJobError("Decision version changed after production workflow start")
    if decision.status != "APPROVED_FOR_PRODUCTION":
        raise PermanentJobError("Decision approval is no longer production-eligible")
    approval = session.get(DecisionApprovalModel, workflow.decision_approval_id)
    if approval is None or not approval_matches_decision(approval, decision):
        raise PermanentJobError("production Decision approval is stale")
    superseding = session.scalar(
        select(DecisionModel.id).where(
            DecisionModel.organization_id == workflow.organization_id,
            DecisionModel.business_id == workflow.business_id,
            DecisionModel.supersedes_decision_id == decision.id,
        )
    )
    if superseding is not None:
        raise PermanentJobError("production cannot continue from superseded Decision")


def _validated_output(
    run: AgentRunModel,
    model_type: type[OutputModelT],
    label: str,
) -> OutputModelT:
    if run.status != AgentRunStatus.SUCCEEDED.value or run.output_data is None:
        if run.status in {
            AgentRunStatus.QUEUED.value,
            AgentRunStatus.RUNNING.value,
            AgentRunStatus.RETRY_WAIT.value,
        }:
            raise TransientJobError(f"{label} AgentRun is not ready")
        raise PermanentJobError(f"{label} AgentRun did not produce valid output")
    try:
        return model_type.model_validate(run.output_data)
    except ValidationError as exc:
        raise PermanentJobError(f"{label} output failed schema validation") from exc


def _validate_evidence_refs(
    session: Session,
    workflow: ProductionWorkflowModel,
    refs: Sequence[Any],
) -> None:
    for ref in refs:
        evidence = session.get(EvidenceModel, ref.evidence_id)
        if evidence is None:
            raise PermanentJobError(f"unknown evidence ref: {ref.evidence_id}")
        _scope(workflow).assert_matches(
            organization_id=evidence.organization_id,
            business_id=evidence.business_id,
        )
        if evidence.status != ref.epistemic_status.value:
            raise PermanentJobError("AI output cannot promote or rewrite evidence status")


def _agent_run_by_idempotency(
    session: Session,
    workflow: ProductionWorkflowModel,
    key: str,
) -> AgentRunModel:
    run = session.scalar(
        select(AgentRunModel).where(
            AgentRunModel.organization_id == workflow.organization_id,
            AgentRunModel.business_id == workflow.business_id,
            AgentRunModel.idempotency_key == key,
        )
    )
    if run is None:
        raise TransientJobError(f"AgentRun not created yet: {key}")
    return run


def _asset_version(
    session: Session,
    workflow: ProductionWorkflowModel,
    version_number: int,
) -> AssetVersionModel | None:
    if workflow.asset_id is None:
        return None
    return session.scalar(
        select(AssetVersionModel).where(
            AssetVersionModel.organization_id == workflow.organization_id,
            AssetVersionModel.business_id == workflow.business_id,
            AssetVersionModel.asset_id == workflow.asset_id,
            AssetVersionModel.version_number == version_number,
        )
    )


def _latest_asset_version(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> AssetVersionModel:
    if workflow.asset_id is None:
        raise PermanentJobError("ProductionWorkflow has no Asset")
    row = session.scalar(
        select(AssetVersionModel)
        .where(
            AssetVersionModel.organization_id == workflow.organization_id,
            AssetVersionModel.business_id == workflow.business_id,
            AssetVersionModel.asset_id == workflow.asset_id,
        )
        .order_by(AssetVersionModel.version_number.desc())
    )
    if row is None:
        raise PermanentJobError("ProductionWorkflow Asset has no version")
    return row


def _next_asset_version_number(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> int:
    if workflow.asset_id is None:
        return 1
    current = session.scalar(
        select(func.max(AssetVersionModel.version_number)).where(
            AssetVersionModel.organization_id == workflow.organization_id,
            AssetVersionModel.business_id == workflow.business_id,
            AssetVersionModel.asset_id == workflow.asset_id,
        )
    )
    return int(current or 0) + 1


def _rights_for_version(
    session: Session,
    asset_version_id: str,
) -> AssetRightsProvenanceModel | None:
    return session.scalar(
        select(AssetRightsProvenanceModel).where(
            AssetRightsProvenanceModel.asset_version_id == asset_version_id
        )
    )


def _strategy(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> ContentStrategyModel:
    strategy = session.scalar(
        select(ContentStrategyModel).where(
            ContentStrategyModel.workflow_id == workflow.id
        )
    )
    if strategy is None:
        raise PermanentJobError("ProductionWorkflow ContentStrategy not found")
    _scope(workflow).assert_matches(
        organization_id=strategy.organization_id,
        business_id=strategy.business_id,
    )
    return strategy


def _decision(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> DecisionModel:
    decision = session.get(DecisionModel, workflow.decision_id)
    if decision is None:
        raise PermanentJobError("ProductionWorkflow Decision not found")
    _scope(workflow).assert_matches(
        organization_id=decision.organization_id,
        business_id=decision.business_id,
    )
    return decision


def _scope(workflow: ProductionWorkflowModel) -> TenantScope:
    return TenantScope(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )


def _enqueue_advance(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    suffix: str,
) -> str:
    job = create_job(
        session,
        scope=_scope(workflow),
        job_type=JOB_TYPE_WORKFLOW_ADVANCE,
        payload={
            "payload_schema_version": 1,
            "production_workflow_id": workflow.id,
        },
        payload_schema_version=1,
        idempotency_key=f"production_workflow:{workflow.id}:advance:{suffix}",
        clock=clock,
        max_attempts=20,
        correlation_id=workflow.correlation_id,
        causation_id=workflow.id,
    )
    session.flush()
    queue.enqueue(job.id)
    return job.id


def _workflow_job(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> JobModel | None:
    return session.scalar(
        select(JobModel)
        .where(
            JobModel.organization_id == workflow.organization_id,
            JobModel.business_id == workflow.business_id,
            JobModel.job_type == JOB_TYPE_WORKFLOW_ADVANCE,
            JobModel.idempotency_key
            == f"production_workflow:{workflow.id}:advance:start",
        )
        .order_by(JobModel.created_at)
    )


def assert_phase4_no_external_execution(session: Session, scope: TenantScope) -> None:
    for model in (ActionModel, PublicationModel, ExecutionModel):
        count = session.scalar(
            select(func.count()).select_from(model).where(
                model.organization_id == scope.organization_id,
                model.business_id == scope.business_id,
            )
        )
        if count:
            raise PermanentJobError("Phase 4 must not create external execution objects")
