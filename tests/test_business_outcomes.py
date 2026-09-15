from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from launch_os_v11.analytics.business_outcomes import (
    RESERVED_OUTCOME_PAYLOAD_FIELDS,
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
    OutcomeInstrumentationStatus,
    OutcomeMetricAggregation,
)
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models
from launch_os_v11.runtime.clock import FixedClock
from launch_os_v11.runtime.errors import PermanentJobError, SecretRejectedError

SUBJECT_TYPE = "SyntheticExperiment"
SUBJECT_ID = "synthetic:fixture"


def test_integration_runner_accepts_externally_managed_database(tmp_path: Path) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "LAUNCH_OS_TEST_DATABASE_URL": "postgresql+psycopg://external/test",
            "PATH": f"{tmp_path}:/bin:/usr/bin",
            "PYTHON": str(fake_python),
        }
    )

    result = subprocess.run(
        ["/bin/bash", "scripts/run_business_outcome_integration.sh"],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _seed_scope(session: Session) -> tuple[TenantScope, FixedClock]:
    clock = FixedClock(datetime(2026, 8, 28, 8, 0, tzinfo=UTC))
    organization = create_organization(session, name="Outcome Instrumentation Org")
    business = create_business(
        session,
        organization_id=organization.id,
        name="Outcome Instrumentation Business",
        timezone="UTC",
        actor_user_id=None,
        correlation_id="outcome-business-seed",
    ).record
    return TenantScope(organization.id, business.id), clock


def _count(session: Session, model_type: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model_type)) or 0


def _counts(session: Session, model_types: Iterable[type[Any]]) -> dict[type[Any], int]:
    return {model_type: _count(session, model_type) for model_type in model_types}


def _contract(
    session: Session,
    *,
    scope: TenantScope,
    clock: FixedClock,
    key: str,
    event_type: str,
    outcome_class: BusinessOutcomeClass,
) -> models.OutcomeIngestionContractModel:
    return create_outcome_ingestion_contract(
        session,
        scope=scope,
        provider="synthetic_fixture",
        contract_key=key,
        payload_schema_version=1,
        outcome_class=outcome_class,
        canonical_event_type=event_type,
        identity_boundary="synthetic subject id only",
        pii_classification="none",
        retention_class="test",
        schema={
            "type": "object",
            "required": ["subject_type", "subject_id"],
            "properties": {
                "subject_type": {"type": "string"},
                "subject_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        clock=clock,
    )


def _metric_fixture(
    session: Session,
) -> tuple[
    TenantScope,
    FixedClock,
    models.OutcomeMetricDefinitionModel,
    models.OutcomeIngestionContractModel,
    models.OutcomeIngestionContractModel,
]:
    scope, clock = _seed_scope(session)
    exposure_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="eligible-exposure",
        event_type="outcome.synthetic.eligible_exposure",
        outcome_class=BusinessOutcomeClass.CTA_COMPLETION,
    )
    intent_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="qualified-intent",
        event_type="outcome.synthetic.qualified_intent",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    definition = create_outcome_metric_definition(
        session,
        scope=scope,
        metric_key="qualified_intent_rate",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
        numerator_event_type="outcome.synthetic.qualified_intent",
        denominator_event_type="outcome.synthetic.eligible_exposure",
        aggregation=OutcomeMetricAggregation.RATE,
        eligible_population="Synthetic eligible fixture subjects",
        denominator_description="Synthetic eligible exposure events",
        observation_window_seconds=3600,
        attribution_method="same_subject_observation_window",
        attribution_limitations=[
            "synthetic observations prove mechanics only",
            "attribution is not causal proof",
        ],
        data_availability=OutcomeDataAvailability.AVAILABLE,
        downstream_economic_meaning="Qualified intent is closer to business value than reactions.",
        ingestion_contract_id=intent_contract.id,
        denominator_ingestion_contract_id=exposure_contract.id,
        clock=clock,
    )
    return scope, clock, definition, exposure_contract, intent_contract


def _ingest_fixture_events(
    session: Session,
    *,
    scope: TenantScope,
    clock: FixedClock,
    exposure_contract: models.OutcomeIngestionContractModel,
    intent_contract: models.OutcomeIngestionContractModel,
) -> None:
    start = clock.now() - timedelta(minutes=30)
    for index in range(2):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=exposure_contract.id,
            external_event_id=f"exposure-{index}",
            occurred_at=start + timedelta(minutes=index),
            payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
            clock=clock,
            correlation_id="outcome-synthetic-chain",
            causation_id="owner-deferral-evidence-gap",
        )
    first_intent = ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=intent_contract.id,
        external_event_id="intent-0",
        occurred_at=start + timedelta(minutes=10),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="outcome-synthetic-chain",
        causation_id="owner-deferral-evidence-gap",
    )
    duplicate_intent = ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=intent_contract.id,
        external_event_id="intent-0",
        occurred_at=start + timedelta(minutes=10),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="outcome-synthetic-chain",
        causation_id="owner-deferral-evidence-gap",
    )
    assert first_intent.created
    assert not duplicate_intent.created
    assert duplicate_intent.business_event.id == first_intent.business_event.id


