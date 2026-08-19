from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.analytics.contracts import Phase6CheckpointSpec
from launch_os_v11.application import decision_workflow as base
from launch_os_v11.application.commands import CommandContext, create_business_snapshot
from launch_os_v11.application.decision_governance import GuardedDecisionWorkflowAdvanceHandler
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.execution_models import ActionProposalDetailModel
from launch_os_v11.persistence.models import (
    BusinessMembershipModel,
    DecisionModel,
    DecisionWorkflowModel,
    ExperimentModel,
    ExperimentRuleModel,
    LearningModel,
)
from launch_os_v11.persistence.phase6_models import (
    CheckpointDefinitionModel,
    DecisionLearningLinkModel,
    LearningDetailModel,
    Phase6DecisionIntentModel,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.transport import JobQueue


def create_checkpoint_definition_for_decision(
    session: Session,
    *,
    scope: TenantScope,
    decision_id: str,
    spec: Phase6CheckpointSpec,
    clock: Clock,
) -> CheckpointDefinitionModel:
    decision = session.get(DecisionModel, decision_id)
    if decision is None:
        raise PermanentJobError("Decision not found for Phase 6 checkpoint")
    scope.assert_matches(
        organization_id=decision.organization_id,
        business_id=decision.business_id,
    )
    experiment = session.scalar(
        select(ExperimentModel).where(ExperimentModel.decision_id == decision.id)
    )
    if experiment is None:
        raise PermanentJobError("Phase 6 governed Decision requires an Experiment")
    rule = session.scalar(
        select(ExperimentRuleModel).where(
            ExperimentRuleModel.experiment_id == experiment.id
        )
    )
    if rule is None:
        raise PermanentJobError("Phase 6 governed Experiment requires an ExperimentRule")
    if experiment.metric != spec.metric_key or rule.metric != spec.metric_key:
        raise PermanentJobError("typed checkpoint metric must match the Experiment metric")
    bound_hash = _bound_checkpoint_hash(
        spec=spec,
        experiment_id=experiment.id,
        experiment_rule_id=rule.id,
    )
    existing = session.scalar(
        select(CheckpointDefinitionModel).where(
            CheckpointDefinitionModel.experiment_id == experiment.id
        )
    )
    if existing is not None:
        if existing.contract_hash != bound_hash:
            raise PermanentJobError("immutable checkpoint definition already exists")
        return existing
    executed_intent = session.scalar(
        select(ActionProposalDetailModel).where(
            ActionProposalDetailModel.decision_id == decision.id
        )
    )
    if executed_intent is not None:
        raise PermanentJobError("checkpoint cannot be retrofitted after ActionProposal creation")
    checkpoint = CheckpointDefinitionModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=decision.id,
        experiment_id=experiment.id,
        experiment_rule_id=rule.id,
        schema_version=spec.schema_version,
        metric_key=spec.metric_key,
        source_window_anchor="PUBLICATION_TIME",
        window_seconds=spec.window_seconds,
        grace_seconds=spec.grace_seconds,
        success_operator=spec.success.operator,
        success_value=spec.success.value,
        weak_signal_operator=spec.weak_signal.operator,
        weak_signal_value=spec.weak_signal.value,
        failure_operator=spec.failure.operator,
        failure_value=spec.failure.value,
        coverage_requirement=spec.coverage_requirement,
        attribution_method=spec.attribution_method,
        next_action_on_success=spec.next_action_on_success,
        next_action_on_weak_signal=spec.next_action_on_weak_signal,
        next_action_on_failure=spec.next_action_on_failure,
        contract_hash=bound_hash,
        created_at=clock.now(),
    )
    session.add(checkpoint)
    session.flush()
    return checkpoint


