from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.connectors.telegram_observation import (
    TelegramObservationConnector,
    TelegramObservationUnavailable,
)
from launch_os_v11.domain.enums import (
    CausalityClass,
    ControllerVerdict,
    EpistemicStatus,
    OutboxStatus,
    SourceTrust,
)
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.execution_models import (
    ActionProposalDetailModel,
    ConnectorAccountModel,
    ExternalReferenceModel,
    PublicationExecutionLinkModel,
)
from launch_os_v11.persistence.models import (
    AuditLogModel,
    BusinessEventModel,
    EvidenceModel,
    ExperimentModel,
    ExperimentResultModel,
    LearningModel,
    OutboxEventModel,
    PublicationModel,
    SourceRecordModel,
)
from launch_os_v11.persistence.phase6_models import (
    CheckpointDefinitionModel,
    ConnectorObservationModel,
    ConnectorObservationStateModel,
    ExperimentResultDetailModel,
    LearningControllerReviewModel,
    LearningDetailModel,
    MetricVersionModel,
    NormalizedObservationLinkModel,
)
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION,
    JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION,
    JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES,
    JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT,
    JOB_TYPE_LEARNING_RUN_GOVERNED,
    RuntimeJobContext,
)
from launch_os_v11.runtime.errors import PermanentJobError, TransientJobError
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.transport import JobQueue

TELEGRAM_ALLOWED_UPDATES = (
    "channel_post",
    "message_reaction",
    "message_reaction_count",
)
REACTION_EVENT_TYPES = {
    "telegram.message_reaction",
    "telegram.message_reaction_count",
}
METRIC_CALCULATION_VERSION = "phase6.telegram_reaction_changes.v1"
EXCLUDED_EVENT_RULE_VERSION = "phase6.reaction_change.event_identity.v1"
TELEGRAM_RETENTION_GAP = timedelta(hours=23)


@dataclass(frozen=True)
class ObservationIngestResult:
    observation: ConnectorObservationModel
    business_event: BusinessEventModel
    evidence: EvidenceModel
    publication_id: str | None
    created: bool


@dataclass(frozen=True)
class MetricCalculationResult:
    metric: MetricVersionModel
    created: bool


@dataclass(frozen=True)
class CheckpointInterpretationResult:
    result: ExperimentResultModel
    detail: ExperimentResultDetailModel
    created: bool


@dataclass(frozen=True)
class GovernedLearningResult:
    learning: LearningModel
    detail: LearningDetailModel
    reviews: tuple[LearningControllerReviewModel, ...]
    created: bool


def configure_telegram_observation(
    session: Session,
    *,
    scope: TenantScope,
    connector_account_id: str,
    clock: Clock,
    allowed_update_types: tuple[str, ...] = TELEGRAM_ALLOWED_UPDATES,
) -> ConnectorObservationStateModel:
    account = session.get(ConnectorAccountModel, connector_account_id)
    if account is None:
        raise PermanentJobError("ConnectorAccount not found for Telegram observation")
    scope.assert_matches(
        organization_id=account.organization_id,
        business_id=account.business_id,
    )
    if account.provider != "telegram" or not account.auth_healthy:
        raise PermanentJobError("Telegram connector is not observation-ready")
    unsupported = set(allowed_update_types) - set(TELEGRAM_ALLOWED_UPDATES)
    if unsupported:
        raise PermanentJobError("unsupported Telegram observation update type")
    existing = session.scalar(
        select(ConnectorObservationStateModel).where(
            ConnectorObservationStateModel.connector_account_id == account.id
        )
    )
    if existing is not None:
        existing.allowed_update_types = list(allowed_update_types)
        existing.updated_at = clock.now()
        session.flush()
        return existing
    state = ConnectorObservationStateModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        connector_account_id=account.id,
        observation_mode="LONG_POLL",
        last_update_id=None,
        coverage_started_at=clock.now(),
        last_successful_ingest_at=None,
        freshness_status="UNKNOWN",
        gap_detected=False,
        allowed_update_types=list(allowed_update_types),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    session.add(state)
    session.flush()
    return state


def enqueue_telegram_observation_job(
    session: Session,
    *,
    scope: TenantScope,
    connector_account_id: str,
    queue: JobQueue,
    clock: Clock,
    cycle_id: str,
) -> str:
    job = create_job(
        session,
        scope=scope,
        job_type=JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES,
        payload={
            "payload_schema_version": 1,
            "connector_account_id": connector_account_id,
        },
        payload_schema_version=1,
        idempotency_key=f"telegram-observe:{connector_account_id}:{cycle_id}",
        clock=clock,
        max_attempts=3,
        correlation_id=f"telegram-observe:{connector_account_id}",
        causation_id=None,
    )
    queue.enqueue(job.id)
    return job.id


