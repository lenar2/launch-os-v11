from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.contracts import AgentContract, JsonObject
from launch_os_v11.ai_runtime.errors import AIContextError
from launch_os_v11.domain.enums import EpistemicStatus, SourceTrust
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import (
    BusinessModel,
    ConstraintModel,
    EvidenceModel,
    GoalModel,
    SourceRecordModel,
)
from launch_os_v11.runtime.security import assert_no_secrets


class ContextReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: str = Field(min_length=1)
    object_id: str = Field(min_length=1)


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: str
    business_id: str
    source_object_type: str
    source_object_id: str
    provenance_ref: str
    epistemic_status: EpistemicStatus
    trust_class: SourceTrust
    data_boundary: Literal["TRUSTED_INTERNAL_DATA", "UNTRUSTED_DATA"]
    occurred_at: datetime | None
    recorded_at: datetime | None
    content: str
    structured_projection: JsonObject = Field(default_factory=dict)
    sensitivity: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"] = "INTERNAL"
    retention: Literal["SHORT", "STANDARD", "AUDIT"] = "STANDARD"

    def manifest_entry(self) -> JsonObject:
        return {
            "organization_id": self.organization_id,
            "business_id": self.business_id,
            "source_object_type": self.source_object_type,
            "source_object_id": self.source_object_id,
            "provenance_ref": self.provenance_ref,
            "epistemic_status": self.epistemic_status.value,
            "trust_class": self.trust_class.value,
            "data_boundary": self.data_boundary,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "content_hash": _stable_hash(self.model_dump(mode="json")),
            "sensitivity": self.sensitivity,
            "retention": self.retention,
        }


@dataclass(frozen=True)
class ContextBundle:
    items: tuple[ContextItem, ...]
    manifest: JsonObject
    context_hash: str
    structured_context: str


@dataclass(frozen=True)
class ContextBudget:
    max_items: int = 20
    max_content_chars: int = 600


