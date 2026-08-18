from pathlib import Path

import pytest

from launch_os_v11.execution.contracts import (
    TELEGRAM_SECRET_REF,
    ConnectorReadiness,
    TelegramConnectorRejected,
    TelegramPublishTextCommand,
)
from launch_os_v11.execution.telegram import FakeTelegramConnector, SettingsSecretResolver
from launch_os_v11.platform.config import Settings
from launch_os_v11.runtime.contracts import (
    EXECUTABLE_JOB_TYPES,
    JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
    RESERVED_JOB_TYPES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_phase5_execution_job_is_activated_not_reserved() -> None:
    assert JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH in EXECUTABLE_JOB_TYPES
    assert JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH not in RESERVED_JOB_TYPES


def test_fake_telegram_connector_is_deterministic() -> None:
    connector = FakeTelegramConnector(
        message_id="42",
        readiness=ConnectorReadiness(
            auth_healthy=True,
            write_capability=True,
            capabilities={"can_post_messages": True},
        ),
    )
    readiness = connector.check_readiness(chat_id="-1001")
    assert readiness.write_capability
    result = connector.publish_text(
        TelegramPublishTextCommand(chat_id="-1001", text="hello")
    )
    assert result.message_id == "42"
    assert connector.call_count == 1


def test_missing_telegram_secret_fails_with_sanitized_error() -> None:
    resolver = SettingsSecretResolver(Settings())
    with pytest.raises(TelegramConnectorRejected) as error:
        resolver.resolve(TELEGRAM_SECRET_REF)
    assert str(error.value) == "TELEGRAM_CREDENTIAL_UNAVAILABLE"


def test_production_workflow_still_has_no_execution_import() -> None:
    source = (
        ROOT / "src/launch_os_v11/application/production_workflow.py"
    ).read_text(encoding="utf-8")
    assert "launch_os_v11.execution" not in source
    assert "TelegramExecutionHandler" not in source
