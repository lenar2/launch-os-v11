export PYTHONUTF8=1
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
PYTHON ?= python3

.PHONY: install lint type test test-migrations test-postgres check migrate downgrade run-api

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

type:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

test-migrations:
	$(PYTHON) -m pytest tests/test_migrations.py

test-postgres:
	./scripts/run_postgres_integration.sh

check: lint type test

migrate:
	$(PYTHON) -m alembic upgrade head

downgrade:
	$(PYTHON) -m alembic downgrade base

run-api:
	$(PYTHON) -m uvicorn launch_os_v11.api.main:app --reload
