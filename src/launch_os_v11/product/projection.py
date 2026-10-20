"""Human projection of one launch. UNKNOWN stays unknown. Synthetic stays labeled."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from launch_os_v11.application.decision_workflow import (
    DecisionWorkflowStatus,
    get_user_decision_view,
)
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    ActionModel,
    AssetVersionModel,
    BusinessEventModel,
    DecisionModel,
    DecisionWorkflowModel,
    ExecutionModel,
    LaunchModel,
    PublicationModel,
    SourceRecordModel,
)
from launch_os_v11.persistence.phase6_models import MetricVersionModel
from launch_os_v11.persistence.production_models import ProductionWorkflowModel
from launch_os_v11.product.errors import ProductError

BASELINE_OWNER_QUESTIONS_ANSWERED = 0
CAPABILITY_TOTAL = 7
GENERATION_PROVENANCE = "SYNTHETIC_FAKE_ADAPTER"
MODEL_INTELLIGENCE = "NOT_PROVEN"
PUBLICATION_AUTHORITY = "NOT_GRANTED"


@dataclass(frozen=True)
class FieldView:
    label: str
    value: str
    status: str
    note: str


@dataclass(frozen=True)
class QuestionView:
    question_id: str
    prompt: str
    answer: str
    answered: bool


@dataclass(frozen=True)
class LaunchRoomView:
    launch_id: str
    organization_id: str
    business_id: str
    owner_user_id: str
    goal: str
    offer_name: str
    audience: str
    snapshot_id: str | None
    snapshot_fields: tuple[FieldView, ...]
    decision_id: str | None
    decision_status: str | None
    decision: str | None
    reasons: tuple[str, ...]
    what_happens_now: str | None
    canonical_what_happens_now: str | None
    next_checkpoint: str | None
    approval_state: str
    approval_consequence: str
    material_body: str | None
    material_status: str | None
    observation_statement: str
    measured_current: str
    measured_numeric_value: None
    observation_coverage: str
    causality: str
    manual_note_count: int
    adaptation_stance: str
    adaptation_statement: str
    questions: tuple[QuestionView, ...]
    capability_answered: int
    capability_total: int
    baseline_answered: int
    capability_delta: int
    baseline_definition: str
    generation_provenance: str
    model_intelligence: str
    publication_authority: str
    action_count: int
    execution_count: int
    publication_count: int
    metric_version_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def project_launch_room(
    session: Session,
    launch_id: str,
    *,
    scope: TenantScope | None = None,
) -> LaunchRoomView:
    launch = session.get(LaunchModel, launch_id)
    if launch is None:
        raise ProductError("not_found", "Launch not found")
    if scope is not None:
        try:
            scope.assert_matches(
                organization_id=launch.organization_id,
                business_id=launch.business_id,
            )
        except TenantScopeViolation as exc:
            raise ProductError(
                "scope_violation",
                "This launch is not in the requested business.",
            ) from exc
    intent = _intent(session, launch)
    goal = _text(intent, "goal") or "UNKNOWN"
    offer_name = _text(intent, "offer_name") or "UNKNOWN"
    audience_raw = intent.get("audience")
    audience = audience_raw if isinstance(audience_raw, str) and audience_raw.strip() else ""
    owner_user_id = _text(intent, "owner_user_id")
    workflow = _latest_workflow(session, launch)
    decision = _decision(session, workflow)
    canonical_now = None
    reasons: tuple[str, ...] = ()
    next_checkpoint = None
    decision_text = None
    decision_status = None
    decision_id = None
    if decision is not None:
        user_view = get_user_decision_view(
            session,
            scope=TenantScope(
                organization_id=launch.organization_id,
                business_id=launch.business_id,
            ),
            decision_id=decision.id,
        )
        decision_id = decision.id
        decision_status = decision.status
        decision_text = user_view.decision
        reasons = user_view.reasons
        canonical_now = user_view.what_happens_now
        next_checkpoint = user_view.next_checkpoint
    material_body, material_status = _material(session, launch)
    manual_notes = _events(session, launch, "launch_room.manual_note")
    metric_count = _count(session, MetricVersionModel, launch)
    action_count = _count(session, ActionModel, launch)
    execution_count = _count(session, ExecutionModel, launch)
    publication_count = _count(session, PublicationModel, launch)
    approval_state, approval_consequence = _approval_state(session, launch, workflow)
    observation = (
        "Measured current: UNKNOWN. Coverage: NO_CONNECTOR_OBSERVATION. "
        "Causality: UNKNOWN. Missing data is not a zero result."
    )
    if manual_notes:
        observation += (
            f" Manual notes on record: {len(manual_notes)}. A note is not a metric."
        )
    if decision_text is None:
        adaptation_stance = "NOT_STARTED"
        adaptation_statement = "Not available yet. The team has not decided."
        what_now = None
    elif _unconsumed(session, launch, "launch_room.adaptation_requested"):
        adaptation_stance = "BLOCKED_WITHOUT_MEASUREMENT"
        adaptation_statement = decision_text
        what_now = "A new decision is waiting. It does not publish anything."
    elif any(
        event.payload.get("consumed_by_workflow_id") == (workflow.id if workflow else None)
        for event in _events(session, launch, "launch_room.adaptation_requested")
    ):
        adaptation_stance = "BLOCKED_WITHOUT_MEASUREMENT"
        adaptation_statement = (
            f"{decision_text} Measured current remains UNKNOWN, so this is not a "
            "performance verdict."
        )
        what_now = canonical_now
    else:
        adaptation_stance = "NOT_STARTED"
        adaptation_statement = (
            f"Next checkpoint: {next_checkpoint or 'UNKNOWN'}. "
            "Adaptation has not started, because there is no measured result."
        )
        what_now = canonical_now
    snapshot_fields = _snapshot_fields(
        session,
        launch,
        goal=goal,
        offer_name=offer_name,
        audience=audience,
        known_fact=_text(intent, "known_fact"),
    )
    questions = _questions(
        goal=goal,
        offer_name=offer_name,
        audience=audience,
        snapshot_fields=snapshot_fields,
        decision_text=decision_text,
        reasons=reasons,
        material_body=material_body,
        approval_state=approval_state,
        approval_consequence=approval_consequence,
        observation=observation,
        adaptation_statement=adaptation_statement,
    )
    answered = sum(1 for question in questions if question.answered)
    return LaunchRoomView(
        launch_id=launch.id,
        organization_id=launch.organization_id,
        business_id=launch.business_id,
        owner_user_id=owner_user_id,
        goal=goal,
        offer_name=offer_name,
        audience=audience or "UNKNOWN",
        snapshot_id=launch.snapshot_id,
        snapshot_fields=snapshot_fields,
        decision_id=decision_id,
        decision_status=decision_status,
        decision=decision_text,
        reasons=reasons,
        what_happens_now=what_now,
        canonical_what_happens_now=canonical_now,
        next_checkpoint=next_checkpoint,
        approval_state=approval_state,
        approval_consequence=approval_consequence,
        material_body=material_body,
        material_status=material_status,
        observation_statement=observation,
        measured_current="UNKNOWN",
        measured_numeric_value=None,
        observation_coverage="NO_CONNECTOR_OBSERVATION",
        causality="UNKNOWN",
        manual_note_count=len(manual_notes),
        adaptation_stance=adaptation_stance,
        adaptation_statement=adaptation_statement,
        questions=questions,
        capability_answered=answered,
        capability_total=CAPABILITY_TOTAL,
        baseline_answered=BASELINE_OWNER_QUESTIONS_ANSWERED,
        capability_delta=answered - BASELINE_OWNER_QUESTIONS_ANSWERED,
        baseline_definition=(
            "Before Launch Room, the HTTP surface was /health only and answered "
            "none of the seven owner questions."
        ),
        generation_provenance=GENERATION_PROVENANCE,
        model_intelligence=MODEL_INTELLIGENCE,
        publication_authority=PUBLICATION_AUTHORITY,
        action_count=action_count,
        execution_count=execution_count,
        publication_count=publication_count,
        metric_version_count=metric_count,
    )


def _questions(
    *,
    goal: str,
    offer_name: str,
    audience: str,
    snapshot_fields: tuple[FieldView, ...],
    decision_text: str | None,
    reasons: tuple[str, ...],
    material_body: str | None,
    approval_state: str,
    approval_consequence: str,
    observation: str,
    adaptation_statement: str,
) -> tuple[QuestionView, ...]:
    known = [field for field in snapshot_fields if field.status != "UNKNOWN"]
    unknown = [field for field in snapshot_fields if field.status == "UNKNOWN"]
    launching = f"{offer_name}. Goal: {goal}. Audience: {audience or 'UNKNOWN'}."
    known_answer = (
        "Known: " + "; ".join(f"{field.label}={field.value}" for field in known)
        + ". UNKNOWN: "
        + "; ".join(field.label for field in unknown)
        + "."
    )
    decision_answer = (
        "Not available yet."
        if decision_text is None
        else decision_text
        + (" Reasons: " + " | ".join(reasons) if reasons else "")
    )
    material_answer = (
        "Not available yet."
        if not material_body or offer_name not in material_body
        else material_body
    )
    if approval_state == "NOT_READY":
        approval_answer = "Not available yet."
    else:
        approval_answer = f"{approval_state}. {approval_consequence}"
    adaptation_answered = not adaptation_statement.startswith("Not available")
    rows = (
        ("what_are_we_launching", "What are we launching?", launching, True),
        ("what_is_known", "What is known versus unknown?", known_answer, bool(unknown)),
        ("team_decision", "What did the team decide?", decision_answer, decision_text is not None),
        (
            "materials",
            "What material is ready?",
            material_answer,
            material_body is not None and offer_name in material_body,
        ),
        (
            "needs_decision",
            "What needs my decision?",
            approval_answer,
            approval_state != "NOT_READY",
        ),
        ("what_happened", "What happened?", observation, "UNKNOWN" in observation),
        (
            "what_next",
            "What will we do next?",
            adaptation_statement,
            adaptation_answered,
        ),
    )
    return tuple(
        QuestionView(question_id=qid, prompt=prompt, answer=answer, answered=answered)
        for qid, prompt, answer, answered in rows
    )


def _snapshot_fields(
    session: Session,
    launch: LaunchModel,
    *,
    goal: str,
    offer_name: str,
    audience: str,
    known_fact: str,
) -> tuple[FieldView, ...]:
    del session
    audience_field = (
        FieldView(
            "Audience name",
            audience,
            "OWNER_STATED",
            "Named by the owner. Size is not measured.",
        )
        if audience
        else FieldView(
            "Audience name",
            "UNKNOWN",
            "UNKNOWN",
            "The owner did not name an audience.",
        )
    )
    fact_field = (
        FieldView(
            "Owner note",
            known_fact,
            "OWNER_STATED",
            "Not connector-verified and not a metric.",
        )
        if known_fact
        else FieldView(
            "Owner note",
            "UNKNOWN",
            "UNKNOWN",
            "No extra owner note.",
        )
    )
    return (
        FieldView("Offer", offer_name, "OWNER_STATED", "Stated by the owner at launch open."),
        FieldView("Goal", goal, "OWNER_STATED", "Stated by the owner. Not a measured result."),
        audience_field,
        FieldView(
            "Channel publish capability",
            "NOT_CONNECTED",
            "UNKNOWN",
            "No Telegram connector is authorized from this room.",
        ),
        FieldView("Income", "UNKNOWN", "UNKNOWN", "No payment observation. Not zero."),
        FieldView("Audience size", "UNKNOWN", "UNKNOWN", "No audience connector. Not zero."),
        FieldView(
            "Qualified replies",
            "UNKNOWN",
            "UNKNOWN",
            "No observation has been normalized. Not zero.",
        ),
        fact_field,
        FieldView(
            "Business snapshot",
            launch.snapshot_id or "UNKNOWN",
            "OWNER_STATED" if launch.snapshot_id else "UNKNOWN",
            "Immutable snapshot id. Later edits do not rewrite it.",
        ),
    )


def _approval_state(
    session: Session,
    launch: LaunchModel,
    workflow: DecisionWorkflowModel | None,
) -> tuple[str, str]:
    if workflow is None or workflow.final_decision_id is None:
        return (
            "NOT_READY",
            "Nothing is waiting for approval, and nothing can be published.",
        )
    if _unconsumed(session, launch, "launch_room.revision_requested"):
        return (
            "REVISION_REQUESTED",
            "The revision is recorded. The current decision is not approved "
            "and no external write was created.",
        )
    if workflow.status == DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value:
        return (
            "AWAITING_OWNER",
            "Approving lets production prepare a draft. It does not publish.",
        )
    if workflow.status == DecisionWorkflowStatus.APPROVED_FOR_PRODUCTION.value:
        return (
            "APPROVED",
            "This decision may be drafted. Publication authority is still not granted.",
        )
    if workflow.status in {
        DecisionWorkflowStatus.BLOCKED.value,
        DecisionWorkflowStatus.ESCALATED.value,
    }:
        return (
            "BLOCKED",
            "Controllers stopped the decision. Nothing was approved or published.",
        )
    return (
        "IN_PROGRESS",
        "The governed workflow is still running. No approval has been granted.",
    )


def _intent(session: Session, launch: LaunchModel) -> dict[str, object]:
    source = session.scalar(
        select(SourceRecordModel).where(
            SourceRecordModel.organization_id == launch.organization_id,
            SourceRecordModel.business_id == launch.business_id,
            SourceRecordModel.provider == "launch_room",
            SourceRecordModel.external_id == f"intent-{launch.id}",
        )
    )
    if source is None or not isinstance(source.payload, dict):
        return {}
    return source.payload


def _latest_workflow(session: Session, launch: LaunchModel) -> DecisionWorkflowModel | None:
    return session.scalar(
        select(DecisionWorkflowModel)
        .where(
            DecisionWorkflowModel.organization_id == launch.organization_id,
            DecisionWorkflowModel.business_id == launch.business_id,
            DecisionWorkflowModel.launch_id == launch.id,
        )
        .order_by(DecisionWorkflowModel.created_at.desc())
    )


def _decision(
    session: Session,
    workflow: DecisionWorkflowModel | None,
) -> DecisionModel | None:
    if workflow is None or workflow.final_decision_id is None:
        return None
    return session.get(DecisionModel, workflow.final_decision_id)


def _material(session: Session, launch: LaunchModel) -> tuple[str | None, str | None]:
    workflow = session.scalar(
        select(ProductionWorkflowModel)
        .where(
            ProductionWorkflowModel.organization_id == launch.organization_id,
            ProductionWorkflowModel.business_id == launch.business_id,
            ProductionWorkflowModel.launch_id == launch.id,
            ProductionWorkflowModel.final_asset_version_id.is_not(None),
        )
        .order_by(ProductionWorkflowModel.created_at.desc())
    )
    if workflow is None or workflow.final_asset_version_id is None:
        return None, None
    version = session.get(AssetVersionModel, workflow.final_asset_version_id)
    if version is None:
        return None, workflow.status
    return version.body, workflow.status


def _events(
    session: Session,
    launch: LaunchModel,
    event_type: str,
) -> list[BusinessEventModel]:
    rows = session.scalars(
        select(BusinessEventModel)
        .where(
            BusinessEventModel.organization_id == launch.organization_id,
            BusinessEventModel.business_id == launch.business_id,
            BusinessEventModel.event_type == event_type,
        )
        .order_by(BusinessEventModel.recorded_at)
    ).all()
    return [row for row in rows if row.payload.get("launch_id") == launch.id]


def _unconsumed(session: Session, launch: LaunchModel, event_type: str) -> bool:
    return any(
        not row.payload.get("consumed_by_workflow_id")
        for row in _events(session, launch, event_type)
    )


def _count(session: Session, model: Any, launch: LaunchModel) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(model)
        .where(
            model.organization_id == launch.organization_id,
            model.business_id == launch.business_id,
        )
    )
    return int(value or 0)


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""
