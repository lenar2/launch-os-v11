"""Add Phase 3 governed decision workflow persistence.

Revision ID: 0004_phase3_decision_workflow
Revises: 0003_phase2b_ai_runtime
Create Date: 2026-08-17

Affected tables/indexes: decision workflow state, specialist contributions,
decision candidates, decision approvals, AgentRun idempotency, controller review
candidate binding, and final Decision source/proposal metadata.
Rollback: drops Phase 3 indexes/constraints/tables/columns.
Backfill: pre-production rows receive empty JSON defaults; no production backfill
is required for Phase 3.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0004_phase3_decision_workflow"
down_revision = "0003_phase2b_ai_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _json_default(value: str) -> sa.TextClause:
    if _is_sqlite():
        return sa.text(f"'{value}'")
    return sa.text(f"'{value}'::json")


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.create_index("ix_agent_runs_idempotency_key", "agent_runs", ["idempotency_key"])
    if not _is_sqlite():
        op.create_unique_constraint(
            "uq_agent_runs_tenant_idempotency",
            "agent_runs",
            ["organization_id", "business_id", "idempotency_key"],
        )

    op.create_table(
        "decision_workflows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("launch_id", sa.String(length=36), nullable=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_revision_rounds", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("final_decision_id", sa.String(length=36), nullable=True),
        sa.Column("final_approval_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["launch_id"], ["launches.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["business_snapshots.id"]),
        sa.ForeignKeyConstraint(["final_decision_id"], ["decisions.id"]),
        sa.CheckConstraint(
            "status in ('SNAPSHOT_READY', 'SPECIALISTS_RUNNING', 'SPECIALISTS_READY', "
            "'CHIEF_RUNNING', 'DECISION_CANDIDATE_READY', 'CONTROLLERS_RUNNING', "
            "'BLOCKED', 'REVISION_REQUIRED', 'CANDIDATE_ACCEPTED', "
            "'FINAL_DECISION_MATERIALIZED', 'AWAITING_DECISION_APPROVAL', "
            "'APPROVED_FOR_PRODUCTION', 'ESCALATED')",
            name="ck_decision_workflows_status_phase3",
        ),
        sa.CheckConstraint(
            "revision_count >= 0",
            name="ck_decision_workflows_revision_count_nonnegative",
        ),
        sa.CheckConstraint(
            "max_revision_rounds >= 0",
            name="ck_decision_workflows_max_revision_rounds_nonnegative",
        ),
    )
    for index_name, columns in (
        ("ix_decision_workflows_organization_id", ["organization_id"]),
        ("ix_decision_workflows_business_id", ["business_id"]),
        ("ix_decision_workflows_launch_id", ["launch_id"]),
        ("ix_decision_workflows_snapshot_id", ["snapshot_id"]),
        ("ix_decision_workflows_final_decision_id", ["final_decision_id"]),
        ("ix_decision_workflows_final_approval_id", ["final_approval_id"]),
        ("ix_decision_workflows_correlation_id", ["correlation_id"]),
        ("ix_decision_workflows_causation_id", ["causation_id"]),
    ):
        op.create_index(index_name, "decision_workflows", columns)

    op.create_table(
        "specialist_contributions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("contract_key", sa.String(length=128), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("instruction_version", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "context_manifest",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["decision_workflows.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["business_snapshots.id"]),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.UniqueConstraint(
            "workflow_id",
            "contract_key",
            "contract_version",
            name="uq_specialist_contribution_workflow_contract",
        ),
        sa.UniqueConstraint("agent_run_id", name="uq_specialist_contributions_agent_run"),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_specialist_contributions_schema_version",
        ),
    )
    for index_name, columns in (
        ("ix_specialist_contributions_organization_id", ["organization_id"]),
        ("ix_specialist_contributions_business_id", ["business_id"]),
        ("ix_specialist_contributions_workflow_id", ["workflow_id"]),
        ("ix_specialist_contributions_snapshot_id", ["snapshot_id"]),
        ("ix_specialist_contributions_agent_run_id", ["agent_run_id"]),
        ("ix_specialist_contributions_context_hash", ["context_hash"]),
        ("ix_specialist_contributions_correlation_id", ["correlation_id"]),
        ("ix_specialist_contributions_causation_id", ["causation_id"]),
    ):
        op.create_index(index_name, "specialist_contributions", columns)

    op.create_table(
        "decision_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("chief_agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("previous_candidate_id", sa.String(length=36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("revision_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("selected_action", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column(
            "specialist_contribution_ids",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("[]"),
        ),
        sa.Column(
            "controller_review_ids",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("[]"),
        ),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "context_manifest",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["decision_workflows.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["business_snapshots.id"]),
        sa.ForeignKeyConstraint(["chief_agent_run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["previous_candidate_id"], ["decision_candidates.id"]),
        sa.UniqueConstraint("workflow_id", "version_number", name="uq_candidate_workflow_version"),
        sa.UniqueConstraint("chief_agent_run_id", name="uq_candidate_agent_run"),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_decision_candidates_version_positive",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_decision_candidates_schema_version",
        ),
        sa.CheckConstraint(
            "status in ('CANDIDATE', 'UNDER_REVIEW', 'REVISION_REQUIRED', "
            "'BLOCKED', 'ACCEPTED', 'MATERIALIZED')",
            name="ck_decision_candidates_status_phase3",
        ),
    )
    for index_name, columns in (
        ("ix_decision_candidates_organization_id", ["organization_id"]),
        ("ix_decision_candidates_business_id", ["business_id"]),
        ("ix_decision_candidates_workflow_id", ["workflow_id"]),
        ("ix_decision_candidates_snapshot_id", ["snapshot_id"]),
        ("ix_decision_candidates_chief_agent_run_id", ["chief_agent_run_id"]),
        ("ix_decision_candidates_previous_candidate_id", ["previous_candidate_id"]),
        ("ix_decision_candidates_context_hash", ["context_hash"]),
        ("ix_decision_candidates_correlation_id", ["correlation_id"]),
        ("ix_decision_candidates_causation_id", ["causation_id"]),
    ):
        op.create_index(index_name, "decision_candidates", columns)

    with op.batch_alter_table("controller_reviews") as batch:
        batch.add_column(sa.Column("decision_candidate_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("agent_run_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("controller_type", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("contract_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("contract_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("instruction_version", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("output_schema_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("context_hash", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column(
                "context_manifest",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}"),
            )
        )
        batch.add_column(sa.Column("severity", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("issues", sa.JSON(), nullable=False, server_default=_json_default("[]"))
        )
        batch.add_column(
            sa.Column(
                "required_changes",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "evidence_refs",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column("conditions", sa.JSON(), nullable=False, server_default=_json_default("[]"))
        )
        batch.add_column(sa.Column("correlation_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("causation_id", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_controller_reviews_decision_candidate_id_decision_candidates",
            "decision_candidates",
            ["decision_candidate_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_controller_reviews_agent_run_id_agent_runs",
            "agent_runs",
            ["agent_run_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_controller_reviews_snapshot_id_business_snapshots",
            "business_snapshots",
            ["snapshot_id"],
            ["id"],
        )
    for index_name, columns in (
        ("ix_controller_reviews_decision_candidate_id", ["decision_candidate_id"]),
        ("ix_controller_reviews_agent_run_id", ["agent_run_id"]),
        ("ix_controller_reviews_snapshot_id", ["snapshot_id"]),
        ("ix_controller_reviews_controller_type", ["controller_type"]),
        ("ix_controller_reviews_correlation_id", ["correlation_id"]),
        ("ix_controller_reviews_causation_id", ["causation_id"]),
    ):
        op.create_index(index_name, "controller_reviews", columns)
    if not _is_sqlite():
        op.create_unique_constraint(
            "uq_controller_review_candidate_controller",
            "controller_reviews",
            ["decision_candidate_id", "controller_type"],
        )

    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("source_candidate_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "why_alternatives_not_selected",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column("hypotheses", sa.JSON(), nullable=False, server_default=_json_default("[]"))
        )
        batch.add_column(
            sa.Column("assumptions", sa.JSON(), nullable=False, server_default=_json_default("[]"))
        )
        batch.add_column(
            sa.Column(
                "experiment_proposal",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}"),
            )
        )
        batch.add_column(
            sa.Column(
                "required_assets",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "required_actions",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.create_foreign_key(
            "fk_decisions_source_candidate_id_decision_candidates",
            "decision_candidates",
            ["source_candidate_id"],
            ["id"],
        )
    op.create_index("ix_decisions_source_candidate_id", "decisions", ["source_candidate_id"])

    op.create_table(
        "decision_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=128), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("object_version_id", sa.String(length=36), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["decision_workflows.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["decision_candidates.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.UniqueConstraint(
            "decision_id",
            "action_type",
            "object_version_id",
            name="uq_decision_approval_exact_version_action",
        ),
        sa.CheckConstraint(
            "object_version >= 1",
            name="ck_decision_approvals_version_positive",
        ),
    )
    for index_name, columns in (
        ("ix_decision_approvals_organization_id", ["organization_id"]),
        ("ix_decision_approvals_business_id", ["business_id"]),
        ("ix_decision_approvals_workflow_id", ["workflow_id"]),
        ("ix_decision_approvals_decision_id", ["decision_id"]),
        ("ix_decision_approvals_candidate_id", ["candidate_id"]),
        ("ix_decision_approvals_approved_by_user_id", ["approved_by_user_id"]),
        ("ix_decision_approvals_correlation_id", ["correlation_id"]),
        ("ix_decision_approvals_causation_id", ["causation_id"]),
    ):
        op.create_index(index_name, "decision_approvals", columns)

    if not _is_sqlite():
        op.create_foreign_key(
            "fk_decision_workflows_final_approval_id_decision_approvals",
            "decision_workflows",
            "decision_approvals",
            ["final_approval_id"],
            ["id"],
        )


def downgrade() -> None:
    if not _is_sqlite():
        op.drop_constraint(
            "fk_decision_workflows_final_approval_id_decision_approvals",
            "decision_workflows",
            type_="foreignkey",
        )
    for index_name in (
        "ix_decision_approvals_causation_id",
        "ix_decision_approvals_correlation_id",
        "ix_decision_approvals_approved_by_user_id",
        "ix_decision_approvals_candidate_id",
        "ix_decision_approvals_decision_id",
        "ix_decision_approvals_workflow_id",
        "ix_decision_approvals_business_id",
        "ix_decision_approvals_organization_id",
    ):
        op.drop_index(index_name, table_name="decision_approvals")
    op.drop_table("decision_approvals")

    op.drop_index("ix_decisions_source_candidate_id", table_name="decisions")
    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint(
            "fk_decisions_source_candidate_id_decision_candidates",
            type_="foreignkey",
        )
        for column_name in (
            "required_actions",
            "required_assets",
            "experiment_proposal",
            "assumptions",
            "hypotheses",
            "why_alternatives_not_selected",
            "source_candidate_id",
        ):
            batch.drop_column(column_name)

    if not _is_sqlite():
        op.drop_constraint(
            "uq_controller_review_candidate_controller",
            "controller_reviews",
            type_="unique",
        )
    for index_name in (
        "ix_controller_reviews_causation_id",
        "ix_controller_reviews_correlation_id",
        "ix_controller_reviews_controller_type",
        "ix_controller_reviews_snapshot_id",
        "ix_controller_reviews_agent_run_id",
        "ix_controller_reviews_decision_candidate_id",
    ):
        op.drop_index(index_name, table_name="controller_reviews")
    with op.batch_alter_table("controller_reviews") as batch:
        batch.drop_constraint(
            "fk_controller_reviews_snapshot_id_business_snapshots",
            type_="foreignkey",
        )
        batch.drop_constraint("fk_controller_reviews_agent_run_id_agent_runs", type_="foreignkey")
        batch.drop_constraint(
            "fk_controller_reviews_decision_candidate_id_decision_candidates",
            type_="foreignkey",
        )
        for column_name in (
            "causation_id",
            "correlation_id",
            "conditions",
            "evidence_refs",
            "required_changes",
            "issues",
            "severity",
            "context_manifest",
            "context_hash",
            "output_schema_version",
            "instruction_version",
            "contract_version",
            "contract_key",
            "controller_type",
            "snapshot_id",
            "agent_run_id",
            "decision_candidate_id",
        ):
            batch.drop_column(column_name)

    for table_name, indexes in (
        (
            "decision_candidates",
            (
                "ix_decision_candidates_causation_id",
                "ix_decision_candidates_correlation_id",
                "ix_decision_candidates_context_hash",
                "ix_decision_candidates_previous_candidate_id",
                "ix_decision_candidates_chief_agent_run_id",
                "ix_decision_candidates_snapshot_id",
                "ix_decision_candidates_workflow_id",
                "ix_decision_candidates_business_id",
                "ix_decision_candidates_organization_id",
            ),
        ),
        (
            "specialist_contributions",
            (
                "ix_specialist_contributions_causation_id",
                "ix_specialist_contributions_correlation_id",
                "ix_specialist_contributions_context_hash",
                "ix_specialist_contributions_agent_run_id",
                "ix_specialist_contributions_snapshot_id",
                "ix_specialist_contributions_workflow_id",
                "ix_specialist_contributions_business_id",
                "ix_specialist_contributions_organization_id",
            ),
        ),
        (
            "decision_workflows",
            (
                "ix_decision_workflows_causation_id",
                "ix_decision_workflows_correlation_id",
                "ix_decision_workflows_final_approval_id",
                "ix_decision_workflows_final_decision_id",
                "ix_decision_workflows_snapshot_id",
                "ix_decision_workflows_launch_id",
                "ix_decision_workflows_business_id",
                "ix_decision_workflows_organization_id",
            ),
        ),
    ):
        for index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
    op.drop_table("decision_candidates")
    op.drop_table("specialist_contributions")
    op.drop_table("decision_workflows")

    if not _is_sqlite():
        op.drop_constraint("uq_agent_runs_tenant_idempotency", "agent_runs", type_="unique")
    op.drop_index("ix_agent_runs_idempotency_key", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("idempotency_key")
