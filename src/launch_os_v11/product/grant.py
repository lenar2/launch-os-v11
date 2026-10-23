"""Local client grant for one browser.

This is not a login and not a user id. The server mints a random secret, stores
only its hash, and returns the secret in an HttpOnly cookie. A launch id or a
field in the request does not select the owner.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import DateTime, String, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.domain.time import utc_now
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.projection import LaunchRoomView

CLIENT_COOKIE = "launch_room_client"
FORBIDDEN_CLIENT_FIELDS = frozenset(
    {
        "actor_user_id",
        "owner_user_id",
        "user_id",
        "grant",
        "client_grant",
        "token",
        "secret",
    }
)


class GrantBase(DeclarativeBase):
    pass


class ClientGrantModel(GrantBase):
    __tablename__ = "launch_room_client_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    launch_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def ensure_grant_tables(engine: Engine) -> None:
    GrantBase.metadata.create_all(engine)


def new_client_secret() -> str:
    return secrets.token_urlsafe(32)


def remember_client(
    session: Session,
    *,
    secret: str,
    view: LaunchRoomView,
) -> None:
    existing = session.scalar(
        select(ClientGrantModel).where(ClientGrantModel.launch_id == view.launch_id)
    )
    if existing is not None:
        return
    session.add(
        ClientGrantModel(
            id=new_id(),
            secret_hash=_hash(secret),
            launch_id=view.launch_id,
            user_id=view.owner_user_id,
            organization_id=view.organization_id,
            business_id=view.business_id,
            created_at=utc_now(),
        )
    )


def known_client(session: Session, secret: str) -> bool:
    if not secret:
        return False
    found = session.scalar(
        select(ClientGrantModel.id).where(ClientGrantModel.secret_hash == _hash(secret))
    )
    return found is not None


def operator_for_client(
    session: Session,
    *,
    secret: str,
    launch_id: str,
) -> TrustedOperator | None:
    if not secret:
        return None
    row = session.scalar(
        select(ClientGrantModel).where(
            ClientGrantModel.secret_hash == _hash(secret),
            ClientGrantModel.launch_id == launch_id,
        )
    )
    if row is None:
        return None
    return TrustedOperator(
        user_id=row.user_id,
        scope=TenantScope(organization_id=row.organization_id, business_id=row.business_id),
    )


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
