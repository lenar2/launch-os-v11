"""Add Phase 5 governed Telegram execution persistence.

Revision ID: 0006_phase5_telegram_execution
Revises: 0005_phase4_production_workflow
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase5_telegram_execution"
down_revision: str | None = "0005_phase4_production_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=False),
        sa.Column("target_chat_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("auth_healthy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_capability", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_class", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.UniqueConstraint(
            "business_id",
            "channel_id",
            "provider",
            name="uq_connector_account_business_channel_provider",
        ),
    )
    _indexes(
        "connector_accounts",
        ["organization_id", "business_id", "channel_id", "provider"],
    )

    op.create_table(
        "action_proposal_details",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("production_workflow_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("asset_version_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("connector_account_id", sa.String(length=36), nullable=False),
        sa.Column("target_chat_id", sa.String(length=255), nullable=False),
        sa.Column("delivery_payload", sa.JSON(), nullable=False),
        sa.Column("delivery_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["production_workflow_id"], ["production_workflows.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["asset_version_id"], ["asset_versions.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["connector_account_id"], ["connector_accounts.id"]),
        sa.UniqueConstraint("action_id", name="uq_action_proposal_detail_action"),
    )
    _indexes(
        "action_proposal_details",
        [
            "organization_id",
            "business_id",
            "action_id",
            "production_workflow_id",
            "decision_id",
            "asset_version_id",
            "channel_id",
            "connector_account_id",
            "delivery_payload_hash",
            "correlation_id",
            "causation_id",
        ],
    )

    op.create_table(
        "execution_controller_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("controller_type", sa.String(length=128), nullable=False),
        sa.Column("verdict", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.UniqueConstraint(
            "action_id",
            "controller_type",
            name="uq_execution_review_action_controller",
        ),
        sa.CheckConstraint(
            "verdict in ('PASS', 'PASS_WITH_CONDITIONS', 'REVISE', 'BLOCK')",
            name="ck_execution_controller_reviews_verdict",
        ),
    )
    _indexes(
        "execution_controller_reviews",
        ["organization_id", "business_id", "action_id", "controller_type"],
    )

    op.create_table(
        "permission_evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("permission_policy_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["permission_policy_id"], ["permission_policies.id"]),
        sa.UniqueConstraint("action_id", name="uq_permission_evaluation_action"),
        sa.CheckConstraint(
            "outcome in ('BLOCKED', 'APPROVAL_REQUIRED', 'ALLOWED')",
            name="ck_permission_evaluations_outcome",
        ),
    )
    _indexes(
        "permission_evaluations",
        ["organization_id", "business_id", "action_id", "permission_policy_id"],
    )

    op.create_table(
        "global_execution_controls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column(
            "automation_paused", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "execution_paused", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "revoke_all_write_capabilities",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("business_id", name="uq_global_execution_control_business"),
    )
    _indexes(
        "global_execution_controls",
        ["organization_id", "business_id", "updated_by_user_id"],
    )

    op.create_table(
        "external_references",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("connector_account_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("external_object_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_parent_id", sa.String(length=255), nullable=True),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["connector_account_id"], ["connector_accounts.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.UniqueConstraint(
            "provider",
            "connector_account_id",
            "external_object_type",
            "external_id",
            name="uq_external_reference_provider_account_object",
        ),
        sa.UniqueConstraint("execution_id", name="uq_external_reference_execution"),
    )
    _indexes(
        "external_references",
        [
            "organization_id",
            "business_id",
            "provider",
            "connector_account_id",
            "channel_id",
            "action_id",
            "execution_id",
        ],
    )

    op.create_table(
        "publication_execution_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("external_reference_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.ForeignKeyConstraint(["external_reference_id"], ["external_references.id"]),
        sa.UniqueConstraint(
            "publication_id", name="uq_publication_execution_link_publication"
        ),
        sa.UniqueConstraint(
            "execution_id", name="uq_publication_execution_link_execution"
        ),
    )
    _indexes(
        "publication_execution_links",
        [
            "organization_id",
            "business_id",
            "publication_id",
            "action_id",
            "execution_id",
            "external_reference_id",
        ],
    )


def downgrade() -> None:
    for table in [
        "publication_execution_links",
        "external_references",
        "global_execution_controls",
        "permission_evaluations",
        "execution_controller_reviews",
        "action_proposal_details",
        "connector_accounts",
    ]:
        op.drop_table(table)


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)
