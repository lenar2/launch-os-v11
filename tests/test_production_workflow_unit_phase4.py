from dataclasses import replace

import pytest
from pydantic import ValidationError

from launch_os_v11.ai_runtime.contracts import AgentAuthority
from launch_os_v11.ai_runtime.errors import AIContractError
from launch_os_v11.ai_runtime.schemas import AssetDraftProposal, ContentStrategyProposal
from launch_os_v11.production.governance import _contains_hard_manipulation
from launch_os_v11.production.registry import (
    CONTENT_DIRECTOR_CONTRACT_KEY,
    REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS,
    TELEGRAM_WRITER_CONTRACT_KEY,
    phase4_agent_registry,
)


def test_phase4_registry_separates_production_authorities() -> None:
    registry = phase4_agent_registry()
    director = registry.resolve(
        contract_key=CONTENT_DIRECTOR_CONTRACT_KEY,
        contract_version=1,
    )
    writer = registry.resolve(
        contract_key=TELEGRAM_WRITER_CONTRACT_KEY,
        contract_version=1,
    )
    assert set(director.authority_boundaries) == {
        AgentAuthority.READ_CONTEXT,
        AgentAuthority.PROPOSE_CONTENT_STRATEGY,
    }
    assert set(writer.authority_boundaries) == {
        AgentAuthority.READ_CONTEXT,
        AgentAuthority.PROPOSE_ASSET_DRAFT,
    }
    for key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS:
        controller = registry.resolve(contract_key=key, contract_version=1)
        assert set(controller.authority_boundaries) == {
            AgentAuthority.READ_CONTEXT,
            AgentAuthority.REVIEW_ASSET_VERSION,
        }


def test_phase4_production_contracts_fail_closed_on_authority_expansion() -> None:
    registry = phase4_agent_registry()
    writer = registry.resolve(
        contract_key=TELEGRAM_WRITER_CONTRACT_KEY,
        contract_version=1,
    )
    with pytest.raises(AIContractError):
        replace(
            writer,
            authority_boundaries=(
                AgentAuthority.READ_CONTEXT,
                AgentAuthority.PROPOSE_ASSET_DRAFT,
                AgentAuthority.REVIEW_ASSET_VERSION,
            ),
        )


def test_asset_draft_requires_evidence_for_evidence_backed_claim() -> None:
    with pytest.raises(ValidationError):
        AssetDraftProposal.model_validate(
            {
                "schema_name": "AssetDraftProposal",
                "schema_version": 1,
                "body": "Our customers increased revenue 100%.",
                "opening": None,
                "cta": "Reply",
                "claim_inventory": [
                    {
                        "text": "Customers increased revenue 100%",
                        "claim_type": "RESULT",
                        "requires_evidence": True,
                        "evidence_ref": None,
                    }
                ],
                "evidence_refs": [],
                "content_notes": [],
                "rights": {
                    "origin": "GENERATED",
                    "related_source_asset_ids": [],
                    "permission_scope": "Original generated text",
                    "customer_content_consent_ref": None,
                    "publication_restrictions": [],
                    "license_expires_at": None,
                },
            }
        )


def test_asset_draft_claim_reference_must_be_declared() -> None:
    with pytest.raises(ValidationError):
        AssetDraftProposal.model_validate(
            {
                "schema_name": "AssetDraftProposal",
                "schema_version": 1,
                "body": "Readers asked for this.",
                "opening": None,
                "cta": "Reply",
                "claim_inventory": [
                    {
                        "text": "Readers asked for this",
                        "claim_type": "FACTUAL",
                        "requires_evidence": True,
                        "evidence_ref": "evidence-1",
                    }
                ],
                "evidence_refs": [],
                "content_notes": [],
                "rights": {
                    "origin": "GENERATED",
                    "related_source_asset_ids": [],
                    "permission_scope": "Original generated text",
                    "customer_content_consent_ref": None,
                    "publication_restrictions": [],
                    "license_expires_at": None,
                },
            }
        )


def test_content_strategy_keeps_strategy_separate_from_asset_body() -> None:
    proposal = ContentStrategyProposal.model_validate(
        {
            "schema_name": "ContentStrategyProposal",
            "schema_version": 1,
            "objective": "Increase replies",
            "audience": "Warm audience",
            "content_job": "Explain pilot",
            "core_message": "Pilot is available",
            "angle": "Audience request",
            "message_mechanism": "Concise invitation",
            "tone": "calm",
            "cta_intent": "Reply",
            "channel_format": "TELEGRAM_POST_COPY",
            "evidence_refs": [],
            "allowed_claims": [],
            "forbidden_or_unsupported_claims": [],
            "brand_constraints": [],
            "production_constraints": [],
            "risks": [],
            "unknowns": [],
        }
    )
    assert not hasattr(proposal, "body")


@pytest.mark.parametrize(
    "body",
    [
        "If you don't buy, you are not ready.",
        "Buy now or you'll regret staying where you are.",
        "Prove your worth by joining.",
    ],
)
def test_hard_manipulation_is_deterministically_detected(body: str) -> None:
    assert _contains_hard_manipulation(body)
