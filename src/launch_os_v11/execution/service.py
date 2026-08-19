from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    ExecutionStatus,
    ExperimentStatus,
    OutboxStatus,
    PermissionMode,
    PublicationStatus,
)
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.execution.contracts import (
    TELEGRAM_PUBLISH_ACTION,
    TELEGRAM_SECRET_REF,
    PermissionOutcome,
    TelegramAmbiguousOutcome,
    TelegramConnector,
    TelegramConnectorRejected,
    TelegramPublishTextCommand,
)
from launch_os_v11.execution.governance import (
    DeterministicExecutionReview,
    evaluate_execution_controllers,
    reviews_pass,
)
from launch_os_v11.persistence.execution_models import (
    ActionProposalDetailModel,
    ConnectorAccountModel,
    ExecutionControllerReviewModel,
    ExternalReferenceModel,
    GlobalExecutionControlModel,
    PermissionEvaluationModel,
    PublicationExecutionLinkModel,
)
from launch_os_v11.persistence.models import (
    ActionModel,
    ApprovalModel,
    AssetVersionModel,
    AuditLogModel,
    BusinessMembershipModel,
    ChannelModel,
    ExecutionModel,
    ExperimentModel,
    OutboxEventModel,
    PermissionPolicyModel,
    PublicationModel,
)
from launch_os_v11.persistence.production_models import ProductionWorkflowModel
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
    RuntimeJobContext,
)
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.security import assert_no_secrets
from launch_os_v11.runtime.transport import JobQueue


@dataclass(frozen=True)
class ActionProposalResult:
    action: ActionModel
    detail: ActionProposalDetailModel
    permission: PermissionEvaluationModel
    created: bool


@dataclass(frozen=True)
class ApprovalExecutionResult:
    approval: ApprovalModel
    execution: ExecutionModel
    job_id: str
    created: bool


def probe_and_register_telegram_connector(
    session: Session,
    *,
    scope: TenantScope,
    channel_id: str,
    target_chat_id: str,
    connector: TelegramConnector,
    clock: Clock,
    secret_ref: str = TELEGRAM_SECRET_REF,
) -> ConnectorAccountModel:
    channel = _channel_for_scope(session, scope=scope, channel_id=channel_id)
    if channel.provider != "telegram":
        raise PermanentJobError("Phase 5 connector registration requires a Telegram channel")
    readiness = connector.check_readiness(chat_id=target_chat_id)
    existing = session.scalar(
        select(ConnectorAccountModel).where(
            ConnectorAccountModel.business_id == scope.business_id,
            ConnectorAccountModel.channel_id == channel_id,
            ConnectorAccountModel.provider == "telegram",
        )
    )
    account = existing or ConnectorAccountModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        channel_id=channel_id,
        provider="telegram",
        secret_ref=secret_ref,
        target_chat_id=target_chat_id,
        status="UNAVAILABLE",
        auth_healthy=False,
        write_capability=False,
        capabilities={},
        last_checked_at=clock.now(),
        last_error_class=None,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    account.secret_ref = secret_ref
    account.target_chat_id = target_chat_id
    account.auth_healthy = readiness.auth_healthy
    account.write_capability = readiness.write_capability
    account.capabilities = dict(readiness.capabilities)
    account.status = (
        "READY"
        if readiness.auth_healthy and readiness.write_capability
        else "UNAVAILABLE"
    )
    account.last_checked_at = clock.now()
    account.last_error_class = readiness.error_class
    account.updated_at = clock.now()
    if existing is None:
        session.add(account)
    session.flush()
    return account


def ensure_default_telegram_permission_policy(
    session: Session,
    *,
    scope: TenantScope,
) -> PermissionPolicyModel:
    existing = session.scalar(
        select(PermissionPolicyModel).where(
            PermissionPolicyModel.organization_id == scope.organization_id,
            PermissionPolicyModel.business_id == scope.business_id,
            PermissionPolicyModel.action_type == TELEGRAM_PUBLISH_ACTION,
        )
    )
    if existing is not None:
        return existing
    policy = PermissionPolicyModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_type=TELEGRAM_PUBLISH_ACTION,
        mode=PermissionMode.EXECUTE_AFTER_APPROVAL.value,
        requires_approval=True,
        public_visibility=True,
        version=1,
    )
    session.add(policy)
    session.flush()
    return policy