def enqueue_checkpoint_interpretation_job(
    session: Session,
    *,
    scope: TenantScope,
    metric_version_id: str,
    queue: JobQueue,
    clock: Clock,
) -> str:
    metric = session.get(MetricVersionModel, metric_version_id)
    if metric is None:
        raise PermanentJobError("MetricVersion not found for checkpoint interpretation")
    scope.assert_matches(
        organization_id=metric.organization_id,
        business_id=metric.business_id,
    )
    job = create_job(
        session,
        scope=scope,
        job_type=JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT,
        payload={
            "payload_schema_version": 1,
            "metric_version_id": metric.id,
        },
        payload_schema_version=1,
        idempotency_key=f"checkpoint-interpret:{metric.id}",
        clock=clock,
        max_attempts=2,
        correlation_id=f"checkpoint:{metric.id}",
        causation_id=metric.id,
    )
    queue.enqueue(job.id)
    return job.id


def ingest_telegram_update(
    session: Session,
    *,
    scope: TenantScope,
    connector_account_id: str,
    update: dict[str, Any],
    ingested_at: datetime,
) -> ObservationIngestResult:
    account = session.get(ConnectorAccountModel, connector_account_id)
    if account is None:
        raise PermanentJobError("ConnectorAccount not found during Telegram ingestion")
    scope.assert_matches(
        organization_id=account.organization_id,
        business_id=account.business_id,
    )
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise PermanentJobError("Telegram update_id is required")
    event_type = _telegram_event_type(update)
    event_time, message_id, chat_id = _telegram_event_identity(update, event_type)
    event_identity = str(update_id)
    existing = session.scalar(
        select(ConnectorObservationModel).where(
            ConnectorObservationModel.connector_account_id == account.id,
            ConnectorObservationModel.provider_event_identity == event_identity,
        )
    )
    if existing is not None:
        event, evidence, publication_id = _normalize_observation(
            session,
            scope=scope,
            observation=existing,
        )
        return ObservationIngestResult(
            observation=existing,
            business_event=event,
            evidence=evidence,
            publication_id=publication_id,
            created=False,
        )

    observation = ConnectorObservationModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        connector_account_id=account.id,
        provider="telegram",
        provider_event_identity=event_identity,
        provider_event_type=event_type,
        external_object_id=message_id,
        external_parent_id=chat_id,
        event_time=event_time,
        ingested_at=ingested_at,
        raw_payload=update,
        payload_hash=_hash_payload(update),
        trust_class=SourceTrust.UNTRUSTED_EXTERNAL.value,
    )
    session.add(observation)
    session.flush()
    event, evidence, publication_id = _normalize_observation(
        session,
        scope=scope,
        observation=observation,
    )
    return ObservationIngestResult(
        observation=observation,
        business_event=event,
        evidence=evidence,
        publication_id=publication_id,
        created=True,
    )


class TelegramObservationHandler:
    def __init__(
        self,
        *,
        connector: TelegramObservationConnector,
        queue: JobQueue,
    ) -> None:
        self._connector = connector
        self._queue = queue

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("Telegram observation payload_schema_version must be 1")
        connector_account_id = payload.get("connector_account_id")
        if not isinstance(connector_account_id, str):
            raise PermanentJobError("connector_account_id is required")
        state = session.scalar(
            select(ConnectorObservationStateModel).where(
                ConnectorObservationStateModel.connector_account_id == connector_account_id
            )
        )
        if state is None:
            raise PermanentJobError("Telegram observation state is not configured")
        context.scope.assert_matches(
            organization_id=state.organization_id,
            business_id=state.business_id,
        )
        if state.observation_mode != "LONG_POLL":
            raise PermanentJobError("unsupported Telegram observation mode")
        if (
            state.last_successful_ingest_at is not None
            and clock.now() - state.last_successful_ingest_at > TELEGRAM_RETENTION_GAP
        ):
            state.gap_detected = True
        offset = state.last_update_id + 1 if state.last_update_id is not None else None
        try:
            updates = self._connector.get_updates(
                offset=offset,
                allowed_updates=tuple(state.allowed_update_types),
                timeout_seconds=0,
            )
        except TelegramObservationUnavailable as error:
            raise TransientJobError(str(error)) from None

        publication_ids = set(_publication_ids_for_account(session, connector_account_id))
        max_update_id = state.last_update_id
        for update in sorted(updates, key=_update_sort_key):
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                raise PermanentJobError("Telegram update_id is invalid")
            ingested = ingest_telegram_update(
                session,
                scope=context.scope,
                connector_account_id=connector_account_id,
                update=update,
                ingested_at=clock.now(),
            )
            if ingested.publication_id is not None:
                publication_ids.add(ingested.publication_id)
            if max_update_id is None or update_id > max_update_id:
                max_update_id = update_id

        state.last_update_id = max_update_id
        state.last_successful_ingest_at = clock.now()
        state.freshness_status = "FRESH"
        state.updated_at = clock.now()
        session.flush()

        for publication_id in sorted(publication_ids):
            job = create_job(
                session,
                scope=context.scope,
                job_type=JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION,
                payload={
                    "payload_schema_version": 1,
                    "publication_id": publication_id,
                },
                payload_schema_version=1,
                idempotency_key=f"metric:{publication_id}:observation-job:{context.job_id}",
                clock=clock,
                max_attempts=2,
                correlation_id=context.correlation_id,
                causation_id=context.job_id,
            )
            self._queue.enqueue(job.id)


class NormalizeConnectorObservationHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        del clock
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("normalization payload_schema_version must be 1")
        observation_id = payload.get("observation_id")
        if not isinstance(observation_id, str):
            raise PermanentJobError("observation_id is required")
        observation = session.get(ConnectorObservationModel, observation_id)
        if observation is None:
            raise PermanentJobError("ConnectorObservation not found")
        context.scope.assert_matches(
            organization_id=observation.organization_id,
            business_id=observation.business_id,
        )
        _normalize_observation(session, scope=context.scope, observation=observation)


def calculate_metric_version(
    session: Session,
    *,
    scope: TenantScope,
    publication_id: str,
    clock: Clock,
) -> MetricCalculationResult:
    publication = session.get(PublicationModel, publication_id)
    if publication is None or publication.published_at is None:
        raise PermanentJobError("published Publication is required for metric calculation")
    scope.assert_matches(
        organization_id=publication.organization_id,
        business_id=publication.business_id,
    )
    checkpoint, external = _checkpoint_context_for_publication(session, publication.id)
    if checkpoint.metric_key != "telegram_reaction_changes":
        raise PermanentJobError("unsupported Phase 6 metric key")
    state = session.scalar(
        select(ConnectorObservationStateModel).where(
            ConnectorObservationStateModel.connector_account_id == external.connector_account_id
        )
    )
    source_window_start = publication.published_at
    source_window_end = publication.published_at + timedelta(seconds=checkpoint.window_seconds)
    availability, coverage = _metric_coverage(
        state=state,
        source_window_start=source_window_start,
        source_window_end=source_window_end,
        grace_seconds=checkpoint.grace_seconds,
        now=clock.now(),
    )
    candidate_events = session.scalars(
        select(BusinessEventModel).where(
            BusinessEventModel.organization_id == scope.organization_id,
            BusinessEventModel.business_id == scope.business_id,
            BusinessEventModel.event_type.in_(REACTION_EVENT_TYPES),
            BusinessEventModel.occurred_at >= source_window_start,
            BusinessEventModel.occurred_at <= source_window_end,
        )
    ).all()
    events = sorted(
        (
            event
            for event in candidate_events
            if event.payload.get("publication_id") == publication.id
        ),
        key=lambda event: (event.occurred_at, event.id),
    )
    event_ids = [event.id for event in events]
    observed_count = len(event_ids)
    value_numeric: float | None
    if availability == "AVAILABLE" or observed_count > 0:
        value_numeric = float(observed_count)
    else:
        value_numeric = None
    derivation = {
        "metric_key": checkpoint.metric_key,
        "publication_id": publication.id,
        "checkpoint_contract_hash": checkpoint.contract_hash,
        "event_ids": event_ids,
        "availability": availability,
        "coverage": coverage,
        "source_window_start": source_window_start.isoformat(),
        "source_window_end": source_window_end.isoformat(),
        "last_successful_ingest_at": (
            state.last_successful_ingest_at.isoformat()
            if state is not None and state.last_successful_ingest_at is not None
            else None
        ),
        "calculation_version": METRIC_CALCULATION_VERSION,
    }
    derivation_hash = _hash_payload(derivation)
    latest = session.scalar(
        select(MetricVersionModel)
        .where(
            MetricVersionModel.business_id == scope.business_id,
            MetricVersionModel.metric_key == checkpoint.metric_key,
            MetricVersionModel.subject_type == "Publication",
            MetricVersionModel.subject_id == publication.id,
        )
        .order_by(MetricVersionModel.version_number.desc())
        .limit(1)
    )
    if latest is not None and latest.derivation_hash == derivation_hash:
        return MetricCalculationResult(metric=latest, created=False)

    metric_id = new_id()
    source = SourceRecordModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="launch_os",
        external_id=f"metric:{metric_id}",
        source_type="metric_version",
        trust=SourceTrust.INTERNAL_SYSTEM.value,
        payload={
            "metric_version_id": metric_id,
            "derivation_hash": derivation_hash,
            "included_business_event_ids": event_ids,
        },
        source_occurred_at=clock.now(),
        ingested_at=clock.now(),
    )
    session.add(source)
    session.flush()
    evidence = EvidenceModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement=(
            f"{checkpoint.metric_key} for Publication {publication.id}: "
            f"availability={availability}, observed_count={observed_count}."
        ),
        status=(
            EpistemicStatus.DERIVED_FACT.value
            if availability == "AVAILABLE"
            else EpistemicStatus.UNKNOWN.value
        ),
        confidence=None,
        occurred_at=source_window_end,
        recorded_at=clock.now(),
        conflicts_with_evidence_ids=[],
    )
    session.add(evidence)
    session.flush()
    metric = MetricVersionModel(
        id=metric_id,
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        checkpoint_definition_id=checkpoint.id,
        metric_key=checkpoint.metric_key,
        subject_type="Publication",
        subject_id=publication.id,
        source_provider="telegram",
        source_connector_account_id=external.connector_account_id,
        version_number=(latest.version_number + 1 if latest is not None else 1),
        value_numeric=value_numeric,
        value_type="COUNT",
        availability_status=availability,
        coverage_status=coverage,
        source_window_start=source_window_start,
        source_window_end=source_window_end,
        included_business_event_ids=event_ids,
        excluded_event_rule_version=EXCLUDED_EVENT_RULE_VERSION,
        calculation_version=METRIC_CALCULATION_VERSION,
        calculated_at=clock.now(),
        previous_metric_version_id=latest.id if latest is not None else None,
        derivation_hash=derivation_hash,
        evidence_id=evidence.id,
    )
    session.add(metric)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="METRIC_VERSION_CALCULATED",
        object_type="MetricVersion",
        object_id=metric.id,
        payload={
            "metric_key": metric.metric_key,
            "publication_id": publication.id,
            "version_number": metric.version_number,
            "availability_status": metric.availability_status,
            "coverage_status": metric.coverage_status,
        },
        correlation_id=f"metric:{publication.id}",
        causation_id=publication.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="metric.version.calculated",
        aggregate_type="MetricVersion",
        aggregate_id=metric.id,
        payload={
            "publication_id": publication.id,
            "metric_key": metric.metric_key,
            "availability_status": metric.availability_status,
        },
        clock=clock,
        correlation_id=f"metric:{publication.id}",
        causation_id=publication.id,
    )
    return MetricCalculationResult(metric=metric, created=True)


class CalculateMetricVersionHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("metric payload_schema_version must be 1")
        publication_id = payload.get("publication_id")
        if not isinstance(publication_id, str):
            raise PermanentJobError("publication_id is required")
        calculate_metric_version(
            session,
            scope=context.scope,
            publication_id=publication_id,
            clock=clock,
        )


def interpret_checkpoint(
    session: Session,
    *,
    scope: TenantScope,
    metric_version_id: str,
    clock: Clock,
) -> CheckpointInterpretationResult:
    metric = session.get(MetricVersionModel, metric_version_id)
    if metric is None:
        raise PermanentJobError("MetricVersion not found")
    scope.assert_matches(
        organization_id=metric.organization_id,
        business_id=metric.business_id,
    )
    existing_detail = session.scalar(
        select(ExperimentResultDetailModel).where(
            ExperimentResultDetailModel.metric_version_id == metric.id
        )
    )
    if existing_detail is not None:
        existing_result = session.get(
            ExperimentResultModel,
            existing_detail.experiment_result_id,
        )
        if existing_result is None:
            raise PermanentJobError("ExperimentResult detail points to missing result")
        return CheckpointInterpretationResult(
            result=existing_result,
            detail=existing_detail,
            created=False,
        )
    checkpoint = session.get(CheckpointDefinitionModel, metric.checkpoint_definition_id)
    if checkpoint is None:
        raise PermanentJobError("CheckpointDefinition not found")
    if metric.availability_status != "AVAILABLE" or metric.coverage_status != "COMPLETE":
        result_class = "INSUFFICIENT_DATA"
    else:
        if metric.value_numeric is None:
            raise PermanentJobError("available MetricVersion requires a numeric value")
        if _matches(checkpoint.success_operator, metric.value_numeric, checkpoint.success_value):
            result_class = "SUCCESS"
        elif _matches(
            checkpoint.weak_signal_operator,
            metric.value_numeric,
            checkpoint.weak_signal_value,
        ):
            result_class = "WEAK_SIGNAL"
        elif _matches(checkpoint.failure_operator, metric.value_numeric, checkpoint.failure_value):
            result_class = "FAILURE"
        else:
            raise PermanentJobError("typed checkpoint conditions are non-exhaustive")
    result = ExperimentResultModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        experiment_id=checkpoint.experiment_id,
        result_class=result_class,
        observed_value=json.dumps(
            {
                "metric_version_id": metric.id,
                "value_numeric": metric.value_numeric,
                "availability_status": metric.availability_status,
            },
            sort_keys=True,
        ),
        interpreted_at=clock.now(),
        version=1,
    )
    session.add(result)
    session.flush()
    detail = ExperimentResultDetailModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        experiment_result_id=result.id,
        checkpoint_definition_id=checkpoint.id,
        metric_version_id=metric.id,
        result_class=result_class,
        checkpoint_contract_hash=checkpoint.contract_hash,
        source_coverage_status=metric.coverage_status,
        created_at=clock.now(),
    )
    session.add(detail)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="CHECKPOINT_INTERPRETED",
        object_type="ExperimentResult",
        object_id=result.id,
        payload={
            "metric_version_id": metric.id,
            "result_class": result_class,
            "checkpoint_contract_hash": checkpoint.contract_hash,
        },
        correlation_id=f"checkpoint:{checkpoint.experiment_id}",
        causation_id=metric.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="experiment.checkpoint.interpreted",
        aggregate_type="ExperimentResult",
        aggregate_id=result.id,
        payload={"metric_version_id": metric.id, "result_class": result_class},
        clock=clock,
        correlation_id=f"checkpoint:{checkpoint.experiment_id}",
        causation_id=metric.id,
    )
    return CheckpointInterpretationResult(result=result, detail=detail, created=True)