def _calculate_metric(
    session: Session,
    *,
    scope: TenantScope,
    clock: FixedClock,
    definition: models.OutcomeMetricDefinitionModel,
    corrects_metric_version_id: str | None = None,
) -> models.OutcomeMetricVersionModel:
    return calculate_outcome_metric_version(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        source_window_start=clock.now() - timedelta(hours=1),
        source_window_end=clock.now() + timedelta(hours=1),
        clock=clock,
        corrects_metric_version_id=corrects_metric_version_id,
    ).metric_version


def test_disabled_outcome_pipeline_produces_metric_learning_and_non_live_proposal(
    session: Session,
) -> None:
    untouched_models = (
        models.DecisionModel,
        models.ApprovalModel,
        models.PublicationModel,
        models.ExecutionModel,
    )
    before_counts = _counts(session, untouched_models)
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )

    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
    metric_evidence = session.get(models.EvidenceModel, metric.evidence_id)
    assert metric.version_number == 1
    assert metric.value_numeric == 0.5
    assert metric.numerator_count == 1
    assert metric.denominator_count == 2
    assert metric.availability_status == OutcomeDataAvailability.AVAILABLE.value
    assert metric_evidence is not None
    assert metric_evidence.status == EpistemicStatus.OBSERVATION.value
    assert metric.synthetic_non_live is True

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
        limitations=["synthetic economics prove gate mechanics only"],
        clock=clock,
    ).economic_link
    assert not economic.supports_go

    learning = create_outcome_learning(
        session,
        scope=scope,
        metric_version_id=metric.id,
        economic_link_id=economic.id,
        clock=clock,
    ).learning
    assert learning.causality_class == CausalityClass.UNKNOWN.value
    assert set(learning.evidence_ids) == {metric.evidence_id, economic.evidence_id}

    proposal = create_outcome_experiment_proposal(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        metric_version_id=metric.id,
        economic_link_id=economic.id,
        learning_id=learning.id,
        hypothesis="Qualified intent may be a stronger downstream metric than reactions.",
        treatment="Synthetic non-live treatment",
        control="Synthetic non-live control",
        success_threshold=">= 0.30 qualified intent rate",
        weak_signal_threshold=">= 0.10 qualified intent rate",
        failure_threshold="< 0.10 qualified intent rate",
        limitations=["proposal is disabled and non-live"],
        clock=clock,
    )
    assert proposal.status == OutcomeInstrumentationStatus.DISABLED_NON_LIVE.value
    assert proposal.payload["external_execution_authorized"] is False

    after_counts = _counts(session, untouched_models)
    assert after_counts == before_counts


def test_unavailable_count_outcome_remains_missing_instead_of_zero(session: Session) -> None:
    scope, clock = _seed_scope(session)
    definition = create_outcome_metric_definition(
        session,
        scope=scope,
        metric_key="unavailable_revenue_count",
        outcome_class=BusinessOutcomeClass.REVENUE,
        numerator_event_type="outcome.synthetic.revenue",
        aggregation=OutcomeMetricAggregation.COUNT,
        eligible_population="No connected revenue source",
        denominator_description="Not applicable to count",
        observation_window_seconds=3600,
        attribution_method="none_without_source",
        attribution_limitations=["revenue source is unavailable"],
        data_availability=OutcomeDataAvailability.UNAVAILABLE,
        downstream_economic_meaning="Revenue cannot be computed without a source.",
        clock=clock,
    )

    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
    evidence = session.get(models.EvidenceModel, metric.evidence_id)

    assert metric.numerator_count == 0
    assert metric.value_numeric is None
    assert metric.availability_status == OutcomeDataAvailability.UNAVAILABLE.value
    assert evidence is not None
    assert evidence.status == EpistemicStatus.UNKNOWN.value


