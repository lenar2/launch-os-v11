from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from redis import Redis
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.application.commands import create_business, create_organization
from launch_os_v11.domain.enums import JobStatus, OutboxStatus
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    BusinessEventModel,
    JobModel,
    OutboxEventModel,
)
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import get_settings
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.contracts import (
    EXECUTABLE_JOB_TYPES,
    JOB_TYPE_AI_RUN_CONTROLLER,
    JOB_TYPE_RUNTIME_PROBE,
    RESERVED_JOB_TYPES,
)
from launch_os_v11.runtime.errors import SecretRejectedError
from launch_os_v11.runtime.repositories import (
    claim_job,
    create_job,
    enqueue_due_jobs,
    enqueue_pending_outbox,
)
from launch_os_v11.runtime.scheduler import RuntimeScheduler
from launch_os_v11.runtime.transport import RedisJobQueue
from launch_os_v11.runtime.worker import JobAttemptResult, Worker

pytestmark = [pytest.mark.postgres, pytest.mark.runtime]


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for runtime integration tests")
    return value


def _redis_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_REDIS_URL") or os.environ.get("LAUNCH_OS_REDIS_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_REDIS_URL or LAUNCH_OS_REDIS_URL is required")
    return value


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def _seed_scope(factory: sessionmaker[Session]) -> TenantScope:
    session = factory()
    try:
        with session.begin():
            organization = create_organization(session, name="Runtime Org")
            business = create_business(
                session,
                organization_id=organization.id,
                name="Runtime Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="runtime-seed",
            ).record
            session.flush()
            for outbox in session.scalars(select(OutboxEventModel)).all():
                outbox.status = OutboxStatus.PUBLISHED.value
            session.flush()
        return TenantScope(
            organization_id=organization.id,
            business_id=business.id,
        )
    finally:
        session.close()