def create_action_proposal(
    session: Session,
    *,
    scope: TenantScope,
    production_workflow_id: str,
    connector_account_id: str,
    clock: Clock,
    correlation_id: str | None = None,
) -> ActionProposalResult:
    workflow = session.get(ProductionWorkflowModel, production_workflow_id)
    if workflow is None:
        raise PermanentJobError(f"ProductionWorkflow not found: {production_workflow_id}")
    scope.assert_matches(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )
    if workflow.status != ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value:
        raise PermanentJobError("production workflow is not ready for an action proposal")
    if workflow.final_asset_version_id is None:
        raise PermanentJobError("production workflow has no final asset version")
    asset_version = session.get(AssetVersionModel, workflow.final_asset_version_id)
    if asset_version is None:
        raise PermanentJobError("final AssetVersion not found")
    scope.assert_matches(
        organization_id=asset_version.organization_id,
        business_id=asset_version.business_id,
    )
    account = session.get(ConnectorAccountModel, connector_account_id)
    if account is None:
        raise PermanentJobError(f"ConnectorAccount not found: {connector_account_id}")
    scope.assert_matches(
        organization_id=account.organization_id,
        business_id=account.business_id,
    )

    payload: dict[str, object] = {
        "text": asset_version.body,
        "disable_notification": False,
        "protect_content": False,
    }
    assert_no_secrets(payload)
    payload_hash = _payload_hash(payload)
    idempotency_key = _action_idempotency_key(
        production_workflow_id=workflow.id,
        asset_version_id=asset_version.id,
        connector_account_id=account.id,
        target_chat_id=account.target_chat_id,
        payload_hash=payload_hash,
    )
    existing = session.scalar(
        select(ActionModel).where(ActionModel.idempotency_key == idempotency_key)
    )
    if existing is not None:
        detail = _action_detail(session, existing.id)
        permission = _permission_evaluation(session, existing.id)
        return ActionProposalResult(
            action=existing,
            detail=detail,
            permission=permission,
            created=False,
        )

    action = ActionModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_type=TELEGRAM_PUBLISH_ACTION,
        target_object_type="AssetVersion",
        target_object_id=asset_version.asset_id,
        target_object_version_id=asset_version.id,
        target_object_version=asset_version.version_number,
        status=ActionStatus.PROPOSED.value,
        idempotency_key=idempotency_key,
        version=1,
    )
    session.add(action)
    session.flush()
    detail = ActionProposalDetailModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_id=action.id,
        production_workflow_id=workflow.id,
        decision_id=workflow.decision_id,
        asset_version_id=asset_version.id,
        provider="telegram",
        channel_id=account.channel_id,
        connector_account_id=account.id,
        target_chat_id=account.target_chat_id,
        delivery_payload=payload,
        delivery_payload_hash=payload_hash,
        correlation_id=correlation_id,
        causation_id=workflow.id,
        created_at=clock.now(),
    )
    session.add(detail)
    session.flush()

    reviews = evaluate_execution_controllers(
        session,
        action=action,
        detail=detail,
        account=account,
        now=clock.now(),
    )
    _materialize_reviews(
        session,
        scope=scope,
        action=action,
        reviews=reviews,
        clock=clock,
    )
    policy = ensure_default_telegram_permission_policy(session, scope=scope)
    permission = _evaluate_permission(
        session,
        scope=scope,
        action=action,
        policy=policy,
        reviews=reviews,
        clock=clock,
    )
    action.status = (
        ActionStatus.BLOCKED.value
        if permission.outcome == PermissionOutcome.BLOCKED.value
        else ActionStatus.APPROVAL_REQUIRED.value
    )
    _audit(
        session,
        scope=scope,
        action="ACTION_PROPOSED",
        object_type="ActionProposal",
        object_id=action.id,
        payload={
            "action_type": action.action_type,
            "asset_version_id": asset_version.id,
            "asset_version": asset_version.version_number,
            "connector_account_id": account.id,
            "delivery_payload_hash": payload_hash,
        },
        actor_user_id=None,
        correlation_id=correlation_id or action.id,
        causation_id=workflow.id,
    )
    _audit(
        session,
        scope=scope,
        action="PERMISSION_EVALUATED",
        object_type="ActionProposal",
        object_id=action.id,
        payload={"outcome": permission.outcome},
        actor_user_id=None,
        correlation_id=correlation_id or action.id,
        causation_id=action.id,
    )
    session.flush()
    return ActionProposalResult(
        action=action,
        detail=detail,
        permission=permission,
        created=True,
    )


