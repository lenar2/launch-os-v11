from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from launch_os_v11.connectors.social import (
    CapabilityState,
    SocialAccountReadiness,
    SocialActionCommand,
    SocialActionKind,
    SocialActionResult,
    SocialCapability,
    SocialCapabilityStatus,
    SocialConnectorRejected,
    SocialExternalReference,
    SocialNetwork,
    SocialObservation,
    SocialObservationPage,
)
from launch_os_v11.execution.contracts import (
    TelegramConnector,
    TelegramPublishTextCommand,
)


class TelegramObservationConnector(Protocol):
    def get_updates(
        self,
        *,
        offset: int | None,
        allowed_updates: Sequence[str],
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], ...]: ...


class TelegramSocialConnectorAdapter:
    def __init__(
        self,
        *,
        account_ref: str,
        publish_connector: TelegramConnector,
        observation_connector: TelegramObservationConnector,
        observation_timeout_seconds: int = 0,
    ) -> None:
        if not account_ref.strip():
            raise ValueError("account_ref must not be empty")
        if observation_timeout_seconds < 0:
            raise ValueError("observation_timeout_seconds must not be negative")
        self._account_ref = account_ref
        self._publish_connector = publish_connector
        self._observation_connector = observation_connector
        self._observation_timeout_seconds = observation_timeout_seconds

    def check_readiness(self) -> SocialAccountReadiness:
        telegram = self._publish_connector.check_readiness(chat_id=self._account_ref)
        publish_state = (
            CapabilityState.AVAILABLE
            if telegram.auth_healthy and telegram.write_capability
            else CapabilityState.UNAVAILABLE
        )
        read_state = (
            CapabilityState.AVAILABLE if telegram.auth_healthy else CapabilityState.UNAVAILABLE
        )
        return SocialAccountReadiness(
            network=SocialNetwork.TELEGRAM,
            account_ref=self._account_ref,
            connected=telegram.auth_healthy,
            auth_healthy=telegram.auth_healthy,
            provider_review_state="BOT_API",
            capabilities=(
                SocialCapabilityStatus(SocialCapability.ACCOUNT_READ, read_state),
                SocialCapabilityStatus(SocialCapability.CONTENT_READ, read_state),
                SocialCapabilityStatus(SocialCapability.MESSAGE_READ, read_state),
                SocialCapabilityStatus(SocialCapability.PUBLISH_TEXT, publish_state),
                SocialCapabilityStatus(SocialCapability.MESSAGE_WRITE, publish_state),
                SocialCapabilityStatus(
                    SocialCapability.INSIGHTS_READ,
                    CapabilityState.UNAVAILABLE,
                    "current Telegram slice has no provider analytics connector",
                ),
                SocialCapabilityStatus(
                    SocialCapability.WEBHOOKS,
                    CapabilityState.UNAVAILABLE,
                    "current implementation observes with getUpdates polling",
                ),
            ),
            coverage_gaps=(
                "provider analytics not implemented",
                "webhook observation not implemented",
            ),
            last_provider_error=telegram.error_class,
        )

    def observe(self, *, cursor: str | None, limit: int) -> SocialObservationPage:
        if limit <= 0:
            raise ValueError("limit must be positive")
        offset = _telegram_offset(cursor)
        updates = self._observation_connector.get_updates(
            offset=offset,
            allowed_updates=("message", "channel_post"),
            timeout_seconds=self._observation_timeout_seconds,
        )
        selected = updates[:limit]
        items = tuple(
            observation
            for update in selected
            if (observation := _normalize_telegram_update(update, account_ref=self._account_ref))
            is not None
        )
        next_cursor: str | None = None
        ids = [update.get("update_id") for update in selected]
        integer_ids = [value for value in ids if isinstance(value, int)]
        if integer_ids:
            next_cursor = str(max(integer_ids) + 1)
        return SocialObservationPage(items=items, next_cursor=next_cursor)

    def execute(self, command: SocialActionCommand) -> SocialActionResult:
        if command.network != SocialNetwork.TELEGRAM or command.account_ref != self._account_ref:
            raise SocialConnectorRejected("telegram social command identity mismatch")
        if command.action != SocialActionKind.PUBLISH_TEXT:
            raise SocialConnectorRejected(
                "telegram social adapter currently supports publish_text only"
            )
        text = (command.text or "").strip()
        if not text:
            raise SocialConnectorRejected("telegram publish_text requires text")
        result = self._publish_connector.publish_text(
            TelegramPublishTextCommand(
                chat_id=self._account_ref,
                text=text,
            )
        )
        return SocialActionResult(
            network=SocialNetwork.TELEGRAM,
            account_ref=self._account_ref,
            client_action_id=command.client_action_id,
            external_reference=SocialExternalReference(
                network=SocialNetwork.TELEGRAM,
                account_ref=self._account_ref,
                external_id=result.message_id,
            ),
            provider_status="SUCCEEDED",
        )


def _telegram_offset(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        value = int(cursor)
    except ValueError as error:
        raise SocialConnectorRejected("telegram observation cursor must be an integer") from error
    if value < 0:
        raise SocialConnectorRejected("telegram observation cursor must not be negative")
    return value


def _normalize_telegram_update(
    update: dict[str, Any],
    *,
    account_ref: str,
) -> SocialObservation | None:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return None
    event = update.get("message")
    object_type = "message"
    if not isinstance(event, dict):
        event = update.get("channel_post")
        object_type = "channel_post"
    if not isinstance(event, dict):
        return None

    message_id = event.get("message_id")
    external_id = str(message_id) if isinstance(message_id, int | str) else f"update:{update_id}"

    raw_text = event.get("text")
    if not isinstance(raw_text, str):
        raw_text = event.get("caption")
    text = raw_text if isinstance(raw_text, str) else None

    occurred_at: str | None = None
    raw_date = event.get("date")
    if isinstance(raw_date, int):
        occurred_at = datetime.fromtimestamp(raw_date, tz=UTC).isoformat()

    reply = event.get("reply_to_message")
    parent_external_id: str | None = None
    if isinstance(reply, dict):
        parent_id = reply.get("message_id")
        if isinstance(parent_id, int | str):
            parent_external_id = str(parent_id)

    return SocialObservation(
        network=SocialNetwork.TELEGRAM,
        account_ref=account_ref,
        external_id=external_id,
        object_type=object_type,
        observed_at=datetime.now(tz=UTC).isoformat(),
        occurred_at=occurred_at,
        text=text,
        parent_external_id=parent_external_id,
        provider_payload_ref=f"telegram:update:{update_id}",
    )