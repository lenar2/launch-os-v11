from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import ControllerVerdict, ExperimentStatus
from launch_os_v11.execution.contracts import ExecutionControllerType
from launch_os_v11.persistence.execution_models import (
    ActionProposalDetailModel,
    ConnectorAccountModel,
)
from launch_os_v11.persistence.models import ActionModel, AssetVersionModel, ExperimentModel
from launch_os_v11.persistence.phase6_models import CheckpointDefinitionModel
from launch_os_v11.persistence.production_models import (
    AssetRightsProvenanceModel,
    ProductionWorkflowModel,
)
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.errors import SecretRejectedError
from launch_os_v11.runtime.security import assert_no_secrets


@dataclass(frozen=True)
class DeterministicExecutionReview:
    controller_type: ExecutionControllerType
    verdict: ControllerVerdict
    reason: str
    conditions: tuple[str, ...] = ()


def evaluate_execution_controllers(
    session: Session,
    *,
    action: ActionModel,
    detail: ActionProposalDetailModel,
    account: ConnectorAccountModel,
    now: datetime,
) -> list[DeterministicExecutionReview]:
    return [
        _security_review(detail),
        _privacy_review(session, detail=detail, now=now),
        _platform_review(detail=detail, account=account),
        _execution_review(session, action=action, detail=detail),
        _cost_review(),
    ]


def reviews_pass(reviews: list[DeterministicExecutionReview]) -> bool:
    return all(review.verdict == ControllerVerdict.PASS for review in reviews)


def _security_review(detail: ActionProposalDetailModel) -> DeterministicExecutionReview:
    try:
        assert_no_secrets(detail.delivery_payload)
    except SecretRejectedError:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.SECURITY,
            verdict=ControllerVerdict.BLOCK,
            reason="Secret-like material is forbidden in execution payloads.",
        )
    return DeterministicExecutionReview(
        controller_type=ExecutionControllerType.SECURITY,
        verdict=ControllerVerdict.PASS,
        reason="Execution payload contains no secret-like material.",
    )


def _privacy_review(
    session: Session,
    *,
    detail: ActionProposalDetailModel,
    now: datetime,
) -> DeterministicExecutionReview:
    provenance = session.scalar(
        select(AssetRightsProvenanceModel).where(
            AssetRightsProvenanceModel.asset_version_id == detail.asset_version_id
        )
    )
    if provenance is None:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PRIVACY,
            verdict=ControllerVerdict.BLOCK,
            reason="Asset rights/provenance is required before public execution.",
        )
    if provenance.publication_restrictions:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PRIVACY,
            verdict=ControllerVerdict.BLOCK,
            reason="Asset has unresolved publication restrictions.",
        )
    if provenance.license_expires_at is not None and provenance.license_expires_at <= now:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PRIVACY,
            verdict=ControllerVerdict.BLOCK,
            reason="Asset license has expired.",
        )
    customer_content = bool(provenance.provenance.get("customer_content"))
    if customer_content and not provenance.customer_content_consent_ref:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PRIVACY,
            verdict=ControllerVerdict.BLOCK,
            reason="Customer content requires an explicit consent reference.",
        )
    return DeterministicExecutionReview(
        controller_type=ExecutionControllerType.PRIVACY,
        verdict=ControllerVerdict.PASS,
        reason="Rights/provenance permits public execution.",
    )


def _platform_review(
    *,
    detail: ActionProposalDetailModel,
    account: ConnectorAccountModel,
) -> DeterministicExecutionReview:
    text = detail.delivery_payload.get("text")
    if detail.provider != "telegram" or account.provider != "telegram":
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PLATFORM,
            verdict=ControllerVerdict.BLOCK,
            reason="Only Telegram text publication is supported in Phase 5/6.",
        )
    if not isinstance(text, str) or not text or len(text) > 4096:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PLATFORM,
            verdict=ControllerVerdict.BLOCK,
            reason="Telegram text must contain between 1 and 4096 characters.",
        )
    if (
        account.status != "READY"
        or not account.auth_healthy
        or not account.write_capability
        or account.capabilities.get("can_post_messages") is not True
    ):
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PLATFORM,
            verdict=ControllerVerdict.BLOCK,
            reason="Telegram connector is not ready for channel publication.",
        )
    if detail.target_chat_id != account.target_chat_id:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.PLATFORM,
            verdict=ControllerVerdict.BLOCK,
            reason="Action target does not match the governed connector target.",
        )
    return DeterministicExecutionReview(
        controller_type=ExecutionControllerType.PLATFORM,
        verdict=ControllerVerdict.PASS,
        reason="Telegram target and connector readiness are valid.",
    )


def _execution_review(
    session: Session,
    *,
    action: ActionModel,
    detail: ActionProposalDetailModel,
) -> DeterministicExecutionReview:
    workflow = session.get(ProductionWorkflowModel, detail.production_workflow_id)
    asset_version = session.get(AssetVersionModel, detail.asset_version_id)
    if workflow is None or asset_version is None:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.EXECUTION,
            verdict=ControllerVerdict.BLOCK,
            reason="Production provenance is incomplete.",
        )
    if workflow.status != ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.EXECUTION,
            verdict=ControllerVerdict.BLOCK,
            reason="Production workflow is not ready for an action proposal.",
        )
    if workflow.final_asset_version_id != asset_version.id:
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.EXECUTION,
            verdict=ControllerVerdict.BLOCK,
            reason="Action does not reference the final production asset version.",
        )
    if (
        action.target_object_type != "AssetVersion"
        or action.target_object_id != asset_version.asset_id
        or action.target_object_version_id != asset_version.id
        or action.target_object_version != asset_version.version_number
    ):
        return DeterministicExecutionReview(
            controller_type=ExecutionControllerType.EXECUTION,
            verdict=ControllerVerdict.BLOCK,
            reason="Action exact-version binding is invalid.",
        )
    experiment = session.scalar(
        select(ExperimentModel).where(ExperimentModel.decision_id == detail.decision_id)
    )
    if experiment is not None:
        if experiment.status != ExperimentStatus.DRAFT.value:
            return DeterministicExecutionReview(
                controller_type=ExecutionControllerType.EXECUTION,
                verdict=ControllerVerdict.BLOCK,
                reason=(
                    "Governed Experiment must be DRAFT "
                    "before first external execution."
                ),
            )
        checkpoint = session.scalar(
            select(CheckpointDefinitionModel).where(
                CheckpointDefinitionModel.experiment_id == experiment.id
            )
        )
        if checkpoint is None:
            return DeterministicExecutionReview(
                controller_type=ExecutionControllerType.EXECUTION,
                verdict=ControllerVerdict.BLOCK,
                reason="Governed Experiment is missing its pre-execution typed checkpoint.",
            )
        if (
            checkpoint.decision_id != detail.decision_id
            or checkpoint.metric_key != experiment.metric
        ):
            return DeterministicExecutionReview(
                controller_type=ExecutionControllerType.EXECUTION,
                verdict=ControllerVerdict.BLOCK,
                reason="Governed Experiment checkpoint binding is inconsistent.",
            )
    return DeterministicExecutionReview(
        controller_type=ExecutionControllerType.EXECUTION,
        verdict=ControllerVerdict.PASS,
        reason="Action is exact-bound to the current production-ready asset version.",
    )


def _cost_review() -> DeterministicExecutionReview:
    return DeterministicExecutionReview(
        controller_type=ExecutionControllerType.COST,
        verdict=ControllerVerdict.PASS,
        reason="This Phase 5/6 action contract creates no discretionary spend.",
    )
