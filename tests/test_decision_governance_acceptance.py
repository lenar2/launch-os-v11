from __future__ import annotations

from types import SimpleNamespace

import pytest

from launch_os_v11.application import decision_governance as governance
from launch_os_v11.application import decision_workflow as base
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.persistence.models import ControllerReviewModel, DecisionCandidateModel
from launch_os_v11.runtime.errors import PermanentJobError


class FlushSession:
    def __init__(self) -> None:
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1


def _candidate(
    *,
    selected_action: str = "Run a reversible test",
    risk_class: str = "LOW",
    reversibility: str = "easy",
    critical_unknown: bool = False,
) -> DecisionCandidateModel:
    return DecisionCandidateModel(
        id="candidate-1",
        organization_id="org",
        business_id="biz",
        workflow_id="workflow",
        snapshot_id="snapshot",
        chief_agent_run_id="run",
        version_number=1,
        revision_round=0,
        status=base.DecisionCandidateStatus.UNDER_REVIEW.value,
        schema_version=1,
        selected_action=selected_action,
        payload={
            "selected_action": selected_action,
            "risk_class": risk_class,
            "reversibility": reversibility,
            "unknowns": [
                {"question": "Would more context help?", "critical": critical_unknown}
            ],
        },
        evidence_refs=[],
        specialist_contribution_ids=[],
        controller_review_ids=[],
        context_hash="hash",
        context_manifest={},
    )


def _review(
    controller_type: str,
    verdict: ControllerVerdict,
    *,
    reason: str | None = None,
    conditions: list[str] | None = None,
    required_changes: list[str] | None = None,
) -> ControllerReviewModel:
    return ControllerReviewModel(
        id=f"review-{controller_type}-{verdict.value}",
        organization_id="org",
        business_id="biz",
        controller_name=controller_type,
        controller_type=controller_type,
        verdict=verdict.value,
        reason=reason or verdict.value,
        issues=[],
        required_changes=required_changes or [],
        evidence_refs=[],
        conditions=conditions or [],
        context_manifest={},
    )


def test_pass_with_mandatory_conditions_requires_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _candidate()
    reviews = (
        _review("evidence", ControllerVerdict.PASS),
        _review(
            "economics",
            ControllerVerdict.PASS_WITH_CONDITIONS,
            conditions=["Add a spend ceiling"],
            required_changes=["Add a spend ceiling"],
        ),
    )
    workflow = SimpleNamespace(
        id="workflow",
        status=base.DecisionWorkflowStatus.CONTROLLERS_RUNNING.value,
        revision_count=0,
        max_revision_rounds=2,
    )
    calls: dict[str, int] = {"chief": 0, "enqueue": 0, "materialize": 0}

    monkeypatch.setattr(base, "_latest_candidate", lambda session, workflow: candidate)
    monkeypatch.setattr(
        base,
        "_materialize_controller_reviews",
        lambda session, workflow, candidate: reviews,
    )
    monkeypatch.setattr(
        base,
        "_ensure_chief_run",
        lambda *args, **kwargs: calls.__setitem__("chief", calls["chief"] + 1),
    )
    monkeypatch.setattr(
        base,
        "_enqueue_workflow_advance",
        lambda *args, **kwargs: calls.__setitem__("enqueue", calls["enqueue"] + 1),
    )
    monkeypatch.setattr(base, "_next_candidate_version", lambda session, workflow: 2)
    monkeypatch.setattr(
        base,
        "_materialize_final_decision",
        lambda *args, **kwargs: calls.__setitem__("materialize", calls["materialize"] + 1),
    )

    governance._advance_workflow(
        FlushSession(),
        workflow=workflow,
        queue=SimpleNamespace(),
        clock=SimpleNamespace(),
        registry=SimpleNamespace(),
    )

    assert candidate.status == base.DecisionCandidateStatus.REVISION_REQUIRED.value
    assert workflow.revision_count == 1
    assert workflow.status == base.DecisionWorkflowStatus.CHIEF_RUNNING.value
    assert calls == {"chief": 1, "enqueue": 1, "materialize": 0}
    assert reviews[1].conditions == ["Add a spend ceiling"]


