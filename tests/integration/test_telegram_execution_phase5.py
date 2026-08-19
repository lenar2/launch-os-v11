from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import create_engine, func, inspect, select

from launch_os_v11.ai_runtime.adapters.fake import FakeModelAdapter
from launch_os_v11.ai_runtime.composition import fake_model_router
from launch_os_v11.application.composition import compose_application_handler_registry
from launch_os_v11.application.production_workflow import start_production_workflow
from launch_os_v11.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    ExecutionStatus,
    PublicationStatus,
)
from launch_os_v11.execution.contracts import PermissionOutcome
from launch_os_v11.execution.service import (
    approve_action_proposal,
    create_action_proposal,
    probe_and_register_telegram_connector,
    set_global_execution_controls,
)
from launch_os_v11.execution.telegram import FakeTelegramConnector
from launch_os_v11.persistence.execution_models import (
    ActionProposalDetailModel,
    ExecutionControllerReviewModel,
    ExternalReferenceModel,
    PermissionEvaluationModel,
    PublicationExecutionLinkModel,
)
from launch_os_v11.persistence.models import (
    ActionModel,
    ApprovalModel,
    AssetVersionModel,
    AuditLogModel,
    BusinessMembershipModel,
    ChannelModel,
    ExecutionModel,
    PublicationModel,
)
from launch_os_v11.persistence.production_models import ProductionWorkflowModel
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings, get_settings
from launch_os_v11.production.registry import phase4_agent_registry
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.transport import RedisJobQueue
from launch_os_v11.runtime.worker import Worker
from tests.phase4_assert_support import process_until_status
from tests.phase4_script_support import revision_then_pass_script
from tests.phase4_seed_support import seed_approved_decision

pytestmark = [pytest.mark.postgres, pytest.mark.telegram_execution]


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for Phase 5 tests")
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


def _clear_test_database(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        tables = [
            table
            for table in inspect(engine).get_table_names()
            if table != "alembic_version"
        ]
        if not tables:
            return
        preparer = engine.dialect.identifier_preparer
        table_list = ", ".join(preparer.quote(table) for table in tables)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"TRUNCATE TABLE {table_list} CASCADE")
    finally:
        engine.dispose()


