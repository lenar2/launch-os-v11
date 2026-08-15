from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    organization_id: str
    business_id: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
    causation_id: str | None = None
    actor_user_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    occurred_at: datetime = field(default_factory=utc_now)

    def child(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any] | None = None,
    ) -> "DomainEvent":
        return DomainEvent(
            event_type=event_type,
            organization_id=self.organization_id,
            business_id=self.business_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            correlation_id=self.correlation_id,
            causation_id=self.id,
            actor_user_id=self.actor_user_id,
            payload=payload or {},
        )
