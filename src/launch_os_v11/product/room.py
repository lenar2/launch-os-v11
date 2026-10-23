"""Launch Room commands.

Approach kept: one object-centric room (goal, snapshot, decision, draft,
approval, observation, adaptation).

Approach rejected: a chat thread. Launch OS is not a transcript, and a chat
message must not be readable as publication authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from launch_os_v11.application.commands import (
    CommandContext,
    create_business,
    create_business_event,
    create_business_snapshot,
    create_evidence,
    create_goal,
    create_organization,
    create_source_record,
)
from launch_os_v11.application.decision_governance import _contains_human_worth_violation
from launch_os_v11.application.decision_workflow import (
    DecisionWorkflowStatus,
    _snapshot_payload,
    approve_decision_for_production,
    start_decision_workflow,
)
from launch_os_v11.domain.enums import EpistemicStatus, SourceTrust
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import (
    AssetVersionModel,
    BusinessEventModel,
    BusinessMembershipModel,
    CampaignModel,
    ChannelModel,
    ConstraintModel,
    DecisionWorkflowModel,
    EvidenceModel,
    InformationNeedModel,
    LaunchModel,
    OfferModel,
    ProductModel,
    SourceRecordModel,
    UserModel,
)
from launch_os_v11.persistence.phase6_models import MetricVersionModel
from launch_os_v11.persistence.production_models import (
    AssetVersionCreatorModel,
    ProductionWorkflowModel,
)
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.projection import LaunchRoomView, project_launch_room
from launch_os_v11.product.runtime import LaunchRoomRuntime
from launch_os_v11.product.script import LaunchScriptFacts
from launch_os_v11.production.start import start_production_workflow
from launch_os_v11.production.status import ProductionWorkflowStatus
from launch_os_v11.runtime.errors import PermanentJobError

_T = TypeVar("_T")
_COMMAND_MARKERS = (
    "publish",
    "execute",
    "send it",
    "post it",
    "post now",
    "go live",
    "bot token",
    "api key",
)
_WORTH_MARKERS = (
    "human value",
    "self-worth",
    "self worth",
    "worth",
    "not ready",
    "readiness",
    "personal correctness",
    "your value",
)


class LaunchRoomService:
    def __init__(self, runtime: LaunchRoomRuntime) -> None:
        self._runtime = runtime

    def open_launch(
        self,
        *,
        business_name: str,
        goal: str,
        offer_name: str,
        audience: str | None = None,
        known_fact: str | None = None,
        timezone: str = "UTC",
    ) -> LaunchRoomView:
        _require_text("business_name", business_name)
        _require_text("goal", goal)
        _require_text("offer_name", offer_name)
        _reject_worth("goal", goal)
        if known_fact:
            _reject_worth("known_fact", known_fact)
        audience_value = audience.strip() if isinstance(audience, str) else ""
        fact_value = known_fact.strip() if isinstance(known_fact, str) else ""

        def work(session: Session) -> LaunchRoomView:
            organization = create_organization(session, name=f"{business_name.strip()} org")
            business = create_business(
                session,
                organization_id=organization.id,
                name=business_name.strip(),
                timezone=timezone.strip() or "UTC",
                actor_user_id=None,
                correlation_id=new_id(),
            ).record
            owner = UserModel(
                id=new_id(),
                email=f"owner-{new_id()}@launch-room.invalid",
                display_name="Owner",
            )
            session.add(owner)
            session.flush()
            session.add(
                BusinessMembershipModel(
                    id=new_id(),
                    organization_id=organization.id,
                    business_id=business.id,
                    user_id=owner.id,
                    role="OWNER",
                )
            )
            context = CommandContext(
                organization_id=organization.id,
                business_id=business.id,
                actor_user_id=owner.id,
                correlation_id=new_id(),
            )
            goal_row = create_goal(
                session,
                context=context,
                title=goal.strip()[:255],
                target="UNKNOWN until measured",
                metric="qualified_replies",
            ).record
            product = ProductModel(
                id=new_id(),
                organization_id=organization.id,
                business_id=business.id,
                name=offer_name.strip(),
                description="Owner-stated offer. No measured demand.",
            )
            offer = OfferModel(
                id=new_id(),
                organization_id=organization.id,
                business_id=business.id,
                product_id=product.id,
                name=offer_name.strip(),
                description=goal.strip(),
                price_descriptor=None,
            )
            channel = ChannelModel(
                id=new_id(),
                organization_id=organization.id,
                business_id=business.id,
                provider="telegram",
                handle="not-connected",
                capabilities={"publish": False, "observe": False, "connector": "NOT_CONNECTED"},
            )
            campaign = CampaignModel(
                id=new_id(),
                organization_id=organization.id,
                business_id=business.id,
                name=f"Launch: {offer_name.strip()[:80]}",
                goal_id=goal_row.id,
            )
            session.add_all([product, offer, channel, campaign])
            session.flush()
            launch = LaunchModel(
                id=new_id(),
                organization_id=organization.id,
                business_id=business.id,
                campaign_id=campaign.id,
                offer_id=offer.id,
                goal_id=goal_row.id,
                channel_id=channel.id,
                snapshot_id=None,
                status="GOAL_CAPTURED",
            )
            session.add(launch)
            session.add(
                ConstraintModel(
                    id=new_id(),
                    organization_id=organization.id,
                    business_id=business.id,
                    category="brand",
                    rule="No shame, pressure, or judgment of a person.",
                )
            )
            for question in (
                "What income has been observed?",
                "How large is the audience?",
                "How many qualified replies have been recorded?",
            ):
                session.add(
                    InformationNeedModel(
                        id=new_id(),
                        organization_id=organization.id,
                        business_id=business.id,
                        question=question,
                        critical=False,
                    )
                )
            session.flush()
            create_source_record(
                session,
                context=context,
                provider="launch_room",
                external_id=f"intent-{launch.id}",
                source_type="launch_room_intent",
                trust=SourceTrust.USER_PROVIDED,
                payload={
                    "schema": "LaunchRoomIntent",
                    "launch_id": launch.id,
                    "owner_user_id": owner.id,
                    "goal": goal.strip(),
                    "offer_name": offer_name.strip(),
                    "audience": audience_value or None,
                    "known_fact": fact_value or None,
                    "data_origin": "OWNER_STATED",
                    "model_intelligence": "NOT_PROVEN",
                },
            )
            source = create_source_record(
                session,
                context=context,
                provider="launch_room",
                external_id=f"goal-{launch.id}",
                source_type="launch_goal",
                trust=SourceTrust.USER_PROVIDED,
                payload={"launch_id": launch.id, "kind": "goal"},
            ).record
            create_evidence(
                session,
                context=context,
                source_record_id=source.id,
                statement=f"Owner stated this launch goal: {goal.strip()}",
                status=EpistemicStatus.OBSERVATION,
            )
            # autoflush is off; the snapshot query must see the goal evidence.
            session.flush()
            snapshot = create_business_snapshot(
                session,
                context=context,
                reason="launch_room.goal_captured",
                payload=_snapshot_payload(
                    session,
                    scope=context.scope,
                    launch_id=launch.id,
                ),
            ).record
            launch.snapshot_id = snapshot.id
            session.flush()
            return project_launch_room(session, launch.id)

        return self._write(work)

    def get_room(self, launch_id: str, *, operator: TrustedOperator) -> LaunchRoomView:
        def work(session: Session) -> LaunchRoomView:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            return project_launch_room(session, launch_id, scope=operator.scope)

        return self._write(work)

    def run_team_decision(self, launch_id: str, *, operator: TrustedOperator) -> LaunchRoomView:
        facts, should_run = self._write(
            lambda session: self._prepare_decision(session, launch_id, operator)
        )
        if should_run and facts is not None:
            self._runtime.drain(facts)
            self._assert_decision_ready(launch_id, operator)
        return self.get_room(launch_id, operator=operator)

    def request_revision(
        self,
        launch_id: str,
        note: str,
        *,
        operator: TrustedOperator,
    ) -> LaunchRoomView:
        _require_text("note", note)
        _reject_worth("revision", note)

        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            workflow = _latest_workflow(session, launch)
            if (
                workflow is None
                or workflow.status != DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value
            ):
                raise ProductError(
                    "revision_refused",
                    "A revision can be requested only while a decision is waiting for you.",
                )
            context = _context(launch, operator.user_id)
            source = create_source_record(
                session,
                context=context,
                provider="launch_room",
                external_id=f"revision-{new_id()}",
                source_type="owner_revision",
                trust=SourceTrust.USER_PROVIDED,
                payload={"launch_id": launch.id, "kind": "revision"},
            ).record
            create_evidence(
                session,
                context=context,
                source_record_id=source.id,
                statement=_data_note("Owner revision note", note),
                status=EpistemicStatus.OBSERVATION,
            )
            create_business_event(
                session,
                context=context,
                event_type="launch_room.revision_requested",
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                payload={"launch_id": launch.id, "consumed_by_workflow_id": None},
            )

        self._write(work)
        return self.get_room(launch_id, operator=operator)

    def approve(self, launch_id: str, *, operator: TrustedOperator) -> LaunchRoomView:
        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            if _unconsumed(session, launch, "launch_room.revision_requested"):
                raise ProductError(
                    "revision_pending",
                    "Run the team again before approval. The revision is not an approval.",
                )
            workflow = _latest_workflow(session, launch)
            if workflow is None:
                raise ProductError("approval_refused", "There is no decision to approve.")
            try:
                approve_decision_for_production(
                    session,
                    context=_context(launch, operator.user_id),
                    workflow_id=workflow.id,
                    approved_by_user_id=operator.user_id,
                )
            except PermanentJobError as exc:
                raise ProductError("approval_refused", str(exc)) from exc

        self._write(work)
        return self.get_room(launch_id, operator=operator)

    def prepare_materials(self, launch_id: str, *, operator: TrustedOperator) -> LaunchRoomView:
        facts = self._write(lambda session: self._prepare_materials(session, launch_id, operator))
        if facts is not None:
            self._runtime.drain(facts)
            self._assert_materials_ready(launch_id, operator)
        return self.get_room(launch_id, operator=operator)

    def save_draft(
        self,
        launch_id: str,
        body: str,
        *,
        operator: TrustedOperator,
    ) -> LaunchRoomView:
        _require_text("body", body)
        _reject_worth("draft", body)

        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            workflow = session.scalar(
                select(ProductionWorkflowModel)
                .where(
                    ProductionWorkflowModel.organization_id == launch.organization_id,
                    ProductionWorkflowModel.business_id == launch.business_id,
                    ProductionWorkflowModel.launch_id == launch.id,
                    ProductionWorkflowModel.final_asset_version_id.is_not(None),
                )
                .order_by(ProductionWorkflowModel.created_at.desc())
            )
            if workflow is None or workflow.final_asset_version_id is None:
                raise ProductError(
                    "draft_refused",
                    "Prepare the unpublished draft before editing it. Editing does not publish.",
                )
            current = session.get(AssetVersionModel, workflow.final_asset_version_id)
            if current is None:
                raise ProductError("draft_refused", "The current draft could not be found.")
            version_number = int(
                session.scalar(
                    select(func.max(AssetVersionModel.version_number)).where(
                        AssetVersionModel.asset_id == current.asset_id
                    )
                )
                or 0
            )
            version = AssetVersionModel(
                id=new_id(),
                organization_id=launch.organization_id,
                business_id=launch.business_id,
                asset_id=current.asset_id,
                version_number=version_number + 1,
                body=body.strip(),
                created_by_user_id=operator.user_id,
                provenance={
                    "schema_name": "AssetVersionProvenance",
                    "schema_version": 1,
                    "origin": "OWNER_EDIT",
                    "model_intelligence": "NOT_PROVEN",
                    "publication_performed": False,
                },
                created_at=utc_now(),
            )
            session.add(version)
            session.flush()
            session.add(
                AssetVersionCreatorModel(
                    id=new_id(),
                    organization_id=launch.organization_id,
                    business_id=launch.business_id,
                    asset_version_id=version.id,
                    creator_type="USER",
                    created_by_user_id=operator.user_id,
                    created_by_agent_run_id=None,
                    created_at=utc_now(),
                )
            )
            workflow.final_asset_version_id = version.id
            create_business_event(
                session,
                context=_context(launch, operator.user_id),
                event_type="launch_room.draft_edited",
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                payload={
                    "launch_id": launch.id,
                    "asset_version_id": version.id,
                    "is_metric": False,
                    "publication_performed": False,
                },
            )

        self._write(work)
        return self.get_room(launch_id, operator=operator)

    def record_manual_note(
        self,
        launch_id: str,
        note: str,
        *,
        operator: TrustedOperator,
    ) -> LaunchRoomView:
        _require_text("note", note)
        _reject_worth("note", note)

        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            create_business_event(
                session,
                context=_context(launch, operator.user_id),
                event_type="launch_room.manual_note",
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                payload={
                    "launch_id": launch.id,
                    "statement": _data_note("Manual note, not a metric", note),
                    "is_metric": False,
                },
            )

        self._write(work)
        return self.get_room(launch_id, operator=operator)

    def record_untrusted_message(
        self,
        launch_id: str,
        message: str,
        *,
        operator: TrustedOperator,
    ) -> LaunchRoomView:
        _require_text("message", message)

        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
            create_business_event(
                session,
                context=_context(launch, operator.user_id),
                event_type="launch_room.untrusted_message_not_instruction",
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                payload={
                    "launch_id": launch.id,
                    "accepted_as_instruction": False,
                    "publication_performed": False,
                    "sha256_16": digest,
                },
            )

        self._write(work)
        return self.get_room(launch_id, operator=operator)

    def adapt(self, launch_id: str, *, operator: TrustedOperator) -> LaunchRoomView:
        def work(session: Session) -> LaunchScriptFacts:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            if _metric_count(session, launch) != 0:
                raise ProductError(
                    "adapt_refused",
                    "A measured metric exists. This local room only adapts the unknown case.",
                )
            create_business_event(
                session,
                context=_context(launch, operator.user_id),
                event_type="launch_room.adaptation_requested",
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                payload={"launch_id": launch.id, "consumed_by_workflow_id": None},
            )
            return self._start_cycle(session, launch, operator.user_id)

        facts = self._write(work)
        self._runtime.drain(facts)
        self._assert_decision_ready(launch_id, operator)
        return self.get_room(launch_id, operator=operator)

    def _prepare_decision(
        self,
        session: Session,
        launch_id: str,
        operator: TrustedOperator,
    ) -> tuple[LaunchScriptFacts | None, bool]:
        launch = _launch(session, launch_id)
        _authorize(session, launch, operator)
        if not _unconsumed(session, launch, "launch_room.revision_requested"):
            workflow = _latest_workflow(session, launch)
            if workflow is not None and workflow.final_decision_id is not None:
                return None, False
        if _unconsumed(session, launch, "launch_room.adaptation_requested"):
            raise ProductError(
                "adapt_pending",
                "Finish adaptation with the adapt action. Do not mix it into a normal decision.",
            )
        return self._start_cycle(session, launch, operator.user_id), True

    def _prepare_materials(
        self,
        session: Session,
        launch_id: str,
        operator: TrustedOperator,
    ) -> LaunchScriptFacts | None:
        launch = _launch(session, launch_id)
        _authorize(session, launch, operator)
        approved = session.scalar(
            select(DecisionWorkflowModel)
            .where(
                DecisionWorkflowModel.organization_id == launch.organization_id,
                DecisionWorkflowModel.business_id == launch.business_id,
                DecisionWorkflowModel.launch_id == launch.id,
                DecisionWorkflowModel.status
                == DecisionWorkflowStatus.APPROVED_FOR_PRODUCTION.value,
                DecisionWorkflowModel.final_decision_id.is_not(None),
            )
            .order_by(DecisionWorkflowModel.created_at.desc())
        )
        if approved is None or approved.final_decision_id is None:
            raise ProductError(
                "materials_refused",
                "Materials wait for an owner-approved decision. Approval does not publish.",
            )
        existing = session.scalar(
            select(ProductionWorkflowModel).where(
                ProductionWorkflowModel.organization_id == launch.organization_id,
                ProductionWorkflowModel.business_id == launch.business_id,
                ProductionWorkflowModel.decision_id == approved.final_decision_id,
            )
        )
        if (
            existing is not None
            and existing.status == ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value
        ):
            return None
        try:
            start_production_workflow(
                session,
                scope=TenantScope(
                    organization_id=launch.organization_id,
                    business_id=launch.business_id,
                ),
                queue=self._runtime.queue,
                clock=self._runtime.clock,
                decision_id=approved.final_decision_id,
                correlation_id=new_id(),
            )
        except PermanentJobError as exc:
            raise ProductError("materials_refused", str(exc)) from exc
        return _facts(session, launch, adapting=False)

    def _start_cycle(
        self,
        session: Session,
        launch: LaunchModel,
        actor_user_id: str,
    ) -> LaunchScriptFacts:
        session.flush()
        fresh = _unconsumed(session, launch, "launch_room.revision_requested") or _unconsumed(
            session, launch, "launch_room.adaptation_requested"
        )
        adapting = _unconsumed(session, launch, "launch_room.adaptation_requested")
        try:
            result = start_decision_workflow(
                session,
                context=_context(launch, actor_user_id),
                queue=self._runtime.queue,
                clock=self._runtime.clock,
                launch_id=launch.id,
                snapshot_id=None if fresh or launch.snapshot_id is None else launch.snapshot_id,
            )
        except PermanentJobError as exc:
            raise ProductError("workflow_failed", str(exc)) from exc
        launch.snapshot_id = result.snapshot.id
        launch.status = "DECISION_REQUESTED"
        for event_type in (
            "launch_room.revision_requested",
            "launch_room.adaptation_requested",
        ):
            for event in _events(session, launch, event_type):
                if event.payload.get("consumed_by_workflow_id"):
                    continue
                event.payload = {**event.payload, "consumed_by_workflow_id": result.workflow.id}
        session.flush()
        return _facts(session, launch, adapting=adapting)

    def _assert_decision_ready(self, launch_id: str, operator: TrustedOperator) -> None:
        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            workflow = _latest_workflow(session, launch)
            if (
                workflow is None
                or workflow.status != DecisionWorkflowStatus.AWAITING_DECISION_APPROVAL.value
            ):
                status = workflow.status if workflow is not None else "missing"
                raise ProductError(
                    "workflow_failed",
                    f"Decision workflow stopped at {status}. No decision was invented.",
                )

        self._write(work)

    def _assert_materials_ready(self, launch_id: str, operator: TrustedOperator) -> None:
        def work(session: Session) -> None:
            launch = _launch(session, launch_id)
            _authorize(session, launch, operator)
            workflow = session.scalar(
                select(ProductionWorkflowModel)
                .where(
                    ProductionWorkflowModel.organization_id == launch.organization_id,
                    ProductionWorkflowModel.business_id == launch.business_id,
                    ProductionWorkflowModel.launch_id == launch.id,
                )
                .order_by(ProductionWorkflowModel.created_at.desc())
            )
            ready = ProductionWorkflowStatus.READY_FOR_ACTION_PROPOSAL.value
            if workflow is None or workflow.status != ready:
                status = workflow.status if workflow is not None else "missing"
                raise ProductError(
                    "workflow_failed",
                    f"Production workflow stopped at {status}. No asset was invented.",
                )

        self._write(work)

    def _write(self, work: Callable[[Session], _T]) -> _T:
        session = self._runtime.session_factory()
        try:
            with session.begin():
                return work(session)
        finally:
            session.close()


def _facts(session: Session, launch: LaunchModel, *, adapting: bool) -> LaunchScriptFacts:
    source = session.scalar(
        select(SourceRecordModel).where(
            SourceRecordModel.organization_id == launch.organization_id,
            SourceRecordModel.business_id == launch.business_id,
            SourceRecordModel.external_id == f"goal-{launch.id}",
        )
    )
    if source is None:
        raise ProductError("workflow_failed", "Launch goal evidence is missing.")
    evidence = session.scalar(
        select(EvidenceModel).where(
            EvidenceModel.organization_id == launch.organization_id,
            EvidenceModel.business_id == launch.business_id,
            EvidenceModel.source_record_id == source.id,
        )
    )
    if evidence is None:
        raise ProductError("workflow_failed", "Launch goal evidence is missing.")
    intent_source = session.scalar(
        select(SourceRecordModel).where(
            SourceRecordModel.organization_id == launch.organization_id,
            SourceRecordModel.business_id == launch.business_id,
            SourceRecordModel.external_id == f"intent-{launch.id}",
        )
    )
    payload = intent_source.payload if intent_source is not None else {}
    goal = payload.get("goal")
    offer = payload.get("offer_name")
    audience = payload.get("audience")
    revision = session.scalar(
        select(SourceRecordModel.id).where(
            SourceRecordModel.organization_id == launch.organization_id,
            SourceRecordModel.business_id == launch.business_id,
            SourceRecordModel.source_type == "owner_revision",
        )
    )
    return LaunchScriptFacts(
        evidence_id=evidence.id,
        evidence_status=EpistemicStatus(evidence.status),
        goal=goal if isinstance(goal, str) else "UNKNOWN",
        offer_name=offer if isinstance(offer, str) else "UNKNOWN",
        audience=audience if isinstance(audience, str) else None,
        revision_requested=revision is not None,
        adapting_without_measurement=adapting,
        revision_note=_revision_note(session, launch),
    )


def _revision_note(session: Session, launch: LaunchModel) -> str:
    sources = session.scalars(
        select(SourceRecordModel)
        .where(
            SourceRecordModel.organization_id == launch.organization_id,
            SourceRecordModel.business_id == launch.business_id,
            SourceRecordModel.source_type == "owner_revision",
        )
        .order_by(SourceRecordModel.ingested_at)
    ).all()
    note = ""
    for source in sources:
        payload = source.payload if isinstance(source.payload, dict) else {}
        if payload.get("launch_id") != launch.id:
            continue
        evidence = session.scalar(
            select(EvidenceModel).where(
                EvidenceModel.organization_id == launch.organization_id,
                EvidenceModel.business_id == launch.business_id,
                EvidenceModel.source_record_id == source.id,
            )
        )
        if evidence is not None and evidence.statement.strip():
            note = evidence.statement.strip()
    return note


def _authorize(session: Session, launch: LaunchModel, operator: TrustedOperator) -> None:
    try:
        operator.scope.assert_matches(
            organization_id=launch.organization_id,
            business_id=launch.business_id,
        )
    except TenantScopeViolation as exc:
        raise ProductError(
            "scope_violation",
            "This launch is not in the requested business.",
        ) from exc
    _assert_owner(session, launch, operator.user_id)


def _launch(session: Session, launch_id: str) -> LaunchModel:
    launch = session.get(LaunchModel, launch_id)
    if launch is None:
        raise ProductError("not_found", "Launch not found")
    return launch


def _latest_workflow(session: Session, launch: LaunchModel) -> DecisionWorkflowModel | None:
    return session.scalar(
        select(DecisionWorkflowModel)
        .where(
            DecisionWorkflowModel.organization_id == launch.organization_id,
            DecisionWorkflowModel.business_id == launch.business_id,
            DecisionWorkflowModel.launch_id == launch.id,
        )
        .order_by(DecisionWorkflowModel.created_at.desc())
    )


def _events(session: Session, launch: LaunchModel, event_type: str) -> list[BusinessEventModel]:
    rows = session.scalars(
        select(BusinessEventModel).where(
            BusinessEventModel.organization_id == launch.organization_id,
            BusinessEventModel.business_id == launch.business_id,
            BusinessEventModel.event_type == event_type,
        )
    ).all()
    return [row for row in rows if row.payload.get("launch_id") == launch.id]


def _unconsumed(session: Session, launch: LaunchModel, event_type: str) -> bool:
    return any(
        not event.payload.get("consumed_by_workflow_id")
        for event in _events(session, launch, event_type)
    )


def _context(launch: LaunchModel, actor_user_id: str) -> CommandContext:
    return CommandContext(
        organization_id=launch.organization_id,
        business_id=launch.business_id,
        actor_user_id=actor_user_id,
        correlation_id=new_id(),
    )


def _assert_owner(session: Session, launch: LaunchModel, user_id: str) -> None:
    membership = session.scalar(
        select(BusinessMembershipModel).where(
            BusinessMembershipModel.organization_id == launch.organization_id,
            BusinessMembershipModel.business_id == launch.business_id,
            BusinessMembershipModel.user_id == user_id,
        )
    )
    if membership is None or membership.role.upper() != "OWNER":
        raise ProductError("owner_required", "Only the business owner can do that.")


def _metric_count(session: Session, launch: LaunchModel) -> int:
    value = session.scalar(
        select(MetricVersionModel.id).where(
            MetricVersionModel.organization_id == launch.organization_id,
            MetricVersionModel.business_id == launch.business_id,
        )
    )
    return 0 if value is None else 1


def _require_text(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProductError("invalid_input", f"{field} is required.")


def _reject_worth(field: str, value: str) -> None:
    if _contains_human_worth_violation({field: value}) or any(
        marker in value.lower() for marker in _WORTH_MARKERS
    ):
        raise ProductError(
            "constitutional_boundary",
            "Launch OS will not treat business performance as a judgment of a person.",
        )


def _data_note(prefix: str, note: str) -> str:
    compact = " ".join(note.split())
    if any(marker in compact.lower() for marker in _COMMAND_MARKERS):
        return f"{prefix} was recorded. A request to publish or execute was ignored."
    if len(compact) > 280:
        compact = compact[:277] + "..."
    return f"{prefix} (data, not permission to publish): {compact}"
