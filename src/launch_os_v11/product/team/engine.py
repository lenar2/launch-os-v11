"""Executable launch-team graph. One claimed worker owns a job until the lease ends."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from launch_os_v11.domain.ids import new_id
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.team.adapters import (
    ModelUnavailable,
    SpecialistExecutor,
    TestDoubleExecutor,
    TransientTeamError,
)
from launch_os_v11.product.team.contracts import (
    REAL_MODEL_EXECUTION,
    TEST_DOUBLE,
    ArtifactView,
    Assignment,
    LaunchConstraints,
    RoleStatus,
    SpecialistOutput,
    TeamSnapshot,
)
from launch_os_v11.product.team.roles import RoleSpec, affected_roles, by_id, catalog
from launch_os_v11.product.team.store import (
    TeamArtifactModel,
    TeamCycleModel,
    TeamJobModel,
    TeamPacketModel,
    claim_job,
    job_by_key,
)

LEASE = timedelta(seconds=30)
MAX_ATTEMPTS = 3
MAX_REWORK = 4
Clock = Callable[[], datetime]
_T = TypeVar("_T")


def system_clock() -> datetime:
    return datetime.now(UTC)


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TeamEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        executor: SpecialistExecutor | None = None,
        roles: tuple[RoleSpec, ...] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._sessions = session_factory
        self._executor = executor if executor is not None else TestDoubleExecutor()
        self._roles = roles if roles is not None else catalog()
        self._clock = clock if clock is not None else system_clock

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is not None:
            return current.astimezone(UTC).replace(tzinfo=None)
        return current

    def start(
        self,
        *,
        launch_id: str,
        organization_id: str,
        business_id: str,
        intent: str,
        constraints: LaunchConstraints,
    ) -> str:
        def work(session: Session) -> str:
            existing = session.scalar(
                select(TeamCycleModel).where(TeamCycleModel.launch_id == launch_id)
            )
            if existing is not None:
                return existing.id
            cycle = TeamCycleModel(
                id=new_id(),
                organization_id=organization_id,
                business_id=business_id,
                launch_id=launch_id,
                intent=intent.strip(),
                constraints_json=json.dumps(constraints.to_json()),
                status="running",
                rework_count=0,
                provenance=self._executor.provenance,
                real_model_execution=REAL_MODEL_EXECUTION,
            )
            session.add(cycle)
            session.flush()
            self._ensure_jobs(session, cycle, generation_for=None)
            return cycle.id

        return self._tx(work)

    def run_until_idle(self, launch_id: str, *, worker_id: str, limit: int = 80) -> None:
        for _ in range(limit):
            if not self.step(launch_id, worker_id=worker_id):
                return
        raise ProductError("workflow_failed", "Launch team did not finish.")

    def step(self, launch_id: str, *, worker_id: str) -> bool:
        job_id = self.claim_one(launch_id, worker_id=worker_id)
        if job_id is None:
            return False
        self.complete_claimed(job_id, worker_id=worker_id)
        return True

    def claim_one(self, launch_id: str, *, worker_id: str) -> str | None:
        def work(session: Session) -> str | None:
            cycle = self._cycle(session, launch_id)
            if cycle.status in {"MODEL_UNAVAILABLE", "AWAITING_OWNER"}:
                return None
            now = self._now()
            self._release_expired(session, cycle.id, now)
            session.expire_all()
            current = self._current(session, cycle.id)
            jobs = self._jobs(session, cycle.id)
            for job in jobs:
                if job.status != "waiting":
                    continue
                role = by_id(self._roles)[job.role]
                needed = self._dependency_ids(role)
                if not all(name in current for name in needed):
                    continue
                session.execute(
                    update(TeamJobModel)
                    .where(
                        TeamJobModel.id == job.id,
                        TeamJobModel.status == "waiting",
                    )
                    .values(status="queued")
                )
            session.expire_all()
            jobs = self._jobs(session, cycle.id)
            ready = [
                job
                for job in jobs
                if job.status == "queued" and _as_naive(job.available_at) <= now
            ]
            ready.sort(key=lambda job: (job.role, job.generation))
            candidate = ready[0] if ready else None
            if candidate is None:
                self._refresh_status(session, cycle)
                return None
            expected = json.dumps(self._input_ids(session, cycle, candidate.role), sort_keys=True)
            session.execute(
                update(TeamJobModel)
                .where(TeamJobModel.id == candidate.id)
                .values(expected_inputs_json=expected)
            )
            session.expire_all()
            claimed = claim_job(
                session,
                job_id=candidate.id,
                worker_id=worker_id,
                now=now,
                lease=LEASE,
            )
            if claimed is None:
                return None
            session.expire_all()
            return claimed.id

        return self._tx(work)

    def complete_claimed(self, job_id: str, *, worker_id: str) -> None:
        assignment = self._assignment(job_id, worker_id)
        if assignment is None:
            return
        try:
            output = self._executor.execute(assignment)
        except ModelUnavailable as exc:
            self._stop_unavailable(job_id, str(exc))
            return
        except TransientTeamError as exc:
            self._retry(job_id, str(exc))
            return
        self._commit_output(job_id, worker_id, assignment, output)

    def apply_change(
        self,
        launch_id: str,
        *,
        budget_cents: int | None = None,
        weeks: int | None = None,
        offer_wording: str | None = None,
    ) -> set[str]:
        def work(session: Session) -> set[str]:
            cycle = self._cycle(session, launch_id)
            if cycle.rework_count >= MAX_REWORK:
                cycle.status = "AWAITING_OWNER"
                return set()
            current = LaunchConstraints.from_json(json.loads(cycle.constraints_json))
            fields: set[str] = set()
            budget = current.budget_cents
            duration = current.weeks
            wording = current.offer_wording
            if budget_cents is not None and budget_cents != current.budget_cents:
                budget = budget_cents
                fields.add("budget_cents")
            if weeks is not None and weeks != current.weeks:
                duration = weeks
                fields.add("weeks")
            if offer_wording is not None and offer_wording.strip() != current.offer_wording:
                wording = offer_wording.strip()
                fields.add("offer_wording")
            if not fields:
                return set()
            cycle.constraints_json = json.dumps(
                LaunchConstraints(budget, duration, wording).to_json()
            )
            cycle.rework_count += 1
            cycle.status = "running"
            touched = affected_roles(self._roles, fields)
            for artifact in self._rows(session, cycle.id):
                if artifact.role in touched and artifact.status == "current":
                    artifact.status = "stale"
            self._ensure_jobs(session, cycle, generation_for=touched)
            return touched

        return self._tx(work)

    def recheck_critic(self, launch_id: str) -> str:
        def work(session: Session) -> str:
            cycle = self._cycle(session, launch_id)
            output, packet = self._critic_output(session, cycle)
            artifact = self._write_artifact(
                session,
                cycle,
                "critic",
                output,
                json.loads(packet),
            )
            self._save_packet(session, cycle.id, artifact.id, packet)
            return str(output.body["verdict"])

        return self._tx(work)

    def job_status(self, launch_id: str) -> dict[str, str]:
        session = self._sessions()
        try:
            cycle = self._cycle(session, launch_id)
            found: dict[str, str] = {}
            jobs = sorted(self._jobs(session, cycle.id), key=lambda job: job.generation)
            for job in jobs:
                found[job.role] = job.status
            return found
        finally:
            session.close()

    def snapshot(self, launch_id: str) -> TeamSnapshot | None:
        session = self._sessions()
        try:
            cycle = session.scalar(
                select(TeamCycleModel).where(TeamCycleModel.launch_id == launch_id)
            )
            if cycle is None:
                return None
            return self._snapshot(session, cycle)
        finally:
            session.close()

    def artifact_rows(self, launch_id: str, role: str) -> list[tuple[int, str, str]]:
        session = self._sessions()
        try:
            cycle = self._cycle(session, launch_id)
            rows = session.scalars(
                select(TeamArtifactModel)
                .where(
                    TeamArtifactModel.cycle_id == cycle.id,
                    TeamArtifactModel.role == role,
                )
                .order_by(TeamArtifactModel.version)
            ).all()
            return [(row.version, row.status, row.body_json) for row in rows]
        finally:
            session.close()

    def _assignment(self, job_id: str, worker_id: str) -> Assignment | None:
        session = self._sessions()
        try:
            job = session.get(TeamJobModel, job_id)
            if job is None or job.status != "running" or job.claim_owner != worker_id:
                return None
            cycle = session.get(TeamCycleModel, job.cycle_id)
            if cycle is None:
                return None
            role = by_id(self._roles)[job.role]
            inputs = self._views(session, cycle, job.role)
            return Assignment(
                role_id=role.role_id,
                responsibility=role.responsibility,
                tools=role.tools,
                intent=cycle.intent,
                constraints=LaunchConstraints.from_json(json.loads(cycle.constraints_json)),
                inputs=inputs,
            )
        finally:
            session.close()

    def _commit_output(
        self,
        job_id: str,
        worker_id: str,
        assignment: Assignment,
        output: SpecialistOutput,
    ) -> None:
        def work(session: Session) -> None:
            job = session.get(TeamJobModel, job_id)
            if job is None or job.status != "running" or job.claim_owner != worker_id:
                return
            cycle = session.get(TeamCycleModel, job.cycle_id)
            if cycle is None:
                return
            current_ids = self._input_ids(session, cycle, job.role)
            expected = json.loads(job.expected_inputs_json)
            if current_ids != expected:
                job.status = "stale"
                job.claim_owner = None
                job.lease_expires = None
                job.error_summary = "inputs changed before the result was saved"
                self._ensure_jobs(session, cycle, generation_for={job.role})
                return
            if output.provenance not in {TEST_DOUBLE, self._executor.provenance}:
                raise ProductError("workflow_failed", "Specialist provenance is not labeled.")
            packet = {
                role: {
                    "id": item.artifact_id,
                    "version": item.version,
                    "body": dict(item.body),
                }
                for role, item in assignment.inputs.items()
            }
            encoded = json.dumps(packet, sort_keys=True)
            if job.role == "critic":
                output.body["packet_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            artifact = self._write_artifact(session, cycle, job.role, output, packet)
            job.status = "succeeded"
            job.artifact_id = artifact.id
            job.claim_owner = None
            job.lease_expires = None
            job.error_summary = None
            if job.role == "critic":
                self._save_packet(session, cycle.id, job.id, encoded)
            self._refresh_status(session, cycle)

        self._tx(work)

    def _critic_output(
        self,
        session: Session,
        cycle: TeamCycleModel,
    ) -> tuple[SpecialistOutput, str]:
        inputs = self._views(session, cycle, "critic")
        packet = {
            role: {"id": item.artifact_id, "version": item.version, "body": dict(item.body)}
            for role, item in inputs.items()
        }
        encoded = json.dumps(packet, sort_keys=True)
        role = by_id(self._roles)["critic"]
        output = self._executor.execute(
            Assignment(
                role_id="critic",
                responsibility=role.responsibility,
                tools=role.tools,
                intent=cycle.intent,
                constraints=LaunchConstraints.from_json(json.loads(cycle.constraints_json)),
                inputs=inputs,
            )
        )
        output.body["packet_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return output, encoded

    def _stop_unavailable(self, job_id: str, message: str) -> None:
        def work(session: Session) -> None:
            job = session.get(TeamJobModel, job_id)
            if job is None or job.status != "running":
                return
            job.status = "blocked"
            job.claim_owner = None
            job.lease_expires = None
            job.error_summary = message[:300]
            cycle = session.get(TeamCycleModel, job.cycle_id)
            if cycle is not None:
                cycle.status = "MODEL_UNAVAILABLE"

        self._tx(work)

    def _retry(self, job_id: str, message: str) -> None:
        def work(session: Session) -> None:
            job = session.get(TeamJobModel, job_id)
            if job is None or job.status != "running":
                return
            job.claim_owner = None
            job.lease_expires = None
            job.error_summary = message[:300]
            if job.attempt_count < job.max_attempts:
                job.status = "queued"
                job.available_at = self._now() + timedelta(seconds=5)
            else:
                job.status = "failed"
                cycle = session.get(TeamCycleModel, job.cycle_id)
                if cycle is not None:
                    cycle.status = "AWAITING_OWNER"

        self._tx(work)

    def _ensure_jobs(
        self,
        session: Session,
        cycle: TeamCycleModel,
        *,
        generation_for: set[str] | None,
    ) -> None:
        now = self._now()
        for role in self._roles:
            if generation_for is not None and role.role_id not in generation_for:
                continue
            generation = self._next_generation(session, cycle.id, role.role_id)
            key = f"{cycle.id}:{role.role_id}:{generation}"
            if job_by_key(session, key) is not None:
                continue
            session.add(
                TeamJobModel(
                    id=new_id(),
                    cycle_id=cycle.id,
                    role=role.role_id,
                    idempotency_key=key,
                    status="waiting",
                    generation=generation,
                    claim_owner=None,
                    lease_expires=None,
                    attempt_count=0,
                    max_attempts=MAX_ATTEMPTS,
                    available_at=now,
                    expected_inputs_json="{}",
                    artifact_id=None,
                    error_summary=None,
                )
            )
        session.flush()

    def _release_expired(self, session: Session, cycle_id: str, now: datetime) -> None:
        for job in self._jobs(session, cycle_id):
            if job.status != "running" or job.lease_expires is None:
                continue
            if _as_naive(job.lease_expires) > now:
                continue
            status = "queued" if job.attempt_count < job.max_attempts else "failed"
            session.execute(
                update(TeamJobModel)
                .where(
                    TeamJobModel.id == job.id,
                    TeamJobModel.status == "running",
                )
                .values(
                    status=status,
                    claim_owner=None,
                    lease_expires=None,
                    available_at=now,
                )
            )

    def _write_artifact(
        self,
        session: Session,
        cycle: TeamCycleModel,
        role: str,
        output: SpecialistOutput,
        packet: Mapping[str, object],
    ) -> TeamArtifactModel:
        version = 1
        for row in self._rows(session, cycle.id):
            if row.role != role:
                continue
            version = max(version, row.version + 1)
            if row.status in {"current", "stale"}:
                row.status = "superseded"
        input_ids = {
            key: value.get("id")
            for key, value in packet.items()
            if isinstance(value, dict)
        }
        artifact = TeamArtifactModel(
            id=new_id(),
            cycle_id=cycle.id,
            role=role,
            version=version,
            status="current",
            body_json=json.dumps(output.body),
            input_ids_json=json.dumps(input_ids, sort_keys=True),
            quality=output.quality,
            provenance=output.provenance,
        )
        session.add(artifact)
        session.flush()
        return artifact

    def _save_packet(self, session: Session, cycle_id: str, job_id: str, packet: str) -> None:
        session.add(
            TeamPacketModel(
                id=new_id(),
                cycle_id=cycle_id,
                job_id=job_id,
                packet_json=packet,
                packet_hash=hashlib.sha256(packet.encode("utf-8")).hexdigest(),
            )
        )

    def _refresh_status(self, session: Session, cycle: TeamCycleModel) -> None:
        if cycle.status == "MODEL_UNAVAILABLE":
            return
        jobs = self._jobs(session, cycle.id)
        if any(job.status == "blocked" for job in jobs):
            cycle.status = "MODEL_UNAVAILABLE"
            return
        current = self._current(session, cycle.id)
        if "critic" in current:
            quality = current["critic"].quality
            cycle.status = "AWAITING_OWNER" if quality == "BLOCKED" else "READY_FOR_OWNER"
            return
        if any(job.status in {"queued", "running", "waiting"} for job in jobs):
            cycle.status = "running"

    def _snapshot(self, session: Session, cycle: TeamCycleModel) -> TeamSnapshot:
        current = self._current(session, cycle.id)
        jobs = {job.role: job for job in self._jobs(session, cycle.id)}
        roles: list[RoleStatus] = []
        for role in self._roles:
            artifact = current.get(role.role_id)
            job = jobs.get(role.role_id)
            state = "not_started"
            if artifact is not None:
                state = "ready" if artifact.quality != "BLOCKED" else "blocked"
            elif job is not None and job.status == "running":
                state = "working"
            elif job is not None and job.status in {"waiting", "queued"}:
                state = "waiting"
            elif job is not None and job.status == "blocked":
                state = "blocked"
            summary = ""
            if artifact is not None:
                body = json.loads(artifact.body_json)
                summary = _summary(body)
            roles.append(
                RoleStatus(
                    role.role_id,
                    role.title,
                    state,
                    None if artifact is None else artifact.version,
                    summary,
                )
            )
        conflicts: tuple[str, ...] = ()
        critic = current.get("critic")
        if critic is not None:
            body = json.loads(critic.body_json)
            raw = body.get("conflicts")
            if isinstance(raw, list):
                conflicts = tuple(str(item) for item in raw)
        needs = [
            "Publication is not authorized.",
            "Audience size, revenue, and replies are UNKNOWN.",
        ]
        if cycle.status == "MODEL_UNAVAILABLE":
            needs.insert(0, "The model transport is not connected.")
        if conflicts:
            needs.insert(0, "The critic found a conflict for the owner.")
        materials = tuple(
            f"{row.role} v{row.version} {row.status}"
            for row in self._rows(session, cycle.id)
            if row.role in {"editorial", "offer", "finance", "strategy"}
        )
        ready = "Review the first piece. Nothing has been published."
        if cycle.status == "running":
            ready = "The team is still working. No external step is available."
        if cycle.status == "AWAITING_OWNER":
            ready = "The owner needs to resolve a block before the next step."
        return TeamSnapshot(
            status=cycle.status,
            provenance=cycle.provenance,
            real_model_execution=cycle.real_model_execution,
            roles=tuple(roles),
            conflicts=conflicts,
            needs_owner=tuple(needs),
            materials=materials,
            ready_step=ready,
        )

    def _views(
        self,
        session: Session,
        cycle: TeamCycleModel,
        role_id: str,
    ) -> dict[str, ArtifactView]:
        current = self._current(session, cycle.id)
        names = self._dependency_ids(by_id(self._roles)[role_id])
        if role_id == "critic":
            names = tuple(
                role.role_id for role in self._roles if role.kind == "specialist"
            )
        return {
            name: ArtifactView(
                artifact_id=current[name].id,
                role_id=name,
                version=current[name].version,
                body=json.loads(current[name].body_json),
            )
            for name in names
            if name in current
        }

    def _input_ids(self, session: Session, cycle: TeamCycleModel, role_id: str) -> dict[str, str]:
        views = self._views(session, cycle, role_id)
        return {name: item.artifact_id for name, item in views.items()}

    def _dependency_ids(self, role: RoleSpec) -> tuple[str, ...]:
        if role.kind == "critic":
            return ("producer",)
        return role.reads

    def _next_generation(self, session: Session, cycle_id: str, role: str) -> int:
        generations = [
            job.generation for job in self._jobs(session, cycle_id) if job.role == role
        ]
        if not generations:
            return 1
        return max(generations) + 1

    def _current(self, session: Session, cycle_id: str) -> dict[str, TeamArtifactModel]:
        found: dict[str, TeamArtifactModel] = {}
        for row in self._rows(session, cycle_id):
            if row.status == "current":
                found[row.role] = row
        return found

    def _rows(self, session: Session, cycle_id: str) -> list[TeamArtifactModel]:
        return list(
            session.scalars(
                select(TeamArtifactModel)
                .where(TeamArtifactModel.cycle_id == cycle_id)
                .order_by(TeamArtifactModel.version)
            ).all()
        )

    def _jobs(self, session: Session, cycle_id: str) -> list[TeamJobModel]:
        return list(
            session.scalars(
                select(TeamJobModel).where(TeamJobModel.cycle_id == cycle_id)
            ).all()
        )

    def _cycle(self, session: Session, launch_id: str) -> TeamCycleModel:
        cycle = session.scalar(select(TeamCycleModel).where(TeamCycleModel.launch_id == launch_id))
        if cycle is None:
            raise ProductError("not_started", "The launch team has not started.")
        return cycle

    def _tx(self, work: Callable[[Session], _T]) -> _T:
        session = self._sessions()
        try:
            with session.begin():
                return work(session)
        finally:
            session.close()


def _as_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _summary(body: dict[str, object]) -> str:
    for key in ("decision", "verdict", "wording", "mechanism", "first_material", "concept"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value[:180]
    unknowns = body.get("unknown")
    if isinstance(unknowns, list) and unknowns:
        return "UNKNOWN: " + ", ".join(str(item) for item in unknowns)
    return "Recorded."