class ContextBuilder:
    def __init__(self, *, budget: ContextBudget | None = None) -> None:
        self._budget = budget or ContextBudget()

    def build(
        self,
        *,
        session: Session,
        scope: TenantScope,
        contract: AgentContract,
        requested_refs: tuple[ContextReference, ...] = (),
    ) -> ContextBundle:
        allowed = set(contract.allowed_context_types)
        items: list[ContextItem] = []
        if requested_refs:
            for reference in sorted(
                requested_refs,
                key=lambda item: (item.object_type, item.object_id),
            ):
                if reference.object_type not in allowed:
                    raise AIContextError(
                        f"context type not allowed for agent: {reference.object_type}"
                    )
                item = self._load_reference(session=session, scope=scope, reference=reference)
                if item is not None:
                    items.append(item)
        else:
            items.extend(self._collect_default_items(session=session, scope=scope, allowed=allowed))

        sorted_items = sorted(
            items,
            key=lambda item: (
                item.source_object_type,
                item.occurred_at.isoformat() if item.occurred_at else "",
                item.source_object_id,
            ),
        )
        limited_items = tuple(sorted_items[: self._budget.max_items])
        present_types = {item.source_object_type for item in limited_items}
        missing = set(contract.required_context_types) - present_types
        if missing:
            raise AIContextError(f"required context missing: {', '.join(sorted(missing))}")

        context_payload = {
            "schema_name": "AgentScopedContext",
            "schema_version": 1,
            "purpose": contract.contract_key,
            "items": [item.model_dump(mode="json") for item in limited_items],
        }
        assert_no_secrets(context_payload)
        context_hash = _stable_hash(context_payload)
        manifest_items = [item.manifest_entry() for item in limited_items]
        manifest: JsonObject = {
            "schema_name": "AgentContextManifest",
            "schema_version": 1,
            "purpose": contract.contract_key,
            "item_count": len(manifest_items),
            "items": manifest_items,
            "context_hash": context_hash,
        }
        assert_no_secrets(manifest)
        return ContextBundle(
            items=limited_items,
            manifest=manifest,
            context_hash=context_hash,
            structured_context=json.dumps(
                context_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )

    def _collect_default_items(
        self,
        *,
        session: Session,
        scope: TenantScope,
        allowed: set[str],
    ) -> list[ContextItem]:
        items: list[ContextItem] = []
        if "business" in allowed:
            business = session.get(BusinessModel, scope.business_id)
            if business is not None:
                scope.assert_matches(
                    organization_id=business.organization_id,
                    business_id=business.id,
                )
                items.append(_business_item(scope=scope, business=business))
        if "goal" in allowed:
            items.extend(
                _goal_item(scope=scope, goal=row)
                for row in session.scalars(
                    select(GoalModel)
                    .where(
                        GoalModel.organization_id == scope.organization_id,
                        GoalModel.business_id == scope.business_id,
                    )
                    .order_by(GoalModel.created_at, GoalModel.id)
                    .limit(self._budget.max_items)
                )
            )
        if "constraint" in allowed:
            items.extend(
                _constraint_item(scope=scope, constraint=row)
                for row in session.scalars(
                    select(ConstraintModel)
                    .where(
                        ConstraintModel.organization_id == scope.organization_id,
                        ConstraintModel.business_id == scope.business_id,
                    )
                    .order_by(ConstraintModel.created_at, ConstraintModel.id)
                    .limit(self._budget.max_items)
                )
            )
        if "source_record" in allowed:
            items.extend(
                _source_record_item(scope=scope, source_record=row, budget=self._budget)
                for row in session.scalars(
                    select(SourceRecordModel)
                    .where(
                        SourceRecordModel.organization_id == scope.organization_id,
                        SourceRecordModel.business_id == scope.business_id,
                    )
                    .order_by(SourceRecordModel.ingested_at, SourceRecordModel.id)
                    .limit(self._budget.max_items)
                )
            )
        if "evidence" in allowed:
            items.extend(
                _evidence_item(scope=scope, evidence=row, budget=self._budget)
                for row in session.scalars(
                    select(EvidenceModel)
                    .where(
                        EvidenceModel.organization_id == scope.organization_id,
                        EvidenceModel.business_id == scope.business_id,
                    )
                    .order_by(EvidenceModel.recorded_at, EvidenceModel.id)
                    .limit(self._budget.max_items)
                )
            )
        return items

    def _load_reference(
        self,
        *,
        session: Session,
        scope: TenantScope,
        reference: ContextReference,
    ) -> ContextItem | None:
        if reference.object_type == "business":
            business = session.get(BusinessModel, reference.object_id)
            if business is None:
                return None
            scope.assert_matches(organization_id=business.organization_id, business_id=business.id)
            return _business_item(scope=scope, business=business)
        if reference.object_type == "goal":
            goal = session.get(GoalModel, reference.object_id)
            if goal is None:
                return None
            scope.assert_matches(organization_id=goal.organization_id, business_id=goal.business_id)
            return _goal_item(scope=scope, goal=goal)
        if reference.object_type == "constraint":
            constraint = session.get(ConstraintModel, reference.object_id)
            if constraint is None:
                return None
            scope.assert_matches(
                organization_id=constraint.organization_id,
                business_id=constraint.business_id,
            )
            return _constraint_item(scope=scope, constraint=constraint)
        if reference.object_type == "source_record":
            source_record = session.get(SourceRecordModel, reference.object_id)
            if source_record is None:
                return None
            scope.assert_matches(
                organization_id=source_record.organization_id,
                business_id=source_record.business_id,
            )
            return _source_record_item(
                scope=scope,
                source_record=source_record,
                budget=self._budget,
            )
        if reference.object_type == "evidence":
            evidence = session.get(EvidenceModel, reference.object_id)
            if evidence is None:
                return None
            scope.assert_matches(
                organization_id=evidence.organization_id,
                business_id=evidence.business_id,
            )
            return _evidence_item(scope=scope, evidence=evidence, budget=self._budget)
        raise AIContextError(f"unsupported context type: {reference.object_type}")


def _business_item(*, scope: TenantScope, business: BusinessModel) -> ContextItem:
    content = f"Business name: {business.name}; timezone: {business.timezone}"
    assert_no_secrets(content)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type="business",
        source_object_id=business.id,
        provenance_ref=f"business:{business.id}",
        epistemic_status=EpistemicStatus.FACT,
        trust_class=SourceTrust.INTERNAL_SYSTEM,
        data_boundary="TRUSTED_INTERNAL_DATA",
        occurred_at=business.created_at,
        recorded_at=business.updated_at,
        content=content,
        structured_projection={
            "name": business.name,
            "timezone": business.timezone,
            "version": business.version,
        },
    )


