"""Local Launch Room HTTP surface.

Mounted only for an explicit local or test runtime. A client-supplied user id
is never accepted as identity. The operator is the one this process created
when it opened the launch.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.page import render_error, render_home, render_room
from launch_os_v11.product.projection import LaunchRoomView
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime

router = APIRouter()
_CLIENT_IDENTITY_KEYS = {"actor_user_id", "owner_user_id", "user_id"}


def _service(request: Request) -> LaunchRoomService:
    runtime = getattr(request.app.state, "launch_room", None)
    if not isinstance(runtime, LaunchRoomRuntime):
        raise ProductError("not_authorized", "Launch Room is not mounted on this process.")
    return LaunchRoomService(runtime)


def _operators(request: Request) -> dict[str, TrustedOperator]:
    current = getattr(request.app.state, "launch_room_operators", None)
    if not isinstance(current, dict):
        current = {}
        request.app.state.launch_room_operators = current
    return current


def _bind(request: Request, view: LaunchRoomView) -> None:
    _operators(request)[view.launch_id] = TrustedOperator(
        user_id=view.owner_user_id,
        scope=TenantScope(
            organization_id=view.organization_id,
            business_id=view.business_id,
        ),
    )


def _bound(request: Request, launch_id: str) -> TrustedOperator:
    operator = _operators(request).get(launch_id)
    if operator is None:
        raise ProductError(
            "not_authorized",
            "This process has no trusted operator for that launch.",
        )
    return operator


def _reject_client_identity(payload: Mapping[str, object]) -> None:
    if any(key in payload for key in _CLIENT_IDENTITY_KEYS):
        raise ProductError(
            "identity_untrusted",
            "A client-supplied user id is not a trusted server identity.",
        )


def _public(view: LaunchRoomView) -> dict[str, object]:
    payload = view.to_dict()
    payload.pop("owner_user_id", None)
    return payload


def _status(exc: ProductError) -> int:
    if exc.code == "identity_untrusted":
        return 403
    if exc.code in {"not_found", "not_authorized", "scope_violation"}:
        return 404
    return 409


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    return {key: value for key, value in parse_qsl(raw, keep_blank_values=True)}


@router.get("/launch-room", response_class=HTMLResponse)
def launch_room_home() -> str:
    return render_home()


@router.post("/launch-room", response_model=None)
async def launch_room_open(request: Request) -> RedirectResponse | HTMLResponse:
    form = await _form(request)
    try:
        _reject_client_identity(form)
        view = _service(request).open_launch(
            business_name=form.get("business_name", ""),
            goal=form.get("goal", ""),
            offer_name=form.get("offer_name", ""),
            audience=form.get("audience") or None,
            known_fact=form.get("known_fact") or None,
            timezone=form.get("timezone") or "UTC",
        )
        _bind(request, view)
    except ProductError as exc:
        return HTMLResponse(render_error(str(exc)), status_code=_status(exc))
    return RedirectResponse(f"/launch-room/{view.launch_id}", status_code=303)


@router.get("/launch-room/{launch_id}", response_class=HTMLResponse)
def launch_room_page(request: Request, launch_id: str) -> HTMLResponse:
    try:
        operator = _bound(request, launch_id)
        view = _service(request).get_room(launch_id, operator=operator)
    except ProductError as exc:
        return HTMLResponse(render_error(str(exc)), status_code=_status(exc))
    return HTMLResponse(render_room(view))


@router.post("/launch-room/{launch_id}/{action}", response_model=None)
async def launch_room_action(
    request: Request,
    launch_id: str,
    action: str,
) -> RedirectResponse | HTMLResponse:
    form = await _form(request)
    try:
        _reject_client_identity(form)
        view = _perform(request, launch_id, action, form)
    except ProductError as exc:
        return HTMLResponse(render_error(str(exc)), status_code=_status(exc))
    del view
    return RedirectResponse(f"/launch-room/{launch_id}", status_code=303)


@router.post("/api/launch-room")
async def api_open(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(
            {"code": "invalid_input", "message": "JSON object required"},
            status_code=400,
        )
    try:
        _reject_client_identity(payload)
        view = _service(request).open_launch(
            business_name=str(payload.get("business_name", "")),
            goal=str(payload.get("goal", "")),
            offer_name=str(payload.get("offer_name", "")),
            audience=_optional_str(payload.get("audience")),
            known_fact=_optional_str(payload.get("known_fact")),
            timezone=str(payload.get("timezone") or "UTC"),
        )
        _bind(request, view)
    except ProductError as exc:
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=_status(exc))
    return JSONResponse(_public(view))


@router.get("/api/launch-room/{launch_id}")
def api_get(request: Request, launch_id: str) -> JSONResponse:
    try:
        operator = _bound(request, launch_id)
        return JSONResponse(_public(_service(request).get_room(launch_id, operator=operator)))
    except ProductError as exc:
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=_status(exc))


@router.post("/api/launch-room/{launch_id}/{action}")
async def api_action(request: Request, launch_id: str, action: str) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    try:
        _reject_client_identity(payload)
        view = _perform(request, launch_id, action, payload)
    except ProductError as exc:
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=_status(exc))
    return JSONResponse(_public(view))


def _perform(
    request: Request,
    launch_id: str,
    action: str,
    payload: Mapping[str, object],
) -> LaunchRoomView:
    service = _service(request)
    operator = _bound(request, launch_id)
    note = _text(payload, "note")
    if action == "decision":
        return service.run_team_decision(launch_id, operator=operator)
    if action == "revision":
        return service.request_revision(launch_id, note, operator=operator)
    if action == "approve":
        return service.approve(launch_id, operator=operator)
    if action == "materials":
        return service.prepare_materials(launch_id, operator=operator)
    if action == "note":
        return service.record_manual_note(launch_id, note, operator=operator)
    if action == "message":
        return service.record_untrusted_message(
            launch_id,
            _text(payload, "message"),
            operator=operator,
        )
    if action == "adapt":
        return service.adapt(launch_id, operator=operator)
    raise ProductError("not_found", "Unknown room action.")


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key, "")
    return value if isinstance(value, str) else ""


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
