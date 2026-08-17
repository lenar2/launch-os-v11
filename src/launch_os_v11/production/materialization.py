from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.schemas import (
    AssetDraftProposal,
    ContentStrategyProposal,
    ControllerReviewOutput,
)
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.time import utc_now
from launch_os_v11.persistence.models import (
    AgentDefinitionModel,
    AssetModel,
    AssetVersionModel,
    CreativeBriefModel,
)
from launch_os_v11.persistence.production_models import (
    AssetReviewModel,
    AssetRightsProvenanceModel,
    AssetVersionCreatorModel,
    ContentStrategyModel,
    CreativeBriefDetailModel,
    ProductionWorkflowModel,
)
from launch_os_v11.production.registry import REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
from launch_os_v11.production.support import (
    _agent_run_by_idempotency,
    _asset_version,
    _decision,
    _next_asset_version_number,
    _validate_evidence_refs,
    _validated_output,
)
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets

ASSET_TYPE_TELEGRAM_POST_COPY = "TELEGRAM_POST_COPY"


def _materialize_content_strategy(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> ContentStrategyModel:
    existing = session.scalar(
        select(ContentStrategyModel).where(ContentStrategyModel.workflow_id == workflow.id)
    )
    if existing is not None:
        return existing
    run = _agent_run_by_idempotency(
        session,
        workflow,
        f"production_workflow:{workflow.id}:content_strategy",
    )
    output = _validated_output(run, ContentStrategyProposal, "content strategy")
    _validate_evidence_refs(session, workflow, output.evidence_refs)
    if run.context_hash is None:
        raise PermanentJobError("content strategy run missing context hash")
    row = ContentStrategyModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        workflow_id=workflow.id,
        decision_id=workflow.decision_id,
        snapshot_id=workflow.snapshot_id,
        agent_run_id=run.id,
        schema_version=output.schema_version,
        payload=output.model_dump(mode="json"),
        evidence_refs=[item.model_dump(mode="json") for item in output.evidence_refs],
        context_hash=run.context_hash,
        context_manifest=dict(run.context_manifest or {}),
        correlation_id=workflow.correlation_id,
        causation_id=run.id,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _materialize_creative_brief(
    session: Session,
    workflow: ProductionWorkflowModel,
    strategy: ContentStrategyModel,
) -> CreativeBriefModel:
    existing_detail = session.scalar(
        select(CreativeBriefDetailModel).where(
            CreativeBriefDetailModel.workflow_id == workflow.id
        )
    )
    if existing_detail is not None:
        brief = session.get(CreativeBriefModel, existing_detail.creative_brief_id)
        if brief is None:
            raise PermanentJobError("CreativeBrief detail points to missing brief")
        return brief
    proposal = ContentStrategyProposal.model_validate(strategy.payload)
    brief = CreativeBriefModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        decision_id=workflow.decision_id,
        title="Telegram launch post",
        objective=proposal.objective,
        constraints=[
            *proposal.brand_constraints,
            *proposal.production_constraints,
            *[
                f"unsupported claim: {value}"
                for value in proposal.forbidden_or_unsupported_claims
            ],
        ],
    )
    session.add(brief)
    session.flush()
    detail_payload = {
        "audience": proposal.audience,
        "channel_format": proposal.channel_format,
        "content_job": proposal.content_job,
        "core_message": proposal.core_message,
        "angle": proposal.angle,
        "message_mechanism": proposal.message_mechanism,
        "tone": proposal.tone,
        "cta": proposal.cta_intent,
        "evidence_refs": [item.model_dump(mode="json") for item in proposal.evidence_refs],
        "allowed_claims": proposal.allowed_claims,
        "claim_constraints": proposal.forbidden_or_unsupported_claims,
        "brand_constraints": proposal.brand_constraints,
        "production_requirements": proposal.production_constraints,
        "experiment_binding": _decision(session, workflow).experiment_proposal,
        "rights_restrictions": [],
    }
    assert_no_secrets(detail_payload)
    detail = CreativeBriefDetailModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        workflow_id=workflow.id,
        creative_brief_id=brief.id,
        content_strategy_id=strategy.id,
        snapshot_id=workflow.snapshot_id,
        payload=detail_payload,
        correlation_id=workflow.correlation_id,
        causation_id=strategy.id,
        created_at=utc_now(),
    )
    session.add(detail)
    session.flush()
    return brief


