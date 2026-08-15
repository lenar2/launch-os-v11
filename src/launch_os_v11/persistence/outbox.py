from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import OutboxStatus
from launch_os_v11.domain.events import DomainEvent
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import OutboxEventModel


def append_outbox_event(session: Session, event: DomainEvent) -> OutboxEventModel:
    row = OutboxEventModel(
        id=event.id,
        organization_id=event.organization_id,
        business_id=event.business_id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        payload=event.payload,
        status=OutboxStatus.PENDING.value,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        created_at=utc_now(),
    )
    session.add(row)
    return row
