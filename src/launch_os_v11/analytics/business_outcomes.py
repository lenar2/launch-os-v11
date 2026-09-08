from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.domain.enums import (
    BusinessOutcomeClass,
    CausalityClass,
    EpistemicStatus,
    OutboxStatus,
    OutcomeDataAvailability,
    OutcomeEconomicLinkType,
    OutcomeInstrumentationStatus,
    OutcomeMetricAggregation,
    SourceTrust,
)
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models
from launch_os_v11.persistence.repositories import ScopedRepository
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets

OUTCOME_METRIC_CALCULATION_VERSION = "business_outcomes.metric.v1"
OUTCOME_EVENT_RULE_VERSION = "business_outcomes.event_filter.v1"

PII_FIELD_NAMES = {
    "email",
    "phone",
    "full_name",
    "first_name",
    "last_name",
    "telegram_username",
    "telegram_user_id",
    "customer_name",
}


@dataclass(frozen=True)
class OutcomeIngestResult:
    source_record: models.SourceRecordModel
    evidence: models.EvidenceModel
    business_event: models.BusinessEventModel
    created: bool


@dataclass(frozen=True)
class OutcomeMetricCalculationResult:
    metric_version: models.OutcomeMetricVersionModel
    created: bool


@dataclass(frozen=True)
class OutcomeEconomicLinkResult:
    economic_link: models.OutcomeEconomicLinkModel
    evidence: models.EvidenceModel


@dataclass(frozen=True)
class OutcomeLearningResult:
    learning: models.LearningModel
    created: bool


def create_outcome_ingestion_contract(
    session: Session,
    *,
    scope: TenantScope,
    provider: str,
    contract_key: str,
    payload_schema_version: int,
    outcome_class: BusinessOutcomeClass,
    canonical_event_type: str,
    identity_boundary: str,
    pii_classification: str,
    retention_class: str,
    schema: Mapping[str, object],
    clock: Clock,
) -> models.OutcomeIngestionContractModel:
    assert_no_secrets(schema)
    _validate_contract_schema(schema)
    if payload_schema_version < 1:
        raise PermanentJobError("payload_schema_version must be positive")
    if not provider or not contract_key or not canonical_event_type:
        raise PermanentJobError("outcome ingestion contract identifiers are required")
    source = _source_record(
        session,
        scope=scope,
        provider="launch_os",
        external_id=f"outcome-ingestion-contract:{provider}:{contract_key}:v{payload_schema_version}",
        source_type="outcome_ingestion_contract",
        trust=SourceTrust.INTERNAL_SYSTEM,
        payload={
            "provider": provider,
            "contract_key": contract_key,
            "payload_schema_version": payload_schema_version,
            "canonical_event_type": canonical_event_type,
            "non_live": True,
        },
        source_occurred_at=clock.now(),
        ingested_at=clock.now(),
    )
    contract = models.OutcomeIngestionContractModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider=provider,
        contract_key=contract_key,
        payload_schema_version=payload_schema_version,
        outcome_class=outcome_class.value,
        canonical_event_type=canonical_event_type,
        identity_boundary=identity_boundary,
        pii_classification=pii_classification,
        retention_class=retention_class,
        status=OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value,
        schema=dict(schema),
        provenance_source_record_id=source.id,
    )
    ScopedRepository(session, scope, models.OutcomeIngestionContractModel).add(contract)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_INGESTION_CONTRACT_CREATED",
        object_type="OutcomeIngestionContract",
        object_id=contract.id,
        payload={"contract_key": contract.contract_key, "status": contract.status},
        correlation_id=f"outcome-contract:{contract.id}",
        causation_id=source.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.ingestion_contract.created",
        aggregate_type="OutcomeIngestionContract",
        aggregate_id=contract.id,
        payload={"contract_key": contract.contract_key, "status": contract.status},
        clock=clock,
        correlation_id=f"outcome-contract:{contract.id}",
        causation_id=source.id,
    )
    return contract


