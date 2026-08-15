from fastapi.testclient import TestClient

from launch_os_v11.api.app import create_app
from launch_os_v11.platform.config import Settings


def test_health_endpoints() -> None:
    app = create_app(
        Settings(
            LAUNCH_OS_ENV="test",
            LAUNCH_OS_DATABASE_URL="sqlite:///:memory:",
            LAUNCH_OS_ENABLE_DB_HEALTHCHECK=False,
        )
    )
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok", "database": "not_checked"}
