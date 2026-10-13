from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import create_engine, func, inspect, select

from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep, FakeModelAdapter
from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.ai_runtime.contracts import ModelResultKind
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.application.production_workflow import start_production_workflow
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.execution.service import create_action_proposal
from launch_os_v11.persistence.models import ActionModel, AgentRunModel, AssetModel
from launch_os_v11.persistence.production_models import AssetReviewModel, ProductionWorkflowModel
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings, get_settings
from launch_os_v11.production.registry import (
    REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS,
    phase4_agent_registry,
)
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.transport import RedisJobQueue
from launch_os_v11.runtime.worker import Worker
from tests.phase4_assert_support import process_until_status
from tests.phase4_script_support import _asset_payload, _controller_payload, _strategy_payload
from tests.phase4_seed_support import seed_approved_decision

pytestmark = [pytest.mark.postgres, pytest.mark.production_workflow]
SCENARIOS = (
    ("instagram", "yoga course", "Yoga course sample. Reply PILOT.", "SHORT_FORM_SCRIPT_DRAFT"),
    ("instagram", "bookstore", "New books preview. Reply PILOT.", "SHORT_FORM_SCRIPT_DRAFT"),
    ("tiktok", "language tutor", "Learn a new word. Reply PILOT.", "SHORT_FORM_SCRIPT_DRAFT"),
    ("tiktok", "craft studio", "See the studio process. Reply PILOT.", "SHORT_FORM_SCRIPT_DRAFT"),
    (
        "youtube",
        "nutrition educator",
        "Nutrition basics class. Reply PILOT.",
        "YOUTUBE_SCRIPT_DRAFT",
    ),
    ("youtube", "coding tutor", "Simple code tutorial. Reply PILOT.", "YOUTUBE_SCRIPT_DRAFT"),
)
REJECT_SCENARIOS = (
    ("instagram", "unsupported guarantee", "Guaranteed success. Reply PILOT.", "ESCALATED"),
    ("tiktok", "coercive sales", "If you don't buy you will regret it. Reply PILOT.", "BLOCKED"),
    ("youtube", "missing-proof", "We have record results. Reply PILOT.", "INVALID_OUTPUT"),
)