def _goal_item(*, scope: TenantScope, goal: GoalModel) -> ContextItem:
    content = f"Goal: {goal.title}; target: {goal.target}"
    assert_no_secrets(content)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type="goal",
        source_object_id=goal.id,
        provenance_ref=f"goal:{goal.id}",
        epistemic_status=EpistemicStatus.FACT,
        trust_class=SourceTrust.INTERNAL_SYSTEM,
        data_boundary="TRUSTED_INTERNAL_DATA",
        occurred_at=goal.created_at,
        recorded_at=goal.updated_at,
        content=content,
        structured_projection={"title": goal.title, "metric": goal.metric},
    )


def _constraint_item(*, scope: TenantScope, constraint: ConstraintModel) -> ContextItem:
    content = f"Constraint category: {constraint.category}; rule: {constraint.rule}"
    assert_no_secrets(content)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type="constraint",
        source_object_id=constraint.id,
        provenance_ref=f"constraint:{constraint.id}",
        epistemic_status=EpistemicStatus.FACT,
        trust_class=SourceTrust.INTERNAL_SYSTEM,
        data_boundary="TRUSTED_INTERNAL_DATA",
        occurred_at=constraint.created_at,
        recorded_at=constraint.updated_at,
        content=content,
        structured_projection={"category": constraint.category},
    )


def _source_record_item(
    *,
    scope: TenantScope,
    source_record: SourceRecordModel,
    budget: ContextBudget,
) -> ContextItem:
    assert_no_secrets(source_record.payload)
    payload_text = json.dumps(source_record.payload, sort_keys=True, ensure_ascii=True)
    content = _truncate(payload_text, budget.max_content_chars)
    assert_no_secrets(content)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type="source_record",
        source_object_id=source_record.id,
        provenance_ref=f"source_record:{source_record.id}",
        epistemic_status=EpistemicStatus.OBSERVATION,
        trust_class=_trust(source_record.trust),
        data_boundary="UNTRUSTED_DATA",
        occurred_at=source_record.source_occurred_at,
        recorded_at=source_record.ingested_at,
        content=content,
        structured_projection={
            "provider": source_record.provider,
            "external_id": source_record.external_id,
            "source_type": source_record.source_type,
        },
        sensitivity="CONFIDENTIAL",
    )


def _evidence_item(
    *,
    scope: TenantScope,
    evidence: EvidenceModel,
    budget: ContextBudget,
) -> ContextItem:
    content = _truncate(evidence.statement, budget.max_content_chars)
    assert_no_secrets(content)
    return ContextItem(
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        source_object_type="evidence",
        source_object_id=evidence.id,
        provenance_ref=f"evidence:{evidence.id}",
        epistemic_status=EpistemicStatus(evidence.status),
        trust_class=SourceTrust.UNTRUSTED_EXTERNAL,
        data_boundary="UNTRUSTED_DATA",
        occurred_at=evidence.occurred_at,
        recorded_at=evidence.recorded_at,
        content=content,
        structured_projection={
            "source_record_id": evidence.source_record_id,
            "confidence": evidence.confidence,
        },
        sensitivity="CONFIDENTIAL",
    )


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _trust(value: str) -> SourceTrust:
    try:
        return SourceTrust(value)
    except ValueError:
        return SourceTrust.UNTRUSTED_EXTERNAL


def _stable_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
