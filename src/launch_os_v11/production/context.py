from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.context import (
    ContextBuilder,
    ContextItem,
    ContextReference,
)
from launch_os_v11.domain.enums import EpistemicStatus, SourceTrust
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    AssetVersionModel,
    CreativeBriefModel,
    DecisionModel,
)
from launch_os_v11.persistence.production_models import (
    AssetReviewModel,
    AssetRightsProvenanceModel,
    ContentStrategyModel,
)
from launch_os_v11.runtime.security import assert_no_secrets


class ProductionContextBuilder(ContextBuilder):
    """Extend the governed ContextBuilder with Phase 4 domain projections."""

    def _load_reference(
        self,
        *,
        session: Session,
        scope: TenantScope,
        reference: ContextReference,
    ) -> ContextItem | None:
        if reference.object_type == "decision":
            decision = session.get(DecisionModel, reference.object_id)
            if decision is None:
                return None
            scope.assert_matches(
                organization_id=decision.organization_id,
                business_id=decision.business_id,
            )
            return _item(
                scope=scope,
                object_type="decision",
                object_id=decision.id,
                content=decision.selected_action,
                projection={
                    "version": decision.version,
                    "status": decision.status,
                    "goal_problem": decision.goal_problem,
                    "selected_action": decision.selected_action,
                    "expected_effect": decision.expected_effect,
                    "risk_class": decision.risk_class,
                    "required_assets": list(decision.required_assets or []),
                    "required_actions": list(decision.required_actions or []),
                    "experiment_proposal": dict(decision.experiment_proposal or {}),
                    "evidence_ids": list(decision.evidence_ids or []),
                },
                epistemic_status=EpistemicStatus.OBSERVATION,
                recorded_at=decision.updated_at,
            )
        if reference.object_type == "content_strategy":
            strategy = session.get(ContentStrategyModel, reference.object_id)
            if strategy is None:
                return None
            scope.assert_matches(
                organization_id=strategy.organization_id,
                business_id=strategy.business_id,
            )
            return _item(
                scope=scope,
                object_type="content_strategy",
                object_id=strategy.id,
                content=_json_content(strategy.payload),
                projection={
                    "decision_id": strategy.decision_id,
                    "snapshot_id": strategy.snapshot_id,
                    "payload": strategy.payload,
                    "evidence_refs": strategy.evidence_refs,
                },
                epistemic_status=EpistemicStatus.OBSERVATION,
                recorded_at=strategy.created_at,
            )
        if reference.object_type == "creative_brief":
            brief = session.get(CreativeBriefModel, reference.object_id)
            if brief is None:
                return None
            scope.assert_matches(
                organization_id=brief.organization_id,
                business_id=brief.business_id,
            )
            return _item(
                scope=scope,
                object_type="creative_brief",
                object_id=brief.id,
                content=f"{brief.title}: {brief.objective}",
                projection={
                    "decision_id": brief.decision_id,
                    "title": brief.title,
                    "objective": brief.objective,
                    "constraints": list(brief.constraints or []),
                },
                epistemic_status=EpistemicStatus.OBSERVATION,
                recorded_at=brief.updated_at,
            )
        if reference.object_type == "asset_version":
            version = session.get(AssetVersionModel, reference.object_id)
            if version is None:
                return None
            scope.assert_matches(
                organization_id=version.organization_id,
                business_id=version.business_id,
            )
            return _item(
                scope=scope,
                object_type="asset_version",
                object_id=version.id,
                content=version.body,
                projection={
                    "asset_id": version.asset_id,
                    "version_number": version.version_number,
                    "provenance": version.provenance,
                },
                epistemic_status=EpistemicStatus.OBSERVATION,
                recorded_at=version.created_at,
            )
        if reference.object_type == "asset_review":
            review = session.get(AssetReviewModel, reference.object_id)
            if review is None:
                return None
            scope.assert_matches(
                organization_id=review.organization_id,
                business_id=review.business_id,
            )
            return _item(
                scope=scope,
                object_type="asset_review",
                object_id=review.id,
                content=review.reason,
                projection={
                    "asset_version_id": review.asset_version_id,
                    "controller_type": review.controller_type,
                    "verdict": review.verdict,
                    "issues": review.issues,
                    "required_changes": review.required_changes,
                    "conditions": review.conditions,
                },
                epistemic_status=EpistemicStatus.OBSERVATION,
                recorded_at=review.created_at,
            )
        if reference.object_type == "asset_rights_provenance":
            rights = session.get(AssetRightsProvenanceModel, reference.object_id)
            if rights is None:
                return None
            scope.assert_matches(
                organization_id=rights.organization_id,
                business_id=rights.business_id,
            )
            return _item(
                scope=scope,
                object_type="asset_rights_provenance",
                object_id=rights.id,
                content=f"origin={rights.origin}; permission_scope={rights.permission_scope}",
                projection={
                    "asset_version_id": rights.asset_version_id,
                    "origin": rights.origin,
                    "generated_by_agent_run_id": rights.generated_by_agent_run_id,
                    "related_source_asset_ids": rights.related_source_asset_ids,
                    "permission_scope": rights.permission_scope,
                    "customer_content_consent_ref": rights.customer_content_consent_ref,
                    "publication_restrictions": rights.publication_restrictions,
                },
                epistemic_status=EpistemicStatus.FACT,
                recorded_at=rights.created_at,
            )
        return super()._load_reference(
            session=session,
            scope=scope,
            reference=reference,
        )


def _item(
    *,
    scope: TenantScope,
    object_type: str,
    object_id: str,
    content: str,
    projection: dict[str, object],
    epistemic_status: EpistemicStatus,
    recorded_at: datetime,
) -> ContextItem:
    assert_no_secrets(content)
    assert_no_secrets(projection)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type=object_type,
        source_object_id=object_id,
        provenance_ref=f"{object_type}:{object_id}",
        epistemic_status=epistemic_status,
        trust_class=SourceTrust.INTERNAL_SYSTEM,
        data_boundary="TRUSTED_INTERNAL_DATA",
        occurred_at=None,
        recorded_at=recorded_at,
        content=content[:600],
        structured_projection=projection,
    )


def _json_content(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)[:600]
