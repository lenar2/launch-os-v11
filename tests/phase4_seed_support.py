from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.ai_runtime.contracts import AgentRunStatus
from launch_os_v11.application.decision_workflow import DECISION_APPROVAL_ACTION
from launch_os_v11.domain.enums import ApprovalStatus, EpistemicStatus
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models


class Seed:
    def __init__(
        self,
        *,
        scope: TenantScope,
        decision_id: str,
        evidence_id: str,
    ) -> None:
        self.scope = scope
        self.decision_id = decision_id
        self.evidence_id = evidence_id


def seed_approved_decision(
    factory: sessionmaker[Session],
    *,
    now: datetime,
) -> Seed:
    session = factory()
    try:
        with session.begin():
            scope, user, evidence, snapshot = _seed_business_context(session, now=now)
            decision = _seed_approved_phase3_chain(
                session,
                scope=scope,
                user=user,
                evidence=evidence,
                snapshot=snapshot,
                now=now,
            )
            return Seed(scope=scope, decision_id=decision.id, evidence_id=evidence.id)
    finally:
        session.close()


def _seed_business_context(
    session: Session,
    *,
    now: datetime,
) -> tuple[TenantScope, models.UserModel, models.EvidenceModel, models.BusinessSnapshotModel]:
    organization = models.OrganizationModel(
        id="phase4-org", name="Phase 4 Org", created_at=now, updated_at=now
    )
    business = models.BusinessModel(
        id="phase4-business",
        organization_id=organization.id,
        name="Phase 4 Business",
        timezone="UTC",
        created_at=now,
        updated_at=now,
        version=1,
    )
    user = models.UserModel(
        id="phase4-owner",
        email="phase4@example.test",
        display_name="Owner",
        created_at=now,
        updated_at=now,
    )
    session.add_all([organization, business, user])
    session.flush()
    scope = TenantScope(organization_id=organization.id, business_id=business.id)
    source = models.SourceRecordModel(
        id="phase4-source",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        provider="manual",
        external_id="phase4-source",
        source_type="owner_note",
        trust="USER_PROVIDED",
        payload={"note": "Readers asked for a concise launch post."},
        source_occurred_at=now,
        ingested_at=now,
        created_at=now,
        updated_at=now,
        version=1,
    )
    evidence = models.EvidenceModel(
        id="phase4-evidence",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_record_id=source.id,
        statement="Readers asked for a concise launch post.",
        status=EpistemicStatus.FACT.value,
        confidence=1.0,
        occurred_at=now,
        recorded_at=now,
        conflicts_with_evidence_ids=[],
        created_at=now,
        updated_at=now,
        version=1,
    )
    snapshot = models.BusinessSnapshotModel(
        id="phase4-snapshot",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        version=1,
        reason="Approved Phase 3 decision",
        payload={
            "business": {"name": business.name},
            "offer": {"name": "Pilot"},
            "channel": {"provider": "telegram"},
            "evidence_ids": [evidence.id],
        },
        created_at=now,
    )
    session.add_all([source, evidence, snapshot])
    session.flush()
    return scope, user, evidence, snapshot


