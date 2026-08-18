from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import Base


class ConnectorAccountModel(Base):
    __tablename__ = "connector_accounts"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "channel_id",
            "provider",
            name="uq_connector_account_business_channel_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    target_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    write_capability: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ActionProposalDetailModel(Base):
    __tablename__ = "action_proposal_details"
    __table_args__ = (
        UniqueConstraint("action_id", name="uq_action_proposal_detail_action"),
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
    production_workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("production_workflows.id"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_versions.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), nullable=False, index=True
    )
    connector_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_accounts.id"), nullable=False, index=True
    )
    target_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    delivery_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ExecutionControllerReviewModel(Base):
    __tablename__ = "execution_controller_reviews"
    __table_args__ = (
        UniqueConstraint(
            "action_id",
            "controller_type",
            name="uq_execution_review_action_controller",
        ),
        CheckConstraint(
            "verdict in ('PASS', 'PASS_WITH_CONDITIONS', 'REVISE', 'BLOCK')",
            name="ck_execution_controller_reviews_verdict",
        ),
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
    controller_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PermissionEvaluationModel(Base):
    __tablename__ = "permission_evaluations"
    __table_args__ = (
        UniqueConstraint("action_id", name="uq_permission_evaluation_action"),
        CheckConstraint(
            "outcome in ('BLOCKED', 'APPROVAL_REQUIRED', 'ALLOWED')",
            name="ck_permission_evaluations_outcome",
        ),
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
    permission_policy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("permission_policies.id"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GlobalExecutionControlModel(Base):
    __tablename__ = "global_execution_controls"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_global_execution_control_business"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    automation_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoke_all_write_capabilities: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ExternalReferenceModel(Base):
    __tablename__ = "external_references"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "connector_account_id",
            "external_object_type",
            "external_id",
            name="uq_external_reference_provider_account_object",
        ),
        UniqueConstraint("execution_id", name="uq_external_reference_execution"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_accounts.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id"), nullable=False, index=True
    )
    external_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_parent_id: Mapped[str | None] = mapped_column(String(255))
    action_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actions.id"), nullable=False, index=True
    )
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PublicationExecutionLinkModel(Base):
    __tablename__ = "publication_execution_links"
    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_publication_execution_link_publication"),
        UniqueConstraint("execution_id", name="uq_publication_execution_link_execution"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    publication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("publications.id"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actions.id"), nullable=False, index=True
    )
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id"), nullable=False, index=True
    )
    external_reference_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("external_references.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
