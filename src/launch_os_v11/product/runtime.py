"""In-process governed runtime for the local Launch Room.

Uses SQLite plus the existing worker and fake model router. It never calls a
paid provider and never constructs a live Telegram connector.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.ai_runtime.context import ContextBudget
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.domain.enums import JobStatus
from launch_os_v11.persistence.models import Base, JobModel
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.grant import ensure_grant_tables
from launch_os_v11.product.script import (
    LaunchScriptFacts,
    SyntheticLaunchAdapter,
    bind_launch_script_facts,
    clear_launch_script_facts,
)
from launch_os_v11.production.context import ProductionContextBuilder
from launch_os_v11.runtime.clock import Clock, SystemClock
from launch_os_v11.runtime.transport import JobQueue
from launch_os_v11.runtime.worker import Worker


class MemoryJobQueue:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.messages.append(job_id)

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        del timeout_seconds
        if not self.messages:
            return None
        return self.messages.pop(0)


class LaunchRoomRuntime:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        queue: MemoryJobQueue,
        worker: Worker,
        clock: Clock,
    ) -> None:
        self.session_factory = session_factory
        self.queue: JobQueue = queue
        self._messages = queue
        self.worker = worker
        self.clock = clock

    @classmethod
    def memory(cls) -> LaunchRoomRuntime:
        return cls.open("sqlite+pysqlite:///:memory:")

    @classmethod
    def local_file(cls) -> LaunchRoomRuntime:
        path = Path("var") / "launch-room.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls.open(f"sqlite+pysqlite:///{path.resolve()}")

    @classmethod
    def open(cls, database_url: str, *, environment: str = "local") -> LaunchRoomRuntime:
        if environment not in {"local", "test"}:
            raise ProductError(
                "production_isolated",
                "Launch Room demonstration is not available outside local and test.",
            )
        if not database_url.startswith("sqlite"):
            raise ProductError(
                "production_isolated",
                "Launch Room demonstration cannot attach to a non-local database.",
            )
        connect_args = {"check_same_thread": False}
        engine_kwargs: dict[str, object] = {"future": True, "connect_args": connect_args}
        if database_url.endswith(":memory:"):
            engine_kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **engine_kwargs)
        Base.metadata.create_all(engine)
        ensure_grant_tables(engine)
        factory = create_session_factory(engine)
        queue = MemoryJobQueue()
        adapter = SyntheticLaunchAdapter()
        clock = SystemClock()
        settings = Settings(
            LAUNCH_OS_ENV="local",
            LAUNCH_OS_DATABASE_URL="sqlite+pysqlite:///:memory:",
            LAUNCH_OS_FEATURE_V11_AI_TEAM=False,
        )
        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id="launch-room",
            clock=clock,
            handlers=compose_application_handler_registry(
                settings=settings,
                queue=queue,
                model_router=fake_model_router(adapter),
                context_builder=ProductionContextBuilder(
                    budget=ContextBudget(max_items=40, max_content_chars=12000)
                ),
            ),
        )
        return cls(
            session_factory=factory,
            queue=queue,
            worker=worker,
            clock=clock,
        )

    def drain(self, facts: LaunchScriptFacts, *, limit: int = 240) -> None:
        bind_launch_script_facts(facts)
        try:
            for _ in range(limit):
                if not self._messages.messages:
                    return
                result = self.worker.process_one_from_queue()
                if result is None:
                    return
                if result.status != JobStatus.SUCCEEDED.value:
                    raise ProductError(
                        "workflow_failed",
                        "Governed job "
                        f"{result.job_id} ended as {result.status}: "
                        f"{self._job_error(result.job_id)}",
                    )
            raise ProductError("workflow_failed", "Governed job queue did not drain")
        finally:
            clear_launch_script_facts()

    def _job_error(self, job_id: str) -> str:
        session = self.session_factory()
        try:
            job = session.get(JobModel, job_id)
            if job is None or not job.error_summary:
                return "no error summary"
            return job.error_summary
        finally:
            session.close()
