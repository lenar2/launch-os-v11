from fastapi import FastAPI
from fastapi.responses import JSONResponse

from launch_os_v11.api.launch_room import router as launch_room_router
from launch_os_v11.api.readiness import ReadinessChecker, check_database_readiness
from launch_os_v11.platform.config import Settings, get_settings
from launch_os_v11.product.runtime import LaunchRoomRuntime


def create_app(
    settings: Settings | None = None,
    readiness_checker: ReadinessChecker = check_database_readiness,
    launch_room: LaunchRoomRuntime | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    app = FastAPI(
        title="Launch OS v11",
        version="0.1.0",
        docs_url="/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.launch_room = None
    app.state.launch_room_operators = {}
    if runtime_settings.environment in {"local", "test"} and launch_room is not None:
        app.state.launch_room = launch_room
        app.include_router(launch_room_router)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        readiness = readiness_checker(runtime_settings)
        status_code = 200 if readiness.ready else 503
        status = "ok" if readiness.ready else "not_ready"
        payload = {
            "status": status,
            "database": readiness.database,
            "detail": readiness.detail,
            "migration_version": readiness.migration_version,
            "expected_migration_version": readiness.expected_migration_version,
        }
        return JSONResponse(status_code=status_code, content=payload)

    return app