def create_outcome_metric_definition(
    session: Session,
    *,
    scope: TenantScope,
    metric_key: str,
    outcome_class: BusinessOutcomeClass,
    numerator_event_type: str,
    aggregation: OutcomeMetricAggregation,
    eligible_population: str,
    denominator_description: str,
    observation_window_seconds: int,
    attribution_method: str,
    attribution_limitations: Sequence[str],
    data_availability: OutcomeDataAvailability,
    downstream_economic_meaning: str,
    clock: Clock,
    denominator_event_type: str | None = None,
    value_field: str | None = None,
    ingestion_contract_id: str | None = None,
) -> models.OutcomeMetricDefinitionModel:
    if aggregation == OutcomeMetricAggregation.RATE and denominator_event_type is None:
        raise PermanentJobError("rate outcome metrics require denominator_event_type")
    if aggregation == OutcomeMetricAggregation.SUM and value_field is None:
        raise PermanentJobError("sum outcome metrics require value_field")
    if observation_window_seconds < 1:
        raise PermanentJobError("observation_window_seconds must be positive")
    if not metric_key or not numerator_event_type:
        raise PermanentJobError("outcome metric identifiers are required")
    if ingestion_contract_id is not None:
        ingestion_contract = ScopedRepository(
            session, scope, models.OutcomeIngestionContractModel
        ).require(ingestion_contract_id)
        if ingestion_contract.status != OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value:
            raise PermanentJobError(
                "outcome metric definitions require a disabled non-live ingestion contract"
            )
        if ingestion_contract.canonical_event_type != numerator_event_type:
            raise PermanentJobError(
                "outcome metric numerator event type must match ingestion contract"
            )
        if ingestion_contract.outcome_class != outcome_class.value:
            raise PermanentJobError(
                "outcome metric class must match ingestion contract outcome class"
            )
    source = _source_record(
        session,
        scope=scope,
        provider="launch_os",
        external_id=f"outcome-metric-definition:{metric_key}:v1",
        source_type="outcome_metric_definition",
        trust=SourceTrust.INTERNAL_SYSTEM,
        payload={
            "metric_key": metric_key,
            "outcome_class": outcome_class.value,
            "numerator_event_type": numerator_event_type,
            "denominator_event_type": denominator_event_type,
            "aggregation": aggregation.value,
            "non_live": True,
        },
        source_occurred_at=clock.now(),
        ingested_at=clock.now(),
    )
    definition = models.OutcomeMetricDefinitionModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        metric_key=metric_key,
        definition_version=1,
        outcome_class=outcome_class.value,
        numerator_event_type=numerator_event_type,
        denominator_event_type=denominator_event_type,
        aggregation=aggregation.value,
        value_field=value_field,
        eligible_population=eligible_population,
        denominator_description=denominator_description,
        observation_window_seconds=observation_window_seconds,
        attribution_method=attribution_method,
        attribution_limitations=list(attribution_limitations),
        data_availability=data_availability.value,
        downstream_economic_meaning=downstream_economic_meaning,
        status=OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value,
        ingestion_contract_id=ingestion_contract_id,
        provenance_source_record_id=source.id,
    )
    ScopedRepository(session, scope, models.OutcomeMetricDefinitionModel).add(definition)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_METRIC_DEFINITION_CREATED",
        object_type="OutcomeMetricDefinition",
        object_id=definition.id,
        payload={"metric_key": metric_key, "status": definition.status},
        correlation_id=f"outcome-definition:{definition.id}",
        causation_id=source.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.metric_definition.created",
        aggregate_type="OutcomeMetricDefinition",
        aggregate_id=definition.id,
        payload={"metric_key": metric_key, "status": definition.status},
        clock=clock,
        correlation_id=f"outcome-definition:{definition.id}",
        causation_id=source.id,
    )
    return definition