def test_hypothetical_economic_link_cannot_satisfy_3x_go_gate(session: Session) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)

    economic = create_outcome_economic_link(
        session,
        scope=scope,
        metric_version_id=metric.id,
        link_type=OutcomeEconomicLinkType.HYPOTHETICAL_PROXY,
        downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN,
        epistemic_status=EpistemicStatus.HYPOTHESIS,
        value_per_unit_cents=10000,
        direct_cost_cents=0,
        fully_loaded_execution_cost_cents=100,
        opportunity_cost_cents=100,
        bounded_downside_cents=200,
        expected_benefit_cents=10000,
        limitations=["economic meaning is hypothetical"],
        clock=clock,
    ).economic_link

    assert not economic.supports_go


def test_outcome_proposal_requires_exact_metric_and_economic_evidence(
    session: Session,
) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
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
    incomplete_learning = models.LearningModel(
        id="incomplete-outcome-learning",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        decision_id=None,
        experiment_id=None,
        statement="Incomplete evidence package",
        evidence_ids=[metric.evidence_id],
        causality_class=CausalityClass.UNKNOWN.value,
    )
    session.add(incomplete_learning)
    session.flush()

    with pytest.raises(PermanentJobError):
        create_outcome_experiment_proposal(
            session,
            scope=scope,
            metric_definition_id=definition.id,
            metric_version_id=metric.id,
            economic_link_id=economic.id,
            learning_id=incomplete_learning.id,
            hypothesis="Incomplete evidence should not support a proposal.",
            treatment="Synthetic non-live treatment",
            control="Synthetic non-live control",
            success_threshold=">= 0.30 qualified intent rate",
            weak_signal_threshold=">= 0.10 qualified intent rate",
            failure_threshold="< 0.10 qualified intent rate",
            limitations=["incomplete evidence"],
            clock=clock,
        )


def test_outcome_metric_correction_creates_new_version_without_overwrite(
    session: Session,
) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    first_metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
    first_value = first_metric.value_numeric
    first_derivation_hash = first_metric.derivation_hash

    ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=intent_contract.id,
        external_event_id="intent-1",
        occurred_at=clock.now() + timedelta(minutes=20),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="outcome-synthetic-chain",
        causation_id=first_metric.id,
    )
    second_metric = _calculate_metric(
        session,
        scope=scope,
        clock=clock,
        definition=definition,
        corrects_metric_version_id=first_metric.id,
    )

    assert second_metric.id != first_metric.id
    assert second_metric.version_number == first_metric.version_number + 1
    assert second_metric.corrects_metric_version_id == first_metric.id
    assert second_metric.value_numeric == 1.0
    persisted_first = session.get(models.OutcomeMetricVersionModel, first_metric.id)
    assert persisted_first is not None
    assert persisted_first.value_numeric == first_value
    assert persisted_first.derivation_hash == first_derivation_hash


def test_outcome_payloads_reject_secrets_and_raw_identity(session: Session) -> None:
    scope, clock = _seed_scope(session)

    with pytest.raises(SecretRejectedError):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key="bad-contract",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="outcome.synthetic.qualified_intent",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema={"api_key": "do-not-store"},
            clock=clock,
        )

    contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="identity-rejection",
        event_type="outcome.synthetic.qualified_intent",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )

    with pytest.raises(SecretRejectedError):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id="secret-observation",
            occurred_at=clock.now(),
            payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID, "token": "x"},
            clock=clock,
            correlation_id="secret-rejected",
        )

    with pytest.raises(PermanentJobError):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id="identity-observation",
            occurred_at=clock.now(),
            payload={
                "subject_type": SUBJECT_TYPE,
                "subject_id": SUBJECT_ID,
                "email": "person@example.test",
            },
            clock=clock,
            correlation_id="identity-rejected",
        )


def test_disabled_economics_reject_fact_promotion(session: Session) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)

    for status in (EpistemicStatus.FACT, EpistemicStatus.DERIVED_FACT):
        with pytest.raises(PermanentJobError, match="cannot self-certify"):
            create_outcome_economic_link(
                session,
                scope=scope,
                metric_version_id=metric.id,
                link_type=OutcomeEconomicLinkType.CONTRIBUTION_MARGIN,
                downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN,
                epistemic_status=status,
                value_per_unit_cents=4500,
                direct_cost_cents=0,
                fully_loaded_execution_cost_cents=1000,
                opportunity_cost_cents=500,
                bounded_downside_cents=1500,
                expected_benefit_cents=999999,
                limitations=["must remain non-authoritative"],
                clock=clock,
            )


