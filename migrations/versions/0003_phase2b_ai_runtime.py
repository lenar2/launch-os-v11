"""Add Phase 2B governed AI runtime projections.

Revision ID: 0003_phase2b_ai_runtime
Revises: 0002_phase2a_jobs_runtime
Create Date: 2026-08-16

Affected tables/indexes: agent_definitions and agent_runs contract binding, context
manifest, structured result, provider trace, and AgentRun status constraints.
Rollback: drops Phase 2B indexes/constraints/columns and leaves the Phase 1 AI shells.
Backfill: pre-production rows receive explicit legacy defaults; no production backfill is required.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0003_phase2b_ai_runtime"
down_revision = "0002_phase2a_jobs_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_RUN_STATUS_CHECK = (
    "status in ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', "
    "'REFUSED', 'INVALID_OUTPUT', 'FAILED')"
)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _json_default(value: str) -> sa.TextClause:
    if _is_sqlite():
        return sa.text(f"'{value}'")
    return sa.text(f"'{value}'::json")


def upgrade() -> None:
    with op.batch_alter_table("agent_definitions") as batch:
        batch.add_column(
            sa.Column(
                "contract_key",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column("contract_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "role_name",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column(
                "model_capability",
                sa.String(length=128),
                nullable=False,
                server_default="STANDARD_REASONING",
            )
        )
        batch.add_column(
            sa.Column(
                "allowed_context_types",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "required_context_types",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "authority_boundaries",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "prohibited_actions",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "required_controller_types",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column("abstention_policy", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("escalation_policy", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "instruction_version",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column(
                "eval_suite_identifier",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column(
                "contract_fingerprint",
                sa.String(length=64),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column(
                "output_schema_name",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column("output_schema_version", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_index("ix_agent_definitions_contract_key", "agent_definitions", ["contract_key"])
    op.create_index(
        "ix_agent_definitions_contract_fingerprint",
        "agent_definitions",
        ["contract_fingerprint"],
    )
    if not _is_sqlite():
        op.create_unique_constraint(
            "uq_agent_definitions_contract_version",
            "agent_definitions",
            ["organization_id", "business_id", "contract_key", "contract_version"],
        )
        op.create_check_constraint(
            "ck_agent_definitions_contract_version_positive",
            "agent_definitions",
            "contract_version >= 1",
        )
        op.create_check_constraint(
            "ck_agent_definitions_output_schema_version_positive",
            "agent_definitions",
            "output_schema_version >= 1",
        )

    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("payload_schema_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "agent_contract_key",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column("agent_contract_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "agent_contract_fingerprint",
                sa.String(length=64),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column(
                "output_schema_name",
                sa.String(length=128),
                nullable=False,
                server_default="legacy",
            )
        )
        batch.add_column(
            sa.Column("output_schema_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "context_refs",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("[]"),
            )
        )
        batch.add_column(
            sa.Column(
                "context_manifest",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}"),
            )
        )
        batch.add_column(sa.Column("context_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("output_data", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("refusal_summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("error_class", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("error_summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("provider_name", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("provider_model", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("provider_response_id", sa.String(length=255), nullable=True))
        batch.add_column(
            sa.Column(
                "token_usage",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}"),
            )
        )
        batch.add_column(sa.Column("latency_ms", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "safe_trace_metadata",
                sa.JSON(),
                nullable=False,
                server_default=_json_default("{}"),
            )
        )
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_agent_runs_job_id_jobs", "jobs", ["job_id"], ["id"])

    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])
    op.create_index("ix_agent_runs_agent_contract_key", "agent_runs", ["agent_contract_key"])
    op.create_index("ix_agent_runs_context_hash", "agent_runs", ["context_hash"])
    op.create_index("ix_agent_runs_provider_response_id", "agent_runs", ["provider_response_id"])
    if not _is_sqlite():
        op.create_check_constraint(
            "ck_agent_runs_status_phase2b",
            "agent_runs",
            AGENT_RUN_STATUS_CHECK,
        )
        op.create_check_constraint(
            "ck_agent_runs_payload_schema_positive",
            "agent_runs",
            "payload_schema_version >= 1",
        )
        op.create_check_constraint(
            "ck_agent_runs_contract_version_positive",
            "agent_runs",
            "agent_contract_version >= 1",
        )
        op.create_check_constraint(
            "ck_agent_runs_output_schema_version_positive",
            "agent_runs",
            "output_schema_version >= 1",
        )


def downgrade() -> None:
    if not _is_sqlite():
        op.drop_constraint(
            "ck_agent_runs_output_schema_version_positive",
            "agent_runs",
            type_="check",
        )
        op.drop_constraint(
            "ck_agent_runs_contract_version_positive",
            "agent_runs",
            type_="check",
        )
        op.drop_constraint(
            "ck_agent_runs_payload_schema_positive",
            "agent_runs",
            type_="check",
        )
        op.drop_constraint("ck_agent_runs_status_phase2b", "agent_runs", type_="check")

    for index_name in (
        "ix_agent_runs_provider_response_id",
        "ix_agent_runs_context_hash",
        "ix_agent_runs_agent_contract_key",
        "ix_agent_runs_job_id",
    ):
        op.drop_index(index_name, table_name="agent_runs")

    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("fk_agent_runs_job_id_jobs", type_="foreignkey")
        for column_name in (
            "completed_at",
            "started_at",
            "safe_trace_metadata",
            "latency_ms",
            "token_usage",
            "provider_response_id",
            "provider_model",
            "provider_name",
            "error_summary",
            "error_class",
            "refusal_summary",
            "output_data",
            "context_hash",
            "context_manifest",
            "context_refs",
            "output_schema_version",
            "output_schema_name",
            "agent_contract_fingerprint",
            "agent_contract_version",
            "agent_contract_key",
            "payload_schema_version",
            "job_id",
        ):
            batch.drop_column(column_name)

    if not _is_sqlite():
        op.drop_constraint(
            "ck_agent_definitions_output_schema_version_positive",
            "agent_definitions",
            type_="check",
        )
        op.drop_constraint(
            "ck_agent_definitions_contract_version_positive",
            "agent_definitions",
            type_="check",
        )
    if not _is_sqlite():
        op.drop_constraint(
            "uq_agent_definitions_contract_version",
            "agent_definitions",
            type_="unique",
        )
    op.drop_index("ix_agent_definitions_contract_fingerprint", table_name="agent_definitions")
    op.drop_index("ix_agent_definitions_contract_key", table_name="agent_definitions")

    with op.batch_alter_table("agent_definitions") as batch:
        for column_name in (
            "output_schema_version",
            "output_schema_name",
            "contract_fingerprint",
            "eval_suite_identifier",
            "instruction_version",
            "escalation_policy",
            "abstention_policy",
            "required_controller_types",
            "prohibited_actions",
            "authority_boundaries",
            "required_context_types",
            "allowed_context_types",
            "model_capability",
            "role_name",
            "contract_version",
            "contract_key",
        ):
            batch.drop_column(column_name)
