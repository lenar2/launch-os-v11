import anyio
import httpx

from launch_os_v11.api.app import create_app
from launch_os_v11.api.readiness import ReadinessResult
from launch_os_v11.platform.config import Settings


async def _get_json(app, path: str) -> tuple[int, dict[str, object]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


def test_live_endpoint_only_checks_process_liveness() -> None:
    app = create_app(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL="postgresql+psycopg://localhost/test",
        )
    )

    status_code, payload = anyio.run(_get_json, app, "/health/live")

    assert status_code == 200
    assert payload == {"status": "ok"}


def test_ready_endpoint_returns_200_when_database_gate_passes() -> None:
    def ready_checker(_: Settings) -> ReadinessResult:
        return ReadinessResult(
            ready=True,
            database="ok",
            detail="ready",
            migration_version="0001_initial_domain_core",
            expected_migration_version="0001_initial_domain_core",
        )

    app = create_app(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL="postgresql+psycopg://localhost/test",
        ),
        readiness_checker=ready_checker,
    )

    status_code, payload = anyio.run(_get_json, app, "/health/ready")

    assert status_code == 200
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["migration_version"] == "0001_initial_domain_core"


def test_health_does_not_require_openai_key_when_ai_team_feature_is_disabled() -> None:
    def ready_checker(_: Settings) -> ReadinessResult:
        return ReadinessResult(
            ready=True,
            database="ok",
            detail="ready",
            migration_version="0003_phase2b_ai_runtime",
            expected_migration_version="0003_phase2b_ai_runtime",
        )

    app = create_app(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL="postgresql+psycopg://localhost/test",
            LAUNCH_OS_FEATURE_V11_AI_TEAM=False,
            OPENAI_API_KEY=None,
        ),
        readiness_checker=ready_checker,
    )

    status_code, payload = anyio.run(_get_json, app, "/health/ready")

    assert status_code == 200
    assert payload["status"] == "ok"


def test_ready_endpoint_returns_503_when_database_is_not_checked_or_not_postgres() -> None:
    app = create_app(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL="sqlite:///:memory:",
        )
    )

    status_code, payload = anyio.run(_get_json, app, "/health/ready")

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] == "not_postgresql"