def test_synthetic_contract_schema_is_strict_and_rejects_identity_aliases(
    session: Session,
) -> None:
    scope, clock = _seed_scope(session)
    base = {
        "type": "object",
        "required": ["subject_type", "subject_id"],
        "properties": {
            "subject_type": {"type": "string"},
            "subject_id": {"type": "string"},
        },
    }
    with pytest.raises(PermanentJobError, match="additionalProperties=false"):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key="open-schema",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="outcome.synthetic.qualified_intent",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema=base,
            clock=clock,
        )

    pii_schema = {
        **base,
        "properties": {**base["properties"], "customer_email": {"type": "string"}},
        "additionalProperties": False,
    }
    with pytest.raises(PermanentJobError, match="raw identity"):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key="pii-schema",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="outcome.synthetic.qualified_intent",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema=pii_schema,
            clock=clock,
        )

    contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="strict-payload",
        event_type="outcome.synthetic.qualified_intent",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    with pytest.raises(PermanentJobError, match="raw identity"):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id="pii-alias-field",
            occurred_at=clock.now(),
            payload={
                "subject_type": SUBJECT_TYPE,
                "subject_id": SUBJECT_ID,
                "customer_email": "person@example.test",
            },
            clock=clock,
            correlation_id="strict-schema",
        )
    with pytest.raises(PermanentJobError, match="undeclared fields"):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id="extra-field",
            occurred_at=clock.now(),
            payload={
                "subject_type": SUBJECT_TYPE,
                "subject_id": SUBJECT_ID,
                "unexpected": "x",
            },
            clock=clock,
            correlation_id="strict-schema",
        )
    with pytest.raises(PermanentJobError, match="wrong type"):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id="wrong-type",
            occurred_at=clock.now(),
            payload={"subject_type": SUBJECT_TYPE, "subject_id": 123},
            clock=clock,
            correlation_id="strict-schema",
        )


def test_synthetic_idempotency_conflicts_fail_closed(session: Session) -> None:
    scope, clock = _seed_scope(session)
    first_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="idempotency-a",
        event_type="outcome.synthetic.qualified_intent.a",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    second_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="idempotency-b",
        event_type="outcome.synthetic.qualified_intent.b",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    kwargs = dict(
        session=session,
        scope=scope,
        ingestion_contract_id=first_contract.id,
        external_event_id="shared-id",
        occurred_at=clock.now(),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="idempotency",
        causation_id="cause-a",
    )
    created = ingest_synthetic_outcome_observation(**kwargs)
    replay = ingest_synthetic_outcome_observation(**kwargs)
    assert created.created
    assert not replay.created

    with pytest.raises(PermanentJobError, match="conflicts with a different request"):
        ingest_synthetic_outcome_observation(
            **{**kwargs, "causation_id": "cause-b"}
        )
    with pytest.raises(PermanentJobError, match="conflicts with a different request"):
        ingest_synthetic_outcome_observation(
            **{**kwargs, "ingestion_contract_id": second_contract.id}
        )


def test_learning_and_metric_corrections_require_same_lineage(session: Session) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
    economic = create_outcome_economic_link(
        session,
        scope=scope,
        metric_version_id=metric.id,
        link_type=OutcomeEconomicLinkType.HYPOTHETICAL_PROXY,
        downstream_outcome_class=BusinessOutcomeClass.CONTRIBUTION_MARGIN,
        epistemic_status=EpistemicStatus.HYPOTHESIS,
        value_per_unit_cents=100,
        direct_cost_cents=0,
        fully_loaded_execution_cost_cents=10,
        opportunity_cost_cents=10,
        bounded_downside_cents=20,
        expected_benefit_cents=100,
        limitations=["synthetic"],
        clock=clock,
    ).economic_link

    with pytest.raises(PermanentJobError, match="same definition and subject"):
        calculate_outcome_metric_version(
            session,
            scope=scope,
            metric_definition_id=definition.id,
            subject_type=SUBJECT_TYPE,
            subject_id="other-subject",
            source_window_start=clock.now() - timedelta(hours=1),
            source_window_end=clock.now() + timedelta(hours=1),
            clock=clock,
            corrects_metric_version_id=metric.id,
        )

    other_metric = calculate_outcome_metric_version(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        subject_type=SUBJECT_TYPE,
        subject_id="other-subject",
        source_window_start=clock.now() - timedelta(hours=1),
        source_window_end=clock.now() + timedelta(hours=1),
        clock=clock,
    ).metric_version
    with pytest.raises(PermanentJobError, match="does not match metric version"):
        create_outcome_learning(
            session,
            scope=scope,
            metric_version_id=other_metric.id,
            economic_link_id=economic.id,
            clock=clock,
        )


