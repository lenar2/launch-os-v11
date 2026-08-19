from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import Base


class Phase6DecisionIntentModel(Base):
    __tablename__ = "phase6_decision_intents"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_phase6_decision_intent_workflow"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decision_workflows.id"), nullable=False, index=True
    )
    checkpoint_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checkpoint_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prior_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id"), index=True
    )
    learning_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("learnings.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CheckpointDefinitionModel(Base):
    __tablename__ = "checkpoint_definitions"
    __table_args__ = (
        UniqueConstraint("experiment_id", name="uq_checkpoint_definition_experiment"),
        CheckConstraint("schema_version >= 1", name="ck_checkpoint_schema_positive"),
        CheckConstraint("window_seconds >= 1", name="ck_checkpoint_window_positive"),
        CheckConstraint("grace_seconds >= 0", name="ck_checkpoint_grace_nonnegative"),
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
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id"), nullable=False, index=True
    )
    experiment_rule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_rules.id"), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_window_anchor: Mapped[str] = mapped_column(String(64), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    success_operator: Mapped[str] = mapped_column(String(16), nullable=False)
    success_value: Mapped[float] = mapped_column(Float, nullable=False)
    weak_signal_operator: Mapped[str] = mapped_column(String(16), nullable=False)
    weak_signal_value: Mapped[float] = mapped_column(Float, nullable=False)
    failure_operator: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_value: Mapped[float] = mapped_column(Float, nullable=False)
    coverage_requirement: Mapped[str] = mapped_column(String(64), nullable=False)
    attribution_method: Mapped[str] = mapped_column(String(128), nullable=False)
    next_action_on_success: Mapped[str] = mapped_column(Text, nullable=False)
    next_action_on_weak_signal: Mapped[str] = mapped_column(Text, nullable=False)
    next_action_on_failure: Mapped[str] = mapped_column(Text, nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ConnectorObservationStateModel(Base):
    __tablename__ = "connector_observation_states"
    __table_args__ = (
        UniqueConstraint(
            "connector_account_id", name="uq_connector_observation_state_account"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    connector_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_accounts.id"), nullable=False, index=True
    )
    observation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    last_update_id: Mapped[int | None] = mapped_column(BigInteger)
    coverage_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_successful_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    gap_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_update_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ConnectorObservationModel(Base):
    __tablename__ = "connector_observations"
    __table_args__ = (
        UniqueConstraint(
            "connector_account_id",
            "provider_event_identity",
            name="uq_connector_observation_account_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    connector_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_accounts.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_event_identity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    external_object_id: Mapped[str | None] = mapped_column(String(255), index=True)
    external_parent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trust_class: Mapped[str] = mapped_column(String(64), nullable=False)


class NormalizedObservationLinkModel(Base):
    __tablename__ = "normalized_observation_links"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_normalized_observation_link_observation"),
        UniqueConstraint("business_event_id", name="uq_normalized_observation_link_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_observations.id"), nullable=False, index=True
    )
    source_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_records.id"), nullable=False, index=True
    )
    business_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("business_events.id"), nullable=False, index=True
    )
    evidence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=False, index=True
    )
    publication_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("publications.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MetricVersionModel(Base):
    __tablename__ = "metric_versions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "metric_key",
            "subject_type",
            "subject_id",
            "version_number",
            name="uq_metric_version_subject_version",
        ),
        CheckConstraint("version_number >= 1", name="ck_metric_version_positive"),
        CheckConstraint(
            "availability_status in ('AVAILABLE', 'PARTIAL', 'UNAVAILABLE', 'STALE')",
            name="ck_metric_version_availability",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    checkpoint_definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("checkpoint_definitions.id"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connector_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connector_accounts.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    included_business_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    excluded_event_rule_version: Mapped[str] = mapped_column(String(128), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(128), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_metric_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("metric_versions.id"), index=True
    )
    derivation_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=False, index=True
    )


class ExperimentResultDetailModel(Base):
    __tablename__ = "experiment_result_details"
    __table_args__ = (
        UniqueConstraint("experiment_result_id", name="uq_experiment_result_detail_result"),
        UniqueConstraint("metric_version_id", name="uq_experiment_result_detail_metric"),
        CheckConstraint(
            "result_class in ('SUCCESS', 'WEAK_SIGNAL', 'FAILURE', 'INSUFFICIENT_DATA')",
            name="ck_experiment_result_detail_class",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    experiment_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_results.id"), nullable=False, index=True
    )
    checkpoint_definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("checkpoint_definitions.id"), nullable=False, index=True
    )
    metric_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("metric_versions.id"), nullable=False, index=True
    )
    result_class: Mapped[str] = mapped_column(String(32), nullable=False)
    checkpoint_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_coverage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class LearningControllerReviewModel(Base):
    __tablename__ = "learning_controller_reviews"
    __table_args__ = (
        UniqueConstraint(
            "experiment_result_id",
            "controller_type",
            name="uq_learning_review_result_controller",
        ),
        CheckConstraint(
            "verdict in ('PASS', 'PASS_WITH_CONDITIONS', 'BLOCK')",
            name="ck_learning_controller_review_verdict",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    experiment_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_results.id"), nullable=False, index=True
    )
    controller_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    limits: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    causality_ceiling: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class LearningDetailModel(Base):
    __tablename__ = "learning_details"
    __table_args__ = (
        UniqueConstraint("learning_id", name="uq_learning_detail_learning"),
        UniqueConstraint("experiment_result_id", name="uq_learning_detail_result"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    learning_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learnings.id"), nullable=False, index=True
    )
    experiment_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_results.id"), nullable=False, index=True
    )
    metric_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    interpretation_class: Mapped[str] = mapped_column(String(32), nullable=False)
    limits: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    controller_review_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class DecisionLearningLinkModel(Base):
    __tablename__ = "decision_learning_links"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_decision_learning_link_decision"),
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
    prior_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=False, index=True
    )
    learning_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learnings.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