def ingest_synthetic_outcome_observation(
    session: Session,
    *,
    scope: TenantScope,
    ingestion_contract_id: str,
    external_event_id: str,
    occurred_at: datetime,
    payload: Mapping[str, object],
    clock: Clock,
    correlation_id: str,
    causation_id: str | None = None,
) -> OutcomeIngestResult:
    assert_no_secrets(payload)
    _assert_no_raw_identity(payload)
    contract = ScopedRepository(
        session, scope, models.OutcomeIngestionContractModel
    ).require(ingestion_contract_id)
    _validate_payload_against_contract_schema(payload, contract.schema)
    if contract.status != OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value:
        raise PermanentJobError("synthetic outcome ingestion requires DISABLED_NON_LIVE contract")
    request_fingerprint = _hash_payload(
        {
            "ingestion_contract_id": contract.id,
            "payload_schema_version": contract.payload_schema_version,
            "external_event_id": external_event_id,
            "occurred_at": occurred_at.isoformat(),
            "payload": dict(payload),
            "correlation_id": correlation_id,
            "causation_id": causation_id,
        }
    )
    existing_source = session.scalar(
        select(models.SourceRecordModel).where(
            models.SourceRecordModel.organization_id == scope.organization_id,
            models.SourceRecordModel.business_id == scope.business_id,
            models.SourceRecordModel.provider == contract.provider,
            models.SourceRecordModel.external_id == external_event_id,
        )
    )
    if existing_source is not None:
        existing_event = session.scalar(
            select(models.BusinessEventModel).where(
                models.BusinessEventModel.source_record_id == existing_source.id
            )
        )
        existing_evidence = session.scalar(
            select(models.EvidenceModel).where(
                models.EvidenceModel.source_record_id == existing_source.id
            )
        )
        if existing_event is None or existing_evidence is None:
            raise PermanentJobError("synthetic outcome idempotency records are incomplete")
        if (
            existing_source.source_type != "synthetic_outcome_observation"
            or existing_source.payload.get("ingestion_contract_id") != contract.id
            or existing_source.payload.get("payload_schema_version")
            != contract.payload_schema_version
            or existing_source.payload.get("request_fingerprint") != request_fingerprint
            or existing_event.event_type != contract.canonical_event_type
        ):
            raise PermanentJobError(
                "synthetic outcome external_event_id conflicts with a different request"
            )
        return OutcomeIngestResult(
            source_record=existing_source,
            evidence=existing_evidence,
            business_event=existing_event,
            created=False,
        )
    source = _source_record(
        session,
        scope=scope,
        provider=contract.provider,
        external_id=external_event_id,
        source_type="synthetic_outcome_observation",
        trust=SourceTrust.INTERNAL_SYSTEM,
        payload={
            "ingestion_contract_id": contract.id,
            "payload_schema_version": contract.payload_schema_version,
            "raw_payload": dict(payload),
            "request_fingerprint": request_fingerprint,
            "non_live": True,
        },
        source_occurred_at=occurred_at,
        ingested_at=clock.now(),
    )
    evidence = models.EvidenceModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement=(
            f"Synthetic non-live outcome observation {contract.canonical_event_type} "
            f"recorded from contract {contract.contract_key}."
        ),
        status=EpistemicStatus.OBSERVATION.value,
        confidence=None,
        occurred_at=occurred_at,
        recorded_at=clock.now(),
        conflicts_with_evidence_ids=[],
    )
    ScopedRepository(session, scope, models.EvidenceModel).add(evidence)
    event_payload = {
        "outcome_class": contract.outcome_class,
        "ingestion_contract_id": contract.id,
        "source_record_id": source.id,
        "synthetic_non_live": True,
        **dict(payload),
    }
    business_event = models.BusinessEventModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        event_type=contract.canonical_event_type,
        source_record_id=source.id,
        occurred_at=occurred_at,
        recorded_at=clock.now(),
        payload=event_payload,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    ScopedRepository(session, scope, models.BusinessEventModel).add(business_event)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="SYNTHETIC_OUTCOME_OBSERVATION_INGESTED",
        object_type="BusinessEvent",
        object_id=business_event.id,
        payload={
            "event_type": business_event.event_type,
            "source_record_id": source.id,
            "evidence_id": evidence.id,
        },
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.synthetic_observation.ingested",
        aggregate_type="BusinessEvent",
        aggregate_id=business_event.id,
        payload={"event_type": business_event.event_type, "non_live": True},
        clock=clock,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    return OutcomeIngestResult(
        source_record=source,
        evidence=evidence,
        business_event=business_event,
        created=True,
    )


