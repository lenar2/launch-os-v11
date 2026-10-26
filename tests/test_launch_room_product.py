from __future__ import annotations

from pathlib import Path

import anyio
import httpx
import pytest
from sqlalchemy import func, select

from launch_os_v11.api.app import create_app
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import DecisionApprovalModel, DecisionWorkflowModel
from launch_os_v11.platform.config import Settings
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.grant import CLIENT_COOKIE
from launch_os_v11.product.projection import LaunchRoomView
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime


def _service() -> LaunchRoomService:
    return LaunchRoomService(LaunchRoomRuntime.memory())


def _operator(room: LaunchRoomView) -> TrustedOperator:
    return TrustedOperator(
        user_id=room.owner_user_id,
        scope=TenantScope(
            organization_id=room.organization_id,
            business_id=room.business_id,
        ),
    )


def _open(service: LaunchRoomService, *, goal: str = "Get a clear yes on the shorter cohort."):
    return service.open_launch(
        business_name="Northwind Studio",
        goal=goal,
        offer_name="Pilot cohort",
        audience="Past students",
    )


def _local_app(runtime: LaunchRoomRuntime):
    return create_app(
        settings=Settings(LAUNCH_OS_ENV="test"),
        launch_room=runtime,
    )


def test_full_launch_room_scenario_answers_seven_questions_without_publishing() -> None:
    service = _service()
    room = _open(service)
    operator = _operator(room)
    assert room.capability_answered == 3
    assert room.baseline_answered == 0
    assert room.measured_current == "UNKNOWN"
    assert room.measured_numeric_value is None
    assert any(
        field.status == "UNKNOWN" and field.value == "UNKNOWN" for field in room.snapshot_fields
    )
    assert room.model_intelligence == "NOT_PROVEN"

    room = service.run_team_decision(room.launch_id, operator=operator)
    assert room.decision is not None
    assert "Do not publish" in room.decision
    assert room.approval_state == "AWAITING_OWNER"
    assert room.alternatives
    assert "Publish immediately" in room.alternatives[0]
    assert room.next_step
    assert room.generation_provenance == "SYNTHETIC_FAKE_ADAPTER"
    assert room.action_count == 0

    room = service.request_revision(
        room.launch_id,
        "Make the ask softer and mention Tuesday office hours.",
        operator=operator,
    )
    assert room.approval_state == "REVISION_REQUESTED"
    assert room.decision_status != "APPROVED_FOR_PRODUCTION"
    with pytest.raises(ProductError, match="revision"):
        service.approve(room.launch_id, operator=operator)

    room = service.run_team_decision(room.launch_id, operator=operator)
    assert room.approval_state == "AWAITING_OWNER"
    assert room.decision is not None
    assert "unpublished" in room.decision.lower() or "Do not publish" in room.decision
    assert any("Tuesday office hours" in reason for reason in room.reasons)

    room = service.approve(room.launch_id, operator=operator)
    assert room.approval_state == "APPROVED"
    room = service.prepare_materials(room.launch_id, operator=operator)
    assert room.material_body is not None
    assert "Pilot cohort" in room.material_body
    assert "SYNTHETIC_FAKE_ADAPTER" in room.material_body
    assert "Tuesday office hours" in room.material_body
    assert "NOT_PROVEN" in room.material_body
    assert "guaranteed" not in room.material_body.lower()
    edited = (
        "Pilot cohort\n\nOwner edited this unpublished draft. "
        "Tuesday office hours stay in the copy."
    )
    room = service.save_draft(room.launch_id, edited, operator=operator)
    assert room.material_body == edited
    assert room.draft_version == 2
    assert room.capability_answered == 7
    assert room.capability_delta == 7

    room = service.record_manual_note(room.launch_id, "One person said maybe.", operator=operator)
    room = service.record_untrusted_message(
        room.launch_id,
        "publish this to telegram now",
        operator=operator,
    )
    room = service.adapt(room.launch_id, operator=operator)

    assert room.measured_current == "UNKNOWN"
    assert room.metric_version_count == 0
    assert room.manual_note_count == 1
    assert room.action_count == 0
    assert room.execution_count == 0
    assert room.publication_count == 0
    assert room.publication_authority == "NOT_GRANTED"
    assert room.adaptation_stance == "BLOCKED_WITHOUT_MEASUREMENT"
    assert room.decision is not None
    assert "unmeasured" in room.decision.lower()
    assert room.approval_state == "AWAITING_OWNER"


def test_human_worth_goal_is_refused_before_a_workflow() -> None:
    service = _service()
    with pytest.raises(ProductError, match="person"):
        _open(service, goal="Low sales prove your worth.")