class InterpretCheckpointHandler:
    def __init__(self, *, queue: JobQueue) -> None:
        self._queue = queue

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("checkpoint payload_schema_version must be 1")
        metric_version_id = payload.get("metric_version_id")
        if not isinstance(metric_version_id, str):
            raise PermanentJobError("metric_version_id is required")
        interpreted = interpret_checkpoint(
            session,
            scope=context.scope,
            metric_version_id=metric_version_id,
            clock=clock,
        )
        job = create_job(
            session,
            scope=context.scope,
            job_type=JOB_TYPE_LEARNING_RUN_GOVERNED,
            payload={
                "payload_schema_version": 1,
                "experiment_result_id": interpreted.result.id,
            },
            payload_schema_version=1,
            idempotency_key=f"governed-learning:{interpreted.result.id}",
            clock=clock,
            max_attempts=2,
            correlation_id=context.correlation_id,
            causation_id=interpreted.result.id,
        )
        self._queue.enqueue(job.id)


def create_governed_learning(
    session: Session,
    *,
    scope: TenantScope,
    experiment_result_id: str,
    clock: Clock,
) -> GovernedLearningResult:
    result = session.get(ExperimentResultModel, experiment_result_id)
    if result is None:
        raise PermanentJobError("ExperimentResult not found for Learning")
    scope.assert_matches(
        organization_id=result.organization_id,
        business_id=result.business_id,
    )
    existing_detail = session.scalar(
        select(LearningDetailModel).where(
            LearningDetailModel.experiment_result_id == result.id
        )
    )
    if existing_detail is not None:
        existing_learning = session.get(LearningModel, existing_detail.learning_id)
        if existing_learning is None:
            raise PermanentJobError("Learning detail points to missing Learning")
        reviews = tuple(
            session.scalars(
                select(LearningControllerReviewModel).where(
                    LearningControllerReviewModel.experiment_result_id == result.id
                )
            ).all()
        )
        return GovernedLearningResult(
            learning=existing_learning,
            detail=existing_detail,
            reviews=reviews,
            created=False,
        )
    detail = session.scalar(
        select(ExperimentResultDetailModel).where(
            ExperimentResultDetailModel.experiment_result_id == result.id
        )
    )
    if detail is None:
        raise PermanentJobError("ExperimentResult provenance detail is required")
    metric = session.get(MetricVersionModel, detail.metric_version_id)
    checkpoint = session.get(CheckpointDefinitionModel, detail.checkpoint_definition_id)
    experiment = session.get(ExperimentModel, result.experiment_id)
    if metric is None or checkpoint is None or experiment is None:
        raise PermanentJobError("Learning deterministic inputs are incomplete")
    reviews = _materialize_learning_reviews(
        session,
        scope=scope,
        result=result,
        metric=metric,
        clock=clock,
    )
    if any(review.verdict == ControllerVerdict.BLOCK.value for review in reviews):
        raise PermanentJobError("Learning governance blocked materialization")
    limits = list(
        dict.fromkeys(limit for review in reviews for limit in review.limits)
    )
    evidence_ids = [metric.evidence_id, *_event_evidence_ids(session, metric)]
    evidence_ids = list(dict.fromkeys(evidence_ids))
    causality_class = (
        CausalityClass.UNKNOWN.value
        if result.result_class == "INSUFFICIENT_DATA"
        else CausalityClass.DIRECT_DETERMINISTIC_ATTRIBUTION.value
    )
    learning = LearningModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=checkpoint.decision_id,
        experiment_id=experiment.id,
        statement=_learning_statement(result.result_class, metric),
        evidence_ids=evidence_ids,
        causality_class=causality_class,
        confidence=1.0,
        version=1,
    )
    session.add(learning)
    session.flush()
    learning_detail = LearningDetailModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        learning_id=learning.id,
        experiment_result_id=result.id,
        metric_version_ids=[metric.id],
        interpretation_class=result.result_class,
        limits=limits,
        controller_review_ids=[review.id for review in reviews],
        created_at=clock.now(),
    )
    session.add(learning_detail)
    session.flush()
    _audit(
        session,
        scope=scope,
        action="LEARNING_MATERIALIZED",
        object_type="Learning",
        object_id=learning.id,
        payload={
            "experiment_result_id": result.id,
            "metric_version_id": metric.id,
            "result_class": result.result_class,
            "causality_class": learning.causality_class,
            "limits": limits,
        },
        correlation_id=f"learning:{experiment.id}",
        causation_id=result.id,
    )
    _outbox(
        session,
        scope=scope,
        event_type="learning.materialized",
        aggregate_type="Learning",
        aggregate_id=learning.id,
        payload={
            "experiment_result_id": result.id,
            "metric_version_id": metric.id,
            "result_class": result.result_class,
        },
        clock=clock,
        correlation_id=f"learning:{experiment.id}",
        causation_id=result.id,
    )
    return GovernedLearningResult(
        learning=learning,
        detail=learning_detail,
        reviews=reviews,
        created=True,
    )


