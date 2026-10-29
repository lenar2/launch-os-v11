"""Launch team graph. Every model result in this file is a TEST_DOUBLE."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import ActionModel, ExecutionModel, PublicationModel
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime
from launch_os_v11.product.team.adapters import (
    ChatBridgeExecutor,
    ModelInvocationExecutor,
    ModelUnavailable,
    TestDoubleExecutor,
    TransientTeamError,
)
from launch_os_v11.product.team.contracts import (
    REAL_MODEL_EXECUTION,
    Assignment,
    LaunchConstraints,
)
from launch_os_v11.product.team.engine import MutableClock, TeamEngine
from launch_os_v11.product.team.roles import RoleSpec, catalog
from launch_os_v11.product.team.store import TeamArtifactModel

INTENT = (
    "Разработать запуск онлайн-курса для существующей аудитории "
    "за три недели с ограниченным бюджетом."
)
OFFER = "Three-week course for the existing audience"


def _runtime(tmp_path: Path) -> LaunchRoomRuntime:
    url = f"sqlite+pysqlite:///{tmp_path / 'team.sqlite'}"
    return LaunchRoomRuntime.open(url, environment="test")


def _engine(
    runtime: LaunchRoomRuntime,
    *,
    executor: object | None = None,
    clock: MutableClock | None = None,
    roles: tuple[RoleSpec, ...] | None = None,
) -> TeamEngine:
    kwargs: dict[str, object] = {}
    if executor is not None:
        kwargs["executor"] = executor
    if clock is not None:
        kwargs["clock"] = clock
    if roles is not None:
        kwargs["roles"] = roles
    return TeamEngine(runtime.session_factory, **kwargs)


def _open_course(service: LaunchRoomService):
    return service.open_launch(
        business_name="Northwind Studio",
        goal=INTENT,
        offer_name=OFFER,
        audience="Existing students",
    )


def _operator(room):
    return TrustedOperator(
        user_id=room.owner_user_id,
        scope=TenantScope(organization_id=room.organization_id, business_id=room.business_id),
    )


def _start(
    engine: TeamEngine,
    room,
    *,
    budget: int = 100_000,
    weeks: int = 3,
    wording: str = OFFER,
) -> None:
    engine.start(
        launch_id=room.launch_id,
        organization_id=room.organization_id,
        business_id=room.business_id,
        intent=INTENT,
        constraints=LaunchConstraints(budget, weeks, wording),
    )


def _body(engine: TeamEngine, launch_id: str, role: str) -> dict[str, object]:
    rows = [row for row in engine.artifact_rows(launch_id, role) if row[1] == "current"]
    assert rows
    return json.loads(rows[-1][2])


def _counts(runtime: LaunchRoomRuntime) -> dict[str, int]:
    session = runtime.session_factory()
    try:
        def count(model: object) -> int:
            value = session.scalar(select(func.count()).select_from(model))
            return int(value or 0)

        return {
            "actions": count(ActionModel),
            "executions": count(ExecutionModel),
            "publications": count(PublicationModel),
        }
    finally:
        session.close()


def test_course_launch_passes_specialist_results_forward(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = LaunchRoomService(runtime)
    room = _open_course(service)
    engine = _engine(runtime)
    _start(engine, room)
    first_id = engine.start(
        launch_id=room.launch_id,
        organization_id=room.organization_id,
        business_id=room.business_id,
        intent=INTENT,
        constraints=LaunchConstraints(100_000, 3, OFFER),
    )
    second_id = engine.start(
        launch_id=room.launch_id,
        organization_id=room.organization_id,
        business_id=room.business_id,
        intent=INTENT,
        constraints=LaunchConstraints(1, 1, "other"),
    )
    assert first_id == second_id
    engine.run_until_idle(room.launch_id, worker_id="lead")
    audience = _body(engine, room.launch_id, "audience")
    offer = _body(engine, room.launch_id, "offer")
    strategy = _body(engine, room.launch_id, "strategy")
    editorial = _body(engine, room.launch_id, "editorial")
    creative = _body(engine, room.launch_id, "creative")
    funnel = _body(engine, room.launch_id, "funnel")
    finance = _body(engine, room.launch_id, "finance")
    operations = _body(engine, room.launch_id, "operations")
    producer = _body(engine, room.launch_id, "producer")
    critic = _body(engine, room.launch_id, "critic")
    assert audience["size"] == "UNKNOWN"
    assert "willingness to pay" in audience["unknown"]
    assert offer["audience_artifact_id"] == offer["input_ids"]["audience"]
    assert offer["wording"] == OFFER
    assert offer["price_status"] == "ASSUMPTION"
    assert strategy["weeks"] == 3
    assert strategy["offer_wording"] == OFFER
    assert strategy["input_ids"]["audience"] == offer["input_ids"]["audience"]
    assert strategy["input_ids"]["offer"] != offer["audience_artifact_id"]
    assert editorial["weeks"] == 3
    assert editorial["pieces"][0].endswith(OFFER)
    assert editorial["input_ids"]["offer"] == strategy["input_ids"]["offer"]
    assert creative["editorial_artifact_id"] == creative["input_ids"]["editorial"]
    assert OFFER in str(creative["concept"])
    assert funnel["offer_wording"] == OFFER
    assert funnel["weeks"] == 3
    assert funnel["input_ids"]["offer"] == strategy["input_ids"]["offer"]
    assert finance["budget_cents"] == 100_000
    assert finance["revenue"] == "UNKNOWN"
    assert finance["weeks"] == 3
    assert finance["input_ids"]["strategy"] == editorial["input_ids"]["strategy"]
    assert operations["calendar"] == ["Week 1", "Week 2", "Week 3"]
    assert operations["ready_for_external_delivery"] is False
    assert producer["publication_authority"] == "NOT_GRANTED"
    assert critic["verdict"] == "PASS_WITH_UNKNOWNS"
    assert critic["copied_author_verdict"] is False
    assert "audience" in critic["packet_roles"]
    assert "producer" not in critic["packet_roles"]
    snapshot = engine.snapshot(room.launch_id)
    assert snapshot is not None
    assert snapshot.real_model_execution == REAL_MODEL_EXECUTION
    assert snapshot.provenance == "TEST_DOUBLE"
    assert _counts(runtime) == {"actions": 0, "executions": 0, "publications": 0}
    audience_rows = engine.artifact_rows(room.launch_id, "audience")
    assert audience_rows == [(1, "current", audience_rows[0][2])]


def test_constraint_change_reworks_only_dependents_and_keeps_old_versions(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = LaunchRoomService(runtime)
    room = _open_course(service)
    operator = _operator(room)
    engine = _engine(runtime)
    _start(engine, room)
    engine.run_until_idle(room.launch_id, worker_id="lead")
    audience_before = engine.artifact_rows(room.launch_id, "audience")
    service.apply_team_change(
        room.launch_id,
        operator=operator,
        budget_cents=50_000,
        weeks=2,
    )
    audience_after = engine.artifact_rows(room.launch_id, "audience")
    assert audience_after == audience_before
    assert _body(engine, room.launch_id, "strategy")["weeks"] == 2
    assert _body(engine, room.launch_id, "finance")["budget_cents"] == 50_000
    assert _body(engine, room.launch_id, "editorial")["weeks"] == 2
    assert _body(engine, room.launch_id, "operations")["calendar"] == ["Week 1", "Week 2"]
    finance_rows = engine.artifact_rows(room.launch_id, "finance")
    assert len(finance_rows) >= 2
    assert finance_rows[0][1] == "superseded"
    assert json.loads(finance_rows[0][2])["budget_cents"] == 100_000
    wording = "Include specific office hours in the unpublished draft"
    service.apply_team_change(room.launch_id, operator=operator, offer_wording=wording)
    offer_rows = engine.artifact_rows(room.launch_id, "offer")
    assert offer_rows[0][1] == "superseded"
    assert OFFER in offer_rows[0][2]
    assert wording in offer_rows[-1][2]
    assert engine.artifact_rows(room.launch_id, "audience") == audience_before
    assert wording in _body(engine, room.launch_id, "editorial")["pieces"][0]
    assert _counts(runtime)["publications"] == 0


def test_critic_uses_the_specialist_packet_not_the_producer_verdict(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    engine.run_until_idle(room.launch_id, worker_id="lead")
    review_before = engine.artifact_rows(room.launch_id, "review")
    session = runtime.session_factory()
    try:
        with session.begin():
            row = session.scalar(
                select(TeamArtifactModel).where(
                    TeamArtifactModel.role == "strategy",
                    TeamArtifactModel.status == "current",
                )
            )
            assert row is not None
            body = json.loads(row.body_json)
            body["weeks"] = 9
            row.body_json = json.dumps(body)
    finally:
        session.close()
    assert engine.recheck_critic(room.launch_id) == "BLOCKED"
    critic = _body(engine, room.launch_id, "critic")
    assert "finance duration does not match strategy" in critic["conflicts"]
    assert critic["copied_author_verdict"] is False
    assert engine.artifact_rows(room.launch_id, "review") == review_before


def test_unavailable_transport_does_not_invent_a_result(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    for executor in (ChatBridgeExecutor(), ModelInvocationExecutor()):
        launch_id = new_id()
        engine = _engine(runtime, executor=executor)
        engine.start(
            launch_id=launch_id,
            organization_id=room.organization_id,
            business_id=room.business_id,
            intent=INTENT,
            constraints=LaunchConstraints(100_000, 3, OFFER),
        )
        engine.step(launch_id, worker_id="lead")
        snapshot = engine.snapshot(launch_id)
        assert snapshot is not None
        assert snapshot.status == "MODEL_UNAVAILABLE"
        assert snapshot.real_model_execution == REAL_MODEL_EXECUTION
        assert engine.artifact_rows(launch_id, "audience") == []


def test_expired_lease_can_be_claimed_once_and_a_late_result_is_ignored(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    engine = _engine(runtime, clock=clock)
    _start(engine, room)
    first = engine.claim_one(room.launch_id, worker_id="worker-a")
    assert first is not None
    clock.advance(31)
    second = engine.claim_one(room.launch_id, worker_id="worker-b")
    assert second == first
    engine.complete_claimed(first, worker_id="worker-a")
    engine.complete_claimed(first, worker_id="worker-b")
    rows = engine.artifact_rows(room.launch_id, "audience")
    assert len([row for row in rows if row[1] == "current"]) == 1


def test_retry_waits_and_then_succeeds(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))

    class Flaky(TestDoubleExecutor):
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, assignment):
            self.calls += 1
            if self.calls == 1 and assignment.role_id == "audience":
                raise TransientTeamError("timed out")
            return super().execute(assignment)

    engine = _engine(runtime, executor=Flaky(), clock=clock)
    _start(engine, room)
    assert engine.step(room.launch_id, worker_id="lead") is True
    assert engine.artifact_rows(room.launch_id, "audience") == []
    assert engine.step(room.launch_id, worker_id="lead") is False
    clock.advance(5)
    engine.run_until_idle(room.launch_id, worker_id="lead")
    assert _body(engine, room.launch_id, "audience")["size"] == "UNKNOWN"


def test_only_one_worker_claims_the_same_queued_job(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(
            lambda name: engine.claim_one(room.launch_id, worker_id=name),
            ("worker-a", "worker-b"),
        ))
    winners = [job_id for job_id in claimed if job_id is not None]
    assert len(winners) == 1
    assert winners[0] == claimed[0] or winners[0] == claimed[1]


def test_stale_result_is_not_saved_over_newer_inputs(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    engine.step(room.launch_id, worker_id="lead")
    offer_job = engine.claim_one(room.launch_id, worker_id="lead")
    assert offer_job is not None
    session = runtime.session_factory()
    try:
        with session.begin():
            row = session.scalar(
                select(TeamArtifactModel).where(TeamArtifactModel.role == "audience")
            )
            assert row is not None
            row.status = "superseded"
            session.add(
                TeamArtifactModel(
                    id="newer-audience",
                    cycle_id=row.cycle_id,
                    role="audience",
                    version=row.version + 1,
                    status="current",
                    body_json=row.body_json,
                    input_ids_json=row.input_ids_json,
                    quality=row.quality,
                    provenance=row.provenance,
                )
            )
    finally:
        session.close()
    engine.complete_claimed(offer_job, worker_id="lead")
    assert engine.artifact_rows(room.launch_id, "offer") == []


def test_added_specialist_joins_review_without_a_new_queue(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    extra = RoleSpec(
        "sponsor",
        "Sponsor Fit",
        "Read the audience and say what is still UNKNOWN.",
        ("audience",),
        (),
        ("founder_brief",),
        "specialist",
    )
    engine = _engine(runtime, roles=catalog(extra))
    _start(engine, room)
    engine.run_until_idle(room.launch_id, worker_id="lead")
    sponsor = _body(engine, room.launch_id, "sponsor")
    review = _body(engine, room.launch_id, "review")
    assert "audience" in sponsor["input_ids"]
    assert "sponsor" in review["checked_ids"]


def test_editorial_and_funnel_can_be_claimed_independently(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    for _ in range(6):
        rows = engine.artifact_rows(room.launch_id, "strategy")
        if any(row[1] == "current" for row in rows):
            break
        assert engine.step(room.launch_id, worker_id="lead") is True
    claimed = engine.claim_one(room.launch_id, worker_id="editor")
    status = engine.job_status(room.launch_id)
    assert claimed is not None
    assert status["editorial"] == "running"
    assert status["funnel"] == "queued"
    other = engine.claim_one(room.launch_id, worker_id="funnel-worker")
    assert other is not None
    assert other != claimed


def test_restart_continues_the_same_cycle(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'team.sqlite'}"
    runtime = LaunchRoomRuntime.open(url, environment="test")
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    assert engine.step(room.launch_id, worker_id="before-restart") is True
    restarted = LaunchRoomRuntime.open(url, environment="test")
    resumed = TeamEngine(restarted.session_factory)
    resumed.run_until_idle(room.launch_id, worker_id="after-restart")
    assert _body(resumed, room.launch_id, "critic")["verdict"] == "PASS_WITH_UNKNOWNS"
    assert resumed.artifact_rows(room.launch_id, "audience")[0][1] == "current"


def test_rework_loop_stops_for_the_owner(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    room = _open_course(LaunchRoomService(runtime))
    engine = _engine(runtime)
    _start(engine, room)
    engine.run_until_idle(room.launch_id, worker_id="lead")
    for weeks in (2, 4, 5, 6):
        engine.apply_change(room.launch_id, weeks=weeks)
        engine.run_until_idle(room.launch_id, worker_id="lead")
    blocked = engine.apply_change(room.launch_id, weeks=7)
    assert blocked == set()
    snapshot = engine.snapshot(room.launch_id)
    assert snapshot is not None
    assert snapshot.status == "AWAITING_OWNER"
    assert _body(engine, room.launch_id, "strategy")["weeks"] == 6


def test_foreign_owner_cannot_run_or_read_the_team(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = LaunchRoomService(runtime)
    first = _open_course(service)
    second = service.open_launch(
        business_name="Other Studio",
        goal="A different course.",
        offer_name="Other offer",
    )
    foreign = _operator(second)
    with pytest.raises(ProductError) as caught:
        service.run_launch_team(first.launch_id, operator=foreign)
    assert caught.value.code == "scope_violation"
    impersonated = TrustedOperator(
        user_id=second.owner_user_id,
        scope=TenantScope(
            organization_id=first.organization_id,
            business_id=first.business_id,
        ),
    )
    with pytest.raises(ProductError) as caught:
        service.launch_team_html(first.launch_id, operator=impersonated)
    assert caught.value.code == "owner_required"


def test_room_service_runs_the_team_and_keeps_publication_at_zero(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = LaunchRoomService(runtime)
    room = _open_course(service)
    operator = _operator(room)
    service.run_launch_team(room.launch_id, operator=operator)
    html = service.launch_team_html(room.launch_id, operator=operator)
    assert "NOT_YET_PROVEN" in html
    assert "TEST_DOUBLE" in html
    assert "Independent Launch Critic" in html
    assert _counts(runtime)["publications"] == 0
    assignment = Assignment(
        role_id="audience",
        responsibility="Read the brief.",
        tools=(),
        intent=INTENT,
        constraints=LaunchConstraints(100_000, 3, OFFER),
        inputs={},
    )
    with pytest.raises(ModelUnavailable):
        ChatBridgeExecutor().execute(assignment)
    with pytest.raises(ModelUnavailable):
        ModelInvocationExecutor().execute(assignment)
