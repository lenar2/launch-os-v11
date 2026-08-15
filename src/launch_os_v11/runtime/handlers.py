from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import OutboxStatus
from launch_os_v11.persistence.models import BusinessEventModel, OutboxEventModel
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_OUTBOX_DISPATCH,
    JOB_TYPE_RUNTIME_PROBE,
    RuntimeJobContext,
)
from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError
from launch_os_v11.runtime.security import assert_no_secrets


class JobHandler(Protocol):
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        """Run one idempotent attempt inside the worker attempt transaction."""


class OutboxDispatchHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        assert_no_secrets(payload)
        outbox_event_id = payload.get("outbox_event_id")
        if not isinstance(outbox_event_id, str):
            raise PermanentJobError("outbox_event_id is required")
        outbox_event = session.get(OutboxEventModel, outbox_event_id)
        if outbox_event is None:
            raise PermanentJobError(f"outbox event not found: {outbox_event_id}")
        context.scope.assert_matches(
            organization_id=outbox_event.organization_id,
            business_id=outbox_event.business_id,
        )
        if outbox_event.status == OutboxStatus.PUBLISHED.value:
            return
        outbox_event.status = OutboxStatus.PUBLISHED.value
        outbox_event.published_at = clock.now()


class RuntimeProbeHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        assert_no_secrets(payload)
        if payload.get("write_business_event") is True:
            session.add(
                BusinessEventModel(
                    organization_id=context.organization_id,
                    business_id=context.business_id,
                    event_type="runtime.probe",
                    occurred_at=clock.now(),
                    recorded_at=clock.now(),
                    payload={"job_id": context.job_id},
                    correlation_id=context.correlation_id,
                    causation_id=context.causation_id,
                )
            )
        if payload.get("escape_scope") is True:
            session.add(
                BusinessEventModel(
                    organization_id="escaped-organization",
                    business_id="escaped-business",
                    event_type="runtime.scope_escape",
                    occurred_at=clock.now(),
                    recorded_at=clock.now(),
                    payload={"job_id": context.job_id},
                    correlation_id=context.correlation_id,
                    causation_id=context.causation_id,
                )
            )

        transient_until_attempt = payload.get("transient_until_attempt")
        if (
            isinstance(transient_until_attempt, int)
            and context.attempt_count <= transient_until_attempt
        ):
            raise TransientJobError("deterministic transient probe failure")

        outcome = payload.get("outcome", "success")
        if outcome == "success":
            return
        if outcome == "transient":
            raise TransientJobError("deterministic transient probe failure")
        if outcome == "permanent":
            raise PermanentJobError("deterministic permanent probe failure")
        if outcome == "permanent_secret_error":
            raise PermanentJobError("provider returned token=placeholder-value")
        raise PermanentJobError(f"unsupported runtime probe outcome: {outcome}")


def default_handler_registry() -> dict[str, JobHandler]:
    return {
        JOB_TYPE_OUTBOX_DISPATCH: OutboxDispatchHandler(),
        JOB_TYPE_RUNTIME_PROBE: RuntimeProbeHandler(),
    }
