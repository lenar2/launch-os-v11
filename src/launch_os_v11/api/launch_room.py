"""Local Launch Room HTTP surface. It does not publish and does not call a model provider."""

from __future__ import annotations

from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from launch_os_v11.product.errors import ProductError
from launch_os_v11.product.page import render_error, render_home, render_room
from launch_os_v11.product.room import LaunchRoomService
from launch_os_v11.product.runtime import LaunchRoomRuntime

router = APIRouter()


def _service(request: Request) -> LaunchRoomService:
    runtime = getattr(request.app.state, "launch_room", None)
    if not isinstance(runtime, LaunchRoomRuntime):
        runtime = LaunchRoomRuntime.local_file()
        request.app.state.launch_room = runtime
    return LaunchRoomService(runtime)


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
        view = _service(request).open_launch(
            business_name=form.get("business_name", ""),
            goal=form.get("goal", ""),
            offer_name=form.get("offer_name", ""),
            audience=form.get("audience") or None,
            known_fact=form.get("known_fact") or None,
            timezone=form.get("timezone") or "UTC",
        )
    except ProductError as exc:
        return HTMLResponse(render_error(str(exc)), status_code=400)
    return RedirectResponse(f"/launch-room/{view.launch_id}", status_code=303)


@router.get("/launch-room/{launch_id}", response_class=HTMLResponse)
def launch_room_page(request: Request, launch_id: str) -> HTMLResponse:
    try:
        view = _service(request).get_room(launch_id)
    except ProductError as exc:
        return HTMLResponse(render_error(str(exc)), status_code=404)
    return HTMLResponse(render_room(view))


@router.post("/launch-room/{launch_id}/{action}", response_model=None)
async def launch_room_action(
    request: Request,
    launch_id: str,
    action: str,
) -> RedirectResponse | HTMLResponse:
    form = await _form(request)
    service = _service(request)
    try:
        if action == "decision":
            service.run_team_decision(launch_id)
        elif action == "revision":
            service.request_revision(
                launch_id,
                form.get("note", ""),
                actor_user_id=form.get("actor_user_id", ""),
            )
        elif action == "approve":
            service.approve(launch_id, actor_user_id=form.get("actor_user_id", ""))
        elif action == "materials":
            service.prepare_materials(launch_id)
        elif action == "note":
            service.record_manual_note(launch_id, form.get("note", ""))
        elif action == "adapt":
            service.adapt(launch_id)
        else:
            raise ProductError("not_found", "Unknown room action.")
    except ProductError as exc:
        status = 404 if exc.code == "not_found" else 409
        return HTMLResponse(render_error(str(exc)), status_code=status)
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
        view = _service(request).open_launch(
            business_name=str(payload.get("business_name", "")),
            goal=str(payload.get("goal", "")),
            offer_name=str(payload.get("offer_name", "")),
            audience=_optional_str(payload.get("audience")),
            known_fact=_optional_str(payload.get("known_fact")),
            timezone=str(payload.get("timezone") or "UTC"),
        )
    except ProductError as exc:
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=400)
    return JSONResponse(view.to_dict())


@router.get("/api/launch-room/{launch_id}")
def api_get(request: Request, launch_id: str) -> JSONResponse:
    try:
        return JSONResponse(_service(request).get_room(launch_id).to_dict())
    except ProductError as exc:
        status = 404 if exc.code == "not_found" else 409
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=status)


@router.post("/api/launch-room/{launch_id}/{action}")
async def api_action(request: Request, launch_id: str, action: str) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    service = _service(request)
    try:
        if action == "decision":
            view = service.run_team_decision(launch_id)
        elif action == "revision":
            view = service.request_revision(
                launch_id,
                str(payload.get("note", "")),
                actor_user_id=str(payload.get("actor_user_id", "")),
            )
        elif action == "approve":
            view = service.approve(launch_id, actor_user_id=str(payload.get("actor_user_id", "")))
        elif action == "materials":
            view = service.prepare_materials(launch_id)
        elif action == "note":
            view = service.record_manual_note(launch_id, str(payload.get("note", "")))
        elif action == "message":
            view = service.record_untrusted_message(launch_id, str(payload.get("message", "")))
        elif action == "adapt":
            view = service.adapt(launch_id)
        else:
            raise ProductError("not_found", "Unknown room action.")
    except ProductError as exc:
        status = 404 if exc.code == "not_found" else 409
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=status)
    return JSONResponse(view.to_dict())


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
