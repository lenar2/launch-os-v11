from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.application.commands import create_business, create_organization
from launch_os_v11.domain.enums import JobStatus, OutboxStatus
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import BusinessEventModel, JobModel, OutboxEventModel
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.runtime.clock import Clock, FixedClock
from launch_os_v11.runtime.contracts import JOB_TYPE_RUNTIME_PROBE, RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.handlers import RuntimeProbeHandler
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.transport import JobQueue
from launch_os_v11.runtime.worker import Worker


class ListJobQueue:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.messages.append(job_id)

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        del timeout_seconds
        if not self.messages:
            return None
        return self.messages.pop(0)


class UnexpectedFailureHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        del context, payload, session, clock
        raise RuntimeError("unexpected provider token=placeholder-value")


@pytest.fixture()
def runtime_scope(engine: Engine) -> Iterator[tuple[sessionmaker[Session], TenantScope]]:
    factory = create_session_factory(engine)
    session = factory()
    try:
        with session.begin():
            organization = create_organization(session, name="Runtime Worker Org")
            business = create_business(
                session,
                organization_id=organization.id,
                name="Runtime Worker Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="runtime-worker-seed",
            ).record
            for outbox in session.scalars(select(OutboxEventModel)).all():
                outbox.status = OutboxStatus.PUBLISHED.value
        yield factory, TenantScope(
            organization_id=organization.id,
            business_id=business.id,
        )
    finally:
        session.close()


def test_runtime_probe_permanent_outcome_raises_explicit_permanent_error(
    session: Session,
) -> None:
    context = RuntimeJobContext(
        organization_id="org-runtime-direct",
        business_id="biz-runtime-direct",
        job_id="job-runtime-direct",
        job_type=JOB_TYPE_RUNTIME_PROBE,
        attempt_count=1,
        correlation_id="corr-runtime-direct",
        causation_id="cause-runtime-direct",
    )

    with pytest.raises(PermanentJobError):
        RuntimeProbeHandler().handle(
            context=context,
            payload={"outcome": "permanent"},
            session=session,
            clock=FixedClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC)),
        )


@pytest.mark.parametrize(
    ("payload", "max_attempts", "expected_status", "expected_error_class"),
    [
        ({"outcome": "success"}, 3, JobStatus.SUCCEEDED.value, None),
        ({"outcome": "permanent"}, 3, JobStatus.FAILED.value, "PermanentJobError"),
        ({"outcome": "transient"}, 1, JobStatus.FAILED.value, "TransientJobError"),
        (
            {"transient_until_attempt": 2},
            3,
            JobStatus.RETRY_WAIT.value,
            "TransientJobError",
        ),
    ],
)
def test_worker_records_runtime_probe_classification(
    runtime_scope: tuple[sessionmaker[Session], TenantScope],
    payload: dict[str, object],
    max_attempts: int,
    expected_status: str,
    expected_error_class: str | None,
) -> None:
    factory, scope = runtime_scope
    clock = FixedClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    queue = ListJobQueue()
    job_id = _create_runtime_probe_job(
        factory,
        scope=scope,
        clock=clock,
        queue=queue,
        idempotency_key=f"worker-classification-{expected_status}-{max_attempts}",
        payload=payload,
        max_attempts=max_attempts,
    )

    result = Worker(
        session_factory=factory,
        queue=queue,
        worker_id="worker-classification",
        clock=clock,
        retry_backoff_seconds=60,
    ).process_one_from_queue()

    assert result is not None
    assert result.job_id == job_id
    assert result.status == expected_status
    session = factory()
    try:
        job = _job(session, job_id)
        assert job.status == expected_status
        assert job.attempt_count == 1
        assert job.error_class == expected_error_class
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        if expected_status == JobStatus.RETRY_WAIT.value:
            assert job.completed_at is None
            expected_available_at = clock.now() + timedelta(seconds=60)
            if job.available_at.tzinfo is None:
                expected_available_at = expected_available_at.replace(tzinfo=None)
            assert job.available_at == expected_available_at
    finally:
        session.close()


def test_worker_records_unknown_exception_as_terminal_failed(
    runtime_scope: tuple[sessionmaker[Session], TenantScope],
) -> None:
    factory, scope = runtime_scope
    clock = FixedClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    queue = ListJobQueue()
    job_id = _create_runtime_probe_job(
        factory,
        scope=scope,
        clock=clock,
        queue=queue,
        idempotency_key="worker-unknown-terminal",
        payload={"outcome": "success"},
    )

    result = Worker(
        session_factory=factory,
        queue=queue,
        worker_id="worker-unknown",
        clock=clock,
        handlers={JOB_TYPE_RUNTIME_PROBE: UnexpectedFailureHandler()},
    ).process_one_from_queue()

    assert result is not None
    assert result.job_id == job_id
    assert result.status == JobStatus.FAILED.value
    session = factory()
    try:
        job = _job(session, job_id)
        assert job.error_class == "RuntimeError"
        assert job.error_summary is not None
        assert "[REDACTED]" in job.error_summary
        assert "placeholder-value" not in job.error_summary
    finally:
        session.close()


def test_worker_rolls_back_attempt_side_effects_before_retry_state_persists(
    runtime_scope: tuple[sessionmaker[Session], TenantScope],
) -> None:
    factory, scope = runtime_scope
    clock = FixedClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    queue = ListJobQueue()
    job_id = _create_runtime_probe_job(
        factory,
        scope=scope,
        clock=clock,
        queue=queue,
        idempotency_key="worker-rollback-before-retry-state",
        payload={"transient_until_attempt": 1, "write_business_event": True},
        correlation_id="corr-worker-rollback",
    )

    result = Worker(
        session_factory=factory,
        queue=queue,
        worker_id="worker-rollback",
        clock=clock,
    ).process_one_from_queue()

    assert result is not None
    assert result.job_id == job_id
    assert result.status == JobStatus.RETRY_WAIT.value
    session = factory()
    try:
        assert _job(session, job_id).status == JobStatus.RETRY_WAIT.value
        assert (
            session.scalar(
                select(BusinessEventModel).where(
                    BusinessEventModel.correlation_id == "corr-worker-rollback"
                )
            )
            is None
        )
    finally:
        session.close()


def _create_runtime_probe_job(
    factory: sessionmaker[Session],
    *,
    scope: TenantScope,
    clock: FixedClock,
    queue: JobQueue,
    idempotency_key: str,
    payload: dict[str, object],
    max_attempts: int = 3,
    correlation_id: str = "corr-worker",
) -> str:
    session = factory()
    try:
        with session.begin():
            job = create_job(
                session,
                scope=scope,
                job_type=JOB_TYPE_RUNTIME_PROBE,
                payload=payload,
                payload_schema_version=1,
                idempotency_key=idempotency_key,
                clock=clock,
                max_attempts=max_attempts,
                correlation_id=correlation_id,
                causation_id="cause-worker",
            )
            queue.enqueue(job.id)
            return job.id
    finally:
        session.close()


def _job(session: Session, job_id: str) -> JobModel:
    job = session.get(JobModel, job_id)
    assert job is not None
    return job
