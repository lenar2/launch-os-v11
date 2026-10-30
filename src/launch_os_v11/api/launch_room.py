"""Local Launch Room HTTP surface.

A browser receives a server-minted client grant in an HttpOnly cookie. The
grant is not a user id. launch_id, owner_user_id, and any request field do
not grant the owner. Staging and production do not mount this router.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from launch_os_v11.product.access import TrustedOperator
from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.grant import (
    CLIENT_COOKIE,
    FORBIDDEN_CLIENT_FIELDS,
    known_client,
    new_client_secret,
    operator_for_client,
    remember_client,
)
from launch_os_v11.product.page import render_error, render_home, render_room
from launch_os_v11.product.projection import LaunchRoomView
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime

router = APIRouter()


def _runtime(request: Request) -> LaunchRoomRuntime:
    runtime = getattr(request.app.state, "launch_room", None)
    if not isinstance(runtime, LaunchRoomRuntime):
        raise ProductError("not_authorized", "Launch Room is not mounted on this process.")
    return runtime


def _service(request: Request) -> LaunchRoomService:
    return LaunchRoomService(_runtime(request))


def _reject_client_fields(payload: Mapping[str, object]) -> None:
    if any(key in payload for key in FORBIDDEN_CLIENT_FIELDS):
        raise ProductError(
            "identity_untrusted",
            "A client-supplied user id or grant is not authority.",
        )


def _status(exc: ProductError) -> int:
    if exc.code == "identity_untrusted":
        return 403
    if exc.code in {"not_found", "not_authorized", "scope_violation"}:
        return 404
    return 409


def _json_error(exc: ProductError) -> JSONResponse:
    return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=_status(exc))


def _html_error(exc: ProductError) -> HTMLResponse:
    return HTMLResponse(render_error(str(exc)), status_code=_status(exc))


def _public(view: LaunchRoomView) -> dict[str, object]:
    payload = view.to_dict()
    payload.pop("owner_user_id", None)
    return payload


def _stamp(response: Response, secret: str) -> None:
    response.set_cookie(
        CLIENT_COOKIE,
        secret,
        httponly=True,
        samesite="lax",
        path="/",
        secure=False,
    )


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    return dict(parse_qsl(raw, keep_blank_values=True))


async def _json_body(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ProductError("invalid_input", "JSON object required") from exc
    if not isinstance(payload, dict):
        raise ProductError("invalid_input", "JSON object required")
    return payload


def _secret_for_open(request: Request) -> str:
    presented = request.cookies.get(CLIENT_COOKIE, "")
    session = _runtime(request).session_factory()
    try:
        if known_client(session, presented):
            return presented
    finally:
        session.close()
    return new_client_secret()


def _bind(request: Request, secret: str, view: LaunchRoomView) -> None:
    session = _runtime(request).session_factory()
    try:
        with session.begin():
            remember_client(session, secret=secret, view=view)
    finally:
        session.close()


def _operator(request: Request, launch_id: str) -> TrustedOperator:
    secret = request.cookies.get(CLIENT_COOKIE, "")
    session = _runtime(request).session_factory()
    try:
        operator = operator_for_client(session, secret=secret, launch_id=launch_id)
    finally:
        session.close()
    if operator is None:
        raise ProductError(
            "not_authorized",
            "This browser has no client grant for that launch.",
        )
    return operator


@router.get("/launch-room", response_class=HTMLResponse)
def launch_room_home(request: Request) -> HTMLResponse:
    try:
        _reject_client_fields(dict(request.query_params))
    except ProductError as exc:
        return _html_error(exc)
    return HTMLResponse(render_home())


@router.post("/launch-room", response_model=None)
async def launch_room_open(request: Request) -> Response:
    form = await _form(request)
    try:
        _reject_client_fields(form)
        _reject_client_fields(dict(request.query_params))
        view = _service(request).open_launch(
            business_name=form.get("business_name", ""),
            goal=form.get("goal", ""),
            offer_name=form.get("offer_name", ""),
            audience=form.get("audience") or None,
            known_fact=form.get("known_fact") or None,
            timezone=form.get("timezone") or "UTC",
        )
        secret = _secret_for_open(request)
        _bind(request, secret, view)
    except ProductError as exc:
        return _html_error(exc)
    response = RedirectResponse(f"/launch-room/{view.launch_id}", status_code=303)
    _stamp(response, secret)
    return response


@router.get("/launch-room/{launch_id}", response_class=HTMLResponse)
def launch_room_page(request: Request, launch_id: str) -> HTMLResponse:
    try:
        _reject_client_fields(dict(request.query_params))
        operator = _operator(request, launch_id)
        view = _service(request).get_room(launch_id, operator=operator)
        team_html = _service(request).launch_team_html(launch_id, operator=operator)
    except ProductError as exc:
        return _html_error(exc)
    return HTMLResponse(render_room(view, team_html))


@router.post("/launch-room/{launch_id}/{action}", response_model=None)
async def launch_room_action(request: Request, launch_id: str, action: str) -> Response:
    form = await _form(request)
    try:
        _reject_client_fields(form)
        _reject_client_fields(dict(request.query_params))
        _perform(request, launch_id, action, form)
    except ProductError as exc:
        return _html_error(exc)
    response = RedirectResponse(f"/launch-room/{launch_id}", status_code=303)
    return response


@router.post("/api/launch-room")
async def api_open(request: Request) -> JSONResponse:
    try:
        payload = await _json_body(request)
        _reject_client_fields(payload)
        _reject_client_fields(dict(request.query_params))
        view = _service(request).open_launch(
            business_name=str(payload.get("business_name", "")),
            goal=str(payload.get("goal", "")),
            offer_name=str(payload.get("offer_name", "")),
            audience=_optional_str(payload.get("audience")),
            known_fact=_optional_str(payload.get("known_fact")),
            timezone=str(payload.get("timezone") or "UTC"),
        )
        secret = _secret_for_open(request)
        _bind(request, secret, view)
    except ProductError as exc:
        return _json_error(exc)
    response = JSONResponse(_public(view))
    _stamp(response, secret)
    return response


@router.get("/api/launch-room/{launch_id}")
def api_get(request: Request, launch_id: str) -> JSONResponse:
    try:
        _reject_client_fields(dict(request.query_params))
        operator = _operator(request, launch_id)
        view = _service(request).get_room(launch_id, operator=operator)
    except ProductError as exc:
        return _json_error(exc)
    return JSONResponse(_public(view))


@router.post("/api/launch-room/{launch_id}/{action}")
async def api_action(request: Request, launch_id: str, action: str) -> JSONResponse:
    try:
        payload = await _json_body(request)
        _reject_client_fields(payload)
        _reject_client_fields(dict(request.query_params))
        view = _perform(request, launch_id, action, payload)
    except ProductError as exc:
        return _json_error(exc)
    return JSONResponse(_public(view))


def _perform(
    request: Request,
    launch_id: str,
    action: str,
    payload: Mapping[str, object],
) -> LaunchRoomView:
    service = _service(request)
    operator = _operator(request, launch_id)
    note = _text(payload, "note")
    if action == "decision":
        return service.run_team_decision(launch_id, operator=operator)
    if action == "revision":
        return service.request_revision(launch_id, note, operator=operator)
    if action == "approve":
        return service.approve(launch_id, operator=operator)
    if action == "materials":
        return service.prepare_materials(launch_id, operator=operator)
    if action == "draft":
        return service.save_draft(launch_id, _text(payload, "body"), operator=operator)
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
    if action == "team":
        return service.run_launch_team(launch_id, operator=operator)
    if action == "team-change":
        return service.apply_team_change(
            launch_id,
            operator=operator,
            budget_cents=_optional_int(payload.get("budget_cents")),
            weeks=_optional_int(payload.get("weeks")),
            offer_wording=_optional_str(payload.get("offer_wording")),
        )
    raise ProductError("not_found", "Unknown room action.")


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key, "")
    return value if isinstance(value, str) else ""


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
