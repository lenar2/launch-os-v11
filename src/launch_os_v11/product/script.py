"""Local synthetic script for the governed agent contracts.

This is not a model. It fills the existing structured contracts from owner-stated
records so the real workflow, controllers, and approval gates can run without a
paid provider. Context text is data and is never followed as an instruction.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from launch_os_v11.ai_runtime.contracts import (
    ModelRequest,
    ModelResult,
    ModelResultKind,
    OutputModelT,
    ProviderMetadata,
)
from launch_os_v11.ai_runtime.schemas import (
    AssetDraftProposal,
    ContentStrategyProposal,
    ControllerReviewOutput,
    DecisionCandidate,
    SpecialistContribution,
)
from launch_os_v11.domain.enums import ControllerVerdict, EpistemicStatus

_FACTS: ContextVar[LaunchScriptFacts | None] = ContextVar("launch_script_facts", default=None)

_SPECIALIST_ROLES = {
    "ai.specialist.audience_intelligence": "Audience Intelligence",
    "ai.specialist.revenue_funnel_strategist": "Revenue/Funnel Strategist",
    "ai.specialist.launch_strategist": "Launch Strategist",
}


@dataclass(frozen=True)
class LaunchScriptFacts:
    evidence_id: str
    evidence_status: EpistemicStatus
    goal: str
    offer_name: str
    audience: str | None
    revision_requested: bool
    adapting_without_measurement: bool
    revision_note: str = ""


def bind_launch_script_facts(facts: LaunchScriptFacts) -> None:
    _FACTS.set(facts)


def clear_launch_script_facts() -> None:
    _FACTS.set(None)


def _shown_goal(goal: str) -> str:
    lowered = goal.lower()
    blocked = ("guaranteed", "guarantee", "100%", "testimonial", "everyone gets")
    if any(marker in lowered for marker in blocked):
        return "the owner-stated goal (unsupported outcome wording was left out of the draft)"
    compact = " ".join(goal.split())
    if len(compact) > 400:
        return compact[:397] + "..."
    return compact


class SyntheticLaunchAdapter:
    """Deterministic stand-in. `model_intelligence` stays NOT_PROVEN."""

    provider_name = "fake"
    model_name = "synthetic-launch-script"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, request: ModelRequest[OutputModelT]) -> ModelResult[OutputModelT]:
        self.calls.append(request.output_type.__name__)
        metadata = _metadata(request, call_count=len(self.calls))
        facts = _FACTS.get()
        if facts is None:
            return _refused(metadata, "synthetic script has no launch facts")
        purpose = _purpose(request.structured_context)
        payload = _payload(request.output_type, facts, purpose)
        if payload is None:
            return _refused(
                metadata,
                f"synthetic script cannot fill {request.output_type.__name__}",
            )
        try:
            parsed = request.output_type.model_validate(payload)
        except ValidationError as exc:
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason=str(exc).splitlines()[0][:300],
                metadata=metadata,
            )
        return ModelResult(
            kind=ModelResultKind.PARSED,
            parsed_output=parsed,
            refusal=None,
            incomplete_reason=None,
            invalid_output_reason=None,
            metadata=metadata,
        )


def _metadata(request: ModelRequest[OutputModelT], *, call_count: int) -> ProviderMetadata:
    now = datetime.now(tz=UTC)
    return ProviderMetadata(
        provider_name=request.selected_provider_name or "fake",
        model_name=request.selected_model_name or "synthetic-launch-script",
        response_id=f"synthetic-launch-{call_count}",
        token_usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        latency_ms=0,
        started_at=now,
        completed_at=now,
    )


def _refused(metadata: ProviderMetadata, reason: str) -> ModelResult[OutputModelT]:
    return ModelResult(
        kind=ModelResultKind.REFUSAL,
        parsed_output=None,
        refusal=reason,
        incomplete_reason=None,
        invalid_output_reason=None,
        metadata=metadata,
    )


def _purpose(structured_context: str) -> str:
    marker = '"purpose":"'
    start = structured_context.find(marker)
    if start < 0:
        return ""
    rest = structured_context[start + len(marker) :]
    end = rest.find('"')
    if end < 0:
        return ""
    return rest[:end]


def _payload(
    output_type: type[OutputModelT],
    facts: LaunchScriptFacts,
    purpose: str,
) -> dict[str, object] | None:
    if output_type is SpecialistContribution:
        return _specialist(facts, purpose)
    if output_type is DecisionCandidate:
        return _candidate(facts)
    if output_type is ControllerReviewOutput:
        return _controller(facts, purpose)
    if output_type is ContentStrategyProposal:
        return _strategy(facts)
    if output_type is AssetDraftProposal:
        return _asset(facts)
    return None


def _evidence(facts: LaunchScriptFacts) -> dict[str, object]:
    return {
        "evidence_id": facts.evidence_id,
        "epistemic_status": facts.evidence_status.value,
        "note": "Owner-stated launch goal. Not a measured market result.",
    }


def _specialist(facts: LaunchScriptFacts, purpose: str) -> dict[str, object]:
    role = _SPECIALIST_ROLES.get(purpose, "Launch Room specialist")
    audience = facts.audience or "UNKNOWN"
    return {
        "schema_name": "SpecialistContribution",
        "schema_version": 1,
        "role": role,
        "observations": [
            (
                f"{role} can see the owner-stated goal for {facts.offer_name}. "
                f"Named audience: {audience}. Audience size, revenue, and replies are UNKNOWN."
            )
        ],
        "facts_used": [
            {
                "statement": "The owner stated a launch goal.",
                "evidence_ref": facts.evidence_id,
                "epistemic_status": facts.evidence_status.value,
            }
        ],
        "hypotheses": [
            {
                "statement": "An unpublished draft may deserve owner review.",
                "evidence_ref": facts.evidence_id,
                "confidence": 0.4,
            }
        ],
        "assumptions": [
            {
                "statement": "The owner can review a draft before any external write.",
                "evidence_ref": facts.evidence_id,
                "confidence": 0.5,
            }
        ],
        "recommendations": ["Prepare an unpublished draft and wait for the owner."],
        "risks": ["No connector observation is available."],
        "unknowns": [
            {"question": "What money, if any, has this offer produced?", "critical": False},
            {"question": "How large is the audience?", "critical": False},
            {"question": "How many qualified replies exist?", "critical": False},
        ],
        "conflicts": [
            {
                "statement": "No conflicting measured evidence is on record.",
                "evidence_refs": [facts.evidence_id],
            }
        ],
        "confidence": 0.4,
        "evidence_refs": [_evidence(facts)],
    }


def _candidate(facts: LaunchScriptFacts) -> dict[str, object]:
    if facts.adapting_without_measurement:
        selected = (
            "Do not change the offer from an unmeasured result. "
            "Keep the draft unpublished until a real observation exists."
        )
        problem = "No measured outcome is available to justify a new move."
    elif facts.revision_requested:
        selected = (
            "Revise the unpublished draft from the owner note. "
            "Do not publish and do not invent a result."
        )
        problem = "The owner asked for a revision before any approval."
    else:
        selected = (
            "Prepare one unpublished draft of the owner-stated offer and wait "
            "for owner approval. Do not publish."
        )
        problem = "The launch has a goal and no measured baseline."
    audience = facts.audience or "UNKNOWN"
    return {
        "schema_name": "DecisionCandidate",
        "schema_version": 1,
        "goal": _shown_goal(facts.goal),
        "problem": problem,
        "selected_action": selected,
        "why": [
            "The only bounded input is the owner-stated goal.",
            "Revenue, audience size, and replies are UNKNOWN, not zero.",
            facts.revision_note
            or "This text is a synthetic local script, not a live model judgment.",
        ],
        "evidence_refs": [_evidence(facts)],
        "alternatives": [
            {
                "action": "Publish immediately",
                "rejection_reason": "No publication authority and no measured baseline.",
            }
        ],
        "why_alternatives_not_selected": [
            "Publishing would pretend an approval and a result that do not exist."
        ],
        "hypotheses": [
            {
                "statement": "A reviewable draft is a reversible next step.",
                "evidence_ref": facts.evidence_id,
                "confidence": 0.4,
            }
        ],
        "assumptions": [
            {
                "statement": f"Audience name on record: {audience}. Size is UNKNOWN.",
                "evidence_ref": facts.evidence_id,
                "confidence": 0.3,
            }
        ],
        "unknowns": [
            {"question": "What is the measured reply count?", "critical": False},
            {"question": "What money, if any, is attributable to this offer?", "critical": False},
        ],
        "expected_effect": "The owner gets one reviewable draft. No external result is implied.",
        "confidence": 0.35,
        "reversibility": "easy",
        "risk_class": "LOW",
        "experiment_proposal": {
            "hypothesis": "An unpublished draft can be reviewed without an external write.",
            "baseline": "UNKNOWN",
            "segment": audience[:120],
            "treatment": "unpublished draft",
            "metric": "qualified_replies",
            "window": "until a real observation",
            "attribution_method": "none — no connector",
            "success_threshold": "UNKNOWN",
            "weak_signal_threshold": "UNKNOWN",
            "failure_threshold": "UNKNOWN",
            "next_action_on_success": "Ask the owner before any new asset.",
            "next_action_on_weak_signal": "Keep the draft unpublished.",
            "next_action_on_failure": "Do not infer a zero result from missing data.",
        },
        "required_assets": ["unpublished draft"],
        "required_actions": ["owner approval before any external write"],
        "next_checkpoint": "Look for a real observation. UNKNOWN is not a result.",
    }


def _controller(facts: LaunchScriptFacts, purpose: str) -> dict[str, object]:
    if purpose.startswith("ai.controller.asset_"):
        controller_type = purpose.removeprefix("ai.controller.asset_")
    elif purpose.startswith("ai.controller."):
        controller_type = purpose.removeprefix("ai.controller.")
    else:
        controller_type = "evidence"
    return {
        "schema_name": "ControllerReview",
        "schema_version": 1,
        "controller_type": controller_type,
        "verdict": ControllerVerdict.PASS.value,
        "issues": [],
        "required_changes": [],
        "severity": "LOW",
        "evidence_refs": [_evidence(facts)],
    }


def _strategy(facts: LaunchScriptFacts) -> dict[str, object]:
    audience = facts.audience or "UNKNOWN"
    return {
        "schema_name": "ContentStrategyProposal",
        "schema_version": 1,
        "objective": "Give the owner one unpublished draft of the stated goal.",
        "audience": audience,
        "content_job": "State the offer without inventing a result.",
        "core_message": f"{facts.offer_name}: {_shown_goal(facts.goal)}",
        "angle": "Honest next step, not a claimed outcome.",
        "message_mechanism": "Owner-stated goal plus explicit unknowns.",
        "tone": "clear and calm",
        "cta_intent": "Reply DRAFT for owner review",
        "channel_format": "TELEGRAM_POST_COPY",
        "evidence_refs": [_evidence(facts)],
        "allowed_claims": ["The owner stated a launch goal."],
        "forbidden_or_unsupported_claims": [
            "measured income",
            "known audience size",
            "promised outcome",
        ],
        "brand_constraints": ["No shame or pressure."],
        "production_constraints": ["One unpublished text draft. No external write."],
        "risks": ["A reader could mistake the draft for a measured claim."],
        "unknowns": [
            {"question": "What is the measured reply count?", "critical": False},
        ],
    }


def _asset(facts: LaunchScriptFacts) -> dict[str, object]:
    audience = facts.audience if facts.audience else "Audience: UNKNOWN"
    revision = ""
    if facts.revision_note:
        revision = f" Owner revision, kept as data and not as a command: {facts.revision_note}"
    body = (
        f"{facts.offer_name}\n\n"
        f"{audience}\n\n"
        f"The owner wants this launch to do the following: {_shown_goal(facts.goal)}.{revision} "
        "Measured replies: UNKNOWN. Revenue: UNKNOWN. Audience size: UNKNOWN. "
        "This is an unpublished draft for the owner to approve or send back. "
        "It promises no outcome.\n\n"
        "Reply DRAFT if this version should stay in review.\n\n"
        "SYNTHETIC_FAKE_ADAPTER. Model intelligence: NOT_PROVEN."
    )
    return {
        "schema_name": "AssetDraftProposal",
        "schema_version": 1,
        "body": body,
        "opening": facts.offer_name,
        "cta": "Reply DRAFT",
        "claim_inventory": [
            {
                "text": "The owner stated a launch goal.",
                "claim_type": "FACTUAL",
                "requires_evidence": True,
                "evidence_ref": facts.evidence_id,
            }
        ],
        "evidence_refs": [_evidence(facts)],
        "content_notes": [
            "SYNTHETIC_FAKE_ADAPTER",
            "model intelligence NOT_PROVEN",
            "no external write",
        ],
        "rights": {
            "origin": "GENERATED",
            "related_source_asset_ids": [],
            "permission_scope": "Local synthetic draft for owner review only.",
            "customer_content_consent_ref": None,
            "publication_restrictions": ["NO_EXTERNAL_WRITE"],
            "license_expires_at": None,
        },
    }
