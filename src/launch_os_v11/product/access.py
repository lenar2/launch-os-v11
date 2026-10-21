"""Server-side operator for Launch Room.

This is not a login and not a session. Callers that already established the
owner on the server construct it. HTTP must not build it from form or JSON fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.product.errors import ProductError


@dataclass(frozen=True)
class TrustedOperator:
    user_id: str
    scope: TenantScope

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ProductError("owner_required", "A trusted server user id is required.")
