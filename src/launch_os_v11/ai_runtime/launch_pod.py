from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_SPECIALIST_CONTRACT_KEYS = (
    "ai.specialist.audience_intelligence",
    "ai.specialist.revenue_funnel_strategist",
    "ai.specialist.launch_strategist",
)

LAUNCH_CORE_SPECIALIST_CONTRACT_KEYS = (
    "ai.specialist.business_product_analyst",
    "ai.specialist.offer_positioning_strategist",
    "ai.specialist.experiment_lead",
)

SPECIALIST_CONTRACT_SPECS = (
    (
        "ai.specialist.audience_intelligence",
        "Audience Intelligence",
        "Analyze audience context, facts, hypotheses, unknowns, intent signals, and risks.",
    ),
    (
        "ai.specialist.revenue_funnel_strategist",
        "Revenue/Funnel Strategist",
        (
            "Analyze offer economics, funnel assumptions, conversion mechanisms, "
            "and revenue constraints."
        ),
    ),
    (
        "ai.specialist.launch_strategist",
        "Launch Strategist",
        "Analyze launch sequencing, channel fit, timing, milestones, and reversible options.",
    ),
    (
        "ai.specialist.business_product_analyst",
        "Business/Product Analyst",
        "Analyze business model, product, offer-to-product fit, constraints, and launch context.",
    ),
    (
        "ai.specialist.offer_positioning_strategist",
        "Offer & Positioning Strategist",
        (
            "Analyze positioning, differentiation, offer architecture, objections, "
            "and message-market fit."
        ),
    ),
    (
        "ai.specialist.crm_retention_strategist",
        "CRM & Retention Strategist",
        "Analyze lifecycle, retention, renewal, win-back, expansion, and relationship continuity.",
    ),
    (
        "ai.specialist.experiment_lead",
        "Experiment Lead",
        "Design the smallest useful falsifiable experiment, metric, threshold, and checkpoint.",
    ),
    (
        "ai.specialist.instagram_strategist",
        "Instagram Strategist",
        "Analyze Instagram-native content, distribution, engagement, and launch sequencing.",
    ),
    (
        "ai.specialist.facebook_threads_strategist",
        "Facebook & Threads Strategist",
        (
            "Analyze Facebook and Threads-native distribution, conversation, format, "
            "and launch opportunities."
        ),
    ),
    (
        "ai.specialist.tiktok_strategist",
        "TikTok Strategist",
        (
            "Analyze TikTok-native hooks, formats, distribution, creator behavior, "
            "and launch opportunities."
        ),
    ),
    (
        "ai.specialist.youtube_strategist",
        "YouTube Strategist",
        (
            "Analyze YouTube long-form and Shorts strategy, packaging, sequencing, "
            "and conversion paths."
        ),
    ),
    (
        "ai.specialist.linkedin_strategist",
        "LinkedIn Strategist",
        (
            "Analyze LinkedIn-native thought leadership, distribution, conversation, "
            "and launch opportunities."
        ),
    ),
    (
        "ai.specialist.x_pinterest_bluesky_strategist",
        "X / Pinterest / Bluesky Strategist",
        (
            "Analyze provider-native distribution for X, Pinterest, or Bluesky "
            "without assuming unsupported capabilities."
        ),
    ),
    (
        "ai.specialist.telegram_strategist",
        "Telegram Strategist",
        "Analyze Telegram channel/community sequencing, content, engagement, and launch mechanics.",
    ),
    (
        "ai.specialist.email_strategist",
        "Email Strategist",
        "Analyze email sequencing, segmentation, subject/message strategy, nurture, and retention.",
    ),
    (
        "ai.specialist.community_inbox_operator",
        "Community & Inbox Operator",
        (
            "Analyze comments, messages, mentions, intent, urgency, response opportunities, "
            "and escalation needs."
        ),
    ),
    (
        "ai.specialist.performance_strategist",
        "Performance Strategist",
        "Analyze paid-distribution assumptions, creative/offer fit, measurement, and budget risk.",
    ),
    (
        "ai.specialist.copy_chief",
        "Copy Chief",
        "Analyze message hierarchy, proof, objections, CTA clarity, consistency, and channel fit.",
    ),
)

ALL_SPECIALIST_CONTRACT_KEYS = tuple(spec[0] for spec in SPECIALIST_CONTRACT_SPECS)

CONTENT_DIRECTOR_CONTRACT_KEY = "ai.production.content_director"
TELEGRAM_WRITER_CONTRACT_KEY = "ai.production.telegram_writer"
SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY = "ai.production.short_form_script_writer"
YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY = "ai.production.youtube_script_writer"
CREATIVE_DIRECTOR_CONTRACT_KEY = "ai.production.creative_director"
CAROUSEL_SPECIALIST_CONTRACT_KEY = "ai.production.carousel_specialist"
THUMBNAIL_SPECIALIST_CONTRACT_KEY = "ai.production.thumbnail_specialist"
LANDING_SPECIALIST_CONTRACT_KEY = "ai.production.landing_specialist"

PRODUCTION_SPECIALIST_CONTRACT_KEYS = (
    SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY,
    YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY,
    CREATIVE_DIRECTOR_CONTRACT_KEY,
    CAROUSEL_SPECIALIST_CONTRACT_KEY,
    THUMBNAIL_SPECIALIST_CONTRACT_KEY,
    LANDING_SPECIALIST_CONTRACT_KEY,
)