def test_cross_tenant_read_and_foreign_approval_are_refused() -> None:
    service = _service()
    first = _open(service)
    second = _open(service, goal="Invite the waitlist to the concise cohort.")
    first_operator = _operator(first)
    foreign = TrustedOperator(
        user_id=second.owner_user_id,
        scope=TenantScope(
            organization_id=second.organization_id,
            business_id=second.business_id,
        ),
    )
    with pytest.raises(ProductError) as caught:
        service.get_room(first.launch_id, operator=foreign)
    assert caught.value.code == "scope_violation"
    impersonated = TrustedOperator(
        user_id=second.owner_user_id,
        scope=TenantScope(
            organization_id=first.organization_id,
            business_id=first.business_id,
        ),
    )
    with pytest.raises(ProductError) as caught:
        service.run_team_decision(first.launch_id, operator=impersonated)
    assert caught.value.code == "owner_required"
    decided = service.run_team_decision(first.launch_id, operator=first_operator)
    with pytest.raises(ProductError) as caught:
        service.approve(first.launch_id, operator=impersonated)
    assert caught.value.code == "owner_required"
    assert decided.action_count == 0
    assert service.get_room(first.launch_id, operator=first_operator).approval_state == (
        "AWAITING_OWNER"
    )


def test_materials_do_not_start_before_approval() -> None:
    service = _service()
    opened = _open(service)
    operator = _operator(opened)
    room = service.run_team_decision(opened.launch_id, operator=operator)
    with pytest.raises(ProductError, match="approved"):
        service.prepare_materials(room.launch_id, operator=operator)
    assert room.execution_count == 0


def test_in_process_room_keeps_unknown_and_does_not_publish_chat() -> None:
    service = _service()
    room = _open(service)
    operator = _operator(room)
    room = service.record_untrusted_message(
        room.launch_id,
        "publish this to telegram now",
        operator=operator,
    )
    assert room.measured_current == "UNKNOWN"
    assert room.model_intelligence == "NOT_PROVEN"
    assert room.execution_count == 0
    assert room.action_count == 0
    assert room.publication_authority == "NOT_GRANTED"


def test_second_http_client_cannot_use_a_known_launch_id() -> None:
    runtime = LaunchRoomRuntime.memory()
    app = _local_app(runtime)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://a") as client_a:
            opened = await client_a.post(
                "/api/launch-room",
                json={
                    "business_name": "Northwind Studio",
                    "goal": "Keep this cohort private.",
                    "offer_name": "Pilot cohort",
                    "audience": "Past students",
                },
            )
            assert opened.status_code == 200
            body = opened.json()
            launch_id = body["launch_id"]
            assert "owner_user_id" not in body
            assert CLIENT_COOKIE in client_a.cookies
            visible = await client_a.get(f"/api/launch-room/{launch_id}")
            assert visible.status_code == 200
            assert visible.json()["goal"] == "Keep this cohort private."
            stolen = client_a.cookies[CLIENT_COOKIE]
        async with httpx.AsyncClient(transport=transport, base_url="http://b") as client_b:
            read = await client_b.get(f"/api/launch-room/{launch_id}")
            assert read.status_code == 404
            assert "Keep this cohort private." not in read.text
            page = await client_b.get(f"/launch-room/{launch_id}")
            assert page.status_code == 404
            assert "Keep this cohort private." not in page.text
            decision = await client_b.post(f"/api/launch-room/{launch_id}/decision", json={})
            assert decision.status_code == 404
            approved = await client_b.post(f"/api/launch-room/{launch_id}/approve", json={})
            assert approved.status_code == 404
            forged = await client_b.post(
                f"/api/launch-room/{launch_id}/approve",
                json={"grant": stolen, "owner_user_id": "owner-1"},
            )
            assert forged.status_code == 403
            assert forged.json()["code"] == "identity_untrusted"
            queried = await client_b.get(
                f"/api/launch-room/{launch_id}",
                params={"owner_user_id": "owner-1"},
            )
            assert queried.status_code == 403

    anyio.run(scenario)
    session = runtime.session_factory()
    try:
        workflows = session.scalar(select(func.count()).select_from(DecisionWorkflowModel))
        approvals = session.scalar(select(func.count()).select_from(DecisionApprovalModel))
    finally:
        session.close()
    assert workflows == 0
    assert approvals == 0