def start_phase6_decision_workflow(
    session: Session,
    *,
    context: CommandContext,
    queue: JobQueue,
    clock: Clock,
    checkpoint_spec: Phase6CheckpointSpec,
    launch_id: str | None = None,
    max_revision_rounds: int = 2,
) -> base.DecisionWorkflowStartResult:
    payload = base._snapshot_payload(
        session,
        scope=context.scope,
        launch_id=launch_id,
    )
    payload["phase6_checkpoint_intent"] = {
        "checkpoint_spec_hash": checkpoint_spec.contract_hash(),
    }
    snapshot = create_business_snapshot(
        session,
        context=context,
        reason="phase6.governed_decision",
        payload=payload,
    ).record
    result = base.start_decision_workflow(
        session,
        context=context,
        queue=queue,
        clock=clock,
        launch_id=launch_id,
        snapshot_id=snapshot.id,
        max_revision_rounds=max_revision_rounds,
    )
    _register_intent(
        session,
        scope=context.scope,
        workflow_id=result.workflow.id,
        checkpoint_spec=checkpoint_spec,
        prior_decision_id=None,
        learning_id=None,
        clock=clock,
    )
    return result


def start_successor_decision_workflow_from_learning(
    session: Session,
    *,
    context: CommandContext,
    queue: JobQueue,
    clock: Clock,
    prior_decision_id: str,
    learning_id: str,
    checkpoint_spec: Phase6CheckpointSpec,
    max_revision_rounds: int = 2,
) -> base.DecisionWorkflowStartResult:
    if context.actor_user_id is None:
        raise PermanentJobError("owner identity is required to start Phase 6 adaptation")
    _assert_owner(session, scope=context.scope, user_id=context.actor_user_id)
    prior = session.get(DecisionModel, prior_decision_id)
    learning = session.get(LearningModel, learning_id)
    if prior is None or learning is None:
        raise PermanentJobError("prior Decision or Learning not found")
    context.scope.assert_matches(
        organization_id=prior.organization_id,
        business_id=prior.business_id,
    )
    context.scope.assert_matches(
        organization_id=learning.organization_id,
        business_id=learning.business_id,
    )
    if learning.decision_id != prior.id:
        raise PermanentJobError("Learning is not bound to the prior Decision")
    learning_detail = session.scalar(
        select(LearningDetailModel).where(LearningDetailModel.learning_id == learning.id)
    )
    if learning_detail is None:
        raise PermanentJobError("Learning provenance detail is required for adaptation")

    payload = base._snapshot_payload(session, scope=context.scope, launch_id=None)
    payload["adaptation"] = {
        "prior_decision_id": prior.id,
        "learning_id": learning.id,
        "experiment_result_id": learning_detail.experiment_result_id,
        "metric_version_ids": list(learning_detail.metric_version_ids),
        "checkpoint_spec_hash": checkpoint_spec.contract_hash(),
    }
    snapshot = create_business_snapshot(
        session,
        context=context,
        reason="phase6.learning_adaptation",
        payload=payload,
    ).record
    result = base.start_decision_workflow(
        session,
        context=context,
        queue=queue,
        clock=clock,
        snapshot_id=snapshot.id,
        max_revision_rounds=max_revision_rounds,
    )
    _register_intent(
        session,
        scope=context.scope,
        workflow_id=result.workflow.id,
        checkpoint_spec=checkpoint_spec,
        prior_decision_id=prior.id,
        learning_id=learning.id,
        clock=clock,
    )
    return result


class Phase6DecisionWorkflowAdvanceHandler:
    def __init__(self, *, registry: AgentRegistry, queue: JobQueue) -> None:
        self._delegate = GuardedDecisionWorkflowAdvanceHandler(
            registry=registry,
            queue=queue,
        )

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        workflow_id = payload.get("workflow_id")
        self._delegate.handle(
            context=context,
            payload=payload,
            session=session,
            clock=clock,
        )
        if isinstance(workflow_id, str):
            _materialize_phase6_intent(
                session,
                scope=context.scope,
                workflow_id=workflow_id,
                clock=clock,
            )


