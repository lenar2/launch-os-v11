from __future__ import annotations

import pytest

from launch_os_v11.connectors.social import (
    CapabilityState,
    FakeSocialConnector,
    SocialAccountReadiness,
    SocialActionCommand,
    SocialActionKind,
    SocialCapability,
    SocialCapabilityStatus,
    SocialConnectorRegistry,
    SocialConnectorRejected,
    SocialDataAvailability,
    SocialMetricValue,
    SocialNetwork,
    SocialObservation,
    SocialObservationPage,
)
from launch_os_v11.connectors.telegram_observation import FakeTelegramObservationConnector
from launch_os_v11.connectors.telegram_social import TelegramSocialConnectorAdapter
from launch_os_v11.execution.contracts import ConnectorReadiness
from launch_os_v11.execution.telegram import FakeTelegramConnector


def _readiness(
    *,
    network: SocialNetwork,
    account_ref: str,
    capability: SocialCapability,
    state: CapabilityState,
) -> SocialAccountReadiness:
    return SocialAccountReadiness(
        network=network,
        account_ref=account_ref,
        connected=True,
        auth_healthy=True,
        capabilities=(SocialCapabilityStatus(capability, state),),
    )


def test_missing_capability_is_unavailable_not_inferred() -> None:
    readiness = _readiness(
        network=SocialNetwork.INSTAGRAM,
        account_ref="ig-1",
        capability=SocialCapability.INSIGHTS_READ,
        state=CapabilityState.AVAILABLE,
    )

    assert readiness.capability_state(SocialCapability.MESSAGE_WRITE) == CapabilityState.UNAVAILABLE
    assert not readiness.can_execute(SocialCapability.MESSAGE_WRITE)


def test_metric_unavailable_cannot_be_encoded_as_zero() -> None:
    with pytest.raises(ValueError, match="UNAVAILABLE metric"):
        SocialMetricValue(
            metric_name="revenue",
            value=0.0,
            availability=SocialDataAvailability.UNAVAILABLE,
        )

    unavailable = SocialMetricValue(
        metric_name="revenue",
        value=None,
        availability=SocialDataAvailability.UNAVAILABLE,
    )
    zero = SocialMetricValue(
        metric_name="revenue",
        value=0.0,
        availability=SocialDataAvailability.AVAILABLE,
    )

    assert unavailable.value is None
    assert zero.value == 0.0


def test_registry_keeps_provider_and_account_capabilities_isolated() -> None:
    instagram = FakeSocialConnector(
        readiness=_readiness(
            network=SocialNetwork.INSTAGRAM,
            account_ref="ig-1",
            capability=SocialCapability.PUBLISH_TEXT,
            state=CapabilityState.USER_HANDOFF_REQUIRED,
        )
    )
    telegram = FakeSocialConnector(
        readiness=_readiness(
            network=SocialNetwork.TELEGRAM,
            account_ref="tg-1",
            capability=SocialCapability.PUBLISH_TEXT,
            state=CapabilityState.AVAILABLE,
        )
    )
    registry = SocialConnectorRegistry()
    registry.register(
        network=SocialNetwork.INSTAGRAM,
        account_ref="ig-1",
        connector=instagram,
    )
    registry.register(
        network=SocialNetwork.TELEGRAM,
        account_ref="tg-1",
        connector=telegram,
    )

    readiness = {
        (item.network, item.account_ref): item
        for item in registry.readiness_map()
    }

    assert readiness[(SocialNetwork.INSTAGRAM, "ig-1")].capability_state(
        SocialCapability.PUBLISH_TEXT
    ) == CapabilityState.USER_HANDOFF_REQUIRED
    assert readiness[(SocialNetwork.TELEGRAM, "tg-1")].capability_state(
        SocialCapability.PUBLISH_TEXT
    ) == CapabilityState.AVAILABLE


def test_registry_blocks_direct_execution_when_provider_requires_handoff() -> None:
    connector = FakeSocialConnector(
        readiness=_readiness(
            network=SocialNetwork.TIKTOK,
            account_ref="creator-1",
            capability=SocialCapability.PUBLISH_TEXT,
            state=CapabilityState.USER_HANDOFF_REQUIRED,
        )
    )
    registry = SocialConnectorRegistry()
    registry.register(
        network=SocialNetwork.TIKTOK,
        account_ref="creator-1",
        connector=connector,
    )

    with pytest.raises(SocialConnectorRejected, match="not directly executable"):
        registry.execute(
            SocialActionCommand(
                network=SocialNetwork.TIKTOK,
                account_ref="creator-1",
                action=SocialActionKind.PUBLISH_TEXT,
                client_action_id="action-1",
                text="hello",
            )
        )

    assert connector.calls == []


