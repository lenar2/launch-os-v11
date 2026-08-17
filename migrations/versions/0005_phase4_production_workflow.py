"""Add Phase 4 governed production workflow persistence.

Revision ID: 0005_phase4_production_workflow
Revises: 0004_phase3_decision_workflow
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase4_production_workflow"
down_revision: str | None = "0004_phase3_decision_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("asset_versions") as batch:
        batch.alter_column(
            "created_by_user_id",
            existing_type=sa.String(36),
            nullable=True,
        )
    _production_workflows()
    _content_strategies()
    _creative_brief_details()
    _asset_version_creators()
    _asset_rights_provenance()
    _asset_reviews()


def downgrade() -> None:
    for table in (
        "asset_reviews",
        "asset_rights_provenance",
        "asset_version_creators",
        "creative_brief_details",
        "content_strategies",
        "production_workflows",
    ):
        op.drop_table(table)
    with op.batch_alter_table("asset_versions") as batch:
        batch.alter_column(
            "created_by_user_id",
            existing_type=sa.String(36),
            nullable=False,
        )


def _production_workflows() -> None:
    _create(
        "production_workflows",
        [
            _id(), *_tenant(), _fk("decision_id", "decisions.id", False),
            _int("decision_version"),
            _fk("decision_approval_id", "decision_approvals.id", False),
            _fk("snapshot_id", "business_snapshots.id", False),
            _fk("launch_id", "launches.id"), _str("status", 64),
            _int("revision_count"), _int("max_revision_rounds"),
            _fk("creative_brief_id", "creative_briefs.id"),
            _fk("asset_id", "assets.id"),
            _fk("final_asset_version_id", "asset_versions.id"),
            _str("correlation_id", 64, True), _str("causation_id", 64, True),
            _dt("created_at"), _dt("updated_at"), _int("version"),
        ],
        [
            sa.CheckConstraint(
                "status in ('DECISION_APPROVAL_VERIFIED','CONTENT_STRATEGY_RUNNING',"
                "'CONTENT_STRATEGY_READY','BRIEF_READY','PRODUCTION_RUNNING',"
                "'ASSET_VERSION_READY','ASSET_CONTROLLERS_RUNNING','BLOCKED',"
                "'REVISION_REQUIRED','PRODUCTION_READY','READY_FOR_ACTION_PROPOSAL',"
                "'ESCALATED')",
                name="ck_production_workflows_status_phase4",
            ),
            sa.CheckConstraint(
                "revision_count >= 0",
                name="ck_production_workflows_revision_count_nonnegative",
            ),
            sa.CheckConstraint(
                "max_revision_rounds >= 0",
                name="ck_production_workflows_max_revision_rounds_nonnegative",
            ),
            sa.UniqueConstraint(
                "business_id", "decision_id", "decision_version",
                name="uq_production_workflow_decision_version",
            ),
        ],
        "organization_id business_id decision_id decision_approval_id snapshot_id "
        "launch_id creative_brief_id asset_id final_asset_version_id correlation_id "
        "causation_id",
    )


def _content_strategies() -> None:
    _create(
        "content_strategies",
        [
            _id(), *_tenant(), _fk("workflow_id", "production_workflows.id", False),
            _fk("decision_id", "decisions.id", False),
            _fk("snapshot_id", "business_snapshots.id", False),
            _fk("agent_run_id", "agent_runs.id", False), _int("schema_version"),
            _json("payload"), _json("evidence_refs"), _str("context_hash", 64),
            _json("context_manifest"), _str("correlation_id", 64, True),
            _str("causation_id", 64, True), _dt("created_at"),
        ],
        [
            sa.CheckConstraint(
                "schema_version >= 1",
                name="ck_content_strategy_schema_version",
            ),
            sa.UniqueConstraint("workflow_id", name="uq_content_strategy_workflow"),
            sa.UniqueConstraint("agent_run_id", name="uq_content_strategy_agent_run"),
        ],
        "organization_id business_id workflow_id decision_id snapshot_id agent_run_id "
        "context_hash correlation_id causation_id",
    )


def _creative_brief_details() -> None:
    _create(
        "creative_brief_details",
        [
            _id(), *_tenant(), _fk("workflow_id", "production_workflows.id", False),
            _fk("creative_brief_id", "creative_briefs.id", False),
            _fk("content_strategy_id", "content_strategies.id", False),
            _fk("snapshot_id", "business_snapshots.id", False), _json("payload"),
            _str("correlation_id", 64, True), _str("causation_id", 64, True),
            _dt("created_at"),
        ],
        [
            sa.UniqueConstraint(
                "creative_brief_id", name="uq_creative_brief_detail_brief"
            )
        ],
        "organization_id business_id workflow_id creative_brief_id snapshot_id "
        "correlation_id causation_id",
    )


def _asset_version_creators() -> None:
    _create(
        "asset_version_creators",
        [
            _id(), *_tenant(), _fk("asset_version_id", "asset_versions.id", False),
            _str("creator_type", 32), _fk("created_by_user_id", "users.id"),
            _fk("created_by_agent_run_id", "agent_runs.id"), _dt("created_at"),
        ],
        [
            sa.CheckConstraint(
                "(creator_type='USER' and created_by_user_id is not null and "
                "created_by_agent_run_id is null) or "
                "(creator_type='AGENT' and created_by_user_id is null and "
                "created_by_agent_run_id is not null) or "
                "(creator_type='SYSTEM' and created_by_user_id is null and "
                "created_by_agent_run_id is null)",
                name="ck_asset_version_creator_identity",
            ),
            sa.UniqueConstraint(
                "asset_version_id", name="uq_asset_version_creator_version"
            ),
        ],
        "organization_id business_id asset_version_id created_by_user_id "
        "created_by_agent_run_id",
    )


def _asset_rights_provenance() -> None:
    _create(
        "asset_rights_provenance",
        [
            _id(), *_tenant(), _fk("asset_version_id", "asset_versions.id", False),
            _str("origin", 64), _fk("generated_by_agent_run_id", "agent_runs.id"),
            _str("model_provider", 64, True), _str("model_name", 255, True),
            _json("related_source_asset_ids"), _text("permission_scope"),
            _str("customer_content_consent_ref", 255, True),
            _json("publication_restrictions"), _dt("license_expires_at", True),
            _json("provenance"), _dt("created_at"),
        ],
        [sa.UniqueConstraint("asset_version_id", name="uq_asset_rights_version")],
        "organization_id business_id asset_version_id generated_by_agent_run_id",
    )


def _asset_reviews() -> None:
    _create(
        "asset_reviews",
        [
            _id(), *_tenant(), _fk("workflow_id", "production_workflows.id", False),
            _fk("asset_version_id", "asset_versions.id", False),
            _fk("agent_run_id", "agent_runs.id", False), _str("controller_type", 128),
            _str("verdict", 64), _text("reason", False), _str("severity", 64),
            _json("issues"), _json("required_changes"), _json("conditions"),
            _json("evidence_refs"), _str("contract_key", 128),
            _int("contract_version"), _str("instruction_version", 128),
            _int("output_schema_version"), _str("context_hash", 64),
            _json("context_manifest"), _str("correlation_id", 64, True),
            _str("causation_id", 64, True), _dt("created_at"),
        ],
        [
            sa.UniqueConstraint(
                "asset_version_id", "controller_type",
                name="uq_asset_review_version_controller",
            ),
            sa.UniqueConstraint("agent_run_id", name="uq_asset_review_agent_run"),
        ],
        "organization_id business_id workflow_id asset_version_id agent_run_id "
        "controller_type context_hash correlation_id causation_id",
    )


def _create(
    table: str,
    columns: list[sa.Column],
    constraints: list[sa.SchemaItem],
    indexes: str,
) -> None:
    op.create_table(table, *columns, *constraints)
    for column in indexes.split():
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def _id() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def _tenant() -> tuple[sa.Column, sa.Column]:
    return _fk("organization_id", "organizations.id", False), _fk(
        "business_id", "businesses.id", False
    )


def _fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey(target), nullable=nullable)


def _str(name: str, length: int, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(length), nullable=nullable)


def _int(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=False)


def _json(name: str) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False)


def _text(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=nullable)


def _dt(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)
