from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


TELEGRAM_PUBLISH_ACTION = "telegram.publish_text"
TELEGRAM_SECRET_REF = "telegram.bot_token"


class PermissionOutcome(StrEnum):
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ALLOWED = "ALLOWED"


class ExecutionControllerType(StrEnum):
    SECURITY = "SECURITY"
    PRIVACY = "PRIVACY"
    PLATFORM = "PLATFORM"
    EXECUTION = "EXECUTION"
    COST = "COST"


@dataclass(frozen=True)
class ConnectorReadiness:
    auth_healthy: bool
    write_capability: bool
    capabilities: dict[str, object]
    bot_identity: str | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class TelegramPublishTextCommand:
    chat_id: str
    text: str
    disable_notification: bool = False
    protect_content: bool = False


@dataclass(frozen=True)
class TelegramPublishResult:
    message_id: str
    chat_id: str


class TelegramConnector(Protocol):
    def check_readiness(self, *, chat_id: str) -> ConnectorReadiness: ...

    def publish_text(
        self,
        command: TelegramPublishTextCommand,
    ) -> TelegramPublishResult: ...


class TelegramConnectorError(RuntimeError):
    pass


class TelegramConnectorRejected(TelegramConnectorError):
    pass


class TelegramAmbiguousOutcome(TelegramConnectorError):
    pass