def calculate_outcome_metric_version(
    session: Session,
    *,
    scope: TenantScope,
    metric_definition_id: str,
    subject_type: str,
    subject_id: str,
    source_window_start: datetime,
    source_window_end: datetime,
    clock: Clock,
    corrects_metric_version_id: str | None = None,
) -> OutcomeMetricCalculationResult:
    if source_window_end <= source_window_start:
        raise PermanentJobError("source window end must be after start")
    definition = ScopedRepository(
        session, scope, models.OutcomeMetricDefinitionModel
    ).require(metric_definition_id)
    session.execute(
        select(models.OutcomeMetricDefinitionModel.id)
        .where(models.OutcomeMetricDefinitionModel.id == definition.id)
        .with_for_update()
    ).scalar_one()
    if definition.status != OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value:
        raise PermanentJobError(
            "outcome metric calculation is only enabled for non-live definitions"
        )
    numerator_events = _events_for_metric(
        session,
        scope=scope,
        event_type=definition.numerator_event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        source_window_start=source_window_start,
        source_window_end=source_window_end,
    )
    denominator_events = (
        _events_for_metric(
            session,
            scope=scope,
            event_type=definition.denominator_event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            source_window_start=source_window_start,
            source_window_end=source_window_end,
        )
        if definition.denominator_event_type is not None
        else []
    )
    all_metric_events = [*denominator_events, *numerator_events]
    if any(event.payload.get("synthetic_non_live") is not True for event in all_metric_events):
        raise PermanentJobError(
            "disabled outcome metrics may only derive from synthetic non-live events"
        )
    numerator_count = len(numerator_events)
    denominator_count = len(denominator_events) if definition.denominator_event_type else None
    value = (
        None
        if definition.data_availability == OutcomeDataAvailability.UNAVAILABLE.value
        else _metric_value(
            definition=definition,
            numerator_events=numerator_events,
            denominator_count=denominator_count,
        )
    )
    availability = (
        definition.data_availability
        if value is not None
        else OutcomeDataAvailability.UNAVAILABLE.value
    )
    coverage = (
        "COMPLETE"
        if availability == OutcomeDataAvailability.AVAILABLE.value
        else availability
    )
    event_ids = [event.id for event in all_metric_events]
    correction_target = None
    if corrects_metric_version_id is not None:
        correction_target = ScopedRepository(
            session, scope, models.OutcomeMetricVersionModel
        ).require(corrects_metric_version_id)
        if (
            correction_target.metric_definition_id != definition.id
            or correction_target.subject_type != subject_type
            or correction_target.subject_id != subject_id
        ):
            raise PermanentJobError(
                "corrected metric version must belong to the same definition and subject"
            )
    derivation = {
        "calculation_version": OUTCOME_METRIC_CALCULATION_VERSION,
        "metric_definition_id": definition.id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "window_start": source_window_start.isoformat(),
        "window_end": source_window_end.isoformat(),
        "included_business_event_ids": event_ids,
        "numerator_count": numerator_count,
        "denominator_count": denominator_count,
        "value_numeric": value,
        "corrects_metric_version_id": corrects_metric_version_id,
    }
    derivation_hash = _hash_payload(derivation)
    existing_derivation = session.scalar(
        select(models.OutcomeMetricVersionModel).where(
            models.OutcomeMetricVersionModel.organization_id == scope.organization_id,
            models.OutcomeMetricVersionModel.business_id == scope.business_id,
            models.OutcomeMetricVersionModel.derivation_hash == derivation_hash,
        )
    )
    if existing_derivation is not None:
        return OutcomeMetricCalculationResult(
            metric_version=existing_derivation,
            created=False,
        )
    latest = session.scalar(
        select(models.OutcomeMetricVersionModel)
        .where(
            models.OutcomeMetricVersionModel.organization_id == scope.organization_id,
            models.OutcomeMetricVersionModel.business_id == scope.business_id,
            models.OutcomeMetricVersionModel.metric_definition_id == definition.id,
            models.OutcomeMetricVersionModel.subject_type == subject_type,
            models.OutcomeMetricVersionModel.subject_id == subject_id,
        )
        .order_by(models.OutcomeMetricVersionModel.version_number.desc())
        .limit(1)
    )
    metric_id = new_id()
    source = _source_record(
        session,
        scope=scope,
        provider="launch_os",
        external_id=f"outcome-metric-version:{metric_id}",
        source_type="outcome_metric_version",
        trust=SourceTrust.INTERNAL_SYSTEM,
        payload={
            "metric_version_id": metric_id,
            "derivation_hash": derivation_hash,
            "included_business_event_ids": event_ids,
            "synthetic_non_live": True,
            "non_live": True,
        },
        source_occurred_at=source_window_end,
        ingested_at=clock.now(),
    )
    evidence = models.EvidenceModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement=(
            f"Synthetic non-live outcome metric {definition.metric_key} for "
            f"{subject_type} {subject_id}: availability={availability}, value={value}, "
            f"numerator={numerator_count}, denominator={denominator_count}."
        ),
        status=(
            EpistemicStatus.OBSERVATION.value
            if availability == OutcomeDataAvailability.AVAILABLE.value
            else EpistemicStatus.UNKNOWN.value
        ),
        confidence=None,
        occurred_at=source_window_end,
        recorded_at=clock.now(),
        conflicts_with_evidence_ids=[],
    )
    ScopedRepository(session, scope, models.EvidenceModel).add(evidence)
    metric = models.OutcomeMetricVersionModel(
        id=metric_id,
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        metric_definition_id=definition.id,
        version_number=(latest.version_number + 1 if latest is not None else 1),
        subject_type=subject_type,
        subject_id=subject_id,
        value_numeric=value,
        numerator_count=numerator_count,
        denominator_count=denominator_count,
        availability_status=availability,
        coverage_status=coverage,
        source_window_start=source_window_start,
        source_window_end=source_window_end,
        included_business_event_ids=event_ids,
        excluded_event_rule_version=OUTCOME_EVENT_RULE_VERSION,
        calculation_version=OUTCOME_METRIC_CALCULATION_VERSION,
        calculated_at=clock.now(),
        corrects_metric_version_id=corrects_metric_version_id,
        derivation_hash=derivation_hash,
        evidence_id=evidence.id,
        synthetic_non_live=True,
    )
    ScopedRepository(session, scope, models.OutcomeMetricVersionModel).add(metric)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_METRIC_VERSION_CALCULATED",
        object_type="OutcomeMetricVersion",
        object_id=metric.id,
        payload={
            "metric_key": definition.metric_key,
            "version_number": metric.version_number,
            "availability_status": metric.availability_status,
        },
        correlation_id=f"outcome-metric:{definition.metric_key}",
        causation_id=definition.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.metric_version.calculated",
        aggregate_type="OutcomeMetricVersion",
        aggregate_id=metric.id,
        payload={
            "metric_key": definition.metric_key,
            "availability_status": metric.availability_status,
        },
        clock=clock,
        correlation_id=f"outcome-metric:{definition.metric_key}",
        causation_id=definition.id,
    )
    return OutcomeMetricCalculationResult(metric_version=metric, created=True)


