from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import JobStatus, OutboxStatus
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import JobModel, OutboxEventModel
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_OUTBOX_DISPATCH,
    REGISTERED_JOB_TYPES,
)
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets, redacted_error_summary
from launch_os_v11.runtime.transport import JobQueue


def create_job(
    session: Session,
    *,
    scope: TenantScope,
    job_type: str,
    payload: dict[str, object],
    payload_schema_version: int,
    idempotency_key: str,
    clock: Clock,
    max_attempts: int = 3,
    available_at: datetime | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> JobModel:
    if job_type not in REGISTERED_JOB_TYPES:
        raise PermanentJobError(f"unknown job type: {job_type}")
    if payload_schema_version < 1:
        raise PermanentJobError("payload_schema_version must be positive")
    if max_attempts < 1:
        raise PermanentJobError("max_attempts must be positive")
    assert_no_secrets(payload)

    existing = session.scalar(
        select(JobModel).where(
            JobModel.organization_id == scope.organization_id,
            JobModel.business_id == scope.business_id,
            JobModel.job_type == job_type,
            JobModel.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing

    job = JobModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        payload=payload,
        payload_schema_version=payload_schema_version,
        attempt_count=0,
        max_attempts=max_attempts,
        available_at=available_at or clock.now(),
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    session.flush()
    return job


def claim_job(
    session: Session,
    *,
    job_id: str,
    worker_id: str,
    clock: Clock,
    lease_duration: timedelta,
) -> JobModel | None:
    now = clock.now()
    claimable = or_(
        and_(
            JobModel.status.in_([JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value]),
            JobModel.available_at <= now,
        ),
        and_(
            JobModel.status == JobStatus.RUNNING.value,
            JobModel.lease_expires_at.is_not(None),
            JobModel.lease_expires_at <= now,
        ),
    )
    statement = (
        update(JobModel)
        .where(JobModel.id == job_id, claimable)
        .values(
            status=JobStatus.RUNNING.value,
            attempt_count=JobModel.attempt_count + 1,
            started_at=now,
            completed_at=None,
            lease_owner=worker_id,
            lease_expires_at=now + lease_duration,
        )
        .returning(JobModel.id)
    )
    claimed_id = session.scalar(statement)
    if claimed_id is None:
        return None
    return session.get(JobModel, claimed_id)


def mark_job_succeeded(session: Session, *, job: JobModel, clock: Clock) -> None:
    job.status = JobStatus.SUCCEEDED.value
    job.completed_at = clock.now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_class = None
    job.error_summary = None


def mark_job_failed_or_retrying(
    session: Session,
    *,
    job_id: str,
    error: BaseException,
    retry: bool,
    clock: Clock,
    retry_backoff: timedelta,
) -> JobModel:
    job = session.get(JobModel, job_id)
    if job is None:
        raise PermanentJobError(f"job not found: {job_id}")
    job.error_class = error.__class__.__name__
    job.error_summary = redacted_error_summary(error)
    job.lease_owner = None
    job.lease_expires_at = None
    if retry and job.attempt_count < job.max_attempts:
        job.status = JobStatus.RETRY_WAIT.value
        job.available_at = clock.now() + retry_backoff
        job.completed_at = None
    else:
        job.status = JobStatus.FAILED.value
        job.completed_at = clock.now()
    return job


def due_job_ids(session: Session, *, clock: Clock, limit: int = 100) -> Sequence[str]:
    rows = session.scalars(
        select(JobModel.id)
        .where(
            JobModel.status.in_([JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value]),
            JobModel.available_at <= clock.now(),
        )
        .order_by(JobModel.available_at, JobModel.created_at)
        .limit(limit)
    ).all()
    return list(rows)


def enqueue_due_jobs(
    session: Session,
    *,
    queue: JobQueue,
    clock: Clock,
    limit: int = 100,
) -> int:
    count = 0
    for job_id in due_job_ids(session, clock=clock, limit=limit):
        queue.enqueue(job_id)
        count += 1
    return count


def recover_expired_leases(session: Session, *, clock: Clock) -> int:
    expired_jobs = session.scalars(
        select(JobModel).where(
            JobModel.status == JobStatus.RUNNING.value,
            JobModel.lease_expires_at.is_not(None),
            JobModel.lease_expires_at <= clock.now(),
        )
    ).all()
    for job in expired_jobs:
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempt_count >= job.max_attempts:
            job.status = JobStatus.FAILED.value
            job.completed_at = clock.now()
            job.error_class = job.error_class or "LeaseExpired"
            job.error_summary = job.error_summary or "Lease expired at max attempts."
        else:
            job.status = JobStatus.RETRY_WAIT.value
            job.available_at = clock.now()
    return len(expired_jobs)


def enqueue_pending_outbox(
    session: Session,
    *,
    queue: JobQueue,
    clock: Clock,
    limit: int = 100,
) -> int:
    outbox_events = session.scalars(
        select(OutboxEventModel)
        .where(OutboxEventModel.status == OutboxStatus.PENDING.value)
        .order_by(OutboxEventModel.created_at)
        .limit(limit)
    ).all()
    count = 0
    for outbox_event in outbox_events:
        scope = TenantScope(
            organization_id=outbox_event.organization_id,
            business_id=outbox_event.business_id,
        )
        job = create_job(
            session,
            scope=scope,
            job_type=JOB_TYPE_OUTBOX_DISPATCH,
            payload={"outbox_event_id": outbox_event.id},
            payload_schema_version=1,
            idempotency_key=f"outbox:{outbox_event.id}",
            clock=clock,
            max_attempts=3,
            available_at=clock.now(),
            correlation_id=outbox_event.correlation_id,
            causation_id=outbox_event.id,
        )
        queue.enqueue(job.id)
        count += 1
    return count