def approve_action_proposal(
    session: Session,
    *,
    scope: TenantScope,
    action_id: str,
    approved_by_user_id: str,
    queue: JobQueue,
    clock: Clock,
) -> ApprovalExecutionResult:
    action = session.get(ActionModel, action_id)
    if action is None:
        raise PermanentJobError(f"ActionProposal not found: {action_id}")
    scope.assert_matches(
        organization_id=action.organization_id,
        business_id=action.business_id,
    )
    _assert_owner(session, scope=scope, user_id=approved_by_user_id)
    if action.status not in {
        ActionStatus.APPROVAL_REQUIRED.value,
        ActionStatus.APPROVED.value,
    }:
        raise PermanentJobError("ActionProposal is not approval-eligible")
    detail = _action_detail(session, action.id)
    permission = _permission_evaluation(session, action.id)
    if permission.outcome != PermissionOutcome.APPROVAL_REQUIRED.value:
        raise PermanentJobError("Permission Engine did not require owner approval")
    _assert_current_action_binding(session, action=action, detail=detail)

    approval = session.scalar(
        select(ApprovalModel).where(
            ApprovalModel.action_id == action.id,
            ApprovalModel.action_type == action.action_type,
            ApprovalModel.object_version_id == action.target_object_version_id,
            ApprovalModel.status == ApprovalStatus.APPROVED.value,
        )
    )
    created = approval is None
    if approval is None:
        approval = ApprovalModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            action_id=action.id,
            action_type=action.action_type,
            object_type=action.target_object_type,
            object_id=action.target_object_id,
            object_version_id=action.target_object_version_id,
            object_version=action.target_object_version,
            approved_by_user_id=approved_by_user_id,
            status=ApprovalStatus.APPROVED.value,
            created_at=clock.now(),
        )
        session.add(approval)
        session.flush()
        _audit(
            session,
            scope=scope,
            action="ACTION_APPROVED",
            object_type="ActionProposal",
            object_id=action.id,
            payload={
                "approval_id": approval.id,
                "asset_version_id": action.target_object_version_id,
                "asset_version": action.target_object_version,
            },
            actor_user_id=approved_by_user_id,
            correlation_id=detail.correlation_id or action.id,
            causation_id=action.id,
        )

    action.status = ActionStatus.APPROVED.value
    execution = session.scalar(
        select(ExecutionModel).where(ExecutionModel.action_id == action.id)
    )
    if execution is None:
        execution = ExecutionModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            action_id=action.id,
            approval_id=approval.id,
            status=ExecutionStatus.PENDING.value,
            idempotency_key=f"execution:{action.id}",
            external_reference=None,
            version=1,
        )
        session.add(execution)
        session.flush()

    job = create_job(
        session,
        scope=scope,
        job_type=JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
        payload={
            "payload_schema_version": 1,
            "action_id": action.id,
            "execution_id": execution.id,
        },
        payload_schema_version=1,
        idempotency_key=f"telegram-execution:{execution.id}",
        clock=clock,
        max_attempts=1,
        correlation_id=detail.correlation_id or action.id,
        causation_id=approval.id,
    )
    queue.enqueue(job.id)
    session.flush()
    return ApprovalExecutionResult(
        approval=approval,
        execution=execution,
        job_id=job.id,
        created=created,
    )


