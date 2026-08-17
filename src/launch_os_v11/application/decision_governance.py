from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.application import decision_workflow as base
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.persistence.models import (
    ControllerReviewModel,
    DecisionCandidateModel,
    DecisionWorkflowModel,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets
from launch_os_v11.runtime.transport import JobQueue


class GuardedDecisionWorkflowAdvanceHandler:
    """Tighten Phase 3 controller semantics on the existing durable workflow spine."""

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
        assert_no_secrets(payload)
        workflow_id = base._workflow_id(payload)
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


def _advance_workflow(
    session: Session,
    *,
    workflow: DecisionWorkflowModel,
    queue: JobQueue,
    clock: Clock,
    registry: AgentRegistry,
) -> None:
    status = base.DecisionWorkflowStatus(workflow.status)
    if status != base.DecisionWorkflowStatus.CONTROLLERS_RUNNING:
        base._advance_workflow(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            registry=registry,
        )
        return

    candidate = base._latest_candidate(session, workflow)
    reviews = base._materialize_controller_reviews(
        session,
        workflow=workflow,
        candidate=candidate,
    )
    outcome = governed_controller_outcome(candidate=candidate, reviews=reviews)

    if outcome == ControllerVerdict.BLOCK:
        candidate.status = base.DecisionCandidateStatus.BLOCKED.value
        workflow.status = base.DecisionWorkflowStatus.BLOCKED.value
        session.flush()
        return

    if outcome in {ControllerVerdict.REVISE, ControllerVerdict.PASS_WITH_CONDITIONS}:
        candidate.status = base.DecisionCandidateStatus.REVISION_REQUIRED.value
        if workflow.revision_count >= workflow.max_revision_rounds:
            workflow.status = base.DecisionWorkflowStatus.ESCALATED.value
            session.flush()
            return
        workflow.revision_count += 1
        workflow.status = base.DecisionWorkflowStatus.REVISION_REQUIRED.value
        base._ensure_chief_run(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            registry=registry,
            previous_candidate=candidate,
            reviews=reviews,
        )
        workflow.status = base.DecisionWorkflowStatus.CHIEF_RUNNING.value
        base._enqueue_workflow_advance(
            session,
            workflow=workflow,
            queue=queue,
            clock=clock,
            suffix=f"after-chief:{base._next_candidate_version(session, workflow)}",
        )
        return

    candidate.status = base.DecisionCandidateStatus.ACCEPTED.value
    workflow.status = base.DecisionWorkflowStatus.CANDIDATE_ACCEPTED.value
    base._materialize_final_decision(session, workflow=workflow, candidate=candidate)
    workflow.status = base.DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value


def governed_controller_outcome(
    *,
    candidate: DecisionCandidateModel,
    reviews: tuple[ControllerReviewModel, ...],
) -> ControllerVerdict:
    """Resolve controller outcomes under deterministic Phase 3 governance rules."""

    by_type = {
        review.controller_type: review
        for review in reviews
        if isinstance(review.controller_type, str)
    }

    constitutional = by_type.get("constitutional")
    if (
        _contains_human_worth_violation(candidate.payload)
        and (
            constitutional is None
            or constitutional.verdict != ControllerVerdict.BLOCK.value
        )
    ):
        raise PermanentJobError(
            "Constitutional Controller must BLOCK deterministic human-worth violations"
        )

    ignored_review_ids: set[str] = set()
    anti_paralysis = by_type.get("anti_analysis_paralysis")
    if anti_paralysis is not None and _is_low_risk_reversible_without_critical_unknown(candidate):
        verdict = ControllerVerdict(anti_paralysis.verdict)
        if verdict in {ControllerVerdict.BLOCK, ControllerVerdict.REVISE} and _missing_info_only(
            anti_paralysis
        ):
            ignored_review_ids.add(anti_paralysis.id)

    effective = [review for review in reviews if review.id not in ignored_review_ids]
    verdicts = {ControllerVerdict(review.verdict) for review in effective}

    if ControllerVerdict.BLOCK in verdicts:
        return ControllerVerdict.BLOCK
    if ControllerVerdict.REVISE in verdicts:
        return ControllerVerdict.REVISE

    conditional_reviews = [
        review
        for review in effective
        if ControllerVerdict(review.verdict) == ControllerVerdict.PASS_WITH_CONDITIONS
    ]
    if any(_mandatory_conditions(review) for review in conditional_reviews):
        return ControllerVerdict.PASS_WITH_CONDITIONS

    # PASS_WITH_CONDITIONS with no actual required condition has no unresolved
    # governance obligation. The original verdict remains persisted for audit.
    return ControllerVerdict.PASS


def _mandatory_conditions(review: ControllerReviewModel) -> tuple[str, ...]:
    values = [*(review.conditions or []), *(review.required_changes or [])]
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _is_low_risk_reversible_without_critical_unknown(
    candidate: DecisionCandidateModel,
) -> bool:
    payload = candidate.payload or {}
    risk_class = str(payload.get("risk_class", "")).upper()
    reversibility = str(payload.get("reversibility", "")).lower()
    unknowns_value = payload.get("unknowns", [])
    unknowns = unknowns_value if isinstance(unknowns_value, list) else []
    has_critical_unknown = any(
        isinstance(item, dict) and bool(item.get("critical")) for item in unknowns
    )
    easily_reversible = (
        "easy" in reversibility
        or ("reversible" in reversibility and "irreversible" not in reversibility)
    )
    return risk_class == "LOW" and easily_reversible and not has_critical_unknown


def _missing_info_only(review: ControllerReviewModel) -> bool:
    text = " ".join(
        [
            review.reason or "",
            *(review.issues or []),
            *(review.required_changes or []),
        ]
    ).lower()
    missing_terms = (
        "missing",
        "unknown",
        "information",
        "need more data",
        "needs more data",
        "insufficient data",
        "evidence gap",
    )
    hard_terms = (
        "security",
        "privacy",
        "illegal",
        "permission",
        "constitutional",
        "human worth",
        "manipulation",
        "deceptive",
        "coercive",
    )
    return any(term in text for term in missing_terms) and not any(
        term in text for term in hard_terms
    )


_BUSINESS_TERMS = (
    "sales",
    "sale",
    "revenue",
    "conversion",
    "reach",
    "price",
    "performance",
    "result",
    "results",
    "rejection",
    "non-purchase",
    "non purchase",
    "discipline",
    "success",
    "failure",
)
_MAPPING_TERMS = (
    "show",
    "shows",
    "prove",
    "proves",
    "mean",
    "means",
    "reflect",
    "reflects",
    "determine",
    "determines",
    "indicate",
    "indicates",
    "demonstrate",
    "demonstrates",
    "reveal",
    "reveals",
)
_WORTH_TERMS = (
    "human value",
    "real value",
    "personal value",
    "your value",
    "self-worth",
    "self worth",
    "worth",
    "rank",
    "not ready",
    "readiness",
    "personal correctness",
    "something wrong with you",
    "failure as a person",
)
_NEGATION_TERMS = ("not", "never", "no", "doesn't", "does not", "do not", "cannot")


def _contains_human_worth_violation(payload: dict[str, object]) -> bool:
    return any(_has_directional_worth_mapping(value) for value in _strings(payload))


def _has_directional_worth_mapping(value: str) -> bool:
    text = re.sub(r"\s+", " ", value.lower()).strip()
    business_positions = _term_positions(text, _BUSINESS_TERMS)
    mapping_positions = _term_positions(text, _MAPPING_TERMS)
    worth_positions = _term_positions(text, _WORTH_TERMS)
    for business_start in business_positions:
        for mapping_start in mapping_positions:
            if mapping_start <= business_start:
                continue
            prefix = text[max(business_start, mapping_start - 18) : mapping_start]
            if any(term in prefix.split() for term in ("not", "never", "no")):
                continue
            if any(term in prefix for term in _NEGATION_TERMS[3:]):
                continue
            for worth_start in worth_positions:
                if business_start < mapping_start < worth_start and worth_start - business_start <= 180:
                    return True
    return False


def _term_positions(text: str, terms: tuple[str, ...]) -> tuple[int, ...]:
    positions: list[int] = []
    for term in terms:
        start = text.find(term)
        while start >= 0:
            positions.append(start)
            start = text.find(term, start + 1)
    return tuple(sorted(positions))


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
