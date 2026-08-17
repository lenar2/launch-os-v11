from __future__ import annotations

from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.context import ContextReference
from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.ai_runtime.service import AgentRunService
from launch_os_v11.persistence.models import AssetVersionModel
from launch_os_v11.persistence.production_models import AssetReviewModel, ProductionWorkflowModel
from launch_os_v11.production.registry import (
    CONTENT_DIRECTOR_CONTRACT_KEY,
    REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS,
    TELEGRAM_WRITER_CONTRACT_KEY,
)
from launch_os_v11.production.support import (
    _decision,
    _next_asset_version_number,
    _rights_for_version,
    _scope,
    _strategy,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import JOB_TYPE_AI_RUN_AGENT, JOB_TYPE_AI_RUN_CONTROLLER
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.transport import JobQueue


def _ensure_content_strategy_run(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    service.create_agent_run(
        session,
        scope=_scope(workflow),
        contract_key=CONTENT_DIRECTOR_CONTRACT_KEY,
        contract_version=1,
        input_ref=f"production_workflow:{workflow.id}:content_strategy",
        context_refs=(
            ContextReference(object_type="business_snapshot", object_id=workflow.snapshot_id),
            ContextReference(object_type="decision", object_id=workflow.decision_id),
            *tuple(
                ContextReference(object_type="evidence", object_id=evidence_id)
                for evidence_id in _decision(session, workflow).evidence_ids
            ),
        ),
        correlation_id=workflow.correlation_id,
        causation_id=workflow.decision_id,
        job_type=JOB_TYPE_AI_RUN_AGENT,
        idempotency_key=f"production_workflow:{workflow.id}:content_strategy",
    )


def _ensure_writer_run(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
    previous_version: AssetVersionModel | None = None,
    reviews: tuple[AssetReviewModel, ...] = (),
) -> None:
    if workflow.creative_brief_id is None:
        raise PermanentJobError("CreativeBrief must exist before writing")
    strategy = _strategy(session, workflow)
    version = _next_asset_version_number(session, workflow)
    refs = [
        ContextReference(object_type="business_snapshot", object_id=workflow.snapshot_id),
        ContextReference(object_type="decision", object_id=workflow.decision_id),
        *[
            ContextReference(object_type="evidence", object_id=evidence_id)
            for evidence_id in _decision(session, workflow).evidence_ids
        ],
        ContextReference(
            object_type="content_strategy",
            object_id=strategy.id,
        ),
        ContextReference(
            object_type="creative_brief",
            object_id=workflow.creative_brief_id,
        ),
    ]
    if previous_version is not None:
        refs.append(
            ContextReference(object_type="asset_version", object_id=previous_version.id)
        )
    refs.extend(
        ContextReference(object_type="asset_review", object_id=review.id)
        for review in reviews
    )
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    service.create_agent_run(
        session,
        scope=_scope(workflow),
        contract_key=TELEGRAM_WRITER_CONTRACT_KEY,
        contract_version=1,
        input_ref=f"production_workflow:{workflow.id}:asset:v{version}",
        context_refs=tuple(refs),
        correlation_id=workflow.correlation_id,
        causation_id=previous_version.id if previous_version is not None else workflow.id,
        job_type=JOB_TYPE_AI_RUN_AGENT,
        idempotency_key=f"production_workflow:{workflow.id}:asset:v{version}",
    )


def _ensure_asset_controller_runs(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    asset_version: AssetVersionModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    if workflow.creative_brief_id is None:
        raise PermanentJobError("CreativeBrief missing before asset review")
    rights = _rights_for_version(session, asset_version.id)
    if rights is None:
        raise PermanentJobError("asset rights provenance must exist before review")
    refs = (
        ContextReference(object_type="business_snapshot", object_id=workflow.snapshot_id),
        ContextReference(object_type="decision", object_id=workflow.decision_id),
        *tuple(
            ContextReference(object_type="evidence", object_id=evidence_id)
            for evidence_id in _decision(session, workflow).evidence_ids
        ),
        ContextReference(object_type="creative_brief", object_id=workflow.creative_brief_id),
        ContextReference(object_type="asset_version", object_id=asset_version.id),
        ContextReference(object_type="asset_rights_provenance", object_id=rights.id),
    )
    service = AgentRunService(registry=registry, queue=queue, clock=clock)
    for contract_key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS:
        service.create_agent_run(
            session,
            scope=_scope(workflow),
            contract_key=contract_key,
            contract_version=1,
            input_ref=(
                f"production_workflow:{workflow.id}:asset:"
                f"{asset_version.version_number}:{contract_key}"
            ),
            context_refs=refs,
            correlation_id=workflow.correlation_id,
            causation_id=asset_version.id,
            job_type=JOB_TYPE_AI_RUN_CONTROLLER,
            idempotency_key=(
                f"production_workflow:{workflow.id}:asset:"
                f"{asset_version.version_number}:{contract_key}"
            ),
        )