def test_registry_executes_only_against_exact_registered_identity() -> None:
    connector = FakeSocialConnector(
        readiness=_readiness(
            network=SocialNetwork.TELEGRAM,
            account_ref="tg-1",
            capability=SocialCapability.PUBLISH_TEXT,
            state=CapabilityState.AVAILABLE,
        )
    )
    registry = SocialConnectorRegistry()
    registry.register(
        network=SocialNetwork.TELEGRAM,
        account_ref="tg-1",
        connector=connector,
    )

    result = registry.execute(
        SocialActionCommand(
            network=SocialNetwork.TELEGRAM,
            account_ref="tg-1",
            action=SocialActionKind.PUBLISH_TEXT,
            client_action_id="action-1",
            text="hello",
        )
    )

    assert result.network == SocialNetwork.TELEGRAM
    assert result.account_ref == "tg-1"
    assert connector.calls[0].text == "hello"


def test_fake_observation_page_is_bounded_by_limit() -> None:
    observations = SocialObservationPage(
        items=(
            SocialObservation(
                network=SocialNetwork.LINKEDIN,
                account_ref="li-1",
                external_id="1",
                object_type="post",
                observed_at="2026-09-16T00:00:00+00:00",
            ),
            SocialObservation(
                network=SocialNetwork.LINKEDIN,
                account_ref="li-1",
                external_id="2",
                object_type="post",
                observed_at="2026-09-16T00:00:01+00:00",
            ),
        ),
        next_cursor="3",
    )
    connector = FakeSocialConnector(
        readiness=_readiness(
            network=SocialNetwork.LINKEDIN,
            account_ref="li-1",
            capability=SocialCapability.CONTENT_READ,
            state=CapabilityState.AVAILABLE,
        ),
        observations=observations,
    )

    page = connector.observe(cursor=None, limit=1)

    assert len(page.items) == 1
    assert page.next_cursor == "3"


def test_telegram_adapter_maps_existing_readiness_without_broadening_capabilities() -> None:
    publisher = FakeTelegramConnector(
        readiness=ConnectorReadiness(
            auth_healthy=True,
            write_capability=True,
            capabilities={"send_message": True},
            bot_identity="bot-1",
        )
    )
    observer = FakeTelegramObservationConnector()
    adapter = TelegramSocialConnectorAdapter(
        account_ref="-100123",
        publish_connector=publisher,
        observation_connector=observer,
    )

    readiness = adapter.check_readiness()

    assert readiness.network == SocialNetwork.TELEGRAM
    assert readiness.capability_state(SocialCapability.PUBLISH_TEXT) == CapabilityState.AVAILABLE
    assert readiness.capability_state(SocialCapability.INSIGHTS_READ) == CapabilityState.UNAVAILABLE
    assert readiness.capability_state(SocialCapability.WEBHOOKS) == CapabilityState.UNAVAILABLE


def test_telegram_adapter_normalizes_updates_and_cursor() -> None:
    publisher = FakeTelegramConnector()
    observer = FakeTelegramObservationConnector(
        updates=[
            {
                "update_id": 10,
                "channel_post": {
                    "message_id": 77,
                    "date": 1789516800,
                    "text": "Launch update",
                },
            }
        ]
    )
    adapter = TelegramSocialConnectorAdapter(
        account_ref="-100123",
        publish_connector=publisher,
        observation_connector=observer,
    )

    page = adapter.observe(cursor="10", limit=10)

    assert page.next_cursor == "11"
    assert len(page.items) == 1
    item = page.items[0]
    assert item.external_id == "77"
    assert item.object_type == "channel_post"
    assert item.text == "Launch update"
    assert item.provider_payload_ref == "telegram:update:10"


def test_telegram_adapter_executes_typed_publish_text_command() -> None:
    publisher = FakeTelegramConnector(message_id="900")
    observer = FakeTelegramObservationConnector()
    adapter = TelegramSocialConnectorAdapter(
        account_ref="-100123",
        publish_connector=publisher,
        observation_connector=observer,
    )
    registry = SocialConnectorRegistry()
    registry.register(
        network=SocialNetwork.TELEGRAM,
        account_ref="-100123",
        connector=adapter,
    )

    result = registry.execute(
        SocialActionCommand(
            network=SocialNetwork.TELEGRAM,
            account_ref="-100123",
            action=SocialActionKind.PUBLISH_TEXT,
            client_action_id="client-42",
            text="Approved launch post",
        )
    )

    assert result.external_reference is not None
    assert result.external_reference.external_id == "900"
    assert publisher.calls[0].text == "Approved launch post"