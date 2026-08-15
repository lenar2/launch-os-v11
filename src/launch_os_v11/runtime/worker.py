from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.domain.enums import JobStatus
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import JobModel
from launch_os_v11.runtime.clock import Clock, SystemClock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError
from launch_os_v11.runtime.handlers import JobHandler, default_handler_registry
from launch_os_v11.runtime.repositories import (
    claim_job,
    mark_job_failed_or_retrying,
    mark_job_succeeded,
)
from launch_os_v11.runtime.transport import JobQueue


@dataclass(frozen=True)
class JobAttemptResult:
    job_id: str
    claimed: bool
    status: str


class Worker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        queue: JobQueue,
        worker_id: str,
        clock: Clock | None = None,
        handlers: dict[str, JobHandler] | None = None,
        lease_seconds: int = 60,
        retry_backoff_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self.worker_id = worker_id
        self._clock = clock or SystemClock()
        self._handlers = handlers or default_handler_registry()
        self._lease_duration = timedelta(seconds=lease_seconds)
        self._retry_backoff = timedelta(seconds=retry_backoff_seconds)

    def process_one_from_queue(self, *, timeout_seconds: int = 1) -> JobAttemptResult | None:
        job_id = self._queue.dequeue(timeout_seconds=timeout_seconds)
        if job_id is None:
            return None
        return self.process_job_id(job_id)

    def process_job_id(self, job_id: str) -> JobAttemptResult:
        claimed = self._claim(job_id)
        if claimed is None:
            return JobAttemptResult(job_id=job_id, claimed=False, status="not_claimed")

        try:
            with self._session_factory() as session, session.begin():
                job = session.get(JobModel, job_id)
                if job is None:
                    raise PermanentJobError(f"job not found: {job_id}")
                if job.status != JobStatus.RUNNING.value or job.lease_owner != self.worker_id:
                    return JobAttemptResult(
                        job_id=job_id,
                        claimed=False,
                        status=job.status,
                    )
                handler = self._handlers.get(job.job_type)
                if handler is None:
                    raise PermanentJobError(f"no executable handler for {job.job_type}")
                context = RuntimeJobContext(
                    organization_id=job.organization_id,
                    business_id=job.business_id,
                    job_id=job.id,
                    job_type=job.job_type,
                    attempt_count=job.attempt_count,
                    correlation_id=job.correlation_id,
                    causation_id=job.causation_id,
                )
                handler.handle(
                    context=context,
                    payload=job.payload,
                    session=session,
                    clock=self._clock,
                )
                self._assert_session_scope(session, context.scope)
                mark_job_succeeded(session, job=job, clock=self._clock)
            return JobAttemptResult(job_id=job_id, claimed=True, status=JobStatus.SUCCEEDED.value)
        except TransientJobError as error:
            return self._record_failure(job_id, error=error, retry=True)
        except (PermanentJobError, TenantScopeViolation) as error:
            return self._record_failure(job_id, error=error, retry=False)
        except Exception as error:
            return self._record_failure(job_id, error=error, retry=False)

    def run_forever(self, *, stop_event: Event | None = None, timeout_seconds: int = 1) -> None:
        shutdown = stop_event or Event()
        while not shutdown.is_set():
            self.process_one_from_queue(timeout_seconds=timeout_seconds)

    def _claim(self, job_id: str) -> JobModel | None:
        with self._session_factory() as session, session.begin():
            return claim_job(
                session,
                job_id=job_id,
                worker_id=self.worker_id,
                clock=self._clock,
                lease_duration=self._lease_duration,
            )

    def _record_failure(
        self,
        job_id: str,
        *,
        error: BaseException,
        retry: bool,
    ) -> JobAttemptResult:
        with self._session_factory() as session, session.begin():
            job = mark_job_failed_or_retrying(
                session,
                job_id=job_id,
                error=error,
                retry=retry,
                clock=self._clock,
                retry_backoff=self._retry_backoff,
            )
            return JobAttemptResult(job_id=job_id, claimed=True, status=job.status)

    @staticmethod
    def _assert_session_scope(session: Session, scope: TenantScope) -> None:
        for instance in [*session.new, *session.dirty]:
            organization_id = getattr(instance, "organization_id", None)
            business_id = getattr(instance, "business_id", None)
            if isinstance(organization_id, str) and isinstance(business_id, str):
                scope.assert_matches(organization_id=organization_id, business_id=business_id)
