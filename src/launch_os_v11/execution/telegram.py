from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from launch_os_v11.execution.contracts import (
    TELEGRAM_SECRET_REF,
    ConnectorReadiness,
    TelegramAmbiguousOutcome,
    TelegramConnectorRejected,
    TelegramPublishResult,
    TelegramPublishTextCommand,
)
from launch_os_v11.platform.config import Settings


class SettingsSecretResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(self, secret_ref: str) -> str:
        if secret_ref != TELEGRAM_SECRET_REF:
            raise TelegramConnectorRejected("TELEGRAM_SECRET_REF_UNSUPPORTED")
        if self._settings.telegram_bot_token is None:
            raise TelegramConnectorRejected("TELEGRAM_CREDENTIAL_UNAVAILABLE")
        value = self._settings.telegram_bot_token.get_secret_value().strip()
        if not value:
            raise TelegramConnectorRejected("TELEGRAM_CREDENTIAL_UNAVAILABLE")
        return value


class TelegramHttpConnector:
    def __init__(
        self,
        *,
        secret_resolver: SettingsSecretResolver,
        secret_ref: str = TELEGRAM_SECRET_REF,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._secret_resolver = secret_resolver
        self._secret_ref = secret_ref
        self._timeout_seconds = timeout_seconds

    def check_readiness(self, *, chat_id: str) -> ConnectorReadiness:
        try:
            me = self._read_call("getMe", {})
            bot_id = me.get("id")
            if not isinstance(bot_id, int | str):
                return ConnectorReadiness(
                    auth_healthy=False,
                    write_capability=False,
                    capabilities={},
                    error_class="TELEGRAM_INVALID_BOT_IDENTITY",
                )
            member = self._read_call(
                "getChatMember",
                {"chat_id": chat_id, "user_id": bot_id},
            )
        except TelegramConnectorRejected as error:
            return ConnectorReadiness(
                auth_healthy=False,
                write_capability=False,
                capabilities={},
                error_class=str(error),
            )

        status = member.get("status")
        can_post = member.get("can_post_messages")
        creator = status == "creator"
        administrator = status == "administrator"
        write_capability = creator or (administrator and can_post is True)
        return ConnectorReadiness(
            auth_healthy=True,
            write_capability=write_capability,
            capabilities={
                "send_message": True,
                "can_post_messages": write_capability,
                "member_status": status if isinstance(status, str) else "unknown",
            },
            bot_identity=str(bot_id),
            error_class=None if write_capability else "TELEGRAM_WRITE_FORBIDDEN",
        )

    def publish_text(
        self,
        command: TelegramPublishTextCommand,
    ) -> TelegramPublishResult:
        payload: dict[str, object] = {
            "chat_id": command.chat_id,
            "text": command.text,
            "disable_notification": command.disable_notification,
            "protect_content": command.protect_content,
        }
        result = self._write_call("sendMessage", payload)
        message_id = result.get("message_id")
        if not isinstance(message_id, int | str):
            raise TelegramAmbiguousOutcome("TELEGRAM_RESPONSE_MISSING_MESSAGE_ID")
        chat = result.get("chat")
        response_chat_id = command.chat_id
        if isinstance(chat, Mapping):
            raw_chat_id = chat.get("id")
            if isinstance(raw_chat_id, int | str):
                response_chat_id = str(raw_chat_id)
        return TelegramPublishResult(
            message_id=str(message_id),
            chat_id=response_chat_id,
        )

    def _read_call(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        try:
            return self._request(method, payload)
        except HTTPError as error:
            raise TelegramConnectorRejected(f"TELEGRAM_HTTP_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise TelegramConnectorRejected("TELEGRAM_READ_UNAVAILABLE") from None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            raise TelegramConnectorRejected("TELEGRAM_INVALID_RESPONSE") from None

    def _write_call(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        try:
            return self._request(method, payload)
        except HTTPError as error:
            raise TelegramConnectorRejected(f"TELEGRAM_HTTP_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise TelegramAmbiguousOutcome("TELEGRAM_TRANSPORT_AMBIGUOUS") from None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            raise TelegramAmbiguousOutcome("TELEGRAM_RESPONSE_AMBIGUOUS") from None

    def _request(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        token = self._secret_resolver.resolve(self._secret_ref)
        url = f"https://api.telegram.org/bot{token}/{method}"
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            raw = response.read()
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Telegram response must be an object")
        if decoded.get("ok") is not True:
            error_code = decoded.get("error_code")
            if isinstance(error_code, int):
                raise TelegramConnectorRejected(f"TELEGRAM_API_{error_code}")
            raise TelegramConnectorRejected("TELEGRAM_API_REJECTED")
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise ValueError("Telegram result must be an object")
        return cast(dict[str, Any], result)


@dataclass
class FakeTelegramConnector:
    message_id: str = "1001"
    readiness: ConnectorReadiness = field(
        default_factory=lambda: ConnectorReadiness(
            auth_healthy=True,
            write_capability=True,
            capabilities={"send_message": True, "can_post_messages": True},
            bot_identity="fake-bot",
        )
    )
    fail_mode: str | None = None
    calls: list[TelegramPublishTextCommand] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def check_readiness(self, *, chat_id: str) -> ConnectorReadiness:
        del chat_id
        return self.readiness

    def publish_text(
        self,
        command: TelegramPublishTextCommand,
    ) -> TelegramPublishResult:
        self.calls.append(command)
        if self.fail_mode == "rejected":
            raise TelegramConnectorRejected("TELEGRAM_FAKE_REJECTED")
        if self.fail_mode == "ambiguous":
            raise TelegramAmbiguousOutcome("TELEGRAM_FAKE_AMBIGUOUS")
        return TelegramPublishResult(
            message_id=self.message_id,
            chat_id=command.chat_id,
        )
