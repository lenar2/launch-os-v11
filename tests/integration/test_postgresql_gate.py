import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from launch_os_v11.api.readiness import check_database_readiness
from launch_os_v11.application.commands import (
    CommandContext,
    create_business,
    create_business_event,
    create_goal,
    create_organization,
)
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    BusinessEventModel,
    BusinessModel,
    GoalModel,
    OutboxEventModel,
)
from launch_os_v11.persistence.repositories import ScopedRepository
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import Settings, get_settings

pytestmark = pytest.mark.postgres


EXPECTED_TABLES = {
    "users",
    "organizations",
    "businesses",
    "business_memberships",
    "goals",
    "constraints",
    "products",
    "offers",
    "channels",
    "source_records",
    "evidence",
    "claims",
    "hypotheses",
    "information_needs",
    "business_snapshots",
    "campaigns",
    "launches",
    "launch_phases",
    "decisions",
    "decision_alternatives",
    "controller_reviews",
    "experiments",
    "experiment_rules",
    "experiment_results",
    "creative_briefs",
    "assets",
    "asset_versions",
    "publications",
    "permission_policies",
    "actions",
    "approvals",
    "executions",
    "business_events",
    "outbox_events",
    "jobs",
    "agent_definitions",
    "agent_runs",
    "audit_logs",
    "feature_flags",
    "learnings",
    "alembic_version",
}


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def _assert_schema_contract(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)

        outbox_indexes = {
            tuple(index["column_names"]) for index in inspector.get_indexes("outbox_events")
        }
        assert ("correlation_id",) in outbox_indexes

        asset_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("asset_versions")
        }
        assert ("asset_id", "version_number") in asset_uniques

        action_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("actions")
        }
        assert ("idempotency_key",) in action_uniques

        offer_fks = {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys("offers")
        }
        assert ("business_id",) in offer_fks
        assert ("product_id",) in offer_fks

        approval_fks = {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys("approvals")
        }
        assert ("action_id",) in approval_fks
        assert ("approved_by_user_id",) in approval_fks

        action_checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("actions")
        }
        assert "ck_actions_target_object_version_positive" in action_checks
    finally:
        engine.dispose()


def _assert_repository_contract(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    session = factory()
    try:
        org = create_organization(session, name="Postgres Org")
        business_a = create_business(
            session,
            organization_id=org.id,
            name="Business A",
            timezone="UTC",
            actor_user_id=None,
            correlation_id="pg-corr-a",
        ).record
        business_b = create_business(
            session,
            organization_id=org.id,
            name="Business B",
            timezone="UTC",
            actor_user_id=None,
            correlation_id="pg-corr-b",
        ).record
        context_a = CommandContext(
            organization_id=org.id,
            business_id=business_a.id,
            actor_user_id=None,
            correlation_id="pg-corr-goal",
        )
        context_b = CommandContext(
            organization_id=org.id,
            business_id=business_b.id,
            actor_user_id=None,
            correlation_id="pg-corr-goal-b",
        )
        goal_a = create_goal(session, context=context_a, title="A", target="A target").record
        goal_b = create_goal(session, context=context_b, title="B", target="B target").record
        session.commit()

        repo_a = ScopedRepository(
            session,
            TenantScope(organization_id=org.id, business_id=business_a.id),
            GoalModel,
        )
        assert repo_a.get(goal_a.id) is not None
        assert repo_a.get(goal_b.id) is None

        occurred = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
        recorded = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        event = create_business_event(
            session,
            context=context_a,
            event_type="postgres.integration_observed",
            occurred_at=occurred,
            recorded_at=recorded,
        ).record
        session.commit()
        persisted_event = session.get(BusinessEventModel, event.id)
        assert persisted_event is not None
        assert persisted_event.occurred_at != persisted_event.recorded_at
    finally:
        session.close()
        engine.dispose()


def _assert_atomic_rollback(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    seed_session = factory()
    try:
        organization = create_organization(seed_session, name="Rollback Org")
        seed_session.commit()
        organization_id = organization.id
    finally:
        seed_session.close()

    rollback_session: Session = factory()
    try:
        with pytest.raises(RuntimeError), rollback_session.begin():
            create_business(
                rollback_session,
                organization_id=organization_id,
                name="Rollback Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="pg-rollback",
            )
            raise RuntimeError("force rollback")
    finally:
        rollback_session.close()

    check_session = factory()
    try:
        assert check_session.scalar(select(func.count()).select_from(BusinessModel)) == 0
        assert check_session.scalar(
            select(func.count()).select_from(OutboxEventModel).where(
                OutboxEventModel.correlation_id == "pg-rollback"
            )
        ) == 0
    finally:
        check_session.close()
        engine.dispose()


def test_postgresql_16_migration_and_integration_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    config = _alembic_config(database_url, monkeypatch)

    command.upgrade(config, "head")
    _assert_schema_contract(database_url)
    readiness = check_database_readiness(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL=database_url,
        )
    )
    assert readiness.ready
    assert readiness.database == "ok"
    _assert_atomic_rollback(database_url)
    _assert_repository_contract(database_url)

    command.downgrade(config, "base")
    engine = create_engine(database_url, future=True)
    try:
        assert "businesses" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    _assert_schema_contract(database_url)
    get_settings.cache_clear()