def test_phase5_governed_telegram_execution_postgresql_redis_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    redis_url = _redis_url()
    config = _alembic_config(database_url, monkeypatch)
    _clear_test_database(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    redis_client: Redis = Redis.from_url(redis_url, decode_responses=True)
    queue_name = "launch_os_v11:test:phase5"
    redis_client.delete(queue_name)
    queue = RedisJobQueue(redis_client, queue_name=queue_name)
    clock = FixedClock(datetime(2026, 8, 19, 2, 0, tzinfo=UTC))
    telegram = FakeTelegramConnector(message_id="5001")

    try:
        _assert_phase5_schema(engine)
        seed = seed_approved_decision(factory, now=clock.now())
        session = factory()
        try:
            with session.begin():
                production = start_production_workflow(
                    session,
                    scope=seed.scope,
                    queue=queue,
                    clock=clock,
                    decision_id=seed.decision_id,
                    max_revision_rounds=2,
                    correlation_id="corr-phase5-production",
                )
                production_workflow_id = production.workflow.id
        finally:
            session.close()

        adapter = FakeModelAdapter[BaseModel](
            script=revision_then_pass_script(seed.evidence_id)
        )
        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id="phase5-worker",
            clock=clock,
            handlers=compose_application_handler_registry(
                settings=Settings(),
                queue=queue,
                registry=phase4_agent_registry(),
                model_router=fake_model_router(adapter),
                telegram_connector=telegram,
            ),
        )
        process_until_status(
            factory,
            worker=worker,
            workflow_id=production_workflow_id,
            status=ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL,
        )
        assert adapter.call_count == 17

        action_id, execution_id, execution_job_id = _create_and_approve_action(
            factory,
            production_workflow_id=production_workflow_id,
            queue=queue,
            clock=clock,
            telegram=telegram,
            channel_suffix="primary",
        )
        result = worker.process_one_from_queue(timeout_seconds=1)
        assert result is not None
        assert result.job_id == execution_job_id
        assert result.claimed
        assert result.status == "SUCCEEDED"
        assert telegram.call_count == 1
        _assert_success_materialized(
            factory,
            action_id=action_id,
            execution_id=execution_id,
            expected_message_id="5001",
        )

        redis_client.rpush(queue_name, execution_job_id)
        duplicate = worker.process_one_from_queue(timeout_seconds=1)
        assert duplicate is not None
        assert duplicate.job_id == execution_job_id
        assert duplicate.claimed is False
        assert telegram.call_count == 1

        paused_action_id, paused_execution_id, paused_job_id = _create_and_approve_action(
            factory,
            production_workflow_id=production_workflow_id,
            queue=queue,
            clock=clock,
            telegram=telegram,
            channel_suffix="paused",
        )
        session = factory()
        try:
            with session.begin():
                set_global_execution_controls(
                    session,
                    scope=seed.scope,
                    updated_by_user_id="phase4-owner",
                    clock=clock,
                    execution_paused=True,
                )
        finally:
            session.close()
        paused_result = worker.process_one_from_queue(timeout_seconds=1)
        assert paused_result is not None
        assert paused_result.job_id == paused_job_id
        assert telegram.call_count == 1
        session = factory()
        try:
            paused_execution = session.get(ExecutionModel, paused_execution_id)
            paused_action = session.get(ActionModel, paused_action_id)
            assert paused_execution is not None
            assert paused_action is not None
            assert paused_execution.status == ExecutionStatus.BLOCKED.value
            assert paused_action.status == ActionStatus.BLOCKED.value
        finally:
            session.close()

        session = factory()
        try:
            with session.begin():
                set_global_execution_controls(
                    session,
                    scope=seed.scope,
                    updated_by_user_id="phase4-owner",
                    clock=clock,
                    execution_paused=False,
                )
        finally:
            session.close()
        stale_action_id, stale_execution_id, stale_job_id = _create_and_approve_action(
            factory,
            production_workflow_id=production_workflow_id,
            queue=queue,
            clock=clock,
            telegram=telegram,
            channel_suffix="stale",
        )
        _supersede_final_asset_version(
            factory,
            production_workflow_id=production_workflow_id,
            now=clock.now(),
        )
        stale_result = worker.process_one_from_queue(timeout_seconds=1)
        assert stale_result is not None
        assert stale_result.job_id == stale_job_id
        assert telegram.call_count == 1
        session = factory()
        try:
            stale_execution = session.get(ExecutionModel, stale_execution_id)
            stale_action = session.get(ActionModel, stale_action_id)
            assert stale_execution is not None
            assert stale_action is not None
            assert stale_execution.status == ExecutionStatus.BLOCKED.value
            assert stale_action.status == ActionStatus.BLOCKED.value
            assert session.scalar(
                select(func.count()).select_from(PublicationModel)
            ) == 1
        finally:
            session.close()
    finally:
        redis_client.delete(queue_name)
        redis_client.close()
        engine.dispose()
        get_settings.cache_clear()


def _create_and_approve_action(
    factory,
    *,
    production_workflow_id: str,
    queue: RedisJobQueue,
    clock: FixedClock,
    telegram: FakeTelegramConnector,
    channel_suffix: str,
) -> tuple[str, str, str]:
    session = factory()
    try:
        with session.begin():
            workflow = session.get(ProductionWorkflowModel, production_workflow_id)
            assert workflow is not None
            channel = ChannelModel(
                id=f"phase5-channel-{channel_suffix}",
                organization_id=workflow.organization_id,
                business_id=workflow.business_id,
                provider="telegram",
                handle=f"@phase5_{channel_suffix}",
                capabilities={"send_message": True},
                version=1,
            )
            session.add(channel)
            session.flush()
            membership = session.scalar(
                select(BusinessMembershipModel).where(
                    BusinessMembershipModel.business_id == workflow.business_id,
                    BusinessMembershipModel.user_id == "phase4-owner",
                )
            )
            if membership is None:
                session.add(
                    BusinessMembershipModel(
                        id="phase5-owner-membership",
                        organization_id=workflow.organization_id,
                        business_id=workflow.business_id,
                        user_id="phase4-owner",
                        role="OWNER",
                    )
                )
                session.flush()
            scope = workflow_scope(workflow)
            account = probe_and_register_telegram_connector(
                session,
                scope=scope,
                channel_id=channel.id,
                target_chat_id=f"-100{channel_suffix}",
                connector=telegram,
                clock=clock,
            )
            proposal = create_action_proposal(
                session,
                scope=scope,
                production_workflow_id=workflow.id,
                connector_account_id=account.id,
                clock=clock,
                correlation_id=f"corr-phase5-{channel_suffix}",
            )
            assert proposal.created
            assert proposal.action.status == ActionStatus.APPROVAL_REQUIRED.value
            assert proposal.permission.outcome == PermissionOutcome.APPROVAL_REQUIRED.value
            assert session.scalar(
                select(func.count())
                .select_from(ExecutionControllerReviewModel)
                .where(ExecutionControllerReviewModel.action_id == proposal.action.id)
            ) == 5
            assert session.scalar(
                select(func.count())
                .select_from(PermissionEvaluationModel)
                .where(PermissionEvaluationModel.action_id == proposal.action.id)
            ) == 1
            approved = approve_action_proposal(
                session,
                scope=scope,
                action_id=proposal.action.id,
                approved_by_user_id="phase4-owner",
                queue=queue,
                clock=clock,
            )
            assert approved.approval.status == ApprovalStatus.APPROVED.value
            return proposal.action.id, approved.execution.id, approved.job_id
    finally:
        session.close()