class GovernedLearningHandler:
    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        if payload.get("payload_schema_version") != 1:
            raise PermanentJobError("learning payload_schema_version must be 1")
        experiment_result_id = payload.get("experiment_result_id")
        if not isinstance(experiment_result_id, str):
            raise PermanentJobError("experiment_result_id is required")
        create_governed_learning(
            session,
            scope=context.scope,
            experiment_result_id=experiment_result_id,
            clock=clock,
        )


def phase6_handler_registry(
    *,
    queue: JobQueue,
    telegram_observation_connector: TelegramObservationConnector,
) -> dict[str, object]:
    return {
        JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES: TelegramObservationHandler(
            connector=telegram_observation_connector,
            queue=queue,
        ),
        JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION: (
            NormalizeConnectorObservationHandler()
        ),
        JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION: CalculateMetricVersionHandler(),
        JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT: InterpretCheckpointHandler(queue=queue),
        JOB_TYPE_LEARNING_RUN_GOVERNED: GovernedLearningHandler(),
    }


def _normalize_observation(
    session: Session,
    *,
    scope: TenantScope,
    observation: ConnectorObservationModel,
) -> tuple[BusinessEventModel, EvidenceModel, str | None]:
    existing = session.scalar(
        select(NormalizedObservationLinkModel).where(
            NormalizedObservationLinkModel.observation_id == observation.id
        )
    )
    if existing is not None:
        event = session.get(BusinessEventModel, existing.business_event_id)
        evidence = session.get(EvidenceModel, existing.evidence_id)
        if event is None or evidence is None:
            raise PermanentJobError("normalized observation link is incomplete")
        return event, evidence, existing.publication_id

    publication_id = _publication_for_observation(session, observation)
    source = SourceRecordModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="telegram",
        external_id=(
            f"{observation.connector_account_id}:{observation.provider_event_identity}"
        ),
        source_type=observation.provider_event_type,
        trust=SourceTrust.UNTRUSTED_EXTERNAL.value,
        payload={
            "connector_observation_id": observation.id,
            "payload_hash": observation.payload_hash,
        },
        source_occurred_at=observation.event_time,
        ingested_at=observation.ingested_at,
    )
    session.add(source)
    session.flush()
    event = BusinessEventModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        event_type=f"telegram.{observation.provider_event_type}",
        source_record_id=source.id,
        occurred_at=observation.event_time,
        recorded_at=observation.ingested_at,
        payload={
            "provider": "telegram",
            "connector_observation_id": observation.id,
            "provider_event_identity": observation.provider_event_identity,
            "message_id": observation.external_object_id,
            "chat_id": observation.external_parent_id,
            "publication_id": publication_id,
            "payload_hash": observation.payload_hash,
        },
        correlation_id=f"telegram-update:{observation.provider_event_identity}",
        causation_id=observation.id,
        version=1,
    )
    session.add(event)
    session.flush()
    evidence = EvidenceModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement=(
            f"Telegram {observation.provider_event_type} observed for message "
            f"{observation.external_object_id or 'unknown'}."
        ),
        status=EpistemicStatus.OBSERVATION.value,
        confidence=None,
        occurred_at=observation.event_time,
        recorded_at=observation.ingested_at,
        conflicts_with_evidence_ids=[],
        version=1,
    )
    session.add(evidence)
    session.flush()
    session.add(
        NormalizedObservationLinkModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            observation_id=observation.id,
            source_record_id=source.id,
            business_event_id=event.id,
            evidence_id=evidence.id,
            publication_id=publication_id,
            created_at=observation.ingested_at,
        )
    )
    session.flush()
    return event, evidence, publication_id


