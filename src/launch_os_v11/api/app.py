from fastapi import FastAPI
from sqlalchemy import text

from launch_os_v11.persistence.session import create_engine_from_settings
from launch_os_v11.platform.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    app = FastAPI(
        title="Launch OS v11",
        version="0.1.0",
        docs_url="/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
    )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        if not runtime_settings.enable_db_healthcheck:
            return {"status": "ok", "database": "not_checked"}

        engine = create_engine_from_settings(runtime_settings)
        try:
            with engine.connect() as connection:
                connection.execute(text("select 1"))
        finally:
            engine.dispose()
        return {"status": "ok", "database": "ok"}

    return app