def test_resolved_conditions_allow_normal_approval_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    reviews = (
        _review("evidence", ControllerVerdict.PASS),
        _review("economics", ControllerVerdict.PASS),
    )
    workflow = SimpleNamespace(
        id="workflow",
        status=base.DecisionWorkflowStatus.CONTROLLERS_RUNNING.value,
        revision_count=1,
        max_revision_rounds=2,
    )
    calls = {"materialize": 0}

    monkeypatch.setattr(base, "_latest_candidate", lambda session, workflow: candidate)
    monkeypatch.setattr(
        base,
        "_materialize_controller_reviews",
        lambda session, workflow, candidate: reviews,
    )
    monkeypatch.setattr(
        base,
        "_materialize_final_decision",
        lambda *args, **kwargs: calls.__setitem__("materialize", calls["materialize"] + 1),
    )

    governance._advance_workflow(
        FlushSession(),
        workflow=workflow,
        queue=SimpleNamespace(),
        clock=SimpleNamespace(),
        registry=SimpleNamespace(),
    )

    assert candidate.status == base.DecisionCandidateStatus.ACCEPTED.value
    assert workflow.status == base.DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value
    assert calls["materialize"] == 1


def test_block_and_revise_dominate_conditional_pass() -> None:
    candidate = _candidate()
    conditional = _review(
        "economics",
        ControllerVerdict.PASS_WITH_CONDITIONS,
        conditions=["Add limit"],
    )
    assert governance.governed_controller_outcome(
        candidate=candidate,
        reviews=(conditional, _review("security", ControllerVerdict.BLOCK)),
    ) == ControllerVerdict.BLOCK
    assert governance.governed_controller_outcome(
        candidate=candidate,
        reviews=(conditional, _review("strategy_red_team", ControllerVerdict.REVISE)),
    ) == ControllerVerdict.REVISE


def test_empty_conditional_verdict_has_no_unresolved_obligation() -> None:
    assert governance.governed_controller_outcome(
        candidate=_candidate(),
        reviews=(_review("economics", ControllerVerdict.PASS_WITH_CONDITIONS),),
    ) == ControllerVerdict.PASS


@pytest.mark.parametrize(
    "text",
    [
        "Your sales show your real value.",
        "Low conversion means you are not ready.",
        "Your price reflects your worth.",
        "Failure means there is something wrong with you.",
    ],
)
def test_constitutional_detector_catches_canonical_worth_mappings(text: str) -> None:
    assert governance._contains_human_worth_violation({"selected_action": text})


@pytest.mark.parametrize(
    "text",
    [
        "The current offer conversion is below the selected baseline.",
        "The evidence does not support this strategy yet.",
        "Human value is invariant and is not determined by price.",
    ],
)
def test_constitutional_detector_allows_business_form_language(text: str) -> None:
    assert not governance._contains_human_worth_violation({"selected_action": text})


def test_constitutional_violation_fails_closed_if_controller_does_not_block() -> None:
    candidate = _candidate(selected_action="Your sales show your real value.")
    with pytest.raises(PermanentJobError):
        governance.governed_controller_outcome(
            candidate=candidate,
            reviews=(_review("constitutional", ControllerVerdict.PASS),),
        )

    assert governance.governed_controller_outcome(
        candidate=candidate,
        reviews=(_review("constitutional", ControllerVerdict.BLOCK),),
    ) == ControllerVerdict.BLOCK


def test_anti_analysis_paralysis_ignores_noncritical_missing_info_block() -> None:
    candidate = _candidate(critical_unknown=False)
    anti = _review(
        "anti_analysis_paralysis",
        ControllerVerdict.BLOCK,
        reason="Missing useful information; need more data before acting.",
    )
    assert governance.governed_controller_outcome(
        candidate=candidate,
        reviews=(anti,),
    ) == ControllerVerdict.PASS


def test_anti_analysis_paralysis_preserves_critical_missing_info_block() -> None:
    candidate = _candidate(critical_unknown=True)
    anti = _review(
        "anti_analysis_paralysis",
        ControllerVerdict.BLOCK,
        reason="Missing critical information before acting.",
    )
    assert governance.governed_controller_outcome(
        candidate=candidate,
        reviews=(anti,),
    ) == ControllerVerdict.BLOCK
