from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class SocialNetwork(StrEnum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    THREADS = "threads"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    X = "x"
    PINTEREST = "pinterest"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    REDDIT = "reddit"
    BLUESKY = "bluesky"
    MASTODON = "mastodon"
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    TWITCH = "twitch"


class SocialCapability(StrEnum):
    ACCOUNT_READ = "account.read"
    CONTENT_READ = "content.read"
    PUBLISH_TEXT = "content.publish.text"
    PUBLISH_IMAGE = "content.publish.image"
    PUBLISH_VIDEO = "content.publish.video"
    PUBLISH_CAROUSEL = "content.publish.carousel"
    PUBLISH_STORY = "content.publish.story"
    PUBLISH_SHORT = "content.publish.short"
    UPLOAD_DRAFT = "content.upload_draft"
    COMMENT_READ = "comment.read"
    COMMENT_WRITE = "comment.write"
    MENTION_READ = "mention.read"
    REACTION_READ = "reaction.read"
    MESSAGE_READ = "message.read"
    MESSAGE_WRITE = "message.write"
    INSIGHTS_READ = "insights.read"
    WEBHOOKS = "webhooks"
    LISTENING_SEARCH = "listening.search"
    TRENDS_READ = "trends.read"
    ADS_REPORTING = "ads.reporting"


class CapabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    READ_ONLY = "READ_ONLY"
    WRITE_LIMITED = "WRITE_LIMITED"
    USER_HANDOFF_REQUIRED = "USER_HANDOFF_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


class SocialDataAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class SocialActionKind(StrEnum):
    PUBLISH_TEXT = "publish_text"
    PUBLISH_MEDIA = "publish_media"
    REPLY_COMMENT = "reply_comment"
    SEND_MESSAGE = "send_message"


@dataclass(frozen=True)
class SocialCapabilityStatus:
    capability: SocialCapability
    state: CapabilityState
    detail: str | None = None


@dataclass(frozen=True)
class SocialMetricValue:
    metric_name: str
    value: float | None
    availability: SocialDataAvailability

    def __post_init__(self) -> None:
        if not self.metric_name.strip():
            raise ValueError("metric_name must not be empty")
        if self.availability == SocialDataAvailability.AVAILABLE and self.value is None:
            raise ValueError("AVAILABLE metric requires a value")
        if self.availability == SocialDataAvailability.UNAVAILABLE and self.value is not None:
            raise ValueError("UNAVAILABLE metric must not manufacture a value")


@dataclass(frozen=True)
class SocialAccountReadiness:
    network: SocialNetwork
    account_ref: str
    connected: bool
    auth_healthy: bool
    scopes_granted: tuple[str, ...] = ()
    provider_review_state: str | None = None
    historical_backfill_complete: bool | None = None
    incremental_sync_healthy: bool | None = None
    freshness_ref: str | None = None
    capabilities: tuple[SocialCapabilityStatus, ...] = ()
    coverage_gaps: tuple[str, ...] = ()
    rate_limit_state: str | None = None
    last_provider_error: str | None = None

    def __post_init__(self) -> None:
        if not self.account_ref.strip():
            raise ValueError("account_ref must not be empty")
        seen: set[SocialCapability] = set()
        for status in self.capabilities:
            if status.capability in seen:
                raise ValueError(f"duplicate capability: {status.capability}")
            seen.add(status.capability)

    def capability_state(self, capability: SocialCapability) -> CapabilityState:
        for status in self.capabilities:
            if status.capability == capability:
                return status.state
        return CapabilityState.UNAVAILABLE

    def can_execute(self, capability: SocialCapability) -> bool:
        return self.capability_state(capability) in {
            CapabilityState.AVAILABLE,
            CapabilityState.WRITE_LIMITED,
        }


@dataclass(frozen=True)
class SocialExternalReference:
    network: SocialNetwork
    account_ref: str
    external_id: str
    provider_url: str | None = None

    def __post_init__(self) -> None:
        if not self.account_ref.strip() or not self.external_id.strip():
            raise ValueError("social external reference requires account_ref and external_id")


@dataclass(frozen=True)
class SocialObservation:
    network: SocialNetwork
    account_ref: str
    external_id: str
    object_type: str
    observed_at: str
    occurred_at: str | None = None
    text: str | None = None
    parent_external_id: str | None = None
    provider_payload_ref: str | None = None
    metrics: tuple[SocialMetricValue, ...] = ()

    def __post_init__(self) -> None:
        required = (self.account_ref, self.external_id, self.object_type, self.observed_at)
        if any(not value.strip() for value in required):
            raise ValueError("social observation identity fields must not be empty")


@dataclass(frozen=True)
class SocialObservationPage:
    items: tuple[SocialObservation, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class SocialActionCommand:
    network: SocialNetwork
    account_ref: str
    action: SocialActionKind
    client_action_id: str
    text: str | None = None
    media_refs: tuple[str, ...] = ()
    target_external_id: str | None = None

    def __post_init__(self) -> None:
        if not self.account_ref.strip() or not self.client_action_id.strip():
            raise ValueError("social action requires account_ref and client_action_id")
        if self.action == SocialActionKind.PUBLISH_TEXT and not (self.text or "").strip():
            raise ValueError("publish_text requires text")
        if self.action == SocialActionKind.PUBLISH_MEDIA and not self.media_refs:
            raise ValueError("publish_media requires at least one media_ref")
        if (
            self.action == SocialActionKind.REPLY_COMMENT
            and (not (self.text or "").strip() or not (self.target_external_id or "").strip())
        ):
            raise ValueError("reply_comment requires text and target_external_id")
        if self.action == SocialActionKind.SEND_MESSAGE and not (self.text or "").strip():
            raise ValueError("send_message requires text")


@dataclass(frozen=True)
class SocialActionResult:
    network: SocialNetwork
    account_ref: str
    client_action_id: str
    external_reference: SocialExternalReference | None
    provider_status: str


class SocialConnector(Protocol):
    def check_readiness(self) -> SocialAccountReadiness: ...

    def observe(self, *, cursor: str | None, limit: int) -> SocialObservationPage: ...

    def execute(self, command: SocialActionCommand) -> SocialActionResult: ...


class SocialConnectorError(RuntimeError):
    pass


class SocialConnectorNotRegistered(SocialConnectorError):
    pass


class SocialConnectorRejected(SocialConnectorError):
    pass


_ACTION_CAPABILITY: dict[SocialActionKind, SocialCapability] = {
    SocialActionKind.PUBLISH_TEXT: SocialCapability.PUBLISH_TEXT,
    SocialActionKind.PUBLISH_MEDIA: SocialCapability.PUBLISH_VIDEO,
    SocialActionKind.REPLY_COMMENT: SocialCapability.COMMENT_WRITE,
    SocialActionKind.SEND_MESSAGE: SocialCapability.MESSAGE_WRITE,
}


class SocialConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[tuple[SocialNetwork, str], SocialConnector] = {}

    def register(
        self,
        *,
        network: SocialNetwork,
        account_ref: str,
        connector: SocialConnector,
    ) -> None:
        key = (network, account_ref)
        if key in self._connectors:
            raise SocialConnectorRejected(
                f"duplicate social connector registration: {network}:{account_ref}"
            )
        readiness = connector.check_readiness()
        if readiness.network != network or readiness.account_ref != account_ref:
            raise SocialConnectorRejected(
                "connector readiness identity does not match registry key"
            )
        self._connectors[key] = connector

    def resolve(self, *, network: SocialNetwork, account_ref: str) -> SocialConnector:
        connector = self._connectors.get((network, account_ref))
        if connector is None:
            raise SocialConnectorNotRegistered(
                f"social connector not registered: {network}:{account_ref}"
            )
        return connector

    def readiness_map(self) -> tuple[SocialAccountReadiness, ...]:
        values = [connector.check_readiness() for connector in self._connectors.values()]
        return tuple(sorted(values, key=lambda value: (value.network.value, value.account_ref)))

    def observe(
        self,
        *,
        network: SocialNetwork,
        account_ref: str,
        cursor: str | None,
        limit: int,
    ) -> SocialObservationPage:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self.resolve(network=network, account_ref=account_ref).observe(
            cursor=cursor,
            limit=limit,
        )

    def execute(self, command: SocialActionCommand) -> SocialActionResult:
        connector = self.resolve(network=command.network, account_ref=command.account_ref)
        readiness = connector.check_readiness()
        capability = _ACTION_CAPABILITY[command.action]
        if not readiness.connected or not readiness.auth_healthy:
            raise SocialConnectorRejected("social connector is not auth-ready")
        if not readiness.can_execute(capability):
            state = readiness.capability_state(capability)
            raise SocialConnectorRejected(
                f"social capability not directly executable: {capability.value}:{state.value}"
            )
        result = connector.execute(command)
        if result.network != command.network or result.account_ref != command.account_ref:
            raise SocialConnectorRejected("social action result identity mismatch")
        if result.client_action_id != command.client_action_id:
            raise SocialConnectorRejected("social action result client_action_id mismatch")
        return result


@dataclass
class FakeSocialConnector:
    readiness: SocialAccountReadiness
    observations: SocialObservationPage = field(
        default_factory=lambda: SocialObservationPage(items=())
    )
    result_external_id: str = "fake-1"
    calls: list[SocialActionCommand] = field(default_factory=list)

    def check_readiness(self) -> SocialAccountReadiness:
        return self.readiness

    def observe(self, *, cursor: str | None, limit: int) -> SocialObservationPage:
        del cursor
        return SocialObservationPage(
            items=self.observations.items[:limit],
            next_cursor=self.observations.next_cursor,
        )

    def execute(self, command: SocialActionCommand) -> SocialActionResult:
        self.calls.append(command)
        return SocialActionResult(
            network=self.readiness.network,
            account_ref=self.readiness.account_ref,
            client_action_id=command.client_action_id,
            external_reference=SocialExternalReference(
                network=self.readiness.network,
                account_ref=self.readiness.account_ref,
                external_id=self.result_external_id,
            ),
            provider_status="FAKE_SUCCEEDED",
        )