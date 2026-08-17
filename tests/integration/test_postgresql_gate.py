import os
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
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
    AuditLogModel,
    Base,
    BusinessEventModel,
    BusinessModel,
    GoalModel,
    OrganizationModel,
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
    "decision_approvals",
    "decision_candidates",
    "decision_workflows",
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
    "specialist_contributions",
    "audit_logs",
    "feature_flags",
    "learnings",
    "alembic_version",
}

ForeignKeyPair = tuple[str, str, str, str]

TENANT_SCOPED_TABLES = {
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
    "decision_approvals",
    "decision_candidates",
    "decision_workflows",
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
    "specialist_contributions",
    "audit_logs",
    "feature_flags",
    "learnings",
}

EXPECTED_FOREIGN_KEYS: set[ForeignKeyPair] = (
    {
        (table_name, "organization_id", "organizations", "id")
        for table_name in TENANT_SCOPED_TABLES
    }
    | {(table_name, "business_id", "businesses", "id") for table_name in TENANT_SCOPED_TABLES}
    | {
        ("businesses", "organization_id", "organizations", "id"),
        ("business_memberships", "user_id", "users", "id"),
        ("offers", "product_id", "products", "id"),
        ("evidence", "source_record_id", "source_records", "id"),
        ("launches", "campaign_id", "campaigns", "id"),
        ("launches", "offer_id", "offers", "id"),
        ("launches", "goal_id", "goals", "id"),
        ("launches", "channel_id", "channels", "id"),
        ("launches", "snapshot_id", "business_snapshots", "id"),
        ("launch_phases", "launch_id", "launches", "id"),
        ("decisions", "snapshot_id", "business_snapshots", "id"),
        ("decisions", "supersedes_decision_id", "decisions", "id"),
        ("decisions", "source_candidate_id", "decision_candidates", "id"),
        ("decision_alternatives", "decision_id", "decisions", "id"),
        ("decision_approvals", "approved_by_user_id", "users", "id"),
        ("decision_approvals", "candidate_id", "decision_candidates", "id"),
        ("decision_approvals", "decision_id", "decisions", "id"),
        ("decision_approvals", "workflow_id", "decision_workflows", "id"),
        ("decision_candidates", "chief_agent_run_id", "agent_runs", "id"),
        ("decision_candidates", "previous_candidate_id", "decision_candidates", "id"),
        ("decision_candidates", "snapshot_id", "business_snapshots", "id"),
        ("decision_candidates", "workflow_id", "decision_workflows", "id"),
        ("decision_workflows", "final_approval_id", "decision_approvals", "id"),
        ("decision_workflows", "final_decision_id", "decisions", "id"),
        ("decision_workflows", "launch_id", "launches", "id"),
        ("decision_workflows", "snapshot_id", "business_snapshots", "id"),
        ("controller_reviews", "decision_id", "decisions", "id"),
        ("controller_reviews", "agent_run_id", "agent_runs", "id"),
        ("controller_reviews", "decision_candidate_id", "decision_candidates", "id"),
        ("controller_reviews", "snapshot_id", "business_snapshots", "id"),
        ("experiments", "decision_id", "decisions", "id"),
        ("experiments", "hypothesis_id", "hypotheses", "id"),
        ("experiment_rules", "experiment_id", "experiments", "id"),
        ("experiment_results", "experiment_id", "experiments", "id"),
        ("creative_briefs", "decision_id", "decisions", "id"),
        ("assets", "creative_brief_id", "creative_briefs", "id"),
        ("asset_versions", "asset_id", "assets", "id"),
        ("publications", "asset_version_id", "asset_versions", "id"),
        ("publications", "channel_id", "channels", "id"),
        ("approvals", "action_id", "actions", "id"),
        ("approvals", "approved_by_user_id", "users", "id"),
        ("executions", "action_id", "actions", "id"),
        ("executions", "approval_id", "approvals", "id"),
        ("business_events", "source_record_id", "source_records", "id"),
        ("agent_runs", "agent_definition_id", "agent_definitions", "id"),
        ("agent_runs", "job_id", "jobs", "id"),
        ("specialist_contributions", "agent_run_id", "agent_runs", "id"),
        ("specialist_contributions", "snapshot_id", "business_snapshots", "id"),
        ("specialist_contributions", "workflow_id", "decision_workflows", "id"),
        ("learnings", "decision_id", "decisions", "id"),
        ("learnings", "experiment_id", "experiments", "id"),
    }
)


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

        agent_definition_indexes = {
            index["name"] for index in inspector.get_indexes("agent_definitions")
        }
        assert "ix_agent_definitions_contract_key" in agent_definition_indexes
        assert "ix_agent_definitions_contract_fingerprint" in agent_definition_indexes
        agent_definition_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("agent_definitions")
        }
        assert (
            "organization_id",
            "business_id",
            "contract_key",
            "contract_version",
        ) in agent_definition_uniques
        agent_definition_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("agent_definitions")
        }
        assert "ck_agent_definitions_contract_version_positive" in agent_definition_checks
        assert (
            "ck_agent_definitions_output_schema_version_positive"
            in agent_definition_checks
        )

        agent_run_indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
        assert "ix_agent_runs_job_id" in agent_run_indexes
        assert "ix_agent_runs_context_hash" in agent_run_indexes
        assert "ix_agent_runs_provider_response_id" in agent_run_indexes
        assert "ix_agent_runs_idempotency_key" in agent_run_indexes
        agent_run_checks = {
            constraint["name"] for constraint in inspector.get_check_constraints("agent_runs")
        }
        assert "ck_agent_runs_status_phase2b" in agent_run_checks
        assert "ck_agent_runs_payload_schema_positive" in agent_run_checks
        assert "ck_agent_runs_contract_version_positive" in agent_run_checks
        assert "ck_agent_runs_output_schema_version_positive" in agent_run_checks

        workflow_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("decision_workflows")
        }
        assert "ck_decision_workflows_status_phase3" in workflow_checks
        candidate_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("decision_candidates")
        }
        assert ("workflow_id", "version_number") in candidate_uniques
        assert ("chief_agent_run_id",) in candidate_uniques
        approval_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("decision_approvals")
        }
        assert ("decision_id", "action_type", "object_version_id") in approval_uniques
    finally:
        engine.dispose()


