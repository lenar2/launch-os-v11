from __future__ import annotations

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.persistence import models
from launch_os_v11.persistence.production_models import (
    AssetReviewModel,
    AssetRightsProvenanceModel,
    AssetVersionCreatorModel,
    ContentStrategyModel,
    CreativeBriefDetailModel,
    ProductionWorkflowModel,
)
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.worker import Worker
from tests.phase4_seed_support import Seed


def process_until_status(
    factory: sessionmaker[Session],
    *,
    worker: Worker,
    workflow_id: str,
    status: ProductionWorkflowStatus,
) -> None:
    seen: list[tuple[str, str]] = []
    for _ in range(160):
        session = factory()
        try:
            workflow = session.get(ProductionWorkflowModel, workflow_id)
            assert workflow is not None
            if workflow.status == status.value:
                return
        finally:
            session.close()
        result = worker.process_one_from_queue(timeout_seconds=1)
        assert result is not None, f"workflow did not reach {status.value}; seen={seen}"
        seen.append((result.job_id, result.status))
    pytest.fail(f"workflow did not reach {status.value}; seen={seen}")


def assert_production_materialization(
    factory: sessionmaker[Session],
    *,
    seed: Seed,
    workflow_id: str,
) -> None:
    session = factory()
    try:
        workflow = session.get(ProductionWorkflowModel, workflow_id)
        assert workflow is not None
        assert workflow.status == ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value
        assert workflow.revision_count == 1
        assert workflow.creative_brief_id is not None
        assert workflow.asset_id is not None
        assert workflow.final_asset_version_id is not None
        assert session.scalar(
            select(func.count()).select_from(ContentStrategyModel).where(
                ContentStrategyModel.workflow_id == workflow_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(CreativeBriefDetailModel).where(
                CreativeBriefDetailModel.workflow_id == workflow_id
            )
        ) == 1
        versions = session.scalars(
            select(models.AssetVersionModel)
            .where(models.AssetVersionModel.asset_id == workflow.asset_id)
            .order_by(models.AssetVersionModel.version_number)
        ).all()
        assert [row.version_number for row in versions] == [1, 2]
        assert all(row.created_by_user_id is None for row in versions)
        assert versions[-1].id == workflow.final_asset_version_id
        assert session.scalar(
            select(func.count()).select_from(AssetVersionCreatorModel).where(
                AssetVersionCreatorModel.business_id == seed.scope.business_id
            )
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(AssetRightsProvenanceModel).where(
                AssetRightsProvenanceModel.business_id == seed.scope.business_id
            )
        ) == 2
        reviews = session.scalars(
            select(AssetReviewModel).where(AssetReviewModel.workflow_id == workflow_id)
        ).all()
        assert len(reviews) == 14
        assert {review.asset_version_id for review in reviews} == {
            versions[0].id,
            versions[1].id,
        }
        runs = session.scalars(
            select(models.AgentRunModel).where(
                models.AgentRunModel.organization_id == seed.scope.organization_id,
                models.AgentRunModel.business_id == seed.scope.business_id,
                models.AgentRunModel.idempotency_key.like("production_workflow:%"),
            )
        ).all()
        assert len(runs) == 17
        for run in runs:
            trace = run.safe_trace_metadata
            assert trace["selected_provider_name"] == "fake"
            assert trace["actual_provider_name"] == "fake"
            assert trace["selected_model_name"] == "fake-structured-model"
            assert trace["actual_model_name"] == "fake-structured-model"
    finally:
        session.close()


def assert_no_duplicate_records(
    factory: sessionmaker[Session],
    *,
    workflow_id: str,
) -> None:
    session = factory()
    try:
        workflow = session.get(ProductionWorkflowModel, workflow_id)
        assert workflow is not None
        assert session.scalar(
            select(func.count()).select_from(ContentStrategyModel).where(
                ContentStrategyModel.workflow_id == workflow_id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(AssetReviewModel).where(
                AssetReviewModel.workflow_id == workflow_id
            )
        ) == 14
        assert workflow.asset_id is not None
        assert session.scalar(
            select(func.count()).select_from(models.AssetVersionModel).where(
                models.AssetVersionModel.asset_id == workflow.asset_id
            )
        ) == 2
    finally:
        session.close()


def assert_phase4_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "production_workflows",
        "content_strategies",
        "creative_brief_details",
        "asset_version_creators",
        "asset_rights_provenance",
        "asset_reviews",
    }.issubset(tables)
    columns = {column["name"]: column for column in inspector.get_columns("asset_versions")}
    assert columns["created_by_user_id"]["nullable"] is True
    checks = {
        item["name"] for item in inspector.get_check_constraints("production_workflows")
    }
    assert "ck_production_workflows_status_phase4" in checks


def assert_phase4_fk_parity(engine) -> None:
    inspector = inspect(engine)
    tables = {
        "production_workflows",
        "content_strategies",
        "creative_brief_details",
        "asset_version_creators",
        "asset_rights_provenance",
        "asset_reviews",
    }
    database_fks: set[tuple[str, str, str, str]] = set()
    for table in tables:
        for foreign_key in inspector.get_foreign_keys(table):
            referred_table = foreign_key["referred_table"]
            assert referred_table is not None
            for constrained, referred in zip(
                foreign_key["constrained_columns"],
                foreign_key["referred_columns"],
                strict=True,
            ):
                database_fks.add((table, constrained, referred_table, referred))
    expected = {
        (table, "organization_id", "organizations", "id") for table in tables
    } | {
        (table, "business_id", "businesses", "id") for table in tables
    } | {
        ("production_workflows", "decision_id", "decisions", "id"),
        ("production_workflows", "decision_approval_id", "decision_approvals", "id"),
        ("production_workflows", "snapshot_id", "business_snapshots", "id"),
        ("production_workflows", "launch_id", "launches", "id"),
        ("production_workflows", "creative_brief_id", "creative_briefs", "id"),
        ("production_workflows", "asset_id", "assets", "id"),
        ("production_workflows", "final_asset_version_id", "asset_versions", "id"),
        ("content_strategies", "workflow_id", "production_workflows", "id"),
        ("content_strategies", "decision_id", "decisions", "id"),
        ("content_strategies", "snapshot_id", "business_snapshots", "id"),
        ("content_strategies", "agent_run_id", "agent_runs", "id"),
        ("creative_brief_details", "workflow_id", "production_workflows", "id"),
        ("creative_brief_details", "creative_brief_id", "creative_briefs", "id"),
        ("creative_brief_details", "content_strategy_id", "content_strategies", "id"),
        ("creative_brief_details", "snapshot_id", "business_snapshots", "id"),
        ("asset_version_creators", "asset_version_id", "asset_versions", "id"),
        ("asset_version_creators", "created_by_user_id", "users", "id"),
        ("asset_version_creators", "created_by_agent_run_id", "agent_runs", "id"),
        ("asset_rights_provenance", "asset_version_id", "asset_versions", "id"),
        ("asset_rights_provenance", "generated_by_agent_run_id", "agent_runs", "id"),
        ("asset_reviews", "workflow_id", "production_workflows", "id"),
        ("asset_reviews", "asset_version_id", "asset_versions", "id"),
        ("asset_reviews", "agent_run_id", "agent_runs", "id"),
    }
    assert database_fks == expected
