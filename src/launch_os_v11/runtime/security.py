from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from launch_os_v11.runtime.errors import SecretRejectedError

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)

SAFE_TELEMETRY_KEYS = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "token_usage",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|credential|password|private[_-]?key|secret|token)\s*=\s*[^,\s;]+"
)


def assert_no_secrets(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered not in SAFE_TELEMETRY_KEYS and any(
                fragment in lowered for fragment in SECRET_KEY_FRAGMENTS
            ):
                raise SecretRejectedError(f"secret-like key rejected at {path}.{key}")
            assert_no_secrets(item, path=f"{path}.{key}")
        return
    if isinstance(value, str):
        if SECRET_ASSIGNMENT.search(value):
            raise SecretRejectedError(f"secret-like value rejected at {path}")
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        for index, item in enumerate(value):
            assert_no_secrets(item, path=f"{path}[{index}]")


def redacted_error_summary(error: BaseException, *, max_length: int = 500) -> str:
    summary = f"{error.__class__.__name__}: {error}"
    redacted = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", summary)
    if len(redacted) > max_length:
        return redacted[: max_length - 3] + "..."
    return redacted
