from __future__ import annotations

from launch_os_v11.ai_runtime.contracts import AgentAuthority
from launch_os_v11.ai_runtime.launch_pod import (
    ALL_SPECIALIST_CONTRACT_KEYS,
    CAROUSEL_SPECIALIST_CONTRACT_KEY,
    CREATIVE_DIRECTOR_CONTRACT_KEY,
    DEFAULT_SPECIALIST_CONTRACT_KEYS,
    LANDING_SPECIALIST_CONTRACT_KEY,
    SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY,
    THUMBNAIL_SPECIALIST_CONTRACT_KEY,
    YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY,
    build_launch_pod_plan,
    select_specialist_contract_keys,
)
from launch_os_v11.ai_runtime.registry import phase3_agent_registry, specialist_contracts
from launch_os_v11.production.registry import (
    phase4_agent_registry,
    production_specialist_contracts,
)


def _snapshot(
    *,
    provider: str | None = None,
    capabilities: dict[str, object] | None = None,
    metric: str = "qualified_replies",
) -> dict[str, object]:
    launch = None
    channels: list[dict[str, object]] = []
    if provider is not None:
        launch = {"channel_id": "channel-1", "status": "ACTIVE"}
        channels = [
            {
                "id": "channel-1",
                "provider": provider,
                "handle": "@launch",
                "capabilities": capabilities or {},
            }
        ]
    return {
        "launch": launch,
        "channels": channels,
        "goals": [
            {
                "id": "goal-1",
                "title": "Launch goal",
                "target": "Improve outcome",
                "metric": metric,
            }
        ],
    }


def test_generic_decision_keeps_minimal_default_specialist_team() -> None:
    assert select_specialist_contract_keys(_snapshot()) == DEFAULT_SPECIALIST_CONTRACT_KEYS


def test_instagram_launch_routes_exact_channel_pod_without_unrelated_specialists() -> None:
    selected = select_specialist_contract_keys(_snapshot(provider="instagram"))

    assert selected == (
        *DEFAULT_SPECIALIST_CONTRACT_KEYS,
        "ai.specialist.business_product_analyst",
        "ai.specialist.offer_positioning_strategist",
        "ai.specialist.experiment_lead",
        "ai.specialist.instagram_strategist",
        "ai.specialist.community_inbox_operator",
        "ai.specialist.copy_chief",
    )
    assert "ai.specialist.tiktok_strategist" not in selected
    assert "ai.specialist.youtube_strategist" not in selected
    assert "ai.specialist.performance_strategist" not in selected
    assert "ai.specialist.crm_retention_strategist" not in selected


def test_paid_retention_launch_adds_needed_cross_functional_roles_only() -> None:
    selected = select_specialist_contract_keys(
        _snapshot(
            provider="instagram",
            capabilities={"post": True, "ads_reporting": True},
            metric="retention_rate",
        )
    )

    assert "ai.specialist.instagram_strategist" in selected
    assert "ai.specialist.community_inbox_operator" in selected
    assert "ai.specialist.copy_chief" in selected
    assert "ai.specialist.performance_strategist" in selected
    assert "ai.specialist.crm_retention_strategist" in selected
    assert "ai.specialist.tiktok_strategist" not in selected


def test_daily_launch_pod_plan_selects_production_team_from_channel_and_assets() -> None:
    plan = build_launch_pod_plan(
        _snapshot(provider="instagram"),
        required_assets=("reel", "carousel", "landing page"),
    )

    assert plan.production_writer_key == SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY
    assert plan.production_support_keys == (
        CREATIVE_DIRECTOR_CONTRACT_KEY,
        CAROUSEL_SPECIALIST_CONTRACT_KEY,
        LANDING_SPECIALIST_CONTRACT_KEY,
    )
    assert THUMBNAIL_SPECIALIST_CONTRACT_KEY not in plan.production_support_keys


def test_youtube_launch_plan_uses_youtube_writer_and_thumbnail_specialist() -> None:
    plan = build_launch_pod_plan(
        _snapshot(provider="youtube"),
        required_assets=("long video", "thumbnail"),
    )

    assert plan.production_writer_key == YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY
    assert plan.production_support_keys == (
        CREATIVE_DIRECTOR_CONTRACT_KEY,
        THUMBNAIL_SPECIALIST_CONTRACT_KEY,
    )


def test_all_launch_pod_decision_specialists_are_real_governed_contracts() -> None:
    contracts = specialist_contracts()
    keys = {contract.contract_key for contract in contracts}

    assert keys == set(ALL_SPECIALIST_CONTRACT_KEYS)
    for contract in contracts:
        assert AgentAuthority.READ_CONTEXT in contract.authority_boundaries
        assert AgentAuthority.PROPOSE_RECOMMENDATION in contract.authority_boundaries
        assert AgentAuthority.PROPOSE_DECISION_CANDIDATE not in contract.authority_boundaries
        assert "external write" in contract.prohibited_actions
        assert "connector access" in contract.prohibited_actions
        assert "credential access" in contract.prohibited_actions


def test_all_launch_pod_production_specialists_are_real_governed_contracts() -> None:
    contracts = production_specialist_contracts()
    keys = {contract.contract_key for contract in contracts}

    assert keys == {
        SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY,
        YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY,
        CREATIVE_DIRECTOR_CONTRACT_KEY,
        CAROUSEL_SPECIALIST_CONTRACT_KEY,
        THUMBNAIL_SPECIALIST_CONTRACT_KEY,
        LANDING_SPECIALIST_CONTRACT_KEY,
    }
    for contract in contracts:
        assert AgentAuthority.READ_CONTEXT in contract.authority_boundaries
        assert "external write" in contract.prohibited_actions
        assert "connector access" in contract.prohibited_actions
        assert "credential access" in contract.prohibited_actions


def test_phase3_and_phase4_registries_keep_authorities_separate() -> None:
    phase3_keys = {contract.contract_key for contract in phase3_agent_registry().contracts()}
    phase4_keys = {contract.contract_key for contract in phase4_agent_registry().contracts()}

    assert set(ALL_SPECIALIST_CONTRACT_KEYS).issubset(phase3_keys)
    assert "ai.chief.growth_producer" in phase3_keys
    assert "ai.controller.evidence" in phase3_keys
    assert len([key for key in phase3_keys if key.startswith("ai.chief.")]) == 1

    assert SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY in phase4_keys
    assert YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY in phase4_keys
    assert CREATIVE_DIRECTOR_CONTRACT_KEY in phase4_keys