def workflow_scope(workflow: ProductionWorkflowModel):
    from launch_os_v11.domain.scope import TenantScope

    return TenantScope(
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
    )


def _assert_success_materialized(
    factory,
    *,
    action_id: str,
    execution_id: str,
    expected_message_id: str,
) -> None:
    session = factory()
    try:
        action = session.get(ActionModel, action_id)
        execution = session.get(ExecutionModel, execution_id)
        assert action is not None
        assert execution is not None
        assert action.status == ActionStatus.EXECUTED.value
        assert execution.status == ExecutionStatus.SUCCEEDED.value
        assert execution.external_reference == expected_message_id
        assert session.scalar(
            select(func.count())
            .select_from(ApprovalModel)
            .where(ApprovalModel.action_id == action_id)
        ) == 1
        publication = session.scalar(
            select(PublicationModel).where(
                PublicationModel.business_id == action.business_id,
                PublicationModel.status == PublicationStatus.PUBLISHED.value,
            )
        )
        assert publication is not None
        external = session.scalar(
            select(ExternalReferenceModel).where(
                ExternalReferenceModel.execution_id == execution_id
            )
        )
        assert external is not None
        assert external.external_id == expected_message_id
        assert session.scalar(
            select(func.count())
            .select_from(PublicationExecutionLinkModel)
            .where(PublicationExecutionLinkModel.execution_id == execution_id)
        ) == 1
        detail = session.scalar(
            select(ActionProposalDetailModel).where(
                ActionProposalDetailModel.action_id == action_id
            )
        )
        assert detail is not None
        assert "token" not in str(detail.delivery_payload).lower()
        audits = session.scalars(
            select(AuditLogModel).where(AuditLogModel.business_id == action.business_id)
        ).all()
        assert all("telegram.bot_token" not in str(row.payload) for row in audits)
    finally:
        session.close()


def _supersede_final_asset_version(
    factory,
    *,
    production_workflow_id: str,
    now: datetime,
) -> None:
    session = factory()
    try:
        with session.begin():
            workflow = session.get(ProductionWorkflowModel, production_workflow_id)
            assert workflow is not None
            assert workflow.final_asset_version_id is not None
            current = session.get(AssetVersionModel, workflow.final_asset_version_id)
            assert current is not None
            next_version = AssetVersionModel(
                id="phase5-stale-replacement",
                organization_id=current.organization_id,
                business_id=current.business_id,
                asset_id=current.asset_id,
                version_number=current.version_number + 1,
                body=current.body + "\nChanged after approval.",
                created_by_user_id="phase4-owner",
                provenance={"source": "phase5-stale-test"},
                created_at=now,
            )
            session.add(next_version)
            session.flush()
            workflow.final_asset_version_id = next_version.id
            session.flush()
    finally:
        session.close()


def _assert_phase5_schema(engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {
        "connector_accounts",
        "action_proposal_details",
        "execution_controller_reviews",
        "permission_evaluations",
        "global_execution_controls",
        "external_references",
        "publication_execution_links",
    }.issubset(tables)