def create_outcome_economic_link(
    session: Session,
    *,
    scope: TenantScope,
    metric_version_id: str,
    link_type: OutcomeEconomicLinkType,
    downstream_outcome_class: BusinessOutcomeClass,
    epistemic_status: EpistemicStatus,
    value_per_unit_cents: int | None,
    direct_cost_cents: int | None,
    fully_loaded_execution_cost_cents: int | None,
    opportunity_cost_cents: int | None,
    bounded_downside_cents: int | None,
    expected_benefit_cents: int | None,
    limitations: Sequence[str],
    clock: Clock,
    hurdle_multiplier: int = 3,
) -> OutcomeEconomicLinkResult:
    if hurdle_multiplier < 1:
        raise PermanentJobError("hurdle_multiplier must be positive")
    values = [
        value_per_unit_cents,
        direct_cost_cents,
        fully_loaded_execution_cost_cents,
        opportunity_cost_cents,
        bounded_downside_cents,
        expected_benefit_cents,
    ]
    if any(value is not None and value < 0 for value in values):
        raise PermanentJobError("economic values cannot be negative")
    metric = ScopedRepository(session, scope, models.OutcomeMetricVersionModel).require(
        metric_version_id
    )
    if metric.synthetic_non_live is not True:
        raise PermanentJobError(
            "disabled outcome economics require a synthetic non-live metric"
        )
    if epistemic_status not in {
        EpistemicStatus.HYPOTHESIS,
        EpistemicStatus.ASSUMPTION,
        EpistemicStatus.UNKNOWN,
    }:
        raise PermanentJobError(
            "disabled outcome economics cannot self-certify FACT or DERIVED_FACT"
        )
    supports_go = False
    latest = session.scalar(
        select(models.OutcomeEconomicLinkModel)
        .where(
            models.OutcomeEconomicLinkModel.organization_id == scope.organization_id,
            models.OutcomeEconomicLinkModel.business_id == scope.business_id,
            models.OutcomeEconomicLinkModel.metric_version_id == metric.id,
        )
        .order_by(models.OutcomeEconomicLinkModel.version_number.desc())
        .limit(1)
    )
    source = _source_record(
        session,
        scope=scope,
        provider="launch_os",
        external_id=(
            f"outcome-economic-link:{metric.id}:v"
            f"{(latest.version_number + 1 if latest else 1)}"
        ),
        source_type="outcome_economic_link",
        trust=SourceTrust.INTERNAL_SYSTEM,
        payload={
            "metric_version_id": metric.id,
            "link_type": link_type.value,
            "epistemic_status": epistemic_status.value,
            "supports_go": supports_go,
            "synthetic_non_live": True,
            "non_live": True,
        },
        source_occurred_at=clock.now(),
        ingested_at=clock.now(),
    )
    evidence = models.EvidenceModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement=(
            f"Outcome economic link for metric version {metric.id}: "
            f"type={link_type.value}, status={epistemic_status.value}, "
            f"supports_3x_go={supports_go}."
        ),
        status=epistemic_status.value,
        confidence=None,
        occurred_at=clock.now(),
        recorded_at=clock.now(),
        conflicts_with_evidence_ids=[],
    )
    ScopedRepository(session, scope, models.EvidenceModel).add(evidence)
    economic_link = models.OutcomeEconomicLinkModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        metric_version_id=metric.id,
        version_number=(latest.version_number + 1 if latest is not None else 1),
        link_type=link_type.value,
        downstream_outcome_class=downstream_outcome_class.value,
        epistemic_status=epistemic_status.value,
        value_per_unit_cents=value_per_unit_cents,
        direct_cost_cents=direct_cost_cents,
        fully_loaded_execution_cost_cents=fully_loaded_execution_cost_cents,
        opportunity_cost_cents=opportunity_cost_cents,
        bounded_downside_cents=bounded_downside_cents,
        expected_benefit_cents=expected_benefit_cents,
        hurdle_multiplier=hurdle_multiplier,
        supports_go=supports_go,
        evidence_id=evidence.id,
        synthetic_non_live=True,
        limitations=list(limitations),
    )
    ScopedRepository(session, scope, models.OutcomeEconomicLinkModel).add(economic_link)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_ECONOMIC_LINK_CREATED",
        object_type="OutcomeEconomicLink",
        object_id=economic_link.id,
        payload={"supports_go": supports_go, "epistemic_status": epistemic_status.value},
        correlation_id=f"outcome-economics:{metric.id}",
        causation_id=metric.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.economic_link.created",
        aggregate_type="OutcomeEconomicLink",
        aggregate_id=economic_link.id,
        payload={"supports_go": supports_go, "epistemic_status": epistemic_status.value},
        clock=clock,
        correlation_id=f"outcome-economics:{metric.id}",
        causation_id=metric.id,
    )
    return OutcomeEconomicLinkResult(economic_link=economic_link, evidence=evidence)