def _publication_for_observation(
    session: Session,
    observation: ConnectorObservationModel,
) -> str | None:
    if observation.external_object_id is None:
        return None
    external = session.scalar(
        select(ExternalReferenceModel).where(
            ExternalReferenceModel.connector_account_id == observation.connector_account_id,
            ExternalReferenceModel.provider == "telegram",
            ExternalReferenceModel.external_object_type == "message",
            ExternalReferenceModel.external_id == observation.external_object_id,
        )
    )
    if external is None:
        return None
    if (
        observation.external_parent_id is not None
        and external.external_parent_id is not None
        and observation.external_parent_id != external.external_parent_id
    ):
        return None
    link = session.scalar(
        select(PublicationExecutionLinkModel).where(
            PublicationExecutionLinkModel.external_reference_id == external.id
        )
    )
    return link.publication_id if link is not None else None


def _checkpoint_context_for_publication(
    session: Session,
    publication_id: str,
) -> tuple[CheckpointDefinitionModel, ExternalReferenceModel]:
    link = session.scalar(
        select(PublicationExecutionLinkModel).where(
            PublicationExecutionLinkModel.publication_id == publication_id
        )
    )
    if link is None:
        raise PermanentJobError("Publication execution lineage is missing")
    external = session.get(ExternalReferenceModel, link.external_reference_id)
    detail = session.scalar(
        select(ActionProposalDetailModel).where(
            ActionProposalDetailModel.action_id == link.action_id
        )
    )
    if external is None or detail is None:
        raise PermanentJobError("Publication external/action lineage is incomplete")
    experiment = session.scalar(
        select(ExperimentModel).where(ExperimentModel.decision_id == detail.decision_id)
    )
    if experiment is None:
        raise PermanentJobError("Phase 6 Publication has no Experiment")
    checkpoint = session.scalar(
        select(CheckpointDefinitionModel).where(
            CheckpointDefinitionModel.experiment_id == experiment.id
        )
    )
    if checkpoint is None:
        raise PermanentJobError("Phase 6 Publication has no typed checkpoint")
    return checkpoint, external


def _metric_coverage(
    *,
    state: ConnectorObservationStateModel | None,
    source_window_start: datetime,
    source_window_end: datetime,
    grace_seconds: int,
    now: datetime,
) -> tuple[str, str]:
    if state is None or state.last_successful_ingest_at is None:
        return "UNAVAILABLE", "UNAVAILABLE"
    if state.coverage_started_at > source_window_start:
        return "UNAVAILABLE", "UNAVAILABLE"
    if state.gap_detected:
        return "PARTIAL", "PARTIAL"
    if now - state.last_successful_ingest_at > TELEGRAM_RETENTION_GAP:
        return "STALE", "STALE"
    required_end = source_window_end + timedelta(seconds=grace_seconds)
    if state.last_successful_ingest_at < required_end:
        return "PARTIAL", "PARTIAL"
    return "AVAILABLE", "COMPLETE"


def _materialize_learning_reviews(
    session: Session,
    *,
    scope: TenantScope,
    result: ExperimentResultModel,
    metric: MetricVersionModel,
    clock: Clock,
) -> tuple[LearningControllerReviewModel, ...]:
    existing = tuple(
        session.scalars(
            select(LearningControllerReviewModel).where(
                LearningControllerReviewModel.experiment_result_id == result.id
            )
        ).all()
    )
    if existing:
        if {review.controller_type for review in existing} != {
            "attribution",
            "learning",
            "stability",
        }:
            raise PermanentJobError("Learning controller set is incomplete")
        return existing

    insufficient = result.result_class == "INSUFFICIENT_DATA"
    reviews = (
        LearningControllerReviewModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            experiment_result_id=result.id,
            controller_type="attribution",
            verdict=(
                ControllerVerdict.PASS_WITH_CONDITIONS.value
                if insufficient
                else ControllerVerdict.PASS.value
            ),
            reason=(
                "Coverage is insufficient for outcome attribution."
                if insufficient
                else "Observed reaction events are exact-bound to the Telegram message lineage."
            ),
            limits=[
                "Message lineage does not establish that wording caused engagement or sales."
            ],
            causality_ceiling=(
                CausalityClass.UNKNOWN.value
                if insufficient
                else CausalityClass.DIRECT_DETERMINISTIC_ATTRIBUTION.value
            ),
            created_at=clock.now(),
        ),
        LearningControllerReviewModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            experiment_result_id=result.id,
            controller_type="learning",
            verdict=ControllerVerdict.PASS_WITH_CONDITIONS.value,
            reason="Learning is bounded to the exact metric version and checkpoint result.",
            limits=[
                "Do not generalize this result beyond the measured publication and window."
            ],
            causality_ceiling=(
                CausalityClass.UNKNOWN.value
                if insufficient
                else CausalityClass.DIRECT_DETERMINISTIC_ATTRIBUTION.value
            ),
            created_at=clock.now(),
        ),
        LearningControllerReviewModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            experiment_result_id=result.id,
            controller_type="stability",
            verdict=ControllerVerdict.PASS_WITH_CONDITIONS.value,
            reason="One publication is a narrow trace and cannot establish a stable business rule.",
            limits=[
                "Single-publication trace; require repeated evidence before broad adaptation."
            ],
            causality_ceiling=(
                CausalityClass.UNKNOWN.value
                if insufficient
                else CausalityClass.DIRECT_DETERMINISTIC_ATTRIBUTION.value
            ),
            created_at=clock.now(),
        ),
    )
    session.add_all(list(reviews))
    session.flush()
    return reviews


