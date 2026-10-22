"""Launch Room HTTP refusal.

There is no trusted multi-user authenticator. A launch id in a shared process
map is not an owner credential, so these routes do not read or change a room.
The single-user contour is the in-process LaunchRoomService.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.page import render_error

router = APIRouter()
_CLIENT_IDENTITY_KEYS = {"actor_user_id", "owner_user_id", "user_id"}
_HTTP_AUTHORITY = ProductError(
    "http_authority_unavailable",
    "Launch Room HTTP is not a multi-user authority surface. "
    "A launch id does not grant the owner.",
)


def _reject_client_identity(payload: Mapping[str, str | object]) -> None:
    if any(key in payload for key in _CLIENT_IDENTITY_KEYS):
        raise ProductError(
            "identity_untrusted",
            "A client-supplied user id is not a trusted server identity.",
        )


def _status(exc: ProductError) -> int:
    if exc.code in {"identity_untrusted", "http_authority_unavailable"}:
        return 403
    if exc.code == "invalid_input":
        return 400
    return 409


def _json_error(exc: ProductError) -> JSONResponse:
    return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=_status(exc))


def _html_error(exc: ProductError) -> HTMLResponse:
    return HTMLResponse(render_error(str(exc)), status_code=_status(exc))


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    return {key: value for key, value in parse_qsl(raw, keep_blank_values=True)}


async def _json_body(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ProductError("invalid_input", "JSON object required") from exc
    if not isinstance(payload, dict):
        raise ProductError("invalid_input", "JSON object required")
    return payload


@router.get("/launch-room", response_class=HTMLResponse)
def launch_room_home() -> HTMLResponse:
    return _html_error(_HTTP_AUTHORITY)


@router.post("/launch-room", response_model=None)
async def launch_room_open(request: Request) -> HTMLResponse:
    try:
        _reject_client_identity(await _form(request))
    except ProductError as exc:
        return _html_error(exc)
    return _html_error(_HTTP_AUTHORITY)


@router.get("/launch-room/{launch_id}", response_class=HTMLResponse)
def launch_room_page(launch_id: str) -> HTMLResponse:
    del launch_id
    return _html_error(_HTTP_AUTHORITY)


@router.post("/launch-room/{launch_id}/{action}", response_model=None)
async def launch_room_action(request: Request, launch_id: str, action: str) -> HTMLResponse:
    del launch_id, action
    try:
        _reject_client_identity(await _form(request))
    except ProductError as exc:
        return _html_error(exc)
    return _html_error(_HTTP_AUTHORITY)


@router.post("/api/launch-room")
async def api_open(request: Request) -> JSONResponse:
    try:
        _reject_client_identity(await _json_body(request))
    except ProductError as exc:
        return _json_error(exc)
    return _json_error(_HTTP_AUTHORITY)


@router.get("/api/launch-room/{launch_id}")
def api_get(launch_id: str) -> JSONResponse:
    del launch_id
    return _json_error(_HTTP_AUTHORITY)


@router.post("/api/launch-room/{launch_id}/{action}")
async def api_action(request: Request, launch_id: str, action: str) -> JSONResponse:
    del launch_id, action
    try:
        _reject_client_identity(await _json_body(request))
    except ProductError as exc:
        return _json_error(exc)
    return _json_error(_HTTP_AUTHORITY)