def set_global_execution_controls(
    session: Session,
    *,
    scope: TenantScope,
    updated_by_user_id: str,
    clock: Clock,
    automation_paused: bool | None = None,
    execution_paused: bool | None = None,
    revoke_all_write_capabilities: bool | None = None,
) -> GlobalExecutionControlModel:
    _assert_owner(session, scope=scope, user_id=updated_by_user_id)
    control = session.scalar(
        select(GlobalExecutionControlModel).where(
            GlobalExecutionControlModel.business_id == scope.business_id
        )
    )
    if control is None:
        control = GlobalExecutionControlModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            automation_paused=False,
            execution_paused=False,
            revoke_all_write_capabilities=False,
            updated_by_user_id=updated_by_user_id,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add(control)
    if automation_paused is not None:
        control.automation_paused = automation_paused
    if execution_paused is not None:
        control.execution_paused = execution_paused
    if revoke_all_write_capabilities is not None:
        control.revoke_all_write_capabilities = revoke_all_write_capabilities
    control.updated_by_user_id = updated_by_user_id
    control.updated_at = clock.now()
    session.flush()
    return control


class TelegramExecutionHandler:
    def __init__(self, *, connector: TelegramConnector) -> None:
        self._connector = connector

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        payload_data = dict(payload)
        assert_no_secrets(payload_data)
        if payload_data.get("payload_schema_version") != 1:
            raise PermanentJobError("Telegram execution payload_schema_version must be 1")
        action_id = payload_data.get("action_id")
        execution_id = payload_data.get("execution_id")
        if not isinstance(action_id, str) or not isinstance(execution_id, str):
            raise PermanentJobError("action_id and execution_id are required")

        action = session.get(ActionModel, action_id)
        execution = session.get(ExecutionModel, execution_id)
        if action is None or execution is None:
            raise PermanentJobError("ActionProposal or Execution not found")
        context.scope.assert_matches(
            organization_id=action.organization_id,
            business_id=action.business_id,
        )
        context.scope.assert_matches(
            organization_id=execution.organization_id,
            business_id=execution.business_id,
        )
        if execution.action_id != action.id:
            raise PermanentJobError("Execution is not bound to ActionProposal")
        if execution.status in {
            ExecutionStatus.SUCCEEDED.value,
            ExecutionStatus.UNKNOWN_EXTERNAL_OUTCOME.value,
        }:
            return

        detail = _action_detail(session, action.id)
        approval = _execution_approval(session, execution)
        account = session.get(ConnectorAccountModel, detail.connector_account_id)
        if account is None:
            raise PermanentJobError("ConnectorAccount not found during execution")

        block_reason = _preflight_block_reason(
            session,
            action=action,
            detail=detail,
            approval=approval,
            account=account,
        )
        if block_reason is not None:
            execution.status = ExecutionStatus.BLOCKED.value
            action.status = ActionStatus.BLOCKED.value
            _audit(
                session,
                scope=context.scope,
                action="EXECUTION_BLOCKED",
                object_type="Execution",
                object_id=execution.id,
                payload={"reason": block_reason},
                actor_user_id=None,
                correlation_id=detail.correlation_id or action.id,
                causation_id=approval.id,
            )
            session.flush()
            return

        existing_reference = session.scalar(
            select(ExternalReferenceModel).where(
                ExternalReferenceModel.execution_id == execution.id
            )
        )
        if existing_reference is not None:
            execution.status = ExecutionStatus.SUCCEEDED.value
            execution.external_reference = existing_reference.external_id
            action.status = ActionStatus.EXECUTED.value
            session.flush()
            return

        text = detail.delivery_payload.get("text")
        if not isinstance(text, str):
            raise PermanentJobError("governed Telegram text payload is invalid")
        command = TelegramPublishTextCommand(
            chat_id=detail.target_chat_id,
            text=text,
            disable_notification=bool(
                detail.delivery_payload.get("disable_notification", False)
            ),
            protect_content=bool(detail.delivery_payload.get("protect_content", False)),
        )
        execution.status = ExecutionStatus.RUNNING.value
        _audit(
            session,
            scope=context.scope,
            action="EXECUTION_STARTED",
            object_type="Execution",
            object_id=execution.id,
            payload={
                "provider": "telegram",
                "action_id": action.id,
                "delivery_payload_hash": detail.delivery_payload_hash,
            },
            actor_user_id=None,
            correlation_id=detail.correlation_id or action.id,
            causation_id=approval.id,
        )
        session.flush()

        try:
            result = self._connector.publish_text(command)
        except TelegramAmbiguousOutcome as error:
            execution.status = ExecutionStatus.UNKNOWN_EXTERNAL_OUTCOME.value
            _audit(
                session,
                scope=context.scope,
                action="EXECUTION_UNKNOWN_EXTERNAL_OUTCOME",
                object_type="Execution",
                object_id=execution.id,
                payload={"error_class": str(error)},
                actor_user_id=None,
                correlation_id=detail.correlation_id or action.id,
                causation_id=approval.id,
            )
            session.flush()
            return
        except TelegramConnectorRejected as error:
            execution.status = ExecutionStatus.FAILED.value
            action.status = ActionStatus.BLOCKED.value
            _audit(
                session,
                scope=context.scope,
                action="EXECUTION_FAILED_SAFE",
                object_type="Execution",
                object_id=execution.id,
                payload={"error_class": str(error)},
                actor_user_id=None,
                correlation_id=detail.correlation_id or action.id,
                causation_id=approval.id,
            )
            session.flush()
            return

        publication = PublicationModel(
            id=new_id(),
            organization_id=context.organization_id,
            business_id=context.business_id,
            asset_version_id=detail.asset_version_id,
            channel_id=detail.channel_id,
            status=PublicationStatus.PUBLISHED.value,
            scheduled_at=None,
            published_at=clock.now(),
            version=1,
        )
        session.add(publication)
        session.flush()
        external_reference = ExternalReferenceModel(
            id=new_id(),
            organization_id=context.organization_id,
            business_id=context.business_id,
            provider="telegram",
            connector_account_id=account.id,
            channel_id=detail.channel_id,
            external_object_type="message",
            external_id=result.message_id,
            external_parent_id=result.chat_id,
            action_id=action.id,
            execution_id=execution.id,
            created_at=clock.now(),
        )
        session.add(external_reference)
        session.flush()
        session.add(
            PublicationExecutionLinkModel(
                id=new_id(),
                organization_id=context.organization_id,
                business_id=context.business_id,
                publication_id=publication.id,
                action_id=action.id,
                execution_id=execution.id,
                external_reference_id=external_reference.id,
                created_at=clock.now(),
            )
        )
        experiment = session.scalar(
            select(ExperimentModel).where(
                ExperimentModel.decision_id == detail.decision_id
            )
        )
        if experiment is not None:
            experiment.status = ExperimentStatus.RUNNING.value
            _audit(
                session,
                scope=context.scope,
                action="EXPERIMENT_STARTED",
                object_type="Experiment",
                object_id=experiment.id,
                payload={
                    "publication_id": publication.id,
                    "action_id": action.id,
                },
                actor_user_id=None,
                correlation_id=detail.correlation_id or action.id,
                causation_id=execution.id,
            )

        execution.status = ExecutionStatus.SUCCEEDED.value
        execution.external_reference = result.message_id
        action.status = ActionStatus.EXECUTED.value
        _audit(
            session,
            scope=context.scope,
            action="EXECUTION_SUCCEEDED",
            object_type="Execution",
            object_id=execution.id,
            payload={
                "provider": "telegram",
                "publication_id": publication.id,
                "external_reference_id": external_reference.id,
            },
            actor_user_id=None,
            correlation_id=detail.correlation_id or action.id,
            causation_id=approval.id,
        )
        _outbox(
            session,
            scope=context.scope,
            event_type="telegram.publication.executed",
            aggregate_type="Publication",
            aggregate_id=publication.id,
            payload={
                "action_id": action.id,
                "execution_id": execution.id,
                "publication_id": publication.id,
                "external_reference_id": external_reference.id,
            },
            clock=clock,
            correlation_id=detail.correlation_id or action.id,
            causation_id=execution.id,
        )
        session.flush()