def _learning_statement(result_class: str, metric: MetricVersionModel) -> str:
    if result_class == "INSUFFICIENT_DATA":
        return (
            "Telegram observation coverage is insufficient to classify the predefined "
            "publication checkpoint."
        )
    value = int(metric.value_numeric or 0)
    if result_class == "SUCCESS":
        return (
            f"The exact Telegram publication recorded {value} observed reaction-change "
            "events and met the predefined success threshold."
        )
    if result_class == "WEAK_SIGNAL":
        return (
            f"The exact Telegram publication recorded {value} observed reaction-change "
            "events and met only the predefined weak-signal threshold."
        )
    return (
        f"The exact Telegram publication recorded {value} observed reaction-change "
        "events and met the predefined failure threshold."
    )


def _event_evidence_ids(session: Session, metric: MetricVersionModel) -> list[str]:
    if not metric.included_business_event_ids:
        return []
    links = session.scalars(
        select(NormalizedObservationLinkModel).where(
            NormalizedObservationLinkModel.business_event_id.in_(
                metric.included_business_event_ids
            )
        )
    ).all()
    return [link.evidence_id for link in links]


def _publication_ids_for_account(session: Session, connector_account_id: str) -> list[str]:
    references = session.scalars(
        select(ExternalReferenceModel).where(
            ExternalReferenceModel.connector_account_id == connector_account_id,
            ExternalReferenceModel.provider == "telegram",
            ExternalReferenceModel.external_object_type == "message",
        )
    ).all()
    result: list[str] = []
    for reference in references:
        link = session.scalar(
            select(PublicationExecutionLinkModel).where(
                PublicationExecutionLinkModel.external_reference_id == reference.id
            )
        )
        if link is not None:
            result.append(link.publication_id)
    return result


def _telegram_event_type(update: dict[str, Any]) -> str:
    for key in TELEGRAM_ALLOWED_UPDATES:
        if key in update:
            value = update.get(key)
            if not isinstance(value, dict):
                raise PermanentJobError("Telegram update payload is invalid")
            return key
    raise PermanentJobError("Telegram update class is not allowed in Phase 6")


def _telegram_event_identity(
    update: dict[str, Any],
    event_type: str,
) -> tuple[datetime, str | None, str | None]:
    body = update.get(event_type)
    if not isinstance(body, dict):
        raise PermanentJobError("Telegram event body is invalid")
    raw_date = body.get("date")
    if not isinstance(raw_date, int):
        raise PermanentJobError("Telegram event_time is required")
    event_time = datetime.fromtimestamp(raw_date, tz=UTC)
    raw_message_id = body.get("message_id")
    message_id = str(raw_message_id) if isinstance(raw_message_id, int | str) else None
    raw_chat = body.get("chat")
    chat_id: str | None = None
    if isinstance(raw_chat, dict):
        raw_chat_id = raw_chat.get("id")
        if isinstance(raw_chat_id, int | str):
            chat_id = str(raw_chat_id)
    return event_time, message_id, chat_id


def _matches(operator: str, value: float, threshold: float) -> bool:
    if operator == "GTE":
        return value >= threshold
    if operator == "GT":
        return value > threshold
    if operator == "LTE":
        return value <= threshold
    if operator == "LT":
        return value < threshold
    if operator == "EQ":
        return value == threshold
    raise PermanentJobError("unsupported typed checkpoint operator")


def _update_sort_key(update: dict[str, Any]) -> int:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise PermanentJobError("Telegram update_id is invalid")
    return update_id


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit(
    session: Session,
    *,
    scope: TenantScope,
    action: str,
    object_type: str,
    object_id: str,
    payload: dict[str, object],
    correlation_id: str,
    causation_id: str | None,
) -> None:
    session.add(
        AuditLogModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            actor_user_id=None,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=1,
        )
    )


def _outbox(
    session: Session,
    *,
    scope: TenantScope,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, object],
    clock: Clock,
    correlation_id: str,
    causation_id: str | None,
) -> None:
    session.add(
        OutboxEventModel(
            id=new_id(),
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status=OutboxStatus.PENDING.value,
            occurred_at=clock.now(),
            correlation_id=correlation_id,
            causation_id=causation_id,
            created_at=clock.now(),
        )
    )
