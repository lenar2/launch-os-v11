from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.application.decision_governance import _contains_human_worth_violation
from launch_os_v11.domain.enums import ControllerVerdict
from launch_os_v11.persistence.models import AssetVersionModel, EvidenceModel
from launch_os_v11.persistence.production_models import (
    AssetReviewModel,
    AssetVersionCreatorModel,
    ProductionWorkflowModel,
)
from launch_os_v11.production.registry import REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
from launch_os_v11.production.support import _rights_for_version, _scope
from launch_os_v11.runtime.errors import TransientJobError


def governed_asset_outcome(
    session: Session,
    *,
    workflow: ProductionWorkflowModel,
    asset_version: AssetVersionModel,
    reviews: tuple[AssetReviewModel, ...],
) -> ControllerVerdict:
    expected = {
        key.removeprefix("ai.controller.asset_")
        for key in REQUIRED_ASSET_CONTROLLER_CONTRACT_KEYS
    }
    present = {review.controller_type for review in reviews}
    missing = expected - present
    if missing:
        raise TransientJobError(
            f"required asset controllers not ready: {', '.join(sorted(missing))}"
        )

    body_payload = {"body": asset_version.body}
    if _contains_human_worth_violation(body_payload):
        return ControllerVerdict.BLOCK
    if _contains_hard_manipulation(asset_version.body):
        return ControllerVerdict.BLOCK
    if _has_unsupported_claims(session, workflow, asset_version):
        return ControllerVerdict.REVISE
    if not _rights_are_complete(session, workflow, asset_version):
        return ControllerVerdict.REVISE

    verdicts = {ControllerVerdict(review.verdict) for review in reviews}
    if ControllerVerdict.BLOCK in verdicts:
        return ControllerVerdict.BLOCK
    if ControllerVerdict.REVISE in verdicts:
        return ControllerVerdict.REVISE
    conditional = [
        review
        for review in reviews
        if ControllerVerdict(review.verdict) == ControllerVerdict.PASS_WITH_CONDITIONS
    ]
    if any(_mandatory_conditions(review) for review in conditional):
        return ControllerVerdict.PASS_WITH_CONDITIONS
    return ControllerVerdict.PASS


def _has_unsupported_claims(
    session: Session,
    workflow: ProductionWorkflowModel,
    asset_version: AssetVersionModel,
) -> bool:
    provenance = asset_version.provenance or {}
    inventory_value = provenance.get("claim_inventory", [])
    inventory = inventory_value if isinstance(inventory_value, list) else []
    declared_refs = {
        item.get("evidence_ref")
        for item in inventory
        if isinstance(item, dict) and isinstance(item.get("evidence_ref"), str)
    }
    for item in inventory:
        if not isinstance(item, dict):
            return True
        claim_type = item.get("claim_type")
        evidence_ref = item.get("evidence_ref")
        if claim_type in {"FACTUAL", "QUANTITATIVE", "TESTIMONIAL", "RESULT"}:
            if not isinstance(evidence_ref, str):
                return True
            evidence = session.get(EvidenceModel, evidence_ref)
            if evidence is None:
                return True
            try:
                _scope(workflow).assert_matches(
                    organization_id=evidence.organization_id,
                    business_id=evidence.business_id,
                )
            except Exception:
                return True
    lowered = asset_version.body.lower()
    risky_markers = ("guaranteed", "guarantee", "100%", "testimonial", "everyone gets")
    return any(marker in lowered for marker in risky_markers) and not declared_refs


def _rights_are_complete(
    session: Session,
    workflow: ProductionWorkflowModel,
    asset_version: AssetVersionModel,
) -> bool:
    rights = _rights_for_version(session, asset_version.id)
    creator = session.scalar(
        select(AssetVersionCreatorModel).where(
            AssetVersionCreatorModel.asset_version_id == asset_version.id
        )
    )
    if rights is None or creator is None:
        return False
    if creator.creator_type != "AGENT" or creator.created_by_agent_run_id is None:
        return False
    if rights.origin == "GENERATED":
        return rights.generated_by_agent_run_id == creator.created_by_agent_run_id
    if rights.origin in {"USER_PROVIDED", "LICENSED", "DERIVED"}:
        return bool(rights.permission_scope)
    return False


def _contains_hard_manipulation(body: str) -> bool:
    lowered = body.lower()
    hard_phrases = (
        "if you don't buy",
        "if you do not buy",
        "you are not ready",
        "you'll regret",
        "you will regret",
        "only worthy people",
        "prove your worth",
    )
    return any(phrase in lowered for phrase in hard_phrases)


def _mandatory_conditions(review: AssetReviewModel) -> tuple[str, ...]:
    values = [*(review.conditions or []), *(review.required_changes or [])]
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
