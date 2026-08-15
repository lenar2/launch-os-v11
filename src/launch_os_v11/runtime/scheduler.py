from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.runtime.clock import Clock, SystemClock
from launch_os_v11.runtime.repositories import (
    enqueue_due_jobs,
    enqueue_pending_outbox,
    recover_expired_leases,
)
from launch_os_v11.runtime.transport import JobQueue


@dataclass(frozen=True)
class SchedulerRunResult:
    recovered_leases: int
    outbox_jobs_enqueued: int
    due_jobs_enqueued: int


class RuntimeScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        queue: JobQueue,
        clock: Clock | None = None,
        batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._clock = clock or SystemClock()
        self._batch_size = batch_size

    def run_once(self) -> SchedulerRunResult:
        with self._session_factory() as session, session.begin():
            recovered = recover_expired_leases(session, clock=self._clock)
            outbox_count = enqueue_pending_outbox(
                session,
                queue=self._queue,
                clock=self._clock,
                limit=self._batch_size,
            )
            due_count = enqueue_due_jobs(
                session,
                queue=self._queue,
                clock=self._clock,
                limit=self._batch_size,
            )
            return SchedulerRunResult(
                recovered_leases=recovered,
                outbox_jobs_enqueued=outbox_count,
                due_jobs_enqueued=due_count,
            )