def _evaluate_permission(
    session: Session,
    *,
    scope: TenantScope,
    action: ActionModel,
    policy: PermissionPolicyModel,
    reviews: list[DeterministicExecutionReview],
    clock: Clock,
) -> PermissionEvaluationModel:
    control = _global_control(session, scope.business_id)
    if control is not None and (
        control.automation_paused
        or control.execution_paused
        or control.revoke_all_write_capabilities
    ):
        outcome = PermissionOutcome.BLOCKED
        reason = "Global execution control blocks external writes."
    elif not reviews_pass(reviews):
        outcome = PermissionOutcome.BLOCKED
        reason = "One or more execution controllers blocked the action."
    elif policy.requires_approval or policy.public_visibility:
        outcome = PermissionOutcome.APPROVAL_REQUIRED
        reason = "Public Telegram publication requires explicit owner approval."
    else:
        outcome = PermissionOutcome.BLOCKED
        reason = "Phase 5 does not permit approval bypass or autopilot."
    evaluation = PermissionEvaluationModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        action_id=action.id,
        permission_policy_id=policy.id,
        outcome=outcome.value,
        reason=reason,
        created_at=clock.now(),
    )
    session.add(evaluation)
    session.flush()
    return evaluation


def _preflight_block_reason(
    session: Session,
    *,
    action: ActionModel,
    detail: ActionProposalDetailModel,
    approval: ApprovalModel,
    account: ConnectorAccountModel,
) -> str | None:
    permission = _permission_evaluation(session, action.id)
    if permission.outcome != PermissionOutcome.APPROVAL_REQUIRED.value:
        return "permission_not_execution_eligible"
    non_pass_review = session.scalar(
        select(ExecutionControllerReviewModel).where(
            ExecutionControllerReviewModel.action_id == action.id,
            ExecutionControllerReviewModel.verdict != "PASS",
        )
    )
    if non_pass_review is not None:
        return "execution_controller_not_passed"
    control = _global_control(session, action.business_id)
    if control is not None:
        if control.revoke_all_write_capabilities:
            return "blocked_by_revoke_all_write_capabilities"
        if control.execution_paused:
            return "blocked_by_global_execution_pause"
        if control.automation_paused:
            return "blocked_by_automation_pause"
    if approval.status != ApprovalStatus.APPROVED.value:
        return "approval_not_active"
    if not _approval_matches_action(approval, action):
        return "stale_or_mismatched_approval"
    try:
        _assert_current_action_binding(session, action=action, detail=detail)
    except PermanentJobError:
        return "stale_or_mismatched_asset_version"
    if account.status != "READY" or not account.auth_healthy or not account.write_capability:
        return "connector_not_ready"
    if account.target_chat_id != detail.target_chat_id:
        return "connector_target_changed"
    experiment = session.scalar(
        select(ExperimentModel).where(
            ExperimentModel.decision_id == detail.decision_id
        )
    )
    if (
        experiment is not None
        and experiment.status != ExperimentStatus.DRAFT.value
    ):
        return "experiment_not_draft"
    if _payload_hash(detail.delivery_payload) != detail.delivery_payload_hash:
        return "action_payload_hash_mismatch"
    return None


