from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import AssetVersionModel, Base

# Phase 4 permits honest AGENT creator identity; the legacy user-only column becomes optional.
AssetVersionModel.__table__.c.created_by_user_id.nullable = True  # type: ignore[attr-defined]


class ProductionWorkflowModel(Base):
    __tablename__ = "production_workflows"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "decision_id",
            "decision_version",
            name="uq_production_workflow_decision_version",
        ),
        CheckConstraint(
            "status in ('DECISION_APPROVAL_VERIFIED', 'CONTENT_STRATEGY_RUNNING', "
            "'CONTENT_STRATEGY_READY', 'BRIEF_READY', 'PRODUCTION_RUNNING', "
            "'ASSET_VERSION_READY', 'ASSET_CONTROLLERS_RUNNING', 'BLOCKED', "
            "'REVISION_REQUIRED', 'PRODUCTION_READY', 'READY_FOR_ACTION_PROPOSAL', "
            "'ESCALATED')",
            name="ck_production_workflows_status_phase4",
        ),
        CheckConstraint(
            "revision_count >= 0",
            name="ck_production_workflows_revision_count_nonnegative",
        ),
        CheckConstraint(
            "max_revision_rounds >= 0",
            name="ck_production_workflows_max_revision_rounds_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_approval_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decision_approvals.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("business_snapshots.id"), nullable=False, index=True
    )
    launch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("launches.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_revision_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    creative_brief_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creative_briefs.id"), index=True
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id"), index=True
    )
    final_asset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContentStrategyModel(Base):
    __tablename__ = "content_strategies"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_content_strategy_workflow"),
        UniqueConstraint("agent_run_id", name="uq_content_strategy_agent_run"),
        CheckConstraint("schema_version >= 1", name="ck_content_strategy_schema_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("production_workflows.id"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("business_snapshots.id"), nullable=False, index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class CreativeBriefDetailModel(Base):
    __tablename__ = "creative_brief_details"
    __table_args__ = (
        UniqueConstraint("creative_brief_id", name="uq_creative_brief_detail_brief"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("production_workflows.id"), nullable=False, index=True
    )
    creative_brief_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_briefs.id"), nullable=False, index=True
    )
    content_strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("content_strategies.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("business_snapshots.id"), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AssetVersionCreatorModel(Base):
    __tablename__ = "asset_version_creators"
    __table_args__ = (
        UniqueConstraint("asset_version_id", name="uq_asset_version_creator_version"),
        CheckConstraint(
            "(creator_type = 'USER' and created_by_user_id is not null and "
            "created_by_agent_run_id is null) or "
            "(creator_type = 'AGENT' and created_by_user_id is null and "
            "created_by_agent_run_id is not null) or "
            "(creator_type = 'SYSTEM' and created_by_user_id is null and "
            "created_by_agent_run_id is null)",
            name="ck_asset_version_creator_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), nullable=False, index=True
    )
    creator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    created_by_agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AssetRightsProvenanceModel(Base):
    __tablename__ = "asset_rights_provenance"
    __table_args__ = (
        UniqueConstraint("asset_version_id", name="uq_asset_rights_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by_agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), index=True
    )
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(255))
    related_source_asset_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    permission_scope: Mapped[str | None] = mapped_column(Text)
    customer_content_consent_ref: Mapped[str | None] = mapped_column(String(255))
    publication_restrictions: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    license_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AssetReviewModel(Base):
    __tablename__ = "asset_reviews"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id",
            "controller_type",
            name="uq_asset_review_version_controller",
        ),
        UniqueConstraint("agent_run_id", name="uq_asset_review_agent_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("production_workflows.id"), nullable=False, index=True
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), nullable=False, index=True
    )
    agent_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    controller_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    issues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_changes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    conditions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    contract_key: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_version: Mapped[str] = mapped_column(String(128), nullable=False)
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
