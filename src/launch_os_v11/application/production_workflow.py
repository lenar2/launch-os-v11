from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.persistence.production_models import ProductionWorkflowModel
from launch_os_v11.production.governance import governed_asset_outcome
from launch_os_v11.production.materialization import (
    _materialize_asset_reviews,
    _materialize_asset_version,
    _materialize_content_strategy,
    _materialize_creative_brief,
)
from launch_os_v11.production.runs import (
    _ensure_asset_controller_runs,
    _ensure_content_strategy_run,
    _ensure_writer_run,
)
from launch_os_v11.production.start import start_production_workflow
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.production.support import (
    _assert_decision_binding,
    _enqueue_advance,
    _latest_asset_version,
    _next_asset_version_number,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets
from launch_os_v11.runtime.transport import JobQueue

__all__ = [
    "ProductionWorkflowAdvanceHandler",
    "ProductionWorkflowStatus",
    "start_production_workflow",
]


class ProductionWorkflowAdvanceHandler:
    def __init__(self, *, registry: AgentRegistry, queue: JobQueue) -> None:
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
        assert_no_secrets(dict(payload))
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("production workflow payload_schema_version must be 1")
        workflow_id = payload.get("production_workflow_id")
        if not isinstance(workflow_id, str):
            raise PermanentJobError("production_workflow_id is required")
        workflow = session.get(ProductionWorkflowModel, workflow_id)
        if workflow is None:
            raise PermanentJobError(f"ProductionWorkflow not found: {workflow_id}")
        context.scope.assert_matches(
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
        )
        _advance_production_workflow(
            session,
            workflow=workflow,
            queue=self._queue,
            clock=clock,
            registry=self._registry,
        )


def _advance_production_workflow(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    _assert_decision_binding(session, workflow)
    status = ProductionWorkflowStatus(workflow.status)
    if status == ProductionWorkflowStatus.DECISION_APPROVAL_VERIFIED:
        _ensure_content_strategy_run(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        workflow.status = ProductionWorkflowStatus.CONTENT_STRATEGY_RUNNING.value
        _enqueue_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix="after-content-strategy",
        )
        return

    if status == ProductionWorkflowStatus.CONTENT_STRATEGY_RUNNING:
        strategy = _materialize_content_strategy(session, workflow)
        workflow.status = ProductionWorkflowStatus.CONTENT_STRATEGY_READY.value
        brief = _materialize_creative_brief(session, workflow, strategy)
        workflow.creative_brief_id = brief.id
        workflow.status = ProductionWorkflowStatus.BRIEF_READY.value
        _ensure_writer_run(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        workflow.status = ProductionWorkflowStatus.PRODUCTION_RUNNING.value
        _enqueue_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix=f"after-writer:{_next_asset_version_number(session, workflow)}",
        )
        return

    if status == ProductionWorkflowStatus.PRODUCTION_RUNNING:
        asset_version = _materialize_asset_version(session, workflow)
        workflow.final_asset_version_id = asset_version.id
        workflow.status = ProductionWorkflowStatus.ASSET_VERSION_READY.value
        _ensure_asset_controller_runs(
            session,
            workflow=workflow,
            asset_version=asset_version,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        workflow.status = ProductionWorkflowStatus.ASSET_CONTROLLERS_RUNNING.value
        _enqueue_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix=f"after-asset-controllers:{asset_version.version_number}",
        )
        return

    if status == ProductionWorkflowStatus.ASSET_CONTROLLERS_RUNNING:
        asset_version = _latest_asset_version(session, workflow)
        reviews = _materialize_asset_reviews(
            session,
            workflow=workflow,
            asset_version=asset_version,
        )
        outcome = governed_asset_outcome(
            session,
            workflow=workflow,
            asset_version=asset_version,
            reviews=reviews,
        )
        if outcome == ControllerVerdict.BLOCK:
            workflow.status = ProductionWorkflowStatus.BLOCKED.value
            session.flush()
            return
        if outcome in {ControllerVerdict.REVISE, ControllerVerdict.PASS_WITH_CONDITIONS}:
            if workflow.revision_count >= workflow.max_revision_rounds:
                workflow.status = ProductionWorkflowStatus.ESCALATED.value
                session.flush()
                return
            workflow.revision_count += 1
            workflow.status = ProductionWorkflowStatus.REVISION_REQUIRED.value
            _ensure_writer_run(
                session,
                workflow=workflow,
                queue=queue,
                clock=clock,
                registry=registry,
                previous_version=asset_version,
                reviews=reviews,
            )
            workflow.status = ProductionWorkflowStatus.PRODUCTION_RUNNING.value
            _enqueue_advance(
                session,
                workflow=workflow,
                queue=queue,
                clock=clock,
                suffix=f"after-writer:{_next_asset_version_number(session, workflow)}",
            )
            return
        workflow.status = ProductionWorkflowStatus.PRODUCTION_READY.value
        workflow.final_asset_version_id = asset_version.id
        workflow.status = ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value
        session.flush()
        return