def _metadata_foreign_keys() -> set[ForeignKeyPair]:
    return {
        (
            table.name,
            foreign_key.parent.name,
            foreign_key.column.table.name,
            foreign_key.column.name,
        )
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
    }


def _database_foreign_keys(database_url: str) -> set[ForeignKeyPair]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        result: set[ForeignKeyPair] = set()
        for table_name in EXPECTED_TABLES - {"alembic_version"}:
            for foreign_key in inspector.get_foreign_keys(table_name):
                referred_table = foreign_key["referred_table"]
                assert referred_table is not None
                for constrained_column, referred_column in zip(
                    foreign_key["constrained_columns"],
                    foreign_key["referred_columns"],
                    strict=True,
                ):
                    result.add((table_name, constrained_column, referred_table, referred_column))
        return result
    finally:
        engine.dispose()


def _assert_foreign_key_parity(database_url: str) -> None:
    assert _database_foreign_keys(database_url) == EXPECTED_FOREIGN_KEYS
    assert _metadata_foreign_keys() == EXPECTED_FOREIGN_KEYS


def _capture_insert_order(engine: Engine) -> tuple[list[str], Any]:
    inserted_tables: list[str] = []

    def before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        normalized = statement.strip().lower()
        if not normalized.startswith("insert into "):
            return
        table_name = normalized.removeprefix("insert into ").split(" ", 1)[0]
        inserted_tables.append(table_name.strip('"'))

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    return inserted_tables, before_cursor_execute


def _first_insert_index(inserted_tables: list[str], table_name: str) -> int:
    return inserted_tables.index(table_name)


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

    rollback_session: Session = factory()
    try:
        with pytest.raises(RuntimeError), rollback_session.begin():
            organization = create_organization(rollback_session, name="Rollback Org")
            create_business(
                rollback_session,
                organization_id=organization.id,
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
        assert (
            check_session.scalar(
                select(func.count()).select_from(OrganizationModel).where(
                    OrganizationModel.name == "Rollback Org"
                )
            )
            == 0
        )
        assert (
            check_session.scalar(
                select(func.count()).select_from(BusinessModel).where(
                    BusinessModel.name == "Rollback Business"
                )
            )
            == 0
        )
        assert (
            check_session.scalar(
                select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.correlation_id == "pg-rollback"
                )
            )
            == 0
        )
        assert check_session.scalar(
            select(func.count()).select_from(OutboxEventModel).where(
                OutboxEventModel.correlation_id == "pg-rollback"
            )
        ) == 0
    finally:
        check_session.close()
        engine.dispose()


