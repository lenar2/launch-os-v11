from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from launch_os_v11.analytics.contracts import TelegramObservationUnavailable
from launch_os_v11.platform.config import Settings


class TelegramHttpObservationConnector:
    def __init__(self, *, settings: Settings, timeout_seconds: float = 15.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    def get_updates(
        self,
        *,
        offset: int | None,
        allowed_updates: Sequence[str],
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], ...]:
        token = self._token()
        payload: dict[str, object] = {
            "timeout": timeout_seconds,
            "allowed_updates": list(allowed_updates),
        }
        if offset is not None:
            payload["offset"] = offset
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
            decoded = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            raise TelegramObservationUnavailable(
                f"TELEGRAM_OBSERVATION_HTTP_{error.code}"
            ) from None
        except (URLError, TimeoutError, OSError):
            raise TelegramObservationUnavailable("TELEGRAM_OBSERVATION_UNAVAILABLE") from None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            raise TelegramObservationUnavailable("TELEGRAM_OBSERVATION_INVALID_RESPONSE") from None
        if not isinstance(decoded, dict) or decoded.get("ok") is not True:
            error_code = decoded.get("error_code") if isinstance(decoded, dict) else None
            suffix = str(error_code) if isinstance(error_code, int) else "REJECTED"
            raise TelegramObservationUnavailable(f"TELEGRAM_OBSERVATION_API_{suffix}")
        result = decoded.get("result")
        if not isinstance(result, list):
            raise TelegramObservationUnavailable("TELEGRAM_OBSERVATION_INVALID_RESULT")
        updates: list[dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict):
                raise TelegramObservationUnavailable("TELEGRAM_OBSERVATION_INVALID_UPDATE")
            updates.append(cast(dict[str, Any], item))
        return tuple(updates)

    def _token(self) -> str:
        if self._settings.telegram_bot_token is None:
            raise TelegramObservationUnavailable("TELEGRAM_CREDENTIAL_UNAVAILABLE")
        value = self._settings.telegram_bot_token.get_secret_value().strip()
        if not value:
            raise TelegramObservationUnavailable("TELEGRAM_CREDENTIAL_UNAVAILABLE")
        return value


@dataclass
class FakeTelegramObservationConnector:
    updates: list[dict[str, Any]] = field(default_factory=list)
    ignore_offset: bool = False
    calls: list[dict[str, object]] = field(default_factory=list)

    def get_updates(
        self,
        *,
        offset: int | None,
        allowed_updates: Sequence[str],
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], ...]:
        self.calls.append(
            {
                "offset": offset,
                "allowed_updates": tuple(allowed_updates),
                "timeout_seconds": timeout_seconds,
            }
        )
        allowed = set(allowed_updates)
        result: list[dict[str, Any]] = []
        for update in self.updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            if not self.ignore_offset and offset is not None and update_id < offset:
                continue
            event_type = next((key for key in allowed if key in update), None)
            if event_type is None:
                continue
            result.append(update)
        return tuple(result)
