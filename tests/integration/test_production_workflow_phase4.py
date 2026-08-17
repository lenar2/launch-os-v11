from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import create_engine

from launch_os_v11.ai_runtime.adapters.fake import FakeModelAdapter
from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.application.production_workflow import start_production_workflow
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings, get_settings
from launch_os_v11.production.registry import phase4_agent_registry
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.production.support import assert_phase4_no_external_execution
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.transport import RedisJobQueue
from launch_os_v11.runtime.worker import Worker
from tests.phase4_assert_support import (
    assert_no_duplicate_records,
    assert_phase4_fk_parity,
    assert_phase4_schema,
    assert_production_materialization,
    process_until_status,
)
from tests.phase4_script_support import revision_then_pass_script
from tests.phase4_seed_support import seed_approved_decision

pytestmark = [pytest.mark.postgres, pytest.mark.production_workflow]


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for Phase 4 tests")
    return value


def _redis_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_REDIS_URL") or os.environ.get(
        "LAUNCH_OS_REDIS_URL"
    )
    if not value:
        pytest.skip("LAUNCH_OS_TEST_REDIS_URL or LAUNCH_OS_REDIS_URL is required")
    return value


def _alembic_config(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Config:
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def test_phase4_governed_production_postgresql_redis_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    redis_url = _redis_url()
    config = _alembic_config(database_url, monkeypatch)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    redis_client: Redis = Redis.from_url(redis_url, decode_responses=True)
    queue_name = "launch_os_v11:test:phase4"
    redis_client.delete(queue_name)
    queue = RedisJobQueue(redis_client, queue_name=queue_name)
    clock = FixedClock(datetime(2026, 8, 18, 1, 0, tzinfo=UTC))

    try:
        assert_phase4_schema(engine)
        assert_phase4_fk_parity(engine)
        seed = seed_approved_decision(factory, now=clock.now())
        session = factory()
        try:
            with session.begin():
                result = start_production_workflow(
                    session,
                    scope=seed.scope,
                    queue=queue,
                    clock=clock,
                    decision_id=seed.decision_id,
                    max_revision_rounds=2,
                    correlation_id="corr-phase4",
                )
                workflow_id = result.workflow.id
                initial_job_id = result.job_id
                assert result.created
        finally:
            session.close()

        assert redis_client.lrange(queue_name, 0, -1) == [initial_job_id]
        adapter = FakeModelAdapter[BaseModel](
            script=revision_then_pass_script(seed.evidence_id)
        )
        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id="phase4-worker",
            clock=clock,
            handlers=compose_application_handler_registry(
                settings=Settings(),
                queue=queue,
                registry=phase4_agent_registry(),
                model_router=fake_model_router(adapter),
            ),
        )
        process_until_status(
            factory,
            worker=worker,
            workflow_id=workflow_id,
            status=ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL,
        )
        assert adapter.call_count == 17
        assert_production_materialization(factory, seed=seed, workflow_id=workflow_id)

        redis_client.rpush(queue_name, initial_job_id)
        duplicate = worker.process_one_from_queue(timeout_seconds=1)
        assert duplicate is not None
        assert duplicate.claimed is False
        assert_no_duplicate_records(factory, workflow_id=workflow_id)

        session = factory()
        try:
            assert_phase4_no_external_execution(session, seed.scope)
        finally:
            session.close()
    finally:
        redis_client.delete(queue_name)
        redis_client.close()
        engine.dispose()
        get_settings.cache_clear()
