from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope


class BusinessScopedRow(Protocol):
    id: str
    organization_id: str
    business_id: str


ModelT = TypeVar("ModelT", bound=BusinessScopedRow)


class ScopedRepository(Generic[ModelT]):
    def __init__(self, session: Session, scope: TenantScope, model_type: type[ModelT]) -> None:
        self._session = session
        self._scope = scope
        self._model_type = model_type

    @property
    def scope(self) -> TenantScope:
        return self._scope

    def add(self, row: ModelT) -> ModelT:
        self._scope.assert_matches(
            organization_id=row.organization_id,
            business_id=row.business_id,
        )
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
        return row