def _materialize_asset_version(
    session: Session,
    workflow: ProductionWorkflowModel,
) -> AssetVersionModel:
    version_number = _next_asset_version_number(session, workflow)
    existing = _asset_version(session, workflow, version_number)
    if existing is not None:
        return existing
    run = _agent_run_by_idempotency(
        session,
        workflow,
        f"production_workflow:{workflow.id}:asset:v{version_number}",
    )
    output = _validated_output(run, AssetDraftProposal, "asset draft")
    _validate_evidence_refs(session, workflow, output.evidence_refs)
    asset = _ensure_asset(session, workflow)
    provenance = {
        "schema_name": "AssetVersionProvenance",
        "schema_version": 1,
        "origin": output.rights.origin,
        "writer_agent_run_id": run.id,
        "claim_inventory": [
            item.model_dump(mode="json") for item in output.claim_inventory
        ],
        "evidence_refs": [item.model_dump(mode="json") for item in output.evidence_refs],
        "content_notes": list(output.content_notes),
    }
    assert_no_secrets(provenance)
    version = AssetVersionModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        asset_id=asset.id,
        version_number=version_number,
        body=output.body,
        created_by_user_id=None,
        provenance=provenance,
        created_at=utc_now(),
    )
    session.add(version)
    session.flush()
    creator = AssetVersionCreatorModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        asset_version_id=version.id,
        creator_type="AGENT",
        created_by_user_id=None,
        created_by_agent_run_id=run.id,
        created_at=utc_now(),
    )
    session.add(creator)
    rights = AssetRightsProvenanceModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        asset_version_id=version.id,
        origin=output.rights.origin,
        generated_by_agent_run_id=run.id if output.rights.origin == "GENERATED" else None,
        model_provider=run.provider_name,
        model_name=run.provider_model,
        related_source_asset_ids=list(output.rights.related_source_asset_ids),
        permission_scope=output.rights.permission_scope,
        customer_content_consent_ref=output.rights.customer_content_consent_ref,
        publication_restrictions=list(output.rights.publication_restrictions),
        license_expires_at=None,
        provenance={
            "writer_agent_run_id": run.id,
            "rights_declaration": output.rights.model_dump(mode="json"),
        },
        created_at=utc_now(),
    )
    session.add(rights)
    workflow.asset_id = asset.id
    workflow.final_asset_version_id = version.id
    session.flush()
    return version


def _materialize_asset_reviews(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    asset_version: AssetVersionModel,
) -> tuple[AssetReviewModel, ...]:
    rows: list[AssetReviewModel] = []
    for contract_key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS:
        controller_type = contract_key.removeprefix("ai.controller.asset_")
        existing = session.scalar(
            select(AssetReviewModel).where(
                AssetReviewModel.asset_version_id == asset_version.id,
                AssetReviewModel.controller_type == controller_type,
            )
        )
        if existing is not None:
            rows.append(existing)
            continue
        run = _agent_run_by_idempotency(
            session,
            workflow,
            (
                f"production_workflow:{workflow.id}:asset:"
                f"{asset_version.version_number}:{contract_key}"
            ),
        )
        output = _validated_output(run, ControllerReviewOutput, "asset controller")
        if output.controller_type != controller_type:
            raise PermanentJobError(
                "asset controller output type does not match registered contract"
            )
        _validate_evidence_refs(session, workflow, output.evidence_refs)
        definition = session.get(AgentDefinitionModel, run.agent_definition_id)
        if definition is None or run.context_hash is None:
            raise PermanentJobError("asset controller run missing durable contract trace")
        conditions = (
            list(output.required_changes)
            if output.verdict == ControllerVerdict.PASS_WITH_CONDITIONS
            else []
        )
        row = AssetReviewModel(
            id=new_id(),
            organization_id=workflow.organization_id,
            business_id=workflow.business_id,
            workflow_id=workflow.id,
            asset_version_id=asset_version.id,
            agent_run_id=run.id,
            controller_type=controller_type,
            verdict=output.verdict.value,
            reason="; ".join(output.issues) or output.verdict.value,
            severity=output.severity.value,
            issues=list(output.issues),
            required_changes=list(output.required_changes),
            conditions=conditions,
            evidence_refs=[
                item.model_dump(mode="json") for item in output.evidence_refs
            ],
            contract_key=run.agent_contract_key,
            contract_version=run.agent_contract_version,
            instruction_version=definition.instruction_version,
            output_schema_version=run.output_schema_version,
            context_hash=run.context_hash,
            context_manifest=dict(run.context_manifest or {}),
            correlation_id=workflow.correlation_id,
            causation_id=asset_version.id,
            created_at=utc_now(),
        )
        session.add(row)
        session.flush()
        rows.append(row)
    return tuple(rows)


def _ensure_asset(session: Session, workflow: ProductionWorkflowModel) -> AssetModel:
    if workflow.asset_id is not None:
        asset = session.get(AssetModel, workflow.asset_id)
        if asset is None:
            raise PermanentJobError("ProductionWorkflow asset binding is broken")
        return asset
    if workflow.creative_brief_id is None:
        raise PermanentJobError("CreativeBrief missing before Asset creation")
    asset = AssetModel(
        id=new_id(),
        organization_id=workflow.organization_id,
        business_id=workflow.business_id,
        creative_brief_id=workflow.creative_brief_id,
        asset_type=ASSET_TYPE_TELEGRAM_POST_COPY,
        title="Telegram launch post",
    )
    session.add(asset)
    session.flush()
    workflow.asset_id = asset.id
    return asset
