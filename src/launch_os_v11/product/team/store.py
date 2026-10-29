"""Durable team jobs. Claim uses one conditional update, like the core worker."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, String, Text, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class TeamBase(DeclarativeBase):
    pass


class TeamCycleModel(TeamBase):
    __tablename__ = "launch_team_cycles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_id: Mapped[str] = mapped_column(String(36), nullable=False)
    launch_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    intent: Mapped[str] = mapped_column(String(2000), nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance: Mapped[str] = mapped_column(String(40), nullable=False)
    real_model_execution: Mapped[str] = mapped_column(String(40), nullable=False)


class TeamArtifactModel(TeamBase):
    __tablename__ = "launch_team_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[str] = mapped_column(String(40), nullable=False)


class TeamJobModel(TeamBase):
    __tablename__ = "launch_team_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(36))
    error_summary: Mapped[str | None] = mapped_column(String(300))


class TeamPacketModel(TeamBase):
    __tablename__ = "launch_team_packets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    packet_json: Mapped[str] = mapped_column(Text, nullable=False)
    packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)


def ensure_team_tables(engine: Engine) -> None:
    TeamBase.metadata.create_all(engine)


def claim_job(
    session: Session,
    *,
    job_id: str,
    worker_id: str,
    now: datetime,
    lease: timedelta,
) -> TeamJobModel | None:
    claimed_id = session.scalar(
        update(TeamJobModel)
        .where(TeamJobModel.id == job_id, TeamJobModel.status == "queued")
        .values(
            status="running",
            claim_owner=worker_id,
            lease_expires=now + lease,
            attempt_count=TeamJobModel.attempt_count + 1,
        )
        .returning(TeamJobModel.id)
    )
    if claimed_id is None:
        return None
    return session.get(TeamJobModel, claimed_id)


def job_by_key(session: Session, key: str) -> TeamJobModel | None:
    return session.scalar(select(TeamJobModel).where(TeamJobModel.idempotency_key == key))
