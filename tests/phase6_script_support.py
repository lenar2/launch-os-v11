from __future__ import annotations

from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep
from launch_os_v11.ai_runtime.contracts import ModelResultKind
from launch_os_v11.ai_runtime.registry import REQUIRED_CONTROLLER_CONTRACT_KEYS
from launch_os_v11.domain.enums import ControllerVerdict, EpistemicStatus


def phase6_decision_script(
    evidence_id: str,
    *,
    selected_action: str,
) -> list[FakeAdapterScriptStep]:
    steps = [
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_specialist_payload(role, evidence_id),
        )
        for role in (
            "Audience Intelligence",
            "Revenue/Funnel Strategist",
            "Launch Strategist",
        )
    ]
    steps.append(
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_candidate_payload(evidence_id, selected_action=selected_action),
        )
    )
    steps.extend(
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_controller_payload(
                key.removeprefix("ai.controller."),
                evidence_id,
            ),
        )
        for key in REQUIRED_CONTROLLER_CONTRACT_KEYS
    )
    return steps


def _evidence_ref(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "epistemic_status": EpistemicStatus.FACT.value,
        "note": "Owner-provided Phase 6 test signal",
    }


def _specialist_payload(role: str, evidence_id: str) -> dict[str, object]:
    return {
        "schema_name": "SpecialistContribution",
        "schema_version": 1,
        "role": role,
        "observations": ["A bounded Telegram publication can test reaction observation."],
        "facts_used": [
            {
                "statement": "The owner authorized a bounded Telegram test.",
                "evidence_ref": evidence_id,
                "epistemic_status": EpistemicStatus.FACT.value,
            }
        ],
        "hypotheses": [
            {
                "statement": "The test publication may receive observable reaction updates.",
                "evidence_ref": evidence_id,
                "confidence": 0.5,
            }
        ],
        "assumptions": [
            {
                "statement": "The Telegram bot remains able to observe configured updates.",
                "evidence_ref": evidence_id,
                "confidence": 0.7,
            }
        ],
        "recommendations": ["Run one reversible governed Telegram experiment."],
        "risks": ["A single publication is a narrow trace."],
        "unknowns": [
            {
                "question": "How many reaction-change updates will be observed?",
                "critical": False,
            }
        ],
        "conflicts": [],
        "confidence": 0.7,
        "evidence_refs": [_evidence_ref(evidence_id)],
    }


def _candidate_payload(
    evidence_id: str,
    *,
    selected_action: str,
) -> dict[str, object]:
    return {
        "schema_name": "DecisionCandidate",
        "schema_version": 1,
        "goal": "Close the Phase 6 observe-measure-learn loop",
        "problem": "Publication outcomes are not yet represented as governed learning",
        "selected_action": selected_action,
        "why": [
            "The action is reversible and owner-approved.",
            "Telegram reaction updates can be bound to the exact published message.",
        ],
        "evidence_refs": [_evidence_ref(evidence_id)],
        "alternatives": [
            {
                "action": "Wait without observing the publication",
                "rejection_reason": "That would not close the learning loop.",
            }
        ],
        "why_alternatives_not_selected": ["Waiting produces no new observed trace."],
        "hypotheses": [
            {
                "statement": "The test publication may receive observable reaction updates.",
                "evidence_ref": evidence_id,
                "confidence": 0.5,
            }
        ],
        "assumptions": [
            {
                "statement": "The configured bot can observe the required Telegram updates.",
                "evidence_ref": evidence_id,
                "confidence": 0.7,
            }
        ],
        "unknowns": [
            {
                "question": "Will the exact publication receive reaction activity?",
                "critical": False,
            }
        ],
        "expected_effect": "Create one auditable publication-to-learning trace",
        "confidence": 0.7,
        "reversibility": "easy",
        "risk_class": "LOW",
        "experiment_proposal": {
            "hypothesis": "The test publication receives observable reaction activity.",
            "baseline": "0 observed reaction-change updates",
            "segment": "dedicated Telegram test channel",
            "treatment": "one governed Telegram test publication",
            "metric": "telegram_reaction_changes",
            "window": "30 seconds",
            "attribution_method": "telegram_message_lineage",
            "success_threshold": ">= 2 observed reaction-change updates",
            "weak_signal_threshold": ">= 1 observed reaction-change update",
            "failure_threshold": "0 observed reaction-change updates",
            "next_action_on_success": "start a bounded successor decision",
            "next_action_on_weak_signal": "preserve the trace and gather more evidence",
            "next_action_on_failure": "inspect observation coverage before changing strategy",
        },
        "required_assets": ["one Telegram test post"],
        "required_actions": ["owner publication approval"],
        "next_checkpoint": "Interpret the fixed 30-second reaction observation window",
    }


def _controller_payload(
    controller_type: str,
    evidence_id: str,
) -> dict[str, object]:
    return {
        "schema_name": "ControllerReview",
        "schema_version": 1,
        "controller_type": controller_type,
        "verdict": ControllerVerdict.PASS.value,
        "issues": [],
        "required_changes": [],
        "severity": "LOW",
        "evidence_refs": [_evidence_ref(evidence_id)],
    }
