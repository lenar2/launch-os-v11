from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.adapters.fake import FakeAdapterScriptStep, FakeModelAdapter
from launch_os_v11.ai_runtime.composition import compose_handler_registry, fake_model_router
from launch_os_v11.ai_runtime.context import ContextReference
from launch_os_v11.ai_runtime.contracts import ModelResultKind
from launch_os_v11.ai_runtime.registry import default_agent_registry
from launch_os_v11.ai_runtime.service import AgentRunService
from launch_os_v11.analytics.business_outcomes import (
    calculate_outcome_metric_version,
    create_outcome_economic_link,
    create_outcome_experiment_proposal,
    create_outcome_ingestion_contract,
    create_outcome_learning,
    create_outcome_metric_definition,
    ingest_synthetic_outcome_observation,
)
from launch_os_v11.application.commands import create_business, create_organization
from launch_os_v11.domain.enums import (
    BusinessOutcomeClass,
    CausalityClass,
    EpistemicStatus,
    OutcomeDataAvailability,
    OutcomeEconomicLinkType,
    OutcomeMetricAggregation,
    SourceTrust,
)
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models
from launch_os_v11.persistence.session import create_session_factory
from launch_os_v11.platform.config import get_settings
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.worker import Worker
from tests.test_business_outcomes import (
    SUBJECT_ID,
    SUBJECT_TYPE,
    _calculate_metric,
    _ingest_fixture_events,
    _metric_fixture,
)

pytestmark = [pytest.mark.postgres, pytest.mark.business_outcomes]

OUTCOME_TABLES = {
    "outcome_ingestion_contracts",
    "outcome_metric_definitions",
    "outcome_metric_versions",
    "outcome_economic_links",
    "outcome_experiment_proposals",
}


