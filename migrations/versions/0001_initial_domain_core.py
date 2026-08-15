"""Initial domain core tables.

Revision ID: 0001_initial_domain_core
Revises:
Create Date: 2026-08-15

Affected tables: Phase 0 platform foundations and Phase 1 domain core.
Rollback: downgrade drops all tables created by this revision in reverse dependency order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_domain_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def id_col() -> sa.Column[str]:
    return sa.Column("id", sa.String(length=36), primary_key=True)


def timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def business_scope() -> list[sa.Column[str]]:
    return [
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
    ]


def version_col() -> sa.Column[int]:
    return sa.Column("version", sa.Integer(), nullable=False, server_default="1")


def business_table(name: str, *columns: sa.Column[object], version: bool = True) -> None:
    common: list[sa.Column[object]] = [id_col(), *business_scope()]
    constraints: list[sa.Constraint] = [
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
    ]
    if version:
        common.append(version_col())
        constraints.append(sa.CheckConstraint("version >= 1", name=f"ck_{name}_version_positive"))
    common.extend(timestamps())
    op.create_table(name, *common, *columns, *constraints)
    op.create_index(f"ix_{name}_organization_id", name, ["organization_id"])
    op.create_index(f"ix_{name}_business_id", name, ["business_id"])


def upgrade() -> None:
    op.create_table(
        "users",
        id_col(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "organizations",
        id_col(),
        sa.Column("name", sa.String(length=255), nullable=False),
        *timestamps(),
    )

    op.create_table(
        "businesses",
        id_col(),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        version_col(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=128), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.CheckConstraint("version >= 1", name="ck_businesses_version_positive"),
    )
    op.create_index("ix_businesses_organization_id", "businesses", ["organization_id"])

    op.create_table(
        "business_memberships",
        id_col(),
        *business_scope(),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("business_id", "user_id", name="uq_membership_business_user"),
    )
    op.create_index(
        "ix_business_memberships_organization_id",
        "business_memberships",
        ["organization_id"],
    )
    op.create_index("ix_business_memberships_business_id", "business_memberships", ["business_id"])
    op.create_index("ix_business_memberships_user_id", "business_memberships", ["user_id"])

    business_table(
        "goals",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    business_table(
        "constraints",
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
    )
    business_table(
        "products",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    business_table(
        "offers",
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_descriptor", sa.String(length=255), nullable=True),
    )
    business_table(
        "channels",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
    )

    business_table(
        "source_records",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=128), nullable=False),
        sa.Column("trust", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "business_id",
            "provider",
            "external_id",
            name="uq_source_record_business_provider_external",
        ),
    )
    business_table(
        "evidence",
        sa.Column(
            "source_record_id",
            sa.String(length=36),
            sa.ForeignKey("source_records.id"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conflicts_with_evidence_ids", sa.JSON(), nullable=False),
    )
    business_table(
        "claims",
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
    )
    business_table(
        "hypotheses",
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("model_confidence", sa.Float(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
    )
    business_table(
        "information_needs",
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "business_snapshots",
        id_col(),
        *business_scope(),
        version_col(),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.CheckConstraint("version >= 1", name="ck_business_snapshots_version_positive"),
    )
    op.create_index(
        "ix_business_snapshots_organization_id",
        "business_snapshots",
        ["organization_id"],
    )
    op.create_index("ix_business_snapshots_business_id", "business_snapshots", ["business_id"])

    business_table(
        "campaigns",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
    )
    business_table(
        "launches",
        sa.Column(
            "campaign_id",
            sa.String(length=36),
            sa.ForeignKey("campaigns.id"),
            nullable=False,
        ),
        sa.Column("offer_id", sa.String(length=36), sa.ForeignKey("offers.id"), nullable=False),
        sa.Column("goal_id", sa.String(length=36), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("channel_id", sa.String(length=36), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.String(length=36),
            sa.ForeignKey("business_snapshots.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    business_table(
        "launch_phases",
        sa.Column("launch_id", sa.String(length=36), sa.ForeignKey("launches.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    business_table(
        "decisions",
        sa.Column("goal_problem", sa.Text(), nullable=False),
        sa.Column("selected_action", sa.Text(), nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reversibility", sa.String(length=128), nullable=False),
        sa.Column("risk_class", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.String(length=36),
            sa.ForeignKey("business_snapshots.id"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=True,
        ),
        sa.Column("next_checkpoint", sa.Text(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("assumption_ids", sa.JSON(), nullable=False),
        sa.Column("known_unknown_ids", sa.JSON(), nullable=False),
    )
    business_table(
        "decision_alternatives",
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
    )
    business_table(
        "controller_reviews",
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=True,
        ),
        sa.Column(
            "asset_version_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column("controller_name", sa.String(length=128), nullable=False),
        sa.Column("verdict", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    business_table(
        "experiments",
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=False,
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(length=36),
            sa.ForeignKey("hypotheses.id"),
            nullable=True,
        ),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("causality_class", sa.String(length=128), nullable=False),
    )
    business_table(
        "experiment_rules",
        sa.Column(
            "experiment_id",
            sa.String(length=36),
            sa.ForeignKey("experiments.id"),
            nullable=False,
        ),
        sa.Column("baseline", sa.Text(), nullable=False),
        sa.Column("segment", sa.Text(), nullable=False),
        sa.Column("treatment", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("window", sa.String(length=128), nullable=False),
        sa.Column("attribution_method", sa.String(length=128), nullable=False),
        sa.Column("success_threshold", sa.String(length=128), nullable=False),
        sa.Column("weak_signal_threshold", sa.String(length=128), nullable=False),
        sa.Column("failure_threshold", sa.String(length=128), nullable=False),
        sa.Column("next_action_on_success", sa.Text(), nullable=False),
        sa.Column("next_action_on_weak_signal", sa.Text(), nullable=False),
        sa.Column("next_action_on_failure", sa.Text(), nullable=False),
    )
    business_table(
        "experiment_results",
        sa.Column(
            "experiment_id",
            sa.String(length=36),
            sa.ForeignKey("experiments.id"),
            nullable=False,
        ),
        sa.Column("result_class", sa.String(length=64), nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=False),
        sa.Column("interpreted_at", sa.DateTime(timezone=True), nullable=False),
    )

    business_table(
        "creative_briefs",
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
    )
    business_table(
        "assets",
        sa.Column(
            "creative_brief_id",
            sa.String(length=36),
            sa.ForeignKey("creative_briefs.id"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
    )
    op.create_table(
        "asset_versions",
        id_col(),
        *business_scope(),
        sa.Column("asset_id", sa.String(length=36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.CheckConstraint("version_number >= 1", name="ck_asset_versions_number_positive"),
        sa.UniqueConstraint("asset_id", "version_number", name="uq_asset_version_number"),
    )
    op.create_index("ix_asset_versions_organization_id", "asset_versions", ["organization_id"])
    op.create_index("ix_asset_versions_business_id", "asset_versions", ["business_id"])
    op.create_index("ix_asset_versions_asset_id", "asset_versions", ["asset_id"])
    business_table(
        "publications",
        sa.Column(
            "asset_version_id",
            sa.String(length=36),
            sa.ForeignKey("asset_versions.id"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.String(length=36), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )

    business_table(
        "permission_policies",
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("public_visibility", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    business_table(
        "actions",
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("target_object_type", sa.String(length=128), nullable=False),
        sa.Column("target_object_id", sa.String(length=36), nullable=False),
        sa.Column("target_object_version_id", sa.String(length=36), nullable=False),
        sa.Column("target_object_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "target_object_version >= 1",
            name="ck_actions_target_object_version_positive",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_actions_idempotency_key"),
    )
    op.create_table(
        "approvals",
        id_col(),
        *business_scope(),
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("actions.id"), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=128), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("object_version_id", sa.String(length=36), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.CheckConstraint("object_version >= 1", name="ck_approvals_object_version_positive"),
    )
    op.create_index("ix_approvals_organization_id", "approvals", ["organization_id"])
    op.create_index("ix_approvals_business_id", "approvals", ["business_id"])
    op.create_index("ix_approvals_action_id", "approvals", ["action_id"])
    business_table(
        "executions",
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("actions.id"), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_executions_idempotency_key"),
    )

    business_table(
        "business_events",
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column(
            "source_record_id",
            sa.String(length=36),
            sa.ForeignKey("source_records.id"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "outbox_events",
        id_col(),
        *business_scope(),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
    )
    op.create_index("ix_outbox_events_organization_id", "outbox_events", ["organization_id"])
    op.create_index("ix_outbox_events_business_id", "outbox_events", ["business_id"])
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])

    business_table(
        "jobs",
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
    )
    business_table(
        "agent_definitions",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    business_table(
        "agent_runs",
        sa.Column(
            "agent_definition_id",
            sa.String(length=36),
            sa.ForeignKey("agent_definitions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("input_ref", sa.String(length=255), nullable=True),
        sa.Column("output_ref", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
    )
    business_table(
        "audit_logs",
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=128), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
    )
    business_table(
        "feature_flags",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("business_id", "key", name="uq_feature_flag_business_key"),
    )
    business_table(
        "learnings",
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id"),
            nullable=True,
        ),
        sa.Column(
            "experiment_id",
            sa.String(length=36),
            sa.ForeignKey("experiments.id"),
            nullable=True,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("causality_class", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    for table_name in (
        "learnings",
        "feature_flags",
        "audit_logs",
        "agent_runs",
        "agent_definitions",
        "jobs",
        "outbox_events",
        "business_events",
        "executions",
        "approvals",
        "actions",
        "permission_policies",
        "publications",
        "asset_versions",
        "assets",
        "creative_briefs",
        "experiment_results",
        "experiment_rules",
        "experiments",
        "controller_reviews",
        "decision_alternatives",
        "decisions",
        "launch_phases",
        "launches",
        "campaigns",
        "business_snapshots",
        "information_needs",
        "hypotheses",
        "claims",
        "evidence",
        "source_records",
        "channels",
        "offers",
        "products",
        "constraints",
        "goals",
        "business_memberships",
        "businesses",
        "organizations",
        "users",
    ):
        op.drop_table(table_name)
