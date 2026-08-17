from __future__ import annotations

from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep
from launch_os_v11.ai_runtime.contracts import ModelResultKind
from launch_os_v11.domain.enums import ControllerVerdict, EpistemicStatus
from launch_os_v11.production.registry import REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS


def revision_then_pass_script(evidence_id: str) -> list[FakeAdapterScriptStep]:
    steps = [
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_strategy_payload(evidence_id),
        ),
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_asset_payload(
                evidence_id,
                body="A concise pilot post. Readers asked for this format. Reply PILOT.",
            ),
        ),
    ]
    steps.extend(
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_controller_payload(
                key.removeprefix("ai.controller.asset_"),
                evidence_id,
                verdict=(
                    ControllerVerdict.REVISE
                    if key.endswith("asset_legal_claims")
                    else ControllerVerdict.PASS
                ),
            ),
        )
        for key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
    )
    steps.append(
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_asset_payload(
                evidence_id,
                body="Readers asked for a concise format. Here is the pilot. Reply PILOT.",
            ),
        )
    )
    steps.extend(
        FakeAdapterScriptStep(
            kind=ModelResultKind.PARSED,
            payload=_controller_payload(
                key.removeprefix("ai.controller.asset_"),
                evidence_id,
                verdict=ControllerVerdict.PASS,
            ),
        )
        for key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
    )
    return steps


def _evidence_ref(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "epistemic_status": EpistemicStatus.FACT.value,
        "note": "Verified owner-provided audience signal",
    }


def _strategy_payload(evidence_id: str) -> dict[str, object]:
    return {
        "schema_name": "ContentStrategyProposal",
        "schema_version": 1,
        "objective": "Increase qualified launch replies",
        "audience": "Warm Telegram audience",
        "content_job": "Present the pilot clearly",
        "core_message": "A concise pilot is available",
        "angle": "Respond directly to audience request",
        "message_mechanism": "Evidence-backed concise invitation",
        "tone": "clear and calm",
        "cta_intent": "Reply PILOT",
        "channel_format": "TELEGRAM_POST_COPY",
        "evidence_refs": [_evidence_ref(evidence_id)],
        "allowed_claims": ["Readers asked for a concise format"],
        "forbidden_or_unsupported_claims": ["guaranteed results"],
        "brand_constraints": ["No shame or pressure"],
        "production_constraints": ["One concise Telegram post"],
        "risks": ["Audience signal may be narrow"],
        "unknowns": [{"question": "Exact reply rate?", "critical": False}],
    }


def _asset_payload(evidence_id: str, *, body: str) -> dict[str, object]:
    return {
        "schema_name": "AssetDraftProposal",
        "schema_version": 1,
        "body": body,
        "opening": "Readers asked for a concise format.",
        "cta": "Reply PILOT",
        "claim_inventory": [
            {
                "text": "Readers asked for a concise format",
                "claim_type": "FACTUAL",
                "requires_evidence": True,
                "evidence_ref": evidence_id,
            }
        ],
        "evidence_refs": [_evidence_ref(evidence_id)],
        "content_notes": ["Keep claims bounded to available evidence"],
        "rights": {
            "origin": "GENERATED",
            "related_source_asset_ids": [],
            "permission_scope": "Original AI-generated text for this business",
            "customer_content_consent_ref": None,
            "publication_restrictions": [],
            "license_expires_at": None,
        },
    }


def _controller_payload(
    controller_type: str,
    evidence_id: str,
    *,
    verdict: ControllerVerdict,
) -> dict[str, object]:
    return {
        "schema_name": "ControllerReview",
        "schema_version": 1,
        "controller_type": controller_type,
        "verdict": verdict.value,
        "issues": ["Revise wording"] if verdict == ControllerVerdict.REVISE else [],
        "required_changes": (
            ["Remove unsupported implication"]
            if verdict == ControllerVerdict.REVISE
            else []
        ),
        "severity": "MEDIUM" if verdict == ControllerVerdict.REVISE else "LOW",
        "evidence_refs": [_evidence_ref(evidence_id)],
    }
