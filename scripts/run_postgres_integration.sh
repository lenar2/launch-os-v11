#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.integration.yml}"
DATABASE_URL="${LAUNCH_OS_TEST_DATABASE_URL:-postgresql+psycopg://launch_os_v11:launch_os_v11@localhost:55432/launch_os_v11_test}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for PostgreSQL integration tests" >&2
  exit 1
fi

docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "${COMPOSE_FILE}" up -d postgres
trap 'docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

LAUNCH_OS_TEST_DATABASE_URL="${DATABASE_URL}" python3 - <<'PY'
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

LAUNCH_OS_DATABASE_URL="${DATABASE_URL}" \
LAUNCH_OS_TEST_DATABASE_URL="${DATABASE_URL}" \
python3 -m pytest -m postgres tests/integration