def _assert_current_action_binding(
    session: Session,
    *,
    action: ActionModel,
    detail: ActionProposalDetailModel,
) -> None:
    workflow = session.get(ProductionWorkflowModel, detail.production_workflow_id)
    asset_version = session.get(AssetVersionModel, detail.asset_version_id)
    if workflow is None or asset_version is None:
        raise PermanentJobError("production binding no longer exists")
    if workflow.status != ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value:
        raise PermanentJobError("production workflow is no longer execution-ready")
    if workflow.final_asset_version_id != detail.asset_version_id:
        raise PermanentJobError("ActionProposal is stale against final AssetVersion")
    if (
        action.target_object_type != "AssetVersion"
        or action.target_object_id != asset_version.asset_id
        or action.target_object_version_id != asset_version.id
        or action.target_object_version != asset_version.version_number
    ):
        raise PermanentJobError("ActionProposal exact-version binding changed")
    if detail.delivery_payload.get("text") != asset_version.body:
        raise PermanentJobError("ActionProposal payload differs from immutable AssetVersion")
    if _payload_hash(detail.delivery_payload) != detail.delivery_payload_hash:
        raise PermanentJobError("ActionProposal payload hash mismatch")


def _materialize_reviews(
    session: Session,
    *,
    scope: TenantScope,
    action: ActionModel,
    reviews: list[DeterministicExecutionReview],
    clock: Clock,
) -> None:
    for review in reviews:
        session.add(
            ExecutionControllerReviewModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                action_id=action.id,
                controller_type=review.controller_type.value,
                verdict=review.verdict.value,
                reason=review.reason,
                conditions=list(review.conditions),
                created_at=clock.now(),
            )
        )
    session.flush()