_CHANNEL_SPECIALISTS: dict[str, tuple[str, ...]] = {
    "instagram": ("ai.specialist.instagram_strategist",),
    "facebook": ("ai.specialist.facebook_threads_strategist",),
    "threads": ("ai.specialist.facebook_threads_strategist",),
    "tiktok": ("ai.specialist.tiktok_strategist",),
    "youtube": ("ai.specialist.youtube_strategist",),
    "linkedin": ("ai.specialist.linkedin_strategist",),
    "x": ("ai.specialist.x_pinterest_bluesky_strategist",),
    "twitter": ("ai.specialist.x_pinterest_bluesky_strategist",),
    "pinterest": ("ai.specialist.x_pinterest_bluesky_strategist",),
    "bluesky": ("ai.specialist.x_pinterest_bluesky_strategist",),
    "telegram": ("ai.specialist.telegram_strategist",),
    "email": ("ai.specialist.email_strategist",),
}

_COMMUNITY_PROVIDERS = {
    "instagram",
    "facebook",
    "threads",
    "tiktok",
    "youtube",
    "linkedin",
    "x",
    "twitter",
    "telegram",
    "reddit",
    "bluesky",
}
_COPY_PROVIDERS = _COMMUNITY_PROVIDERS | {"pinterest", "email"}
_SHORT_FORM_PROVIDERS = {"instagram", "facebook", "threads", "tiktok"}
_RETENTION_TERMS = {
    "retention",
    "renewal",
    "renewals",
    "churn",
    "ltv",
    "lifetime_value",
    "upsell",
    "cross_sell",
    "refund",
    "win_back",
}


@dataclass(frozen=True)
class LaunchPodPlan:
    decision_specialist_keys: tuple[str, ...]
    production_writer_key: str
    production_support_keys: tuple[str, ...]


def build_launch_pod_plan(
    snapshot_payload: Mapping[str, Any],
    *,
    required_assets: tuple[str, ...] = (),
) -> LaunchPodPlan:
    provider = _launch_provider(snapshot_payload)
    writer_key = TELEGRAM_WRITER_CONTRACT_KEY
    if provider in _SHORT_FORM_PROVIDERS:
        writer_key = SHORT_FORM_SCRIPT_WRITER_CONTRACT_KEY
    elif provider == "youtube":
        writer_key = YOUTUBE_SCRIPT_WRITER_CONTRACT_KEY

    support: list[str] = []
    if isinstance(snapshot_payload.get("launch"), Mapping):
        support.append(CREATIVE_DIRECTOR_CONTRACT_KEY)
    normalized_assets = " ".join(required_assets).lower()
    if "carousel" in normalized_assets:
        support.append(CAROUSEL_SPECIALIST_CONTRACT_KEY)
    if "thumbnail" in normalized_assets:
        support.append(THUMBNAIL_SPECIALIST_CONTRACT_KEY)
    if "landing" in normalized_assets or "sales page" in normalized_assets:
        support.append(LANDING_SPECIALIST_CONTRACT_KEY)

    return LaunchPodPlan(
        decision_specialist_keys=select_specialist_contract_keys(snapshot_payload),
        production_writer_key=writer_key,
        production_support_keys=tuple(support),
    )


def select_specialist_contract_keys(snapshot_payload: Mapping[str, Any]) -> tuple[str, ...]:
    selected = list(DEFAULT_SPECIALIST_CONTRACT_KEYS)
    launch = snapshot_payload.get("launch")
    if not isinstance(launch, Mapping):
        return tuple(selected)

    _extend_unique(selected, LAUNCH_CORE_SPECIALIST_CONTRACT_KEYS)
    channel = _launch_channel(snapshot_payload=snapshot_payload, launch=launch)
    if channel is not None:
        provider = _normalize_provider(channel.get("provider"))
        _extend_unique(selected, _CHANNEL_SPECIALISTS.get(provider, ()))
        if provider in _COMMUNITY_PROVIDERS:
            _extend_unique(selected, ("ai.specialist.community_inbox_operator",))
        if provider in _COPY_PROVIDERS:
            _extend_unique(selected, ("ai.specialist.copy_chief",))
        if _channel_has_paid_distribution(channel):
            _extend_unique(selected, ("ai.specialist.performance_strategist",))

    if _needs_retention_specialist(snapshot_payload):
        _extend_unique(selected, ("ai.specialist.crm_retention_strategist",))
    return tuple(selected)


def _launch_provider(snapshot_payload: Mapping[str, Any]) -> str:
    launch = snapshot_payload.get("launch")
    if not isinstance(launch, Mapping):
        return ""
    channel = _launch_channel(snapshot_payload=snapshot_payload, launch=launch)
    return _normalize_provider(channel.get("provider")) if channel is not None else ""


def _launch_channel(
    *,
    snapshot_payload: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    channel_id = launch.get("channel_id")
    if not isinstance(channel_id, str) or not channel_id:
        return None
    channels = snapshot_payload.get("channels")
    if not isinstance(channels, list):
        return None
    for item in channels:
        if isinstance(item, Mapping) and item.get("id") == channel_id:
            return item
    return None


def _normalize_provider(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _channel_has_paid_distribution(channel: Mapping[str, Any]) -> bool:
    capabilities = channel.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return False
    return any(
        value is True and any(token in str(key).lower() for token in ("ads", "paid", "promote"))
        for key, value in capabilities.items()
    )


def _needs_retention_specialist(snapshot_payload: Mapping[str, Any]) -> bool:
    goals = snapshot_payload.get("goals")
    if not isinstance(goals, list):
        return False
    for goal in goals:
        if not isinstance(goal, Mapping):
            continue
        values = (goal.get("metric"), goal.get("title"), goal.get("target"))
        normalized = " ".join(str(value).lower() for value in values if value is not None)
        if any(term in normalized for term in _RETENTION_TERMS):
            return True
    return False


def _extend_unique(target: list[str], values: tuple[str, ...]) -> None:
    for value in values:
        if value not in target:
            target.append(value)