def _database_url() -> str:
    value = os.environ.get("LAUNCH_OS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("LAUNCH_OS_TEST_DATABASE_URL is required for business outcome tests")
    return value


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("LAUNCH_OS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    return Config("alembic.ini")


def _clear_test_database(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        tables = [
            table
            for table in inspect(engine).get_table_names()
            if table != "alembic_version"
        ]
        if not tables:
            return
        preparer = engine.dialect.identifier_preparer
        table_list = ", ".join(preparer.quote(table) for table in tables)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"TRUNCATE TABLE {table_list} CASCADE")
    finally:
        engine.dispose()


def _assert_outcome_tables_present(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        assert OUTCOME_TABLES.issubset(tables)
    finally:
        engine.dispose()


def _assert_outcome_tables_absent(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        assert OUTCOME_TABLES.isdisjoint(tables)
    finally:
        engine.dispose()


def _count(session: Session, model_type: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model_type)) or 0


def test_business_outcome_postgresql_migration_cycle_and_non_live_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    config = _alembic_config(database_url, monkeypatch)
    _clear_test_database(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    _assert_outcome_tables_present(database_url)

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
            _ingest_fixture_events(
                session,
                scope=scope,
                clock=clock,
                exposure_contract=exposure_contract,
                intent_contract=intent_contract,
            )
            metric = _calculate_metric(
                session,
                scope=scope,
                clock=clock,
                definition=definition,
            )
            economic = create_outcome_economic_link(
                session,
                scope=scope,
                metric_version_id=metric.id,
                link_type=OutcomeEconomicLinkType.CONTRIBUTION_MARGIN,
                downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN,
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                value_per_unit_cents=4500,
                direct_cost_cents=0,
                fully_loaded_execution_cost_cents=1000,
                opportunity_cost_cents=500,
                bounded_downside_cents=1500,
                expected_benefit_cents=4500,
                limitations=["synthetic fixture only"],
                clock=clock,
            ).economic_link
            learning = create_outcome_learning(
                session,
                scope=scope,
                metric_version_id=metric.id,
                economic_link_id=economic.id,
                clock=clock,
            ).learning
            proposal = create_outcome_experiment_proposal(
                session,
                scope=scope,
                metric_definition_id=definition.id,
                metric_version_id=metric.id,
                economic_link_id=economic.id,
                learning_id=learning.id,
                hypothesis="Qualified intent can be evaluated before reaction metrics revive.",
                treatment="Synthetic non-live treatment",
                control="Synthetic non-live control",
                success_threshold=">= 0.30 qualified intent rate",
                weak_signal_threshold=">= 0.10 qualified intent rate",
                failure_threshold="< 0.10 qualified intent rate",
                limitations=["disabled/non-live proposal only"],
                clock=clock,
            )
            assert session.in_transaction()
            assert metric.value_numeric == 0.5
            assert metric.availability_status == OutcomeDataAvailability.AVAILABLE.value
            assert not economic.supports_go
            assert learning.causality_class == CausalityClass.UNKNOWN.value
            assert proposal.payload["external_execution_authorized"] is False
            metric_id = metric.id
            economic_evidence_id = economic.evidence_id
            intent_contract_id = intent_contract.id
            proposal_id = proposal.id

        with factory() as session:
            persisted_metric = session.get(models.OutcomeMetricVersionModel, metric_id)
            assert persisted_metric is not None
            assert len(persisted_metric.included_business_event_ids) == 3
            persisted_proposal = session.get(
                models.OutcomeExperimentProposalModel,
                proposal_id,
            )
            assert persisted_proposal is not None
            assert persisted_proposal.status == "DISABLED_NON_LIVE"
            assert _count(session, models.DecisionModel) == 0
            assert _count(session, models.ApprovalModel) == 0
            assert _count(session, models.PublicationModel) == 0
            assert _count(session, models.ExecutionModel) == 0

        with pytest.raises(IntegrityError), factory.begin() as session:
            session.add(
                models.OutcomeEconomicLinkModel(
                    organization_id=scope.organization_id,
                    business_id=scope.business_id,
                    metric_version_id=metric_id,
                    version_number=2,
                    link_type=OutcomeEconomicLinkType.CONTRIBUTION_MARGIN.value,
                    downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN.value,
                    epistemic_status=EpistemicStatus.HYPOTHESIS.value,
                    value_per_unit_cents=4500,
                    direct_cost_cents=0,
                    fully_loaded_execution_cost_cents=1000,
                    opportunity_cost_cents=500,
                    bounded_downside_cents=1500,
                    expected_benefit_cents=999999,
                    hurdle_multiplier=3,
                    supports_go=True,
                    evidence_id=economic_evidence_id,
                    synthetic_non_live=True,
                    limitations=["database must reject GO authority in disabled layer"],
                )
            )

        with pytest.raises(IntegrityError), factory.begin() as session:
            persisted_metric = session.get(models.OutcomeMetricVersionModel, metric_id)
            assert persisted_metric is not None
            persisted_metric.synthetic_non_live = False

        with pytest.raises(IntegrityError), factory.begin() as session:
            persisted_contract = session.get(
                models.OutcomeIngestionContractModel,
                intent_contract_id,
            )
            assert persisted_contract is not None
            persisted_contract.status = "ACTIVE"

        with factory.begin() as session:
            organization = create_organization(session, name="Outcome FK Parent Org")
            business = create_business(
                session,
                organization_id=organization.id,
                name="Outcome FK Parent Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="outcome-orphan-parent",
            ).record
            scope_id = business.id
        with pytest.raises(IntegrityError), factory.begin() as session:
            session.add(
                models.OutcomeMetricVersionModel(
                    organization_id=organization.id,
                    business_id=scope_id,
                    metric_definition_id="missing-definition",
                    version_number=1,
                    subject_type=SUBJECT_TYPE,
                    subject_id=SUBJECT_ID,
                    value_numeric=1.0,
                    numerator_count=1,
                    denominator_count=1,
                    availability_status=OutcomeDataAvailability.AVAILABLE.value,
                    coverage_status="COMPLETE",
                    source_window_start=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
                    source_window_end=datetime(2026, 8, 28, 8, 0, tzinfo=UTC),
                    included_business_event_ids=[],
                    excluded_event_rule_version="test.rule.v1",
                    calculation_version="test.calc.v1",
                    calculated_at=datetime(2026, 8, 28, 8, 0, tzinfo=UTC),
                    derivation_hash="a" * 64,
                    evidence_id="missing-evidence",
                )
            )

        with factory() as session:
            before_counts = {
                models.OrganizationModel: _count(session, models.OrganizationModel),
                models.BusinessModel: _count(session, models.BusinessModel),
                models.AuditLogModel: _count(session, models.AuditLogModel),
                models.OutboxEventModel: _count(session, models.OutboxEventModel),
                models.OutcomeMetricVersionModel: _count(
                    session,
                    models.OutcomeMetricVersionModel,
                ),
            }
        with pytest.raises(RuntimeError), factory.begin() as session:
            scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
            _ingest_fixture_events(
                session,
                scope=scope,
                clock=clock,
                exposure_contract=exposure_contract,
                intent_contract=intent_contract,
            )
            _calculate_metric(session, scope=scope, clock=clock, definition=definition)
            raise RuntimeError("force rollback")
        with factory() as session:
            after_counts = {
                models.OrganizationModel: _count(session, models.OrganizationModel),
                models.BusinessModel: _count(session, models.BusinessModel),
                models.AuditLogModel: _count(session, models.AuditLogModel),
                models.OutboxEventModel: _count(session, models.OutboxEventModel),
                models.OutcomeMetricVersionModel: _count(
                    session,
                    models.OutcomeMetricVersionModel,
                ),
            }
            assert after_counts == before_counts
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    _assert_outcome_tables_absent(database_url)
    command.upgrade(config, "head")
    _assert_outcome_tables_present(database_url)
    get_settings.cache_clear()


class _LocalJobQueue:
    def __init__(self) -> None:
        self.items: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.items.append(job_id)

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        del timeout_seconds
        return self.items.pop(0) if self.items else None


def test_governed_ai_to_business_outcome_loop_stays_disabled_and_non_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    config = _alembic_config(database_url, monkeypatch)
    command.upgrade(config, "head")
    _clear_test_database(database_url)

    engine = create_engine(database_url, future=True)
    factory = create_session_factory(engine)
    queue = _LocalJobQueue()
    clock = FixedClock(datetime(2026, 9, 8, 10, 0, tzinfo=UTC))

    try:
        with factory.begin() as session:
            organization = create_organization(session, name="P009 AI Outcome Org")
            business = create_business(
                session,
                organization_id=organization.id,
                name="P009 AI Outcome Business",
                timezone="UTC",
                actor_user_id=None,
                correlation_id="p009-ai-outcome-seed",
            ).record
            scope = TenantScope(organization.id, business.id)
            source = models.SourceRecordModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="internal_fixture",
                external_id="p009-ai-outcome-context",
                source_type="synthetic_internal_context",
                trust=SourceTrust.INTERNAL_SYSTEM.value,
                payload={
                    "synthetic_non_live": True,
                    "accepted_evidence_gap": True,
                    "real_business_outcome_source": False,
                },
                source_occurred_at=clock.now(),
                ingested_at=clock.now(),
            )
            session.add(source)
            session.flush()
            evidence = models.EvidenceModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                source_record_id=source.id,
                statement=(
                    "Current governed data lacks a real economically meaningful "
                    "business outcome source."
                ),
                status=EpistemicStatus.OBSERVATION.value,
                confidence=None,
                occurred_at=clock.now(),
                recorded_at=clock.now(),
                conflicts_with_evidence_ids=[],
            )
            session.add(evidence)
            session.flush()
            source_id = source.id
            evidence_id = evidence.id

        adapter = FakeModelAdapter[BaseModel](
            script=[
                FakeAdapterScriptStep(
                    kind=ModelResultKind.PARSED,
                    payload={
                        "schema_name": "RuntimeProbeOutput",
                        "schema_version": 1,
                        "message": (
                            "QUALIFIED_INTENT is a candidate internal metric to "
                            "falsify mechanically; it is not established business truth."
                        ),
                        "facts_used": [],
                        "hypotheses": [
                            {
                                "statement": (
                                    "QUALIFIED_INTENT may be closer to business value "
                                    "than reaction-change engagement."
                                ),
                                "confidence": 0.5,
                            }
                        ],
                        "unknowns": [
                            {
                                "question": (
                                    "What real baseline and economic linkage will a future "
                                    "business-outcome source establish?"
                                ),
                                "critical": True,
                            }
                        ],
                        "confidence": 0.5,
                    },
                )
            ]
        )
        service = AgentRunService(
            registry=default_agent_registry(),
            queue=queue,
            clock=clock,
        )
        with factory.begin() as session:
            created = service.create_agent_run(
                session,
                scope=scope,
                contract_key="ai.runtime_probe",
                contract_version=1,
                context_refs=(
                    ContextReference(
                        object_type="business",
                        object_id=scope.business_id,
                    ),
                    ContextReference(
                        object_type="source_record",
                        object_id=source_id,
                    ),
                    ContextReference(
                        object_type="evidence",
                        object_id=evidence_id,
                    ),
                ),
                correlation_id="p009-ai-outcome-loop",
                causation_id=evidence_id,
                idempotency_key="p009-ai-outcome-loop-v1",
            )
            agent_run_id = created.agent_run.id
            job_id = created.job_id

        worker = Worker(
            session_factory=factory,
            queue=queue,
            worker_id="p009-ai-outcome-local-worker",
            clock=clock,
            retry_backoff_seconds=30,
            handlers=compose_handler_registry(
                settings=get_settings(),
                model_router=fake_model_router(adapter),
            ),
        )
        attempt = worker.process_one_from_queue(timeout_seconds=1)
        assert attempt is not None
        assert attempt.job_id == job_id
        assert attempt.status == "SUCCEEDED"

        with factory.begin() as session:
            run = session.get(models.AgentRunModel, agent_run_id)
            assert run is not None
            assert run.status == "SUCCEEDED"
            assert run.provider_name == "fake"
            assert isinstance(run.output_data, dict)
            message = str(run.output_data["message"])

            ai_source = models.SourceRecordModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                provider="launch_os_ai_runtime",
                external_id=f"agent-run:{agent_run_id}",
                source_type="ai_runtime_probe_output",
                trust=SourceTrust.INTERNAL_SYSTEM.value,
                payload={
                    "agent_run_id": agent_run_id,
                    "message": message,
                    "model_output_not_fact": True,
                    "synthetic_non_live": True,
                },
                source_occurred_at=clock.now(),
                ingested_at=clock.now(),
            )
            session.add(ai_source)
            session.flush()
            ai_evidence = models.EvidenceModel(
                id=new_id(),
                organization_id=scope.organization_id,
                business_id=scope.business_id,
                source_record_id=ai_source.id,
                statement=(
                    "A governed AI runtime produced a non-live candidate; "
                    "its content remains model output, not FACT."
                ),
                status=EpistemicStatus.OBSERVATION.value,
                confidence=None,
                occurred_at=clock.now(),
                recorded_at=clock.now(),
                conflicts_with_evidence_ids=[],
            )
            session.add(ai_evidence)
            session.flush()

            schema = {
                "type": "object",
                "required": ["subject_type", "subject_id"],
                "properties": {
                    "subject_type": {"type": "string"},
                    "subject_id": {"type": "string"},
                },
                "additionalProperties": False,
            }
            exposure_contract = create_outcome_ingestion_contract(
                session,
                scope=scope,
                provider="synthetic_fixture",
                contract_key="p009-ai-exposure",
                payload_schema_version=1,
                outcome_class=BusinessOutcomeClass.CTA_COMPLETION,
                canonical_event_type="outcome.p009_ai_exposure",
                identity_boundary="synthetic subject only",
                pii_classification="none",
                retention_class="internal_test",
                schema=schema,
                clock=clock,
            )
            intent_contract = create_outcome_ingestion_contract(
                session,
                scope=scope,
                provider="synthetic_fixture",
                contract_key="p009-ai-qualified-intent",
                payload_schema_version=1,
                outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
                canonical_event_type="outcome.p009_ai_qualified_intent",
                identity_boundary="synthetic subject only",
                pii_classification="none",
                retention_class="internal_test",
                schema=schema,
                clock=clock,
            )
            definition = create_outcome_metric_definition(
                session,
                scope=scope,
                metric_key="p009_ai_qualified_intent_rate",
                outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
                numerator_event_type="outcome.p009_ai_qualified_intent",
                denominator_event_type="outcome.p009_ai_exposure",
                aggregation=OutcomeMetricAggregation.RATE,
                eligible_population="Synthetic internal cohort only",
                denominator_description="Synthetic eligible exposures",
                observation_window_seconds=3600,
                attribution_method="same_subject_observation_window",
                attribution_limitations=[
                    "AI output is not factual evidence",
                    "synthetic observations prove mechanics only",
                    "attribution is not causality",
                ],
                data_availability=OutcomeDataAvailability.AVAILABLE,
                downstream_economic_meaning=(
                    "Candidate internal metric only; real economic linkage is unknown."
                ),
                ingestion_contract_id=intent_contract.id,
                clock=clock,
            )

            payload = {"subject_type": "SyntheticExperiment", "subject_id": "cohort-A"}
            ingest_synthetic_outcome_observation(
                session,
                scope=scope,
                ingestion_contract_id=exposure_contract.id,
                external_event_id="p009-ai-exposure-1",
                occurred_at=clock.now(),
                payload=payload,
                clock=clock,
                correlation_id="p009-ai-outcome-loop",
                causation_id=ai_evidence.id,
            )
            ingest_synthetic_outcome_observation(
                session,
                scope=scope,
                ingestion_contract_id=exposure_contract.id,
                external_event_id="p009-ai-exposure-2",
                occurred_at=clock.now(),
                payload=payload,
                clock=clock,
                correlation_id="p009-ai-outcome-loop",
                causation_id=ai_evidence.id,
            )
            ingest_synthetic_outcome_observation(
                session,
                scope=scope,
                ingestion_contract_id=intent_contract.id,
                external_event_id="p009-ai-intent-1",
                occurred_at=clock.now(),
                payload=payload,
                clock=clock,
                correlation_id="p009-ai-outcome-loop",
                causation_id=ai_evidence.id,
            )

            metric = calculate_outcome_metric_version(
                session,
                scope=scope,
                metric_definition_id=definition.id,
                subject_type="SyntheticExperiment",
                subject_id="cohort-A",
                source_window_start=clock.now() - timedelta(minutes=1),
                source_window_end=clock.now() + timedelta(minutes=1),
                clock=clock,
            ).metric_version
            economic = create_outcome_economic_link(
                session,
                scope=scope,
                metric_version_id=metric.id,
                link_type=OutcomeEconomicLinkType.HYPOTHETICAL_PROXY,
                downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN,
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                value_per_unit_cents=4500,
                direct_cost_cents=0,
                fully_loaded_execution_cost_cents=1000,
                opportunity_cost_cents=500,
                bounded_downside_cents=1500,
                expected_benefit_cents=4500,
                limitations=[
                    "synthetic economics cannot establish real 3x economics"
                ],
                clock=clock,
            ).economic_link
            learning = create_outcome_learning(
                session,
                scope=scope,
                metric_version_id=metric.id,
                economic_link_id=economic.id,
                clock=clock,
            ).learning
            proposal = create_outcome_experiment_proposal(
                session,
                scope=scope,
                metric_definition_id=definition.id,
                metric_version_id=metric.id,
                economic_link_id=economic.id,
                learning_id=learning.id,
                hypothesis=message,
                treatment="Synthetic non-live treatment only",
                control="Synthetic non-live control only",
                success_threshold=">= 0.30 synthetic rate",
                weak_signal_threshold=">= 0.10 synthetic rate",
                failure_threshold="< 0.10 synthetic rate",
                limitations=[
                    "source AI output is model output, not FACT",
                    f"source_agent_run_id={agent_run_id}",
                    f"source_ai_evidence_id={ai_evidence.id}",
                    "no real business outcome source is connected",
                ],
                clock=clock,
            )

            assert metric.value_numeric == 0.5
            assert metric.synthetic_non_live is True
            assert economic.synthetic_non_live is True
            assert not economic.supports_go
            assert learning.causality_class == CausalityClass.UNKNOWN.value
            assert proposal.status == "DISABLED_NON_LIVE"
            assert proposal.payload["external_execution_authorized"] is False
            assert ai_evidence.status == EpistemicStatus.OBSERVATION.value
            assert _count(session, models.DecisionModel) == 0
            assert _count(session, models.ApprovalModel) == 0
            assert _count(session, models.PublicationModel) == 0
            assert _count(session, models.ExecutionModel) == 0
    finally:
        engine.dispose()
        get_settings.cache_clear()