def test_metric_derivation_reuses_older_matching_version(session: Session) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    _ingest_fixture_events(
        session,
        scope=scope,
        clock=clock,
        exposure_contract=exposure_contract,
        intent_contract=intent_contract,
    )
    window_start = clock.now() - timedelta(hours=1)
    first_end = clock.now()
    first = calculate_outcome_metric_version(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        source_window_start=window_start,
        source_window_end=first_end,
        clock=clock,
    )
    ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=intent_contract.id,
        external_event_id="intent-later",
        occurred_at=clock.now() + timedelta(minutes=20),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="later-event",
    )
    second = calculate_outcome_metric_version(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        source_window_start=window_start,
        source_window_end=clock.now() + timedelta(hours=1),
        clock=clock,
        corrects_metric_version_id=first.metric_version.id,
    )
    replay = calculate_outcome_metric_version(
        session,
        scope=scope,
        metric_definition_id=definition.id,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        source_window_start=window_start,
        source_window_end=first_end,
        clock=clock,
    )
    assert first.created
    assert second.created
    assert not replay.created
    assert replay.metric_version.id == first.metric_version.id


@pytest.mark.parametrize("reserved_field", sorted(RESERVED_OUTCOME_PAYLOAD_FIELDS))
def test_reserved_outcome_metadata_is_rejected_in_schema_and_payload(
    session: Session,
    reserved_field: str,
) -> None:
    scope, clock = _seed_scope(session)
    schema = {
        "type": "object",
        "required": ["subject_type", "subject_id"],
        "properties": {
            "subject_type": {"type": "string"},
            "subject_id": {"type": "string"},
            reserved_field: {"type": "string"},
        },
        "additionalProperties": False,
    }
    with pytest.raises(PermanentJobError, match="reserved outcome metadata"):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key=f"reserved-{reserved_field}",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="outcome.synthetic.reserved_metadata",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema=schema,
            clock=clock,
        )

    contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key=f"reserved-payload-{reserved_field}",
        event_type="outcome.synthetic.reserved_payload",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    with pytest.raises(PermanentJobError, match="reserved outcome metadata"):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id=f"reserved-payload-{reserved_field}",
            occurred_at=clock.now(),
            payload={
                "subject_type": SUBJECT_TYPE,
                "subject_id": SUBJECT_ID,
                reserved_field: "forged",
            },
            clock=clock,
            correlation_id="reserved-payload",
        )


def test_synthetic_contract_cannot_use_phase6_live_event_namespace(session: Session) -> None:
    scope, clock = _seed_scope(session)
    schema = {
        "type": "object",
        "required": ["subject_type", "subject_id"],
        "properties": {
            "subject_type": {"type": "string"},
            "subject_id": {"type": "string"},
        },
        "additionalProperties": False,
    }
    before = _count(session, models.BusinessEventModel)
    with pytest.raises(PermanentJobError, match=r"outcome\.synthetic"):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key="phase6-collision",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="telegram.message_reaction",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema=schema,
            clock=clock,
        )
    assert _count(session, models.BusinessEventModel) == before


@pytest.mark.parametrize("unsupported_keyword", ["enum", "pattern", "minLength"])
def test_contract_schema_rejects_unsupported_property_keywords(
    session: Session,
    unsupported_keyword: str,
) -> None:
    scope, clock = _seed_scope(session)
    subject_schema: dict[str, object] = {"type": "string"}
    subject_schema[unsupported_keyword] = (
        ["synthetic:fixture"] if unsupported_keyword == "enum" else "^synthetic:"
    )
    if unsupported_keyword == "minLength":
        subject_schema[unsupported_keyword] = 1
    schema = {
        "type": "object",
        "required": ["subject_type", "subject_id"],
        "properties": {
            "subject_type": {"type": "string"},
            "subject_id": subject_schema,
        },
        "additionalProperties": False,
    }
    with pytest.raises(PermanentJobError, match="unsupported keywords"):
        create_outcome_ingestion_contract(
            session,
            scope=scope,
            provider="synthetic_fixture",
            contract_key=f"unsupported-{unsupported_keyword}",
            payload_schema_version=1,
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            canonical_event_type="outcome.synthetic.schema_keyword",
            identity_boundary="synthetic subject only",
            pii_classification="none",
            retention_class="test",
            schema=schema,
            clock=clock,
        )


