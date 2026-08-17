from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.application.decision_workflow import (
    DECISION_APPROVAL_ACTION,
    approval_matches_decision,
)
from launch_os_v11.domain.enums import ApprovalStatus
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    DecisionApprovalModel,
    DecisionModel,
    DecisionWorkflowModel,
)
from launch_os_v11.persistence.production_models import ProductionWorkflowModel
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.production.support import _enqueue_advance, _workflow_job
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.transport import JobQueue


@dataclass(frozen=True)
class ProductionWorkflowStartResult:
    workflow: ProductionWorkflowModel
    job_id: str
    created: bool


def start_production_workflow(
    session: Session,
    *,
    scope: TenantScope,
    queue: JobQueue,
    clock: Clock,
    decision_id: str,
    max_revision_rounds: int = 2,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> ProductionWorkflowStartResult:
    if max_revision_rounds < 0:
        raise PermanentJobError("max_revision_rounds cannot be negative")
    decision = session.get(DecisionModel, decision_id)
    if decision is None:
        raise PermanentJobError("Decision not found")
    scope.assert_matches(
        organization_id=decision.organization_id,
        business_id=decision.business_id,
    )
    if decision.status != "APPROVED_FOR_PRODUCTION":
        raise PermanentJobError("production requires APPROVED_FOR_PRODUCTION Decision")
    if decision.snapshot_id is None:
        raise PermanentJobError("approved Decision must retain immutable BusinessSnapshot")
    if session.scalar(
        select(DecisionModel.id).where(
            DecisionModel.organization_id == scope.organization_id,
            DecisionModel.business_id == scope.business_id,
            DecisionModel.supersedes_decision_id == decision.id,
        )
    ) is not None:
        raise PermanentJobError("superseded Decision cannot start production")

    approval = session.scalar(
        select(DecisionApprovalModel)
        .where(
            DecisionApprovalModel.organization_id == scope.organization_id,
            DecisionApprovalModel.business_id == scope.business_id,
            DecisionApprovalModel.decision_id == decision.id,
            DecisionApprovalModel.action_type == DECISION_APPROVAL_ACTION,
            DecisionApprovalModel.status == ApprovalStatus.APPROVED.value,
        )
        .order_by(DecisionApprovalModel.created_at.desc())
    )
    if approval is None or not approval_matches_decision(approval, decision):
        raise PermanentJobError("exact-version Decision approval is required")

    existing = session.scalar(
        select(ProductionWorkflowModel).where(
            ProductionWorkflowModel.organization_id == scope.organization_id,
            ProductionWorkflowModel.business_id == scope.business_id,
            ProductionWorkflowModel.decision_id == decision.id,
            ProductionWorkflowModel.decision_version == decision.version,
        )
    )
    if existing is not None:
        job = _workflow_job(session, existing)
        if job is None:
            raise PermanentJobError("idempotent ProductionWorkflow exists without workflow Job")
        return ProductionWorkflowStartResult(
            workflow=existing,
            job_id=job.id,
            created=False,
        )

    decision_workflow = session.scalar(
        select(DecisionWorkflowModel).where(
            DecisionWorkflowModel.organization_id == scope.organization_id,
            DecisionWorkflowModel.business_id == scope.business_id,
            DecisionWorkflowModel.final_decision_id == decision.id,
        )
    )
    workflow = ProductionWorkflowModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=decision.id,
        decision_version=decision.version,
        decision_approval_id=approval.id,
        snapshot_id=decision.snapshot_id,
        launch_id=decision_workflow.launch_id if decision_workflow is not None else None,
        status=ProductionWorkflowStatus.DECISION_APPROVAL_VERIFIED.value,
        revision_count=0,
        max_revision_rounds=max_revision_rounds,
        creative_brief_id=None,
        asset_id=None,
        final_asset_version_id=None,
        correlation_id=correlation_id,
        causation_id=causation_id or decision.id,
        created_at=clock.now(),
        updated_at=clock.now(),
        version=1,
    )
    session.add(workflow)
    session.flush()
    job_id = _enqueue_advance(
        session,
        workflow=workflow,
        queue=queue,
        clock=clock,
        suffix="start",
    )
    return ProductionWorkflowStartResult(
        workflow=workflow,
        job_id=job_id,
        created=True,
    )