def _execution_approval(
    session: Session,
    execution: ExecutionModel,
) -> ApprovalModel:
    if execution.approval_id is None:
        raise PermanentJobError("Execution has no approval binding")
    approval = session.get(ApprovalModel, execution.approval_id)
    if approval is None:
        raise PermanentJobError("Execution approval not found")
    return approval


def _approval_matches_action(approval: ApprovalModel, action: ActionModel) -> bool:
    return (
        approval.action_id == action.id
        and approval.action_type == action.action_type
        and approval.object_type == action.target_object_type
        and approval.object_id == action.target_object_id
        and approval.object_version_id == action.target_object_version_id
        and approval.object_version == action.target_object_version
    )


def _assert_owner(session: Session, *, scope: TenantScope, user_id: str) -> None:
    membership = session.scalar(
        select(BusinessMembershipModel).where(
            BusinessMembershipModel.organization_id == scope.organization_id,
            BusinessMembershipModel.business_id == scope.business_id,
            BusinessMembershipModel.user_id == user_id,
        )
    )
    if membership is None or membership.role.upper() != "OWNER":
        raise PermanentJobError("owner authority is required")


def _channel_for_scope(
    session: Session,
    *,
    scope: TenantScope,
    channel_id: str,
) -> ChannelModel:
    channel = session.get(ChannelModel, channel_id)
    if channel is None:
        raise PermanentJobError(f"Channel not found: {channel_id}")
    scope.assert_matches(
        organization_id=channel.organization_id,
        business_id=channel.business_id,
    )
    return channel


def _action_detail(session: Session, action_id: str) -> ActionProposalDetailModel:
    detail = session.scalar(
        select(ActionProposalDetailModel).where(
            ActionProposalDetailModel.action_id == action_id
        )
    )
    if detail is None:
        raise PermanentJobError("ActionProposal detail not found")
    return detail


def _permission_evaluation(session: Session, action_id: str) -> PermissionEvaluationModel:
    evaluation = session.scalar(
        select(PermissionEvaluationModel).where(
            PermissionEvaluationModel.action_id == action_id
        )
    )
    if evaluation is None:
        raise PermanentJobError("Permission evaluation not found")
    return evaluation


def _global_control(
    session: Session,
    business_id: str,
) -> GlobalExecutionControlModel | None:
    return session.scalar(
        select(GlobalExecutionControlModel).where(
            GlobalExecutionControlModel.business_id == business_id
        )
    )


def _payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _action_idempotency_key(
    *,
    production_workflow_id: str,
    asset_version_id: str,
    connector_account_id: str,
    target_chat_id: str,
    payload_hash: str,
) -> str:
    raw = "|".join(
        [
            TELEGRAM_PUBLISH_ACTION,
            production_workflow_id,
            asset_version_id,
            connector_account_id,
            target_chat_id,
            payload_hash,
        ]
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _audit(
    session: Session,
    *,
    scope: TenantScope,
    action: str,
    object_type: str,
    object_id: str,
    payload: dict[str, Any],
    actor_user_id: str | None,
    correlation_id: str,
    causation_id: str | None,
) -> None:
    assert_no_secrets(payload)
    session.add(
        AuditLogModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            actor_user_id=actor_user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=1,
        )
    )


def _outbox(
    session: Session,
    *,
    scope: TenantScope,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, object],
    clock: Clock,
    correlation_id: str,
    causation_id: str | None,
) -> None:
    assert_no_secrets(payload)
    session.add(
        OutboxEventModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status=OutboxStatus.PENDING.value,
            occurred_at=clock.now(),
            correlation_id=correlation_id,
            causation_id=causation_id,
            created_at=clock.now(),
            published_at=None,
        )
    )