@pytest.mark.parametrize(
    "provider,scenario,body,asset_type,expected_status",
    [(*case, "PRODUCTION_READY") for case in SCENARIOS]
    + [
        (
            provider,
            scenario,
            body,
            "SHORT_FORM_SCRIPT_DRAFT" if provider != "youtube" else "YOUTUBE_SCRIPT_DRAFT",
            status,
        )
        for provider, scenario, body, status in REJECT_SCENARIOS
    ],
)
def test_channel_native_draft_controls_without_external_writes(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    scenario: str,
    body: str,
    asset_type: str,
    expected_status: str,
) -> None:
    db_url = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    redis_url = os.environ.get("LAUNCH_OS_TEST_REDIS_URL")
    if not db_url or not redis_url:
        pytest.skip("isolated PostgreSQL+Redis required")
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    reset_engine = create_engine(db_url, future=True)
    try:
        tables = [
            name for name in inspect(reset_engine).get_table_names() if name != "alembic_version"
        ]
        if tables:
            quoted = ", ".join(
                reset_engine.dialect.identifier_preparer.quote(name) for name in tables
            )
            with reset_engine.begin() as connection:
                connection.exec_driver_sql(f"TRUNCATE TABLE {quoted} CASCADE")
    finally:
        reset_engine.dispose()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(db_url, future=True)
    factory = create_session_factory(engine)
    client = Redis.from_url(redis_url, decode_responses=True)
    queue_name = f"p009:r3:{provider}:{scenario.replace(' ', '-')}"
    client.delete(queue_name)
    queue = RedisJobQueue(client, queue_name=queue_name)
    clock = FixedClock(datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
    try:
        assets = ("short script",) if provider != "youtube" else ("YouTube script", "thumbnail")
        seed = seed_approved_decision(
            factory, now=clock.now(), launch_provider=provider, required_assets=assets
        )
        with factory.begin() as session:
            started = start_production_workflow(
                session,
                scope=seed.scope,
                queue=queue,
                clock=clock,
                decision_id=seed.decision_id,
                max_revision_rounds=0 if expected_status != "PRODUCTION_READY" else 2,
            )
            workflow_id = started.workflow.id
        strategy = _strategy_payload(seed.evidence_id)
        strategy["channel_format"] = asset_type
        strategy["content_job"] = f"Produce draft for {scenario}"
        asset_payload = _asset_payload(seed.evidence_id, body=body)
        if scenario == "missing-proof":
            asset_payload["claim_inventory"][0]["evidence_ref"] = None
        steps = [
            FakeAdapterScriptStep(kind=ModelResultKind.PARSED, payload=strategy),
            FakeAdapterScriptStep(kind=ModelResultKind.PARSED, payload=asset_payload),
        ]
        steps.extend(
            FakeAdapterScriptStep(
                kind=ModelResultKind.PARSED,
                payload=_controller_payload(
                    key.removeprefix("ai.controller.asset_"),
                    seed.evidence_id,
                    verdict=ControllerVerdict.PASS,
                ),
            )
            for key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
        )
        adapter = FakeModelAdapter[BaseModel](script=steps)
        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id=f"p009-native-{provider}",
            clock=clock,
            handlers=compose_application_handler_registry(
                settings=Settings(),
                queue=queue,
                registry=phase4_agent_registry(),
                model_router=fake_model_router(adapter),
            ),
        )
        if expected_status == "INVALID_OUTPUT":
            processed = []
            for _ in range(30):
                job = worker.process_one_from_queue(timeout_seconds=1)
                if job is None:
                    break
                processed.append(job.status)
            assert "FAILED" in processed
            with factory() as session:
                writer = session.scalar(
                    select(AgentRunModel).where(
                        AgentRunModel.idempotency_key
                        == f"production_workflow:{workflow_id}:asset:v1"
                    )
                )
                assert writer is not None and writer.status == "INVALID_OUTPUT"
                assert session.scalar(select(func.count()).select_from(ActionModel)) == 0
            return
        process_until_status(
            factory,
            worker=worker,
            workflow_id=workflow_id,
            status=ProductionWorkflowStatus(expected_status),
        )
        with factory() as session:
            workflow = session.get(ProductionWorkflowModel, workflow_id)
            assert workflow is not None
            assert workflow.status == expected_status
            assert workflow.final_asset_version_id is not None
            assert workflow.asset_id is not None
            asset = session.get(AssetModel, workflow.asset_id)
            assert asset is not None and asset.asset_type == asset_type
            writer = session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.idempotency_key == f"production_workflow:{workflow.id}:asset:v1"
                )
            )
            assert writer is not None
            expected = (
                "ai.production.youtube_script_writer"
                if provider == "youtube"
                else "ai.production.short_form_script_writer"
            )
            assert writer.agent_contract_key == expected
            assert writer.output_data is not None
            assert writer.output_data["body"] == body
            assert len(writer.output_data["evidence_refs"]) == 1
            reviews = session.scalars(
                select(AssetReviewModel).where(AssetReviewModel.workflow_id == workflow_id)
            ).all()
            assert len(reviews) == len(REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS)
            assert all(r.verdict == ControllerVerdict.PASS.value for r in reviews)
            assert expected_status in {
                "PRODUCTION_READY",
                "ESCALATED",
                "BLOCKED",
            }
            assert session.scalar(select(func.count()).select_from(ActionModel)) == 0
            if expected_status == "PRODUCTION_READY":
                # Even a forged approval-ready state must not leak social drafts
                # into the Telegram-only execution engine.
                workflow.status = ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value
                with pytest.raises(PermanentJobError, match="non-Telegram draft assets"):
                    create_action_proposal(
                        session,
                        scope=seed.scope,
                        production_workflow_id=workflow.id,
                        connector_account_id="fake-telegram-account",
                        clock=clock,
                    )
                session.rollback()
            assert adapter.call_count == 9
    finally:
        client.delete(queue_name)
        client.close()
        engine.dispose()
        get_settings.cache_clear()
