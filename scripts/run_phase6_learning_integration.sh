#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.integration.yml}"
DATABASE_URL="${LAUNCH_OS_TEST_DATABASE_URL:-postgresql+psycopg://launch_os_v11:launch_os_v11@localhost:55432/launch_os_v11_test}"
REDIS_URL="${LAUNCH_OS_TEST_REDIS_URL:-redis://localhost:56379/0}"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for Phase 6 learning integration tests" >&2
  exit 1
fi

docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "${COMPOSE_FILE}" up -d postgres redis
trap 'docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

LAUNCH_OS_TEST_DATABASE_URL="${DATABASE_URL}" "${PYTHON_BIN}" - <<'PY'
import os
import time

import psycopg

database_url = os.environ["LAUNCH_OS_TEST_DATABASE_URL"].replace("+psycopg", "")
deadline = time.time() + 60
last_error: Exception | None = None
while time.time() < deadline:
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
        break
    except Exception as exc:
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(f"PostgreSQL did not become ready: {last_error}")
PY

LAUNCH_OS_TEST_REDIS_URL="${REDIS_URL}" "${PYTHON_BIN}" - <<'PY'
import os
import time

from redis import Redis

redis_url = os.environ["LAUNCH_OS_TEST_REDIS_URL"]
deadline = time.time() + 60
last_error: Exception | None = None
while time.time() < deadline:
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        if client.ping():
            client.close()
            break
    except Exception as exc:
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(f"Redis did not become ready: {last_error}")
PY

LAUNCH_OS_DATABASE_URL="${DATABASE_URL}" \
LAUNCH_OS_TEST_DATABASE_URL="${DATABASE_URL}" \
LAUNCH_OS_REDIS_URL="${REDIS_URL}" \
LAUNCH_OS_TEST_REDIS_URL="${REDIS_URL}" \
"${PYTHON_BIN}" -m pytest -m phase6_learning tests/integration