@pytest.mark.parametrize(
    "subject_id",
    ["person@example.test", "+3725551234", "real-user-123"],
)
def test_synthetic_subject_id_boundary_rejects_real_identity_like_values(
    session: Session,
    subject_id: str,
) -> None:
    scope, clock = _seed_scope(session)
    contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key=f"identity-boundary-{abs(hash(subject_id))}",
        event_type="outcome.synthetic.identity_boundary",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    with pytest.raises(PermanentJobError):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id=f"identity-{abs(hash(subject_id))}",
            occurred_at=clock.now(),
            payload={"subject_type": SUBJECT_TYPE, "subject_id": subject_id},
            clock=clock,
            correlation_id="identity-boundary",
        )


def test_metric_filters_events_by_bound_numerator_and_denominator_contracts(
    session: Session,
) -> None:
    scope, clock, definition, exposure_contract, intent_contract = _metric_fixture(session)
    same_event_other_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="intent-other-contract",
        event_type=intent_contract.canonical_event_type,
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    different_provider_contract = create_outcome_ingestion_contract(
        session,
        scope=scope,
        provider="other_synthetic_provider",
        contract_key="intent-other-provider",
        payload_schema_version=1,
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
        canonical_event_type=intent_contract.canonical_event_type,
        identity_boundary="synthetic subject only",
        pii_classification="none",
        retention_class="test",
        schema=intent_contract.schema,
        clock=clock,
    )
    different_schema_version_contract = create_outcome_ingestion_contract(
        session,
        scope=scope,
        provider=intent_contract.provider,
        contract_key="intent-schema-v2",
        payload_schema_version=2,
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
        canonical_event_type=intent_contract.canonical_event_type,
        identity_boundary="synthetic subject only",
        pii_classification="none",
        retention_class="test",
        schema=intent_contract.schema,
        clock=clock,
    )

    start = clock.now() - timedelta(minutes=10)
    ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=exposure_contract.id,
        external_event_id="bound-exposure",
        occurred_at=start,
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="contract-isolation",
    )
    for index, contract in enumerate(
        [
            same_event_other_contract,
            different_provider_contract,
            different_schema_version_contract,
        ]
    ):
        ingest_synthetic_outcome_observation(
            session,
            scope=scope,
            ingestion_contract_id=contract.id,
            external_event_id=f"wrong-intent-{index}",
            occurred_at=start + timedelta(minutes=index + 1),
            payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
            clock=clock,
            correlation_id="contract-isolation",
        )
    ingest_synthetic_outcome_observation(
        session,
        scope=scope,
        ingestion_contract_id=intent_contract.id,
        external_event_id="bound-intent",
        occurred_at=start + timedelta(minutes=5),
        payload={"subject_type": SUBJECT_TYPE, "subject_id": SUBJECT_ID},
        clock=clock,
        correlation_id="contract-isolation",
    )

    metric = _calculate_metric(session, scope=scope, clock=clock, definition=definition)
    assert metric.numerator_count == 1
    assert metric.denominator_count == 1
    assert metric.value_numeric == 1.0


def test_rate_definition_requires_explicit_denominator_contract(session: Session) -> None:
    scope, clock = _seed_scope(session)
    intent_contract = _contract(
        session,
        scope=scope,
        clock=clock,
        key="rate-intent",
        event_type="outcome.synthetic.rate_intent",
        outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
    )
    with pytest.raises(PermanentJobError, match="denominator_ingestion_contract_id"):
        create_outcome_metric_definition(
            session,
            scope=scope,
            metric_key="invalid_rate",
            outcome_class=BusinessOutcomeClass.QUALIFIED_INTENT,
            numerator_event_type=intent_contract.canonical_event_type,
            denominator_event_type="outcome.synthetic.rate_exposure",
            aggregation=OutcomeMetricAggregation.RATE,
            eligible_population="Synthetic subjects",
            denominator_description="Synthetic exposures",
            observation_window_seconds=3600,
            attribution_method="same_subject_window",
            attribution_limitations=["synthetic only"],
            data_availability=OutcomeDataAvailability.AVAILABLE,
            downstream_economic_meaning="Synthetic only",
            ingestion_contract_id=intent_contract.id,
            clock=clock,
        )
