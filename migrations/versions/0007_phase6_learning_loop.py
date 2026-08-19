"""Add Phase 6 governed observation, metrics, learning, and adaptation persistence.

Revision ID: 0007_phase6_learning_loop
Revises: 0006_phase5_telegram_execution
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_phase6_learning_loop"
down_revision: str | None = "0006_phase5_telegram_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phase6_decision_intents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_spec", sa.JSON(), nullable=False),
        sa.Column("checkpoint_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_decision_id", sa.String(length=36), nullable=True),
        sa.Column("learning_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["decision_workflows.id"]),
        sa.ForeignKeyConstraint(["prior_decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["learning_id"], ["learnings.id"]),
        sa.UniqueConstraint("workflow_id", name="uq_phase6_decision_intent_workflow"),
    )
    _indexes(
        "phase6_decision_intents",
        [
            "organization_id",
            "business_id",
            "workflow_id",
            "checkpoint_spec_hash",
            "prior_decision_id",
            "learning_id",
        ],
    )

    op.create_table(
        "checkpoint_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_rule_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("metric_key", sa.String(length=128), nullable=False),
        sa.Column("source_window_anchor", sa.String(length=64), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("grace_seconds", sa.Integer(), nullable=False),
        sa.Column("success_operator", sa.String(length=16), nullable=False),
        sa.Column("success_value", sa.Float(), nullable=False),
        sa.Column("weak_signal_operator", sa.String(length=16), nullable=False),
        sa.Column("weak_signal_value", sa.Float(), nullable=False),
        sa.Column("failure_operator", sa.String(length=16), nullable=False),
        sa.Column("failure_value", sa.Float(), nullable=False),
        sa.Column("coverage_requirement", sa.String(length=64), nullable=False),
        sa.Column("attribution_method", sa.String(length=128), nullable=False),
        sa.Column("next_action_on_success", sa.Text(), nullable=False),
        sa.Column("next_action_on_weak_signal", sa.Text(), nullable=False),
        sa.Column("next_action_on_failure", sa.Text(), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"]),
        sa.ForeignKeyConstraint(["experiment_rule_id"], ["experiment_rules.id"]),
        sa.UniqueConstraint("experiment_id", name="uq_checkpoint_definition_experiment"),
        sa.CheckConstraint("schema_version >= 1", name="ck_checkpoint_schema_positive"),
        sa.CheckConstraint("window_seconds >= 1", name="ck_checkpoint_window_positive"),
        sa.CheckConstraint("grace_seconds >= 0", name="ck_checkpoint_grace_nonnegative"),
    )
    _indexes(
        "checkpoint_definitions",
        ["organization_id", "business_id", "decision_id", "experiment_id", "experiment_rule_id", "metric_key", "contract_hash"],
    )

    op.create_table(
        "connector_observation_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("connector_account_id", sa.String(length=36), nullable=False),
        sa.Column("observation_mode", sa.String(length=32), nullable=False),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
        sa.Column("coverage_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_successful_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_status", sa.String(length=32), nullable=False),
        sa.Column("gap_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_update_types", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["connector_account_id"], ["connector_accounts.id"]),
        sa.UniqueConstraint(
            "connector_account_id", name="uq_connector_observation_state_account"
        ),
    )
    _indexes(
        "connector_observation_states",
        ["organization_id", "business_id", "connector_account_id"],
    )

    op.create_table(
        "connector_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("connector_account_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_event_identity", sa.String(length=255), nullable=False),
        sa.Column("provider_event_type", sa.String(length=128), nullable=False),
        sa.Column("external_object_id", sa.String(length=255), nullable=True),
        sa.Column("external_parent_id", sa.String(length=255), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("trust_class", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["connector_account_id"], ["connector_accounts.id"]),
        sa.UniqueConstraint(
            "connector_account_id",
            "provider_event_identity",
            name="uq_connector_observation_account_event",
        ),
    )
    _indexes(
        "connector_observations",
        [
            "organization_id",
            "business_id",
            "connector_account_id",
            "provider",
            "provider_event_identity",
            "provider_event_type",
            "external_object_id",
            "external_parent_id",
            "event_time",
            "payload_hash",
        ],
    )

    op.create_table(
        "normalized_observation_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("business_event_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["observation_id"], ["connector_observations.id"]),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_records.id"]),
        sa.ForeignKeyConstraint(["business_event_id"], ["business_events.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"]),
        sa.UniqueConstraint(
            "observation_id", name="uq_normalized_observation_link_observation"
        ),
        sa.UniqueConstraint(
            "business_event_id", name="uq_normalized_observation_link_event"
        ),
    )
    _indexes(
        "normalized_observation_links",
        [
            "organization_id",
            "business_id",
            "observation_id",
            "source_record_id",
            "business_event_id",
            "evidence_id",
            "publication_id",
        ],
    )

    op.create_table(
        "metric_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_definition_id", sa.String(length=36), nullable=False),
        sa.Column("metric_key", sa.String(length=128), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_connector_account_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_type", sa.String(length=64), nullable=False),
        sa.Column("availability_status", sa.String(length=32), nullable=False),
        sa.Column("coverage_status", sa.String(length=32), nullable=False),
        sa.Column("source_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("included_business_event_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_event_rule_version", sa.String(length=128), nullable=False),
        sa.Column("calculation_version", sa.String(length=128), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_metric_version_id", sa.String(length=36), nullable=True),
        sa.Column("derivation_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["checkpoint_definition_id"], ["checkpoint_definitions.id"]),
        sa.ForeignKeyConstraint(["source_connector_account_id"], ["connector_accounts.id"]),
        sa.ForeignKeyConstraint(["previous_metric_version_id"], ["metric_versions.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.UniqueConstraint(
            "business_id",
            "metric_key",
            "subject_type",
            "subject_id",
            "version_number",
            name="uq_metric_version_subject_version",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_metric_version_positive"),
        sa.CheckConstraint(
            "availability_status in ('AVAILABLE', 'PARTIAL', 'UNAVAILABLE', 'STALE')",
            name="ck_metric_version_availability",
        ),
    )
    _indexes(
        "metric_versions",
        [
            "organization_id",
            "business_id",
            "checkpoint_definition_id",
            "metric_key",
            "subject_id",
            "source_connector_account_id",
            "previous_metric_version_id",
            "derivation_hash",
            "evidence_id",
        ],
    )

    op.create_table(
        "experiment_result_details",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_result_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_definition_id", sa.String(length=36), nullable=False),
        sa.Column("metric_version_id", sa.String(length=36), nullable=False),
        sa.Column("result_class", sa.String(length=32), nullable=False),
        sa.Column("checkpoint_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("source_coverage_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["experiment_result_id"], ["experiment_results.id"]),
        sa.ForeignKeyConstraint(["checkpoint_definition_id"], ["checkpoint_definitions.id"]),
        sa.ForeignKeyConstraint(["metric_version_id"], ["metric_versions.id"]),
        sa.UniqueConstraint(
            "experiment_result_id", name="uq_experiment_result_detail_result"
        ),
        sa.UniqueConstraint("metric_version_id", name="uq_experiment_result_detail_metric"),
        sa.CheckConstraint(
            "result_class in ('SUCCESS', 'WEAK_SIGNAL', 'FAILURE', 'INSUFFICIENT_DATA')",
            name="ck_experiment_result_detail_class",
        ),
    )
    _indexes(
        "experiment_result_details",
        [
            "organization_id",
            "business_id",
            "experiment_result_id",
            "checkpoint_definition_id",
            "metric_version_id",
        ],
    )

    op.create_table(
        "learning_controller_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_result_id", sa.String(length=36), nullable=False),
        sa.Column("controller_type", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("causality_ceiling", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["experiment_result_id"], ["experiment_results.id"]),
        sa.UniqueConstraint(
            "experiment_result_id",
            "controller_type",
            name="uq_learning_review_result_controller",
        ),
        sa.CheckConstraint(
            "verdict in ('PASS', 'PASS_WITH_CONDITIONS', 'BLOCK')",
            name="ck_learning_controller_review_verdict",
        ),
    )
    _indexes(
        "learning_controller_reviews",
        ["organization_id", "business_id", "experiment_result_id", "controller_type"],
    )

    op.create_table(
        "learning_details",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("learning_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_result_id", sa.String(length=36), nullable=False),
        sa.Column("metric_version_ids", sa.JSON(), nullable=False),
        sa.Column("interpretation_class", sa.String(length=32), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("controller_review_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["learning_id"], ["learnings.id"]),
        sa.ForeignKeyConstraint(["experiment_result_id"], ["experiment_results.id"]),
        sa.UniqueConstraint("learning_id", name="uq_learning_detail_learning"),
        sa.UniqueConstraint("experiment_result_id", name="uq_learning_detail_result"),
    )
    _indexes(
        "learning_details",
        ["organization_id", "business_id", "learning_id", "experiment_result_id"],
    )

    op.create_table(
        "decision_learning_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("prior_decision_id", sa.String(length=36), nullable=False),
        sa.Column("learning_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["prior_decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["learning_id"], ["learnings.id"]),
        sa.UniqueConstraint("decision_id", name="uq_decision_learning_link_decision"),
    )
    _indexes(
        "decision_learning_links",
        ["organization_id", "business_id", "decision_id", "prior_decision_id", "learning_id"],
    )


def downgrade() -> None:
    for table in [
        "decision_learning_links",
        "learning_details",
        "learning_controller_reviews",
        "experiment_result_details",
        "metric_versions",
        "normalized_observation_links",
        "connector_observations",
        "connector_observation_states",
        "checkpoint_definitions",
        "phase6_decision_intents",
    ]:
        op.drop_table(table)


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)
