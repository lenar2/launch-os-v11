from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class BusinessScopedMixin(TimestampMixin, VersionMixin):
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)


class OrganizationModel(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class BusinessModel(TimestampMixin, VersionMixin, Base):
    __tablename__ = "businesses"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_businesses_version_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(128), nullable=False)


class BusinessMembershipModel(TimestampMixin, Base):
    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uq_membership_business_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)


class GoalModel(BusinessScopedMixin, Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(String(128))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConstraintModel(BusinessScopedMixin, Base):
    __tablename__ = "constraints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)


class ProductModel(BusinessScopedMixin, Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OfferModel(BusinessScopedMixin, Base):
    __tablename__ = "offers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price_descriptor: Mapped[str | None] = mapped_column(String(255))


class ChannelModel(BusinessScopedMixin, Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class SourceRecordModel(BusinessScopedMixin, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "provider",
            "external_id",
            name="uq_source_record_business_provider_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(128), nullable=False)
    trust: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceModel(BusinessScopedMixin, Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_records.id"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None]
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conflicts_with_evidence_ids: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )


class ClaimModel(BusinessScopedMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class HypothesisModel(BusinessScopedMixin, Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    model_confidence: Mapped[float | None]
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class InformationNeedModel(BusinessScopedMixin, Base):
    __tablename__ = "information_needs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessSnapshotModel(Base):
    __tablename__ = "business_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CampaignModel(BusinessScopedMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal_id: Mapped[str | None] = mapped_column(String(36))


class LaunchModel(BusinessScopedMixin, Base):
    __tablename__ = "launches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id"), nullable=False, index=True
    )
    offer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("offers.id"), nullable=False, index=True
    )
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("business_snapshots.id")
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)


class LaunchPhaseModel(BusinessScopedMixin, Base):
    __tablename__ = "launch_phases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    launch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("launches.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DecisionModel(BusinessScopedMixin, Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    goal_problem: Mapped[str] = mapped_column(Text, nullable=False)
    selected_action: Mapped[str] = mapped_column(Text, nullable=False)
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None]
    reversibility: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("business_snapshots.id")
    )
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id"), index=True
    )
    next_checkpoint: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    assumption_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    known_unknown_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class DecisionAlternativeModel(BusinessScopedMixin, Base):
    __tablename__ = "decision_alternatives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False)


class ControllerReviewModel(BusinessScopedMixin, Base):
    __tablename__ = "controller_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id"), index=True
    )
    asset_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    controller_name: Mapped[str] = mapped_column(String(128), nullable=False)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentModel(BusinessScopedMixin, Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("hypotheses.id")
    )
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    causality_class: Mapped[str] = mapped_column(String(128), nullable=False)


class ExperimentRuleModel(BusinessScopedMixin, Base):
    __tablename__ = "experiment_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id"), nullable=False, index=True
    )
    baseline: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    treatment: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    window: Mapped[str] = mapped_column(String(128), nullable=False)
    attribution_method: Mapped[str] = mapped_column(String(128), nullable=False)
    success_threshold: Mapped[str] = mapped_column(String(128), nullable=False)
    weak_signal_threshold: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_threshold: Mapped[str] = mapped_column(String(128), nullable=False)
    next_action_on_success: Mapped[str] = mapped_column(Text, nullable=False)
    next_action_on_weak_signal: Mapped[str] = mapped_column(Text, nullable=False)
    next_action_on_failure: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentResultModel(BusinessScopedMixin, Base):
    __tablename__ = "experiment_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id"), nullable=False, index=True
    )
    result_class: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_value: Mapped[str] = mapped_column(Text, nullable=False)
    interpreted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreativeBriefModel(BusinessScopedMixin, Base):
    __tablename__ = "creative_briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class AssetModel(BusinessScopedMixin, Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    creative_brief_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_briefs.id"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class AssetVersionModel(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_asset_version_number"),
        CheckConstraint("version_number >= 1", name="ck_asset_versions_number_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationModel(BusinessScopedMixin, Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PermissionPolicyModel(BusinessScopedMixin, Base):
    __tablename__ = "permission_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    public_visibility: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ActionModel(BusinessScopedMixin, Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint(
            "target_object_version >= 1",
            name="ck_actions_target_object_version_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_object_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_object_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class ApprovalModel(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("object_version >= 1", name="ck_approvals_object_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actions.id"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionModel(BusinessScopedMixin, Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actions.id"), nullable=False, index=True
    )
    approval_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approvals.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    external_reference: Mapped[str | None] = mapped_column(String(255))


class BusinessEventModel(BusinessScopedMixin, Base):
    __tablename__ = "business_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_records.id"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobModel(BusinessScopedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "business_id",
            "job_type",
            "idempotency_key",
            name="uq_jobs_tenant_type_idempotency",
        ),
        CheckConstraint("payload_schema_version >= 1", name="ck_jobs_payload_schema_positive"),
        CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts_positive"),
        CheckConstraint(
            "status in ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED')",
            name="ck_jobs_status_phase2a",
        ),
        Index("ix_jobs_due_scan", "status", "available_at"),
        Index("ix_jobs_claim_scan", "status", "available_at", "lease_expires_at"),
        Index("ix_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_class: Mapped[str | None] = mapped_column(String(255))
    error_summary: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentDefinitionModel(BusinessScopedMixin, Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mission: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AgentRunModel(BusinessScopedMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(255))
    output_ref: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)


class AuditLogModel(BusinessScopedMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)


class FeatureFlagModel(BusinessScopedMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("business_id", "key", name="uq_feature_flag_business_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class LearningModel(BusinessScopedMixin, Base):
    __tablename__ = "learnings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id"), index=True
    )
    experiment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("experiments.id"), index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    causality_class: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float | None]