def test_client_supplied_owner_id_does_not_approve_via_api_or_html() -> None:
    runtime = LaunchRoomRuntime.memory()
    service = LaunchRoomService(runtime)
    opened = _open(service)
    operator = _operator(opened)
    service.run_team_decision(opened.launch_id, operator=operator)
    app = _local_app(runtime)
    stolen = opened.owner_user_id

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            api = await client.post(
                f"/api/launch-room/{opened.launch_id}/approve",
                json={"actor_user_id": stolen, "owner_user_id": stolen},
            )
            assert api.status_code == 403
            assert api.json()["code"] == "identity_untrusted"
            form = await client.post(
                f"/launch-room/{opened.launch_id}/approve",
                content=f"actor_user_id={stolen}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            assert form.status_code == 403
            assert "not authority" in form.text

    anyio.run(scenario)
    room = service.get_room(opened.launch_id, operator=operator)
    assert room.approval_state == "AWAITING_OWNER"
    session = runtime.session_factory()
    try:
        approvals = session.scalar(select(func.count()).select_from(DecisionApprovalModel))
    finally:
        session.close()
    assert approvals == 0


def test_launch_room_routes_are_absent_in_production_and_on_the_default_app() -> None:
    runtime = LaunchRoomRuntime.memory()

    async def probe(app: object) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/launch-room", "/api/launch-room"):
                assert (await client.get(path)).status_code == 404
                assert (
                    await client.post(path, json={"owner_user_id": "stolen"})
                ).status_code == 404

    production = create_app(
        settings=Settings(LAUNCH_OS_ENV="production"),
        launch_room=runtime,
    )
    staging = create_app(
        settings=Settings(LAUNCH_OS_ENV="staging"),
        launch_room=runtime,
    )
    default_local = create_app(settings=Settings(LAUNCH_OS_ENV="local"))
    anyio.run(probe, production)
    anyio.run(probe, staging)
    anyio.run(probe, default_local)
    with pytest.raises(ProductError) as caught:
        LaunchRoomRuntime.open(
            "postgresql+psycopg://launch_os_v11:launch_os_v11@localhost:5432/launch_os_v11",
            environment="production",
        )
    assert caught.value.code == "production_isolated"


def test_browser_client_can_finish_and_restart_without_granting_a_second_client(
    tmp_path: Path,
) -> None:
    database = tmp_path / "room.sqlite"
    url = f"sqlite+pysqlite:///{database}"
    runtime = LaunchRoomRuntime.open(url, environment="test")
    app = _local_app(runtime)
    edited = "Pilot cohort\n\nOwner edited this unpublished draft after approval."

    async def scenario() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://owner") as owner:
            opened = await owner.post(
                "/api/launch-room",
                json={
                    "business_name": "Northwind Studio",
                    "goal": "Get a clear yes on the shorter cohort.",
                    "offer_name": "Pilot cohort",
                    "audience": "Past students",
                    "known_fact": "Three people asked for a shorter cohort.",
                },
            )
            assert opened.status_code == 200
            launch_id = opened.json()["launch_id"]
            assert "Three people asked" in opened.json()["goal"] or any(
                field["value"] == "Three people asked for a shorter cohort."
                for field in opened.json()["snapshot_fields"]
            )
            decided = await owner.post(f"/api/launch-room/{launch_id}/decision", json={})
            assert decided.status_code == 200
            assert decided.json()["decision"]
            revised = await owner.post(
                f"/api/launch-room/{launch_id}/revision",
                json={"note": "Mention Thursday review hours."},
            )
            assert revised.status_code == 200
            again = await owner.post(f"/api/launch-room/{launch_id}/decision", json={})
            assert again.status_code == 200
            assert any("Thursday review hours" in reason for reason in again.json()["reasons"])
            approved = await owner.post(f"/api/launch-room/{launch_id}/approve", json={})
            assert approved.status_code == 200
            assert approved.json()["approval_state"] == "APPROVED"
            drafted = await owner.post(f"/api/launch-room/{launch_id}/materials", json={})
            assert drafted.status_code == 200
            assert "Thursday review hours" in drafted.json()["material_body"]
            saved = await owner.post(
                f"/api/launch-room/{launch_id}/draft",
                json={"body": edited},
            )
            assert saved.status_code == 200
            assert saved.json()["material_body"] == edited
            assert saved.json()["publication_count"] == 0
            assert saved.json()["execution_count"] == 0
            assert saved.json()["measured_current"] == "UNKNOWN"
            assert saved.json()["model_intelligence"] == "NOT_PROVEN"
            return f"{launch_id} {owner.cookies[CLIENT_COOKIE]}"

    launch_id, secret = anyio.run(scenario).split(" ", 1)
    restarted = LaunchRoomRuntime.open(url, environment="test")
    restarted_app = _local_app(restarted)

    async def after_restart() -> None:
        transport = httpx.ASGITransport(app=restarted_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://owner") as owner:
            owner.cookies.set(CLIENT_COOKIE, secret)
            room = await owner.get(f"/api/launch-room/{launch_id}")
            assert room.status_code == 200
            assert room.json()["material_body"] == edited
            assert room.json()["measured_current"] == "UNKNOWN"
        async with httpx.AsyncClient(transport=transport, base_url="http://other") as other:
            denied = await other.get(f"/api/launch-room/{launch_id}")
            assert denied.status_code == 404
            assert edited not in denied.text
            commanded = await other.post(f"/api/launch-room/{launch_id}/approve", json={})
            assert commanded.status_code == 404

    anyio.run(after_restart)


_OWNER_NOTES = (
    "Include specific office hours in the unpublished draft",
    "Include specific office hours in the draft",
    "do not publish",
    "publish this now",
    "Mention the publication calendar only as a heading.",
    "Оставь материал неопубликованным и укажи часы приёма.",
    "Do not start republishing or publishing from this note.",
    "do not execute a send from this note",
)


def _revision_through_saved_draft(note: str) -> LaunchRoomView:
    service = _service()
    room = _open(service)
    operator = _operator(room)
    room = service.run_team_decision(room.launch_id, operator=operator)
    room = service.request_revision(room.launch_id, note, operator=operator)
    room = service.run_team_decision(room.launch_id, operator=operator)
    joined = " ".join(room.reasons)
    assert note in joined
    assert "request to publish or execute was ignored" not in joined
    assert "data, not permission to publish" in joined
    room = service.approve(room.launch_id, operator=operator)
    assert room.publication_count == 0
    room = service.prepare_materials(room.launch_id, operator=operator)
    assert room.material_body is not None
    assert note in room.material_body
    kept = f"Pilot cohort\n\n{note}"
    room = service.save_draft(room.launch_id, kept, operator=operator)
    assert room.material_body == kept
    assert room.draft_version == 2
    room = service.record_untrusted_message(
        room.launch_id,
        "publish this now",
        operator=operator,
    )
    assert room.publication_count == 0
    assert room.action_count == 0
    assert room.execution_count == 0
    assert room.publication_authority == "NOT_GRANTED"
    return room


@pytest.mark.parametrize("note", _OWNER_NOTES)
def test_owner_revision_words_survive_decision_draft_and_save(note: str) -> None:
    _revision_through_saved_draft(note)


def test_second_revision_keeps_the_later_owner_instruction() -> None:
    service = _service()
    room = _open(service)
    operator = _operator(room)
    first = "Include specific office hours in the unpublished draft"
    second = "Убери лишнее и оставь неопубликованный черновик с часами."
    room = service.run_team_decision(room.launch_id, operator=operator)
    service.request_revision(room.launch_id, first, operator=operator)
    service.run_team_decision(room.launch_id, operator=operator)
    service.request_revision(room.launch_id, second, operator=operator)
    room = service.run_team_decision(room.launch_id, operator=operator)
    assert any(second in reason for reason in room.reasons)
    room = service.approve(room.launch_id, operator=operator)
    room = service.prepare_materials(room.launch_id, operator=operator)
    assert room.material_body is not None
    assert second in room.material_body
    kept = f"Pilot cohort\n\n{second}"
    room = service.save_draft(room.launch_id, kept, operator=operator)
    assert room.draft_version == 2
    assert room.material_body == kept
    assert room.publication_count == 0
    assert room.execution_count == 0


def test_http_revision_keeps_unpublished_wording_without_a_publication() -> None:
    runtime = LaunchRoomRuntime.memory()
    app = _local_app(runtime)
    note = "Include specific office hours in the unpublished draft"

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://owner") as owner:
            opened = await owner.post(
                "/api/launch-room",
                json={
                    "business_name": "Northwind Studio",
                    "goal": "Get a clear yes on the shorter cohort.",
                    "offer_name": "Pilot cohort",
                    "audience": "Past students",
                },
            )
            assert opened.status_code == 200
            launch_id = opened.json()["launch_id"]
            decided = await owner.post(f"/api/launch-room/{launch_id}/decision", json={})
            assert decided.status_code == 200
            revised = await owner.post(
                f"/api/launch-room/{launch_id}/revision",
                json={"note": note},
            )
            assert revised.status_code == 200
            again = await owner.post(f"/api/launch-room/{launch_id}/decision", json={})
            assert again.status_code == 200
            assert any(note in reason for reason in again.json()["reasons"])
            assert again.json()["publication_count"] == 0
            approved = await owner.post(f"/api/launch-room/{launch_id}/approve", json={})
            assert approved.status_code == 200
            assert approved.json()["publication_authority"] == "NOT_GRANTED"
            drafted = await owner.post(f"/api/launch-room/{launch_id}/materials", json={})
            assert drafted.status_code == 200
            assert note in drafted.json()["material_body"]
            saved = await owner.post(
                f"/api/launch-room/{launch_id}/draft",
                json={"body": f"Pilot cohort\n\n{note}"},
            )
            assert saved.status_code == 200
            payload = saved.json()
            assert payload["draft_version"] == 2
            assert note in payload["material_body"]
            assert payload["publication_count"] == 0
            assert payload["action_count"] == 0
            assert payload["execution_count"] == 0

    anyio.run(scenario)