def _create_probe_job(
    factory: sessionmaker[Session],
    *,
    scope: TenantScope,
    clock: FixedClock,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
    max_attempts: int = 3,
    available_at: datetime | None = None,
    correlation_id: str = "runtime-correlation",
    causation_id: str | None = "runtime-causation",
) -> str:
    session = factory()
    try:
        with session.begin():
            job = create_job(
                session,
                scope=scope,
                job_type=JOB_TYPE_RUNTIME_PROBE,
                payload=payload or {"outcome": "success"},
                payload_schema_version=1,
                idempotency_key=idempotency_key,
                clock=clock,
                max_attempts=max_attempts,
                available_at=available_at,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            return job.id
    finally:
        session.close()


def _job(session: Session, job_id: str) -> JobModel:
    job = session.get(JobModel, job_id)
    assert job is not None
    return job


def _assert_queue_empty(redis_client: Redis, queue: RedisJobQueue) -> None:
    assert redis_client.llen(queue.queue_name) == 0


def _process_expected_job(
    worker: Worker,
    *,
    expected_job_id: str,
    timeout_seconds: int = 1,
    max_messages: int = 10,
) -> JobAttemptResult:
    seen: list[tuple[str, str, bool]] = []
    for _ in range(max_messages):
        result = worker.process_one_from_queue(timeout_seconds=timeout_seconds)
        assert result is not None, (
            f"expected job {expected_job_id} was not delivered; "
            f"seen deliveries: {seen}"
        )
        seen.append((result.job_id, result.status, result.claimed))
        if result.job_id == expected_job_id:
            return result
    pytest.fail(
        f"expected job {expected_job_id} was not delivered within "
        f"{max_messages} messages; seen deliveries: {seen}"
    )


def test_phase2a_postgresql_redis_runtime_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    redis_url = _redis_url()
    config = _alembic_config(database_url, monkeypatch)
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    redis_client: Redis = Redis.from_url(redis_url, decode_responses=True)
    queue_name = "launch_os_v11:test:phase2a"
    redis_client.delete(queue_name)
    queue = RedisJobQueue(redis_client, queue_name=queue_name)
    clock = FixedClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    worker = Worker(
        session_factory=factory,
        queue=queue,
        worker_id="worker-a",
        clock=clock,
        lease_seconds=30,
        retry_backoff_seconds=60,
    )

    try:
        assert JOB_TYPE_AI_RUN_CONTROLLER in EXECUTABLE_JOB_TYPES
        assert JOB_TYPE_AI_RUN_CONTROLLER not in RESERVED_JOB_TYPES
        assert "ai.run_agent" not in RESERVED_JOB_TYPES
        _assert_job_schema(engine)
        scope = _seed_scope(factory)

        success_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-success",
            payload={"outcome": "success", "write_business_event": True},
            correlation_id="corr-success",
            causation_id="cause-success",
        )
        queue.enqueue(success_job_id)
        result = _process_expected_job(worker, expected_job_id=success_job_id)
        assert result.claimed
        assert result.status == JobStatus.SUCCEEDED.value
        session = factory()
        try:
            job = _job(session, success_job_id)
            assert job.attempt_count == 1
            assert job.status == JobStatus.SUCCEEDED.value
            event = session.scalar(
                select(BusinessEventModel).where(
                    BusinessEventModel.correlation_id == "corr-success"
                )
            )
            assert event is not None
            assert event.causation_id == "cause-success"
        finally:
            session.close()

        concurrent_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-concurrent",
        )
        session_one = factory()
        session_two = factory()
        try:
            with session_one.begin():
                claimed_one = claim_job(
                    session_one,
                    job_id=concurrent_job_id,
                    worker_id="worker-one",
                    clock=clock,
                    lease_duration=timedelta(seconds=30),
                )
            with session_two.begin():
                claimed_two = claim_job(
                    session_two,
                    job_id=concurrent_job_id,
                    worker_id="worker-two",
                    clock=clock,
                    lease_duration=timedelta(seconds=30),
                )
            assert claimed_one is not None
            assert claimed_two is None
        finally:
            session_one.close()
            session_two.close()
        session = factory()
        try:
            with session.begin():
                concurrent_job = _job(session, concurrent_job_id)
                concurrent_job.status = JobStatus.FAILED.value
                concurrent_job.completed_at = clock.now()
                concurrent_job.lease_owner = None
                concurrent_job.lease_expires_at = None
        finally:
            session.close()

        duplicate_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-duplicate",
            payload={"outcome": "success", "write_business_event": True},
            correlation_id="corr-duplicate",
        )
        queue.enqueue(duplicate_job_id)
        queue.enqueue(duplicate_job_id)
        duplicate_result = _process_expected_job(worker, expected_job_id=duplicate_job_id)
        assert duplicate_result.status == JobStatus.SUCCEEDED.value
        duplicate_redelivery = worker.process_one_from_queue(timeout_seconds=1)
        assert duplicate_redelivery is not None
        assert duplicate_redelivery.job_id == duplicate_job_id
        assert duplicate_redelivery.claimed is False
        session = factory()
        try:
            assert _job(session, duplicate_job_id).attempt_count == 1
            assert (
                session.scalar(
                    select(func.count()).select_from(BusinessEventModel).where(
                        BusinessEventModel.correlation_id == "corr-duplicate"
                    )
                )
                == 1
            )
        finally:
            session.close()

        retry_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-retry",
            payload={"transient_until_attempt": 1, "write_business_event": True},
            correlation_id="corr-retry",
        )
        queue.enqueue(retry_job_id)
        retry_result = _process_expected_job(worker, expected_job_id=retry_job_id)
        assert retry_result.status == JobStatus.RETRY_WAIT.value
        session = factory()
        try:
            retry_job = _job(session, retry_job_id)
            assert retry_job.attempt_count == 1
            assert retry_job.available_at == clock.now() + timedelta(seconds=60)
            assert (
                session.scalar(
                    select(func.count()).select_from(BusinessEventModel).where(
                        BusinessEventModel.correlation_id == "corr-retry"
                    )
                )
                == 0
            )
            assert enqueue_due_jobs(session, queue=queue, clock=clock) == 0
        finally:
            session.close()
        _assert_queue_empty(redis_client, queue)
        clock.advance(timedelta(seconds=60))
        scheduler = RuntimeScheduler(session_factory=factory, queue=queue, clock=clock)
        scheduled = scheduler.run_once()
        assert scheduled.outbox_jobs_enqueued == 0
        assert scheduled.due_jobs_enqueued == 1
        retry_success = _process_expected_job(worker, expected_job_id=retry_job_id)
        assert retry_success.status == JobStatus.SUCCEEDED.value
        _assert_queue_empty(redis_client, queue)

        permanent_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-permanent",
            payload={"outcome": "permanent"},
        )
        queue.enqueue(permanent_job_id)
        permanent_result = _process_expected_job(worker, expected_job_id=permanent_job_id)
        assert permanent_result.status == JobStatus.FAILED.value

        max_attempt_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-max-attempt",
            payload={"outcome": "transient"},
            max_attempts=1,
        )
        queue.enqueue(max_attempt_job_id)
        max_attempt_result = _process_expected_job(worker, expected_job_id=max_attempt_job_id)
        assert max_attempt_result.status == JobStatus.FAILED.value

        lease_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-lease",
        )
        session = factory()
        try:
            with session.begin():
                assert claim_job(
                    session,
                    job_id=lease_job_id,
                    worker_id="worker-lease",
                    clock=clock,
                    lease_duration=timedelta(seconds=10),
                )
        finally:
            session.close()
        clock.advance(timedelta(seconds=11))
        recovered = scheduler.run_once()
        assert recovered.recovered_leases >= 1
        session = factory()
        try:
            lease_job = _job(session, lease_job_id)
            assert lease_job.status == JobStatus.RETRY_WAIT.value
            lease_job.status = JobStatus.FAILED.value
            lease_job.completed_at = clock.now()
            session.commit()
        finally:
            session.close()
        redis_client.delete(queue_name)

        future_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-future",
            available_at=clock.now() + timedelta(hours=1),
        )
        session = factory()
        try:
            assert enqueue_due_jobs(session, queue=queue, clock=clock) == 0
            assert _job(session, future_job_id).status == JobStatus.QUEUED.value
        finally:
            session.close()
        _assert_queue_empty(redis_client, queue)

        lost_message_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-message-loss",
        )
        recovered_delivery = scheduler.run_once()
        assert recovered_delivery.due_jobs_enqueued >= 1
        delivered = worker.process_one_from_queue(timeout_seconds=1)
        while delivered is not None and delivered.job_id != lost_message_job_id:
            delivered = worker.process_one_from_queue(timeout_seconds=1)
        assert delivered is not None
        assert delivered.status == JobStatus.SUCCEEDED.value

        outbox_event_id = _assert_repeated_outbox_dispatch(factory, queue, worker, scope, clock)
        session = factory()
        try:
            outbox = session.get(OutboxEventModel, outbox_event_id)
            assert outbox is not None
            assert outbox.status == OutboxStatus.PUBLISHED.value
        finally:
            session.close()

        rollback_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-rollback",
            payload={"outcome": "transient", "write_business_event": True},
            max_attempts=2,
            correlation_id="corr-rollback",
        )
        queue.enqueue(rollback_job_id)
        rollback_result = _process_expected_job(worker, expected_job_id=rollback_job_id)
        assert rollback_result.status == JobStatus.RETRY_WAIT.value
        session = factory()
        try:
            assert (
                session.scalar(
                    select(func.count()).select_from(BusinessEventModel).where(
                        BusinessEventModel.correlation_id == "corr-rollback"
                    )
                )
                == 0
            )
        finally:
            session.close()

        escape_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-scope-escape",
            payload={"escape_scope": True},
        )
        queue.enqueue(escape_job_id)
        escape_result = _process_expected_job(worker, expected_job_id=escape_job_id)
        assert escape_result.status == JobStatus.FAILED.value
        session = factory()
        try:
            assert _job(session, escape_job_id).error_class == "TenantScopeViolation"
            assert (
                session.scalar(
                    select(func.count()).select_from(BusinessEventModel).where(
                        BusinessEventModel.event_type == "runtime.scope_escape"
                    )
                )
                == 0
            )
        finally:
            session.close()

        session = factory()
        try:
            with pytest.raises(SecretRejectedError), session.begin():
                create_job(
                    session,
                    scope=scope,
                    job_type=JOB_TYPE_RUNTIME_PROBE,
                    payload={"api_token": "do-not-store"},
                    payload_schema_version=1,
                    idempotency_key="runtime-secret-payload",
                    clock=clock,
                )
        finally:
            session.close()

        redaction_job_id = _create_probe_job(
            factory,
            scope=scope,
            clock=clock,
            idempotency_key="runtime-error-redaction",
            payload={"outcome": "permanent_secret_error"},
        )
        queue.enqueue(redaction_job_id)
        redaction_result = _process_expected_job(worker, expected_job_id=redaction_job_id)
        assert redaction_result.status == JobStatus.FAILED.value
        session = factory()
        try:
            redaction_job = _job(session, redaction_job_id)
            assert redaction_job.status == JobStatus.FAILED.value
            assert redaction_job.error_summary is not None
            assert "[REDACTED]" in redaction_job.error_summary
            assert "placeholder-value" not in redaction_job.error_summary
        finally:
            session.close()

        command.downgrade(config, "base")
        assert "jobs" not in set(inspect(engine).get_table_names())
        command.upgrade(config, "head")
        _assert_job_schema(engine)
    finally:
        redis_client.delete(queue_name)
        redis_client.close()
        engine.dispose()
        get_settings.cache_clear()