def _seed_approved_phase3_chain(
    session: Session,
    *,
    scope: TenantScope,
    user: models.UserModel,
    evidence: models.EvidenceModel,
    snapshot: models.BusinessSnapshotModel,
    now: datetime,
) -> models.DecisionModel:
    definition = models.AgentDefinitionModel(
        id="phase4-seed-definition",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name="Seed Chief",
        mission="Seed accepted Phase 3 provenance only.",
        output_schema={},
        enabled=True,
        contract_key="seed.phase3.chief",
        contract_version=1,
        role_name="Seed Chief",
        model_capability="DEEP_REASONING",
        allowed_context_types=["business_snapshot"],
        required_context_types=["business_snapshot"],
        authority_boundaries=["READ_CONTEXT"],
        prohibited_actions=["external write"],
        required_controller_types=["seed"],
        abstention_policy="seed",
        escalation_policy="seed",
        instruction_version="seed.v1",
        eval_suite_identifier="seed.v1",
        contract_fingerprint="a" * 64,
        output_schema_name="DecisionCandidate",
        output_schema_version=1,
        created_at=now,
        updated_at=now,
        version=1,
    )
    chief_run = models.AgentRunModel(
        id="phase4-seed-chief-run",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        agent_definition_id=definition.id,
        job_id=None,
        payload_schema_version=1,
        agent_contract_key=definition.contract_key,
        agent_contract_version=1,
        agent_contract_fingerprint=definition.contract_fingerprint,
        output_schema_name="DecisionCandidate",
        output_schema_version=1,
        status=AgentRunStatus.SUCCEEDED.value,
        input_ref="seed",
        output_ref=None,
        context_refs=[],
        context_manifest={},
        context_hash="b" * 64,
        output_data={"seed": True},
        refusal_summary=None,
        error_class=None,
        error_summary=None,
        provider_name="fake",
        provider_model="fake-structured-model",
        provider_response_id="seed",
        token_usage={},
        latency_ms=1,
        safe_trace_metadata={},
        started_at=now,
        completed_at=now,
        correlation_id="corr-phase3-seed",
        causation_id=None,
        idempotency_key="phase4-seed-chief",
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add_all([definition, chief_run])
    session.flush()
    workflow = models.DecisionWorkflowModel(
        id="phase4-decision-workflow",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        launch_id=None,
        snapshot_id=snapshot.id,
        status="CANDIDATE_ACCEPTED",
        revision_count=0,
        max_revision_rounds=2,
        final_decision_id=None,
        final_approval_id=None,
        correlation_id="corr-phase3-seed",
        causation_id=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(workflow)
    session.flush()
    candidate = models.DecisionCandidateModel(
        id="phase4-candidate",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        workflow_id=workflow.id,
        snapshot_id=snapshot.id,
        chief_agent_run_id=chief_run.id,
        previous_candidate_id=None,
        version_number=1,
        revision_round=0,
        status="MATERIALIZED",
        schema_version=1,
        selected_action="Publish a concise Telegram launch post",
        payload={"why": ["Audience requested concise format"]},
        evidence_refs=[{
            "evidence_id": evidence.id,
            "epistemic_status": EpistemicStatus.FACT.value,
            "note": "Owner-provided audience signal",
        }],
        specialist_contribution_ids=[],
        controller_review_ids=[],
        context_hash="b" * 64,
        context_manifest={},
        correlation_id="corr-phase3-seed",
        causation_id=chief_run.id,
        created_at=now,
    )
    session.add(candidate)
    session.flush()
    decision = models.DecisionModel(
        id="phase4-decision",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        goal_problem="Increase qualified launch replies",
        selected_action=candidate.selected_action,
        expected_effect="More qualified replies",
        confidence=0.7,
        reversibility="easy",
        risk_class="LOW",
        status="APPROVED_FOR_PRODUCTION",
        snapshot_id=snapshot.id,
        supersedes_decision_id=None,
        next_checkpoint="Review replies after seven days",
        evidence_ids=[evidence.id],
        assumption_ids=[],
        known_unknown_ids=[],
        source_candidate_id=candidate.id,
        why_alternatives_not_selected=["Waiting would not test the signal"],
        hypotheses=[],
        assumptions=[],
        experiment_proposal={"metric": "qualified_replies", "success_threshold": "10 replies"},
        required_assets=["Telegram post copy"],
        required_actions=["publication approval"],
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(decision)
    session.flush()
    workflow.final_decision_id = decision.id
    workflow.status = "APPROVED_FOR_PRODUCTION"
    approval = models.DecisionApprovalModel(
        id="phase4-decision-approval",
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        workflow_id=workflow.id,
        decision_id=decision.id,
        candidate_id=candidate.id,
        action_type=DECISION_APPROVAL_ACTION,
        object_type="Decision",
        object_id=decision.id,
        object_version_id=decision.id,
        object_version=decision.version,
        approved_by_user_id=user.id,
        status=ApprovalStatus.APPROVED.value,
        correlation_id="corr-phase3-approval",
        causation_id=decision.id,
        created_at=now,
    )
    session.add(approval)
    session.flush()
    workflow.final_approval_id = approval.id
    return decision
