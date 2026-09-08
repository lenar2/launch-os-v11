"""Add disabled business outcome instrumentation persistence.

Revision ID: 0008_business_outcomes
Revises: 0007_phase6_learning_loop
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_business_outcomes"
down_revision: str | None = "0007_phase6_learning_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OUTCOME_CLASSES = (
    "'QUALIFIED_INTENT', 'CTA_COMPLETION', 'LEAD', 'APPLICATION', 'BOOKING', "
    "'CHECKOUT', 'PURCHASE_PAYMENT', 'REFUND', 'RENEWAL', 'RETENTION', "
    "'REVENUE', 'COST', 'CONTRIBUTION_MARGIN'"
)

INSTRUMENTATION_STATUSES = "'DRAFT', 'DISABLED_NON_LIVE', 'RETIRED'"
DISABLED_ECONOMIC_EPISTEMIC_STATUSES = "'HYPOTHESIS', 'ASSUMPTION', 'UNKNOWN'"


def upgrade() -> None:
    op.create_table(
        "outcome_ingestion_contracts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("contract_key", sa.String(length=128), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("outcome_class", sa.String(length=64), nullable=False),
        sa.Column("canonical_event_type", sa.String(length=128), nullable=False),
        sa.Column("identity_boundary", sa.Text(), nullable=False),
        sa.Column("pii_classification", sa.String(length=64), nullable=False),
        sa.Column("retention_class", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column("provenance_source_record_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["provenance_source_record_id"], ["source_records.id"]),
        sa.UniqueConstraint(
            "business_id",
            "provider",
            "contract_key",
            "payload_schema_version",
            name="uq_outcome_ingestion_contract_version",
        ),
        sa.CheckConstraint(
            "payload_schema_version >= 1",
            name="ck_outcome_ingestion_contract_schema_version_positive",
        ),
        sa.CheckConstraint(
            f"status in ({INSTRUMENTATION_STATUSES})",
            name="ck_outcome_ingestion_contract_status",
        ),
        sa.CheckConstraint(
            f"outcome_class in ({OUTCOME_CLASSES})",
            name="ck_outcome_ingestion_contract_class",
        ),
    )
    _indexes(
        "outcome_ingestion_contracts",
        [
            "organization_id",
            "business_id",
            "provider",
            "contract_key",
            "outcome_class",
            "canonical_event_type",
            "status",
            "provenance_source_record_id",
        ],
    )

    op.create_table(
        "outcome_metric_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_key", sa.String(length=128), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("outcome_class", sa.String(length=64), nullable=False),
        sa.Column("numerator_event_type", sa.String(length=128), nullable=False),
        sa.Column("denominator_event_type", sa.String(length=128), nullable=True),
        sa.Column("aggregation", sa.String(length=32), nullable=False),
        sa.Column("value_field", sa.String(length=128), nullable=True),
        sa.Column("eligible_population", sa.Text(), nullable=False),
        sa.Column("denominator_description", sa.Text(), nullable=False),
        sa.Column("observation_window_seconds", sa.Integer(), nullable=False),
        sa.Column("attribution_method", sa.String(length=128), nullable=False),
        sa.Column("attribution_limitations", sa.JSON(), nullable=False),
        sa.Column("data_availability", sa.String(length=32), nullable=False),
        sa.Column("downstream_economic_meaning", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("ingestion_contract_id", sa.String(length=36), nullable=True),
        sa.Column("provenance_source_record_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["ingestion_contract_id"], ["outcome_ingestion_contracts.id"]
        ),
        sa.ForeignKeyConstraint(["provenance_source_record_id"], ["source_records.id"]),
        sa.UniqueConstraint(
            "business_id",
            "metric_key",
            "definition_version",
            name="uq_outcome_metric_definition_version",
        ),
        sa.CheckConstraint(
            "definition_version >= 1",
            name="ck_outcome_metric_definition_version_positive",
        ),
        sa.CheckConstraint(
            "observation_window_seconds >= 1",
            name="ck_outcome_metric_definition_window_positive",
        ),
        sa.CheckConstraint(
            "aggregation in ('COUNT', 'SUM', 'RATE')",
            name="ck_outcome_metric_definition_aggregation",
        ),
        sa.CheckConstraint(
            "data_availability in ('AVAILABLE', 'PARTIAL', 'UNAVAILABLE', 'STALE')",
            name="ck_outcome_metric_definition_data_availability",
        ),
        sa.CheckConstraint(
            f"status in ({INSTRUMENTATION_STATUSES})",
            name="ck_outcome_metric_definition_status",
        ),
        sa.CheckConstraint(
            f"outcome_class in ({OUTCOME_CLASSES})",
            name="ck_outcome_metric_definition_class",
        ),
    )
    _indexes(
        "outcome_metric_definitions",
        [
            "organization_id",
            "business_id",
            "metric_key",
            "outcome_class",
            "numerator_event_type",
            "denominator_event_type",
            "status",
            "ingestion_contract_id",
            "provenance_source_record_id",
        ],
    )

    op.create_table(
        "outcome_metric_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_definition_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("numerator_count", sa.Integer(), nullable=False),
        sa.Column("denominator_count", sa.Integer(), nullable=True),
        sa.Column("availability_status", sa.String(length=32), nullable=False),
        sa.Column("coverage_status", sa.String(length=32), nullable=False),
        sa.Column("source_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("included_business_event_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_event_rule_version", sa.String(length=128), nullable=False),
        sa.Column("calculation_version", sa.String(length=128), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrects_metric_version_id", sa.String(length=36), nullable=True),
        sa.Column("derivation_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("synthetic_non_live", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"], ["outcome_metric_definitions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["corrects_metric_version_id"], ["outcome_metric_versions.id"]
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.UniqueConstraint(
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "version_number",
            name="uq_outcome_metric_version_definition_subject_version",
        ),
        sa.UniqueConstraint(
            "derivation_hash",
            name="uq_outcome_metric_version_derivation_hash",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_outcome_metric_version_positive",
        ),
        sa.CheckConstraint(
            "numerator_count >= 0",
            name="ck_outcome_metric_version_numerator_nonnegative",
        ),
        sa.CheckConstraint(
            "denominator_count is null or denominator_count >= 0",
            name="ck_outcome_metric_version_denominator_nonnegative",
        ),
        sa.CheckConstraint(
            "availability_status in ('AVAILABLE', 'PARTIAL', 'UNAVAILABLE', 'STALE')",
            name="ck_outcome_metric_version_availability",
        ),
        sa.CheckConstraint(
            "synthetic_non_live = true",
            name="ck_outcome_metric_version_synthetic_non_live",
        ),
    )
    _indexes(
        "outcome_metric_versions",
        [
            "organization_id",
            "business_id",
            "metric_definition_id",
            "subject_id",
            "availability_status",
            "corrects_metric_version_id",
            "derivation_hash",
            "evidence_id",
        ],
    )

    op.create_table(
        "outcome_economic_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_version_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.String(length=64), nullable=False),
        sa.Column("downstream_outcome_class", sa.String(length=64), nullable=False),
        sa.Column("epistemic_status", sa.String(length=64), nullable=False),
        sa.Column("value_per_unit_cents", sa.Integer(), nullable=True),
        sa.Column("direct_cost_cents", sa.Integer(), nullable=True),
        sa.Column("fully_loaded_execution_cost_cents", sa.Integer(), nullable=True),
        sa.Column("opportunity_cost_cents", sa.Integer(), nullable=True),
        sa.Column("bounded_downside_cents", sa.Integer(), nullable=True),
        sa.Column("expected_benefit_cents", sa.Integer(), nullable=True),
        sa.Column("hurdle_multiplier", sa.Integer(), nullable=False),
        sa.Column("supports_go", sa.Boolean(), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("synthetic_non_live", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["metric_version_id"], ["outcome_metric_versions.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.UniqueConstraint(
            "metric_version_id",
            "version_number",
            name="uq_outcome_economic_link_metric_version_version",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_outcome_economic_link_version_positive",
        ),
        sa.CheckConstraint(
            (
                "link_type in ('DIRECT_REVENUE', 'CONTRIBUTION_MARGIN', "
                "'VALUE_PROXY', 'HYPOTHETICAL_PROXY', 'NONE')"
            ),
            name="ck_outcome_economic_link_type",
        ),
        sa.CheckConstraint(
            f"downstream_outcome_class in ({OUTCOME_CLASSES})",
            name="ck_outcome_economic_link_class",
        ),
        sa.CheckConstraint(
            f"epistemic_status in ({DISABLED_ECONOMIC_EPISTEMIC_STATUSES})",
            name="ck_outcome_economic_link_epistemic_status",
        ),
        sa.CheckConstraint(
            "supports_go = false",
            name="ck_outcome_economic_link_disabled_no_go",
        ),
        sa.CheckConstraint(
            "synthetic_non_live = true",
            name="ck_outcome_economic_link_synthetic_non_live",
        ),
        sa.CheckConstraint(
            "hurdle_multiplier >= 1",
            name="ck_outcome_economic_link_hurdle_positive",
        ),
        sa.CheckConstraint(
            "value_per_unit_cents is null or value_per_unit_cents >= 0",
            name="ck_outcome_economic_link_value_nonnegative",
        ),
        sa.CheckConstraint(
            "direct_cost_cents is null or direct_cost_cents >= 0",
            name="ck_outcome_economic_link_direct_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "fully_loaded_execution_cost_cents is null or fully_loaded_execution_cost_cents >= 0",
            name="ck_outcome_economic_link_execution_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "opportunity_cost_cents is null or opportunity_cost_cents >= 0",
            name="ck_outcome_economic_link_opportunity_nonnegative",
        ),
        sa.CheckConstraint(
            "bounded_downside_cents is null or bounded_downside_cents >= 0",
            name="ck_outcome_economic_link_downside_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_benefit_cents is null or expected_benefit_cents >= 0",
            name="ck_outcome_economic_link_benefit_nonnegative",
        ),
    )
    _indexes(
        "outcome_economic_links",
        [
            "organization_id",
            "business_id",
            "metric_version_id",
            "downstream_outcome_class",
            "epistemic_status",
            "supports_go",
            "evidence_id",
        ],
    )

    op.create_table(
        "outcome_experiment_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_definition_id", sa.String(length=36), nullable=False),
        sa.Column("metric_version_id", sa.String(length=36), nullable=False),
        sa.Column("economic_link_id", sa.String(length=36), nullable=False),
        sa.Column("learning_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("selected_metric_key", sa.String(length=128), nullable=False),
        sa.Column("eligible_population", sa.Text(), nullable=False),
        sa.Column("treatment", sa.Text(), nullable=False),
        sa.Column("control", sa.Text(), nullable=False),
        sa.Column("success_threshold", sa.Text(), nullable=False),
        sa.Column("weak_signal_threshold", sa.Text(), nullable=False),
        sa.Column("failure_threshold", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"], ["outcome_metric_definitions.id"]
        ),
        sa.ForeignKeyConstraint(["metric_version_id"], ["outcome_metric_versions.id"]),
        sa.ForeignKeyConstraint(["economic_link_id"], ["outcome_economic_links.id"]),
        sa.ForeignKeyConstraint(["learning_id"], ["learnings.id"]),
        sa.CheckConstraint(
            f"status in ({INSTRUMENTATION_STATUSES})",
            name="ck_outcome_experiment_proposal_status",
        ),
    )
    _indexes(
        "outcome_experiment_proposals",
        [
            "organization_id",
            "business_id",
            "metric_definition_id",
            "metric_version_id",
            "economic_link_id",
            "learning_id",
            "status",
            "selected_metric_key",
        ],
    )


def downgrade() -> None:
    for table in [
        "outcome_experiment_proposals",
        "outcome_economic_links",
        "outcome_metric_versions",
        "outcome_metric_definitions",
        "outcome_ingestion_contracts",
    ]:
        op.drop_table(table)


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)