def _assert_job_schema(engine) -> None:
    inspector = inspect(engine)
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    assert {
        "payload_schema_version",
        "attempt_count",
        "max_attempts",
        "available_at",
        "started_at",
        "completed_at",
        "lease_owner",
        "lease_expires_at",
        "error_class",
        "error_summary",
        "correlation_id",
        "causation_id",
        "idempotency_key",
    }.issubset(job_columns)
    indexes = {index["name"] for index in inspector.get_indexes("jobs")}
    assert "ix_jobs_due_scan" in indexes
    assert "ix_jobs_claim_scan" in indexes
    assert "uq_jobs_tenant_type_idempotency" in indexes


def _assert_repeated_outbox_dispatch(
    factory: sessionmaker[Session],
    queue: RedisJobQueue,
    worker: Worker,
    scope: TenantScope,
    clock: FixedClock,
) -> str:
    session = factory()
    try:
        with session.begin():
            outbox = OutboxEventModel(
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                event_type="runtime.outbox",
                aggregate_type="RuntimeProbe",
                aggregate_id="runtime-outbox",
                payload={},
                status=OutboxStatus.PENDING.value,
                occurred_at=clock.now(),
                correlation_id="corr-outbox-dispatch",
                causation_id="cause-outbox-dispatch",
                created_at=clock.now(),
            )
            session.add(outbox)
        outbox_event_id = outbox.id
    finally:
        session.close()

    for _ in range(2):
        session = factory()
        try:
            with session.begin():
                assert enqueue_pending_outbox(session, queue=queue, clock=clock) >= 1
        finally:
            session.close()

    session = factory()
    try:
        assert (
            session.scalar(
                select(func.count()).select_from(JobModel).where(
                    JobModel.idempotency_key == f"outbox:{outbox_event_id}"
                )
            )
            == 1
        )
        dispatch_job = session.scalar(
            select(JobModel).where(JobModel.idempotency_key == f"outbox:{outbox_event_id}")
        )
        assert dispatch_job is not None
        assert dispatch_job.correlation_id == "corr-outbox-dispatch"
        assert dispatch_job.causation_id == outbox_event_id
    finally:
        session.close()

    first = worker.process_one_from_queue(timeout_seconds=1)
    while first is not None and first.job_id != dispatch_job.id:
        first = worker.process_one_from_queue(timeout_seconds=1)
    assert first is not None
    assert first.status == JobStatus.SUCCEEDED.value
    second = worker.process_one_from_queue(timeout_seconds=1)
    if second is not None and second.job_id == dispatch_job.id:
        assert second.claimed is False
    return outbox_event_id
