from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence import models


class BusinessScopedRow(Protocol):
    id: str
    organization_id: str
    business_id: str


ModelT = TypeVar("ModelT")


class ScopedRepository(Generic[ModelT]):
    def __init__(self, session: Session, scope: TenantScope, model_type: type[ModelT]) -> None:
        self._session = session
        self._scope = scope
        self._model_type = model_type

    @property
    def scope(self) -> TenantScope:
        return self._scope

    def add(self, row: ModelT) -> ModelT:
        scoped_row = cast(BusinessScopedRow, row)
        self._scope.assert_matches(
            organization_id=scoped_row.organization_id,
            business_id=scoped_row.business_id,
        )
        _validate_business_references(self._session, self._scope, scoped_row)
        self._session.add(row)
        return row

    def get(self, row_id: str) -> ModelT | None:
        model = cast(Any, self._model_type)
        statement = select(self._model_type).where(
            model.id == row_id,
            model.organization_id == self._scope.organization_id,
            model.business_id == self._scope.business_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def require(self, row_id: str) -> ModelT:
        row = self.get(row_id)
        if row is None:
            msg = f"{self._model_type.__name__} is not visible in the current tenant scope"
            raise TenantScopeViolation(msg)
        return row

    def update_fields(self, row_id: str, **fields: Any) -> ModelT:
        row = self.require(row_id)
        for key, value in fields.items():
            if key in {"organization_id", "business_id", "id"}:
                msg = f"cannot update scoped identity field {key}"
                raise TenantScopeViolation(msg)
            setattr(row, key, value)
        _validate_business_references(self._session, self._scope, cast(BusinessScopedRow, row))
        return row

    def delete(self, row_id: str) -> None:
        row = self.require(row_id)
        self._session.delete(row)


class AppendOnlyScopedRepository(Generic[ModelT]):
    def __init__(self, session: Session, scope: TenantScope, model_type: type[ModelT]) -> None:
        self._session = session
        self._scope = scope
        self._model_type = model_type

    @property
    def scope(self) -> TenantScope:
        return self._scope

    def add(self, row: ModelT) -> ModelT:
        scoped_row = cast(BusinessScopedRow, row)
        self._scope.assert_matches(
            organization_id=scoped_row.organization_id,
            business_id=scoped_row.business_id,
        )
        _validate_business_references(self._session, self._scope, scoped_row)
        self._session.add(row)
        return row

    def get(self, row_id: str) -> ModelT | None:
        model = cast(Any, self._model_type)
        statement = select(self._model_type).where(
            model.id == row_id,
            model.organization_id == self._scope.organization_id,
            model.business_id == self._scope.business_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def require(self, row_id: str) -> ModelT:
        row = self.get(row_id)
        if row is None:
            msg = f"{self._model_type.__name__} is not visible in the current tenant scope"
            raise TenantScopeViolation(msg)
        return row


BusinessSnapshotRepository = AppendOnlyScopedRepository[models.BusinessSnapshotModel]
AssetVersionRepository = AppendOnlyScopedRepository[models.AssetVersionModel]
ApprovalRepository = AppendOnlyScopedRepository[models.ApprovalModel]
BusinessEventRepository = AppendOnlyScopedRepository[models.BusinessEventModel]
AuditLogRepository = AppendOnlyScopedRepository[models.AuditLogModel]
OutboxEventRepository = AppendOnlyScopedRepository[models.OutboxEventModel]


def _is_reference_visible(
    session: Session,
    scope: TenantScope,
    referenced_model: type[Any],
    referenced_id: str,
) -> bool:
    session.flush()
    model = cast(Any, referenced_model)
    statement = select(model.id).where(
        model.id == referenced_id,
        model.organization_id == scope.organization_id,
        model.business_id == scope.business_id,
    )
    return session.execute(statement).scalar_one_or_none() is not None


def _validate_business_references(
    session: Session,
    scope: TenantScope,
    row: BusinessScopedRow,
) -> None:
    for field_name, referenced_model in _REFERENCE_POLICY.get(type(row), ()):
        referenced_id = getattr(row, field_name, None)
        if referenced_id is None:
            continue
        if not _is_reference_visible(session, scope, referenced_model, referenced_id):
            msg = (
                f"{type(row).__name__}.{field_name} references an object outside "
                "the current tenant/business scope"
            )
            raise TenantScopeViolation(msg)


_REFERENCE_POLICY: dict[type[object], tuple[tuple[str, type[Any]], ...]] = {
    models.OfferModel: (("product_id", models.ProductModel),),
    models.EvidenceModel: (("source_record_id", models.SourceRecordModel),),
    models.LaunchModel: (
        ("campaign_id", models.CampaignModel),
        ("offer_id", models.OfferModel),
        ("goal_id", models.GoalModel),
        ("channel_id", models.ChannelModel),
        ("snapshot_id", models.BusinessSnapshotModel),
    ),
    models.LaunchPhaseModel: (("launch_id", models.LaunchModel),),
    models.DecisionModel: (
        ("snapshot_id", models.BusinessSnapshotModel),
        ("supersedes_decision_id", models.DecisionModel),
        ("source_candidate_id", models.DecisionCandidateModel),
    ),
    models.DecisionAlternativeModel: (("decision_id", models.DecisionModel),),
    models.ControllerReviewModel: (
        ("decision_id", models.DecisionModel),
        ("asset_version_id", models.AssetVersionModel),
        ("decision_candidate_id", models.DecisionCandidateModel),
        ("agent_run_id", models.AgentRunModel),
        ("snapshot_id", models.BusinessSnapshotModel),
    ),
    models.DecisionWorkflowModel: (
        ("launch_id", models.LaunchModel),
        ("snapshot_id", models.BusinessSnapshotModel),
        ("final_decision_id", models.DecisionModel),
        ("final_approval_id", models.DecisionApprovalModel),
    ),
    models.SpecialistContributionModel: (
        ("workflow_id", models.DecisionWorkflowModel),
        ("snapshot_id", models.BusinessSnapshotModel),
        ("agent_run_id", models.AgentRunModel),
    ),
    models.DecisionCandidateModel: (
        ("workflow_id", models.DecisionWorkflowModel),
        ("snapshot_id", models.BusinessSnapshotModel),
        ("chief_agent_run_id", models.AgentRunModel),
        ("previous_candidate_id", models.DecisionCandidateModel),
    ),
    models.ExperimentModel: (
        ("decision_id", models.DecisionModel),
        ("hypothesis_id", models.HypothesisModel),
    ),
    models.ExperimentRuleModel: (("experiment_id", models.ExperimentModel),),
    models.ExperimentResultModel: (("experiment_id", models.ExperimentModel),),
    models.CreativeBriefModel: (("decision_id", models.DecisionModel),),
    models.AssetModel: (("creative_brief_id", models.CreativeBriefModel),),
    models.AssetVersionModel: (("asset_id", models.AssetModel),),
    models.PublicationModel: (
        ("asset_version_id", models.AssetVersionModel),
        ("channel_id", models.ChannelModel),
    ),
    models.ApprovalModel: (("action_id", models.ActionModel),),
    models.DecisionApprovalModel: (
        ("workflow_id", models.DecisionWorkflowModel),
        ("decision_id", models.DecisionModel),
        ("candidate_id", models.DecisionCandidateModel),
    ),
    models.ExecutionModel: (
        ("action_id", models.ActionModel),
        ("approval_id", models.ApprovalModel),
    ),
    models.BusinessEventModel: (("source_record_id", models.SourceRecordModel),),
    models.AgentRunModel: (
        ("agent_definition_id", models.AgentDefinitionModel),
        ("job_id", models.JobModel),
    ),
    models.LearningModel: (
        ("decision_id", models.DecisionModel),
        ("experiment_id", models.ExperimentModel),
    ),
}