def create_outcome_learning(
    session: Session,
    *,
    scope: TenantScope,
    metric_version_id: str,
    economic_link_id: str,
    clock: Clock,
) -> OutcomeLearningResult:
    metric = ScopedRepository(session, scope, models.OutcomeMetricVersionModel).require(
        metric_version_id
    )
    economic_link = ScopedRepository(
        session, scope, models.OutcomeEconomicLinkModel
    ).require(economic_link_id)
    if economic_link.metric_version_id != metric.id:
        raise PermanentJobError("learning economic link does not match metric version")
    existing = next(
        (
            row
            for row in session.scalars(
                select(models.LearningModel).where(
                    models.LearningModel.organization_id == scope.organization_id,
                    models.LearningModel.business_id == scope.business_id,
                )
            )
            if metric.evidence_id in row.evidence_ids
            and economic_link.evidence_id in row.evidence_ids
        ),
        None,
    )
    if existing is not None:
        return OutcomeLearningResult(learning=existing, created=False)
    learning = models.LearningModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=None,
        experiment_id=None,
        statement=(
            f"Non-live outcome metric version {metric.id} was calculated and linked to "
            f"economics with supports_go={economic_link.supports_go}; attribution remains "
            "separate from causality."
        ),
        evidence_ids=[metric.evidence_id, economic_link.evidence_id],
        causality_class=CausalityClass.UNKNOWN.value,
        confidence=None,
        version=1,
    )
    ScopedRepository(session, scope, models.LearningModel).add(learning)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_LEARNING_MATERIALIZED",
        object_type="Learning",
        object_id=learning.id,
        payload={
            "metric_version_id": metric.id,
            "economic_link_id": economic_link.id,
            "causality_class": learning.causality_class,
        },
        correlation_id=f"outcome-learning:{metric.id}",
        causation_id=economic_link.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.learning.materialized",
        aggregate_type="Learning",
        aggregate_id=learning.id,
        payload={"metric_version_id": metric.id, "economic_link_id": economic_link.id},
        clock=clock,
        correlation_id=f"outcome-learning:{metric.id}",
        causation_id=economic_link.id,
    )
    return OutcomeLearningResult(learning=learning, created=True)