def _register_intent(
    session: Session,
    *,
    scope: TenantScope,
    workflow_id: str,
    checkpoint_spec: Phase6CheckpointSpec,
    prior_decision_id: str | None,
    learning_id: str | None,
    clock: Clock,
) -> Phase6DecisionIntentModel:
    existing = session.scalar(
        select(Phase6DecisionIntentModel).where(
            Phase6DecisionIntentModel.workflow_id == workflow_id
        )
    )
    if existing is not None:
        if (
            existing.checkpoint_spec_hash != checkpoint_spec.contract_hash()
            or existing.prior_decision_id != prior_decision_id
            or existing.learning_id != learning_id
        ):
            raise PermanentJobError("Phase 6 Decision intent is immutable")
        return existing
    intent = Phase6DecisionIntentModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        workflow_id=workflow_id,
        checkpoint_spec=checkpoint_spec.canonical_payload(),
        checkpoint_spec_hash=checkpoint_spec.contract_hash(),
        prior_decision_id=prior_decision_id,
        learning_id=learning_id,
        created_at=clock.now(),
    )
    session.add(intent)
    session.flush()
    return intent


def _materialize_phase6_intent(
    session: Session,
    *,
    scope: TenantScope,
    workflow_id: str,
    clock: Clock,
) -> None:
    intent = session.scalar(
        select(Phase6DecisionIntentModel).where(
            Phase6DecisionIntentModel.workflow_id == workflow_id
        )
    )
    if intent is None:
        return
    workflow = session.get(DecisionWorkflowModel, workflow_id)
    if workflow is None or workflow.final_decision_id is None:
        return
    scope.assert_matches(
        organization_id=intent.organization_id,
        business_id=intent.business_id,
    )
    decision = session.get(DecisionModel, workflow.final_decision_id)
    if decision is None:
        raise PermanentJobError("Phase 6 workflow final Decision is missing")
    spec = Phase6CheckpointSpec.model_validate(intent.checkpoint_spec)
    create_checkpoint_definition_for_decision(
        session,
        scope=scope,
        decision_id=decision.id,
        spec=spec,
        clock=clock,
    )

    if intent.prior_decision_id is None and intent.learning_id is None:
        return
    if intent.prior_decision_id is None or intent.learning_id is None:
        raise PermanentJobError("Phase 6 adaptation binding is incomplete")
    learning = session.get(LearningModel, intent.learning_id)
    if learning is None or learning.decision_id != intent.prior_decision_id:
        raise PermanentJobError("Phase 6 adaptation Learning binding is invalid")
    if decision.supersedes_decision_id not in {None, intent.prior_decision_id}:
        raise PermanentJobError("successor Decision already supersedes a different Decision")
    decision.supersedes_decision_id = intent.prior_decision_id
    existing_link = session.scalar(
        select(DecisionLearningLinkModel).where(
            DecisionLearningLinkModel.decision_id == decision.id
        )
    )
    if existing_link is None:
        session.add(
            DecisionLearningLinkModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                decision_id=decision.id,
                prior_decision_id=intent.prior_decision_id,
                learning_id=intent.learning_id,
                created_at=clock.now(),
            )
        )
    session.flush()


def _bound_checkpoint_hash(
    *,
    spec: Phase6CheckpointSpec,
    experiment_id: str,
    experiment_rule_id: str,
) -> str:
    payload = {
        "spec": spec.canonical_payload(),
        "experiment_id": experiment_id,
        "experiment_rule_id": experiment_rule_id,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_owner(session: Session, *, scope: TenantScope, user_id: str) -> None:
    membership = session.scalar(
        select(BusinessMembershipModel).where(
            BusinessMembershipModel.organization_id == scope.organization_id,
            BusinessMembershipModel.business_id == scope.business_id,
            BusinessMembershipModel.user_id == user_id,
        )
    )
    if membership is None or membership.role.upper() != "OWNER":
        raise PermanentJobError("Phase 6 adaptation requires exact business owner authority")