def _assert_orphan_side_effects_rejected(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    seed_session = factory()
    try:
        organization = create_organization(seed_session, name="Side Effect FK Org")
        seed_session.commit()
        organization_id = organization.id
    finally:
        seed_session.close()

    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    audit_session = factory()
    try:
        with pytest.raises(IntegrityError), audit_session.begin():
            audit_session.add(
                AuditLogModel(
                    organization_id=organization_id,
                    business_id="missing-business",
                    actor_user_id=None,
                    action="orphan_audit",
                    object_type="Business",
                    object_id="missing-business",
                    payload={},
                    correlation_id="pg-orphan-audit",
                )
            )
        audit_session.rollback()
    finally:
        audit_session.close()

    outbox_session = factory()
    try:
        with pytest.raises(IntegrityError), outbox_session.begin():
            outbox_session.add(
                OutboxEventModel(
                    organization_id=organization_id,
                    business_id="missing-business",
                    event_type="orphan.outbox",
                    aggregate_type="Business",
                    aggregate_id="missing-business",
                    payload={},
                    status="PENDING",
                    occurred_at=now,
                    correlation_id="pg-orphan-outbox",
                    created_at=now,
                )
            )
        outbox_session.rollback()
    finally:
        outbox_session.close()

    check_session = factory()
    try:
        assert (
            check_session.scalar(
                select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.correlation_id == "pg-orphan-audit"
                )
            )
            == 0
        )
        assert (
            check_session.scalar(
                select(func.count()).select_from(OutboxEventModel).where(
                    OutboxEventModel.correlation_id == "pg-orphan-outbox"
                )
            )
            == 0
        )
    finally:
        check_session.close()
        engine.dispose()


def _assert_parent_graph_regression(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    inserted_tables, listener = _capture_insert_order(engine)

    parent_session = factory()
    try:
        with parent_session.begin():
            organization = create_organization(parent_session, name="Parent Graph Org")
            business = create_business(
                parent_session,
                organization_id=organization.id,
                name="Parent Graph Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="pg-parent-graph",
            ).record
            assert business.organization_id == organization.id
            assert parent_session.in_transaction()

            observer_session = factory()
            try:
                assert observer_session.get(OrganizationModel, organization.id) is None
                assert observer_session.get(BusinessModel, business.id) is None
                assert (
                    observer_session.scalar(
                        select(func.count()).select_from(AuditLogModel).where(
                            AuditLogModel.correlation_id == "pg-parent-graph"
                        )
                    )
                    == 0
                )
                assert (
                    observer_session.scalar(
                        select(func.count()).select_from(OutboxEventModel).where(
                            OutboxEventModel.correlation_id == "pg-parent-graph"
                        )
                    )
                    == 0
                )
            finally:
                observer_session.close()

        assert (
            parent_session.scalar(
                select(func.count()).select_from(BusinessModel).where(
                    BusinessModel.id == business.id
                )
            )
            == 1
        )
        assert (
            parent_session.scalar(
                select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.correlation_id == "pg-parent-graph"
                )
            )
            == 1
        )
        assert (
            parent_session.scalar(
                select(func.count()).select_from(OutboxEventModel).where(
                    OutboxEventModel.correlation_id == "pg-parent-graph"
                )
            )
            == 1
        )
        organization_insert = _first_insert_index(inserted_tables, "organizations")
        business_insert = _first_insert_index(inserted_tables, "businesses")
        audit_insert = _first_insert_index(inserted_tables, "audit_logs")
        outbox_insert = _first_insert_index(inserted_tables, "outbox_events")
        assert organization_insert < business_insert
        assert business_insert < audit_insert
        assert business_insert < outbox_insert
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        parent_session.close()

    orphan_session = factory()
    try:
        with pytest.raises(IntegrityError), orphan_session.begin():
            create_business(
                orphan_session,
                organization_id="missing-organization",
                name="Orphan Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="pg-orphan",
            )
        orphan_session.rollback()

        assert (
            orphan_session.scalar(
                select(func.count()).select_from(BusinessModel).where(
                    BusinessModel.name == "Orphan Business"
                )
            )
            == 0
        )
        assert (
            orphan_session.scalar(
                select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.correlation_id == "pg-orphan"
                )
            )
            == 0
        )
        assert (
            orphan_session.scalar(
                select(func.count()).select_from(OutboxEventModel).where(
                    OutboxEventModel.correlation_id == "pg-orphan"
                )
            )
            == 0
        )
    finally:
        orphan_session.close()
        engine.dispose()


def test_postgresql_16_migration_and_integration_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    config = _alembic_config(database_url, monkeypatch)

    command.upgrade(config, "head")
    _assert_schema_contract(database_url)
    _assert_foreign_key_parity(database_url)
    readiness = check_database_readiness(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL=database_url,
        )
    )
    assert readiness.ready
    assert readiness.database == "ok"
    _assert_parent_graph_regression(database_url)
    _assert_orphan_side_effects_rejected(database_url)
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
    _assert_foreign_key_parity(database_url)
    get_settings.cache_clear()
