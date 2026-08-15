"""Add Phase 2A durable async job runtime fields.

Revision ID: 0002_phase2a_jobs_runtime
Revises: 0001_initial_domain_core
Create Date: 2026-08-15

Affected tables/indexes: jobs runtime state, lease, retry, idempotency, and scan indexes.
Rollback: drops Phase 2A job indexes/constraints/columns and leaves the Phase 1 job shell.
Backfill: existing rows receive conservative defaults; no production backfill is required for
pre-production Phase 2A.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0002_phase2a_jobs_runtime"
down_revision = "0001_initial_domain_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = "status in ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED')"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "payload_schema_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
        )
        batch.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("error_class", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("error_summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("correlation_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("causation_id", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column(
                "idempotency_key",
                sa.String(length=255),
                nullable=False,
                server_default="legacy",
            )
        )

    op.execute("update jobs set idempotency_key = id where idempotency_key = 'legacy'")

    op.create_index(
        "uq_jobs_tenant_type_idempotency",
        "jobs",
        ["organization_id", "business_id", "job_type", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_jobs_due_scan", "jobs", ["status", "available_at"])
    op.create_index(
        "ix_jobs_claim_scan",
        "jobs",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])
    op.create_index("ix_jobs_lease_owner", "jobs", ["lease_owner"])
    op.create_index("ix_jobs_correlation_id", "jobs", ["correlation_id"])
    op.create_index("ix_jobs_causation_id", "jobs", ["causation_id"])

    if not _is_sqlite():
        op.create_check_constraint(
            "ck_jobs_payload_schema_positive",
            "jobs",
            "payload_schema_version >= 1",
        )
        op.create_check_constraint(
            "ck_jobs_attempt_count_nonnegative",
            "jobs",
            "attempt_count >= 0",
        )
        op.create_check_constraint(
            "ck_jobs_max_attempts_positive",
            "jobs",
            "max_attempts >= 1",
        )
        op.create_check_constraint("ck_jobs_status_phase2a", "jobs", STATUS_CHECK)


def downgrade() -> None:
    if not _is_sqlite():
        op.drop_constraint("ck_jobs_status_phase2a", "jobs", type_="check")
        op.drop_constraint("ck_jobs_max_attempts_positive", "jobs", type_="check")
        op.drop_constraint("ck_jobs_attempt_count_nonnegative", "jobs", type_="check")
        op.drop_constraint("ck_jobs_payload_schema_positive", "jobs", type_="check")

    for index_name in (
        "ix_jobs_causation_id",
        "ix_jobs_correlation_id",
        "ix_jobs_lease_owner",
        "ix_jobs_lease_expires_at",
        "ix_jobs_claim_scan",
        "ix_jobs_due_scan",
        "uq_jobs_tenant_type_idempotency",
    ):
        op.drop_index(index_name, table_name="jobs")

    with op.batch_alter_table("jobs") as batch:
        for column_name in (
            "idempotency_key",
            "causation_id",
            "correlation_id",
            "error_summary",
            "error_class",
            "lease_expires_at",
            "lease_owner",
            "completed_at",
            "started_at",
            "available_at",
            "max_attempts",
            "attempt_count",
            "payload_schema_version",
        ):
            batch.drop_column(column_name)