def create_outcome_experiment_proposal(
    session: Session,
    *,
    scope: TenantScope,
    metric_definition_id: str,
    metric_version_id: str,
    economic_link_id: str,
    learning_id: str,
    hypothesis: str,
    treatment: str,
    control: str,
    success_threshold: str,
    weak_signal_threshold: str,
    failure_threshold: str,
    limitations: Sequence[str],
    clock: Clock,
) -> models.OutcomeExperimentProposalModel:
    definition = ScopedRepository(
        session, scope, models.OutcomeMetricDefinitionModel
    ).require(metric_definition_id)
    metric = ScopedRepository(session, scope, models.OutcomeMetricVersionModel).require(
        metric_version_id
    )
    economic_link = ScopedRepository(
        session, scope, models.OutcomeEconomicLinkModel
    ).require(economic_link_id)
    learning = ScopedRepository(session, scope, models.LearningModel).require(learning_id)
    if metric.metric_definition_id != definition.id:
        raise PermanentJobError("proposal metric does not match definition")
    if economic_link.metric_version_id != metric.id:
        raise PermanentJobError("proposal economic link does not match metric")
    if economic_link.supports_go:
        raise PermanentJobError("disabled non-live proposal cannot carry GO authority")
    if set(learning.evidence_ids) != {metric.evidence_id, economic_link.evidence_id}:
        raise PermanentJobError("proposal learning evidence must match metric/economic inputs")
    proposal = models.OutcomeExperimentProposalModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        metric_definition_id=definition.id,
        metric_version_id=metric.id,
        economic_link_id=economic_link.id,
        learning_id=learning.id,
        status=OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value,
        hypothesis=hypothesis,
        selected_metric_key=definition.metric_key,
        eligible_population=definition.eligible_population,
        treatment=treatment,
        control=control,
        success_threshold=success_threshold,
        weak_signal_threshold=weak_signal_threshold,
        failure_threshold=failure_threshold,
        evidence_ids=list(learning.evidence_ids),
        limitations=list(limitations),
        payload={
            "non_live": True,
            "supports_go": economic_link.supports_go,
            "causality_class": learning.causality_class,
            "external_execution_authorized": False,
        },
    )
    ScopedRepository(session, scope, models.OutcomeExperimentProposalModel).add(proposal)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="OUTCOME_EXPERIMENT_PROPOSAL_CREATED",
        object_type="OutcomeExperimentProposal",
        object_id=proposal.id,
        payload={"selected_metric_key": definition.metric_key, "status": proposal.status},
        correlation_id=f"outcome-proposal:{proposal.id}",
        causation_id=learning.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="outcome.experiment_proposal.created",
        aggregate_type="OutcomeExperimentProposal",
        aggregate_id=proposal.id,
        payload={"selected_metric_key": definition.metric_key, "status": proposal.status},
        clock=clock,
        correlation_id=f"outcome-proposal:{proposal.id}",
        causation_id=learning.id,
    )
    return proposal


def _metric_value(
    *,
    definition: models.OutcomeMetricDefinitionModel,
    numerator_events: Sequence[models.BusinessEventModel],
    denominator_count: int | None,
) -> float | None:
    if definition.aggregation == OutcomeMetricAggregation.COUNT.value:
        return float(len(numerator_events))
    if definition.aggregation == OutcomeMetricAggregation.RATE.value:
        if denominator_count is None or denominator_count == 0:
            return None
        return len(numerator_events) / denominator_count
    if definition.aggregation == OutcomeMetricAggregation.SUM.value:
        if definition.value_field is None:
            raise PermanentJobError("sum outcome metric requires value_field")
        total = 0.0
        for event in numerator_events:
            value = event.payload.get(definition.value_field)
            if not isinstance(value, int | float):
                raise PermanentJobError("sum outcome metric value field must be numeric")
            total += float(value)
        return total
    raise PermanentJobError(f"unsupported outcome metric aggregation: {definition.aggregation}")


def _events_for_metric(
    session: Session,
    *,
    scope: TenantScope,
    event_type: str | None,
    subject_type: str,
    subject_id: str,
    source_window_start: datetime,
    source_window_end: datetime,
) -> list[models.BusinessEventModel]:
    if event_type is None:
        return []
    rows = list(
        session.scalars(
            select(models.BusinessEventModel)
            .where(
                models.BusinessEventModel.organization_id == scope.organization_id,
                models.BusinessEventModel.business_id == scope.business_id,
                models.BusinessEventModel.event_type == event_type,
                models.BusinessEventModel.occurred_at >= source_window_start,
                models.BusinessEventModel.occurred_at <= source_window_end,
            )
            .order_by(models.BusinessEventModel.occurred_at, models.BusinessEventModel.id)
        )
    )
    return [
        row
        for row in rows
        if row.payload.get("subject_type") == subject_type
        and row.payload.get("subject_id") == subject_id
    ]


def _source_record(
    session: Session,
    *,
    scope: TenantScope,
    provider: str,
    external_id: str,
    source_type: str,
    trust: SourceTrust,
    payload: Mapping[str, object],
    source_occurred_at: datetime,
    ingested_at: datetime,
) -> models.SourceRecordModel:
    assert_no_secrets(payload)
    source = models.SourceRecordModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider=provider,
        external_id=external_id,
        source_type=source_type,
        trust=trust.value,
        payload=dict(payload),
        source_occurred_at=source_occurred_at,
        ingested_at=ingested_at,
    )
    ScopedRepository(session, scope, models.SourceRecordModel).add(source)
    session.flush()
    return source


def _audit(
    session: Session,
    *,
    scope: TenantScope,
    action: str,
    object_type: str,
    object_id: str,
    payload: Mapping[str, object],
    correlation_id: str,
    causation_id: str | None,
) -> None:
    session.add(
        models.AuditLogModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            actor_user_id=None,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=dict(payload),
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
    )


def _outbox(
    session: Session,
    *,
    scope: TenantScope,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: Mapping[str, object],
    clock: Clock,
    correlation_id: str,
    causation_id: str | None,
) -> None:
    session.add(
        models.OutboxEventModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=dict(payload),
            status=OutboxStatus.PENDING.value,
            occurred_at=clock.now(),
            correlation_id=correlation_id,
            causation_id=causation_id,
            created_at=clock.now(),
        )
    )



def _validate_contract_schema(schema: Mapping[str, object]) -> None:
    if schema.get("type") != "object":
        raise PermanentJobError("outcome contract schema must be an object schema")
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping):
        raise PermanentJobError("outcome contract schema properties are required")
    if (
        not isinstance(required, Sequence)
        or isinstance(required, bytes | bytearray | str)
        or any(not isinstance(item, str) for item in required)
    ):
        raise PermanentJobError("outcome contract schema required must be a string list")
    if schema.get("additionalProperties") is not False:
        raise PermanentJobError(
            "outcome contract schema must set additionalProperties=false"
        )
    missing_required = [item for item in required if item not in properties]
    if missing_required:
        raise PermanentJobError("outcome contract schema required fields must be declared")
    for field_name, field_schema in properties.items():
        if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
            raise PermanentJobError("outcome contract schema properties are invalid")
        if _looks_like_pii_field_name(field_name):
            raise PermanentJobError("raw identity fields are not allowed in outcome schemas")
        field_type = field_schema.get("type")
        if field_type not in {"string", "integer", "number", "boolean"}:
            raise PermanentJobError(
                "outcome contract schema supports only scalar property types"
            )


def _validate_payload_against_contract_schema(
    payload: Mapping[str, object],
    schema: Mapping[str, object],
) -> None:
    _validate_contract_schema(schema)
    properties = schema["properties"]
    required = schema["required"]
    assert isinstance(properties, Mapping)
    assert isinstance(required, Sequence)
    allowed = set(properties)
    missing = [item for item in required if item not in payload]
    if missing:
        raise PermanentJobError("synthetic outcome payload is missing required fields")
    extras = set(payload) - allowed
    if extras:
        raise PermanentJobError("synthetic outcome payload contains undeclared fields")
    for field_name, value in payload.items():
        field_schema = properties[field_name]
        assert isinstance(field_schema, Mapping)
        expected_type = field_schema.get("type")
        if not _matches_schema_scalar_type(value, expected_type):
            raise PermanentJobError(
                f"synthetic outcome payload field {field_name} has wrong type"
            )


def _matches_schema_scalar_type(value: object, expected_type: object) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return False


def _looks_like_pii_field_name(field_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", field_name.lower())
    pii_names = {
        "email",
        "phone",
        "fullname",
        "firstname",
        "lastname",
        "customername",
        "customeremail",
        "customerphone",
        "address",
        "streetaddress",
        "postaladdress",
        "telegramusername",
        "telegramuserid",
        "username",
        "useremail",
        "userphone",
    }
    return normalized in pii_names



def _assert_no_raw_identity(payload: Mapping[str, object]) -> None:
    for key, value in payload.items():
        if key.lower() in PII_FIELD_NAMES or _looks_like_pii_field_name(key):
            raise PermanentJobError("raw identity fields are not allowed in outcome fixtures")
        if isinstance(value, Mapping):
            _assert_no_raw_identity(value)
        elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
            for item in value:
                if isinstance(item, Mapping):
                    _assert_no_raw_identity(item)


def _hash_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
