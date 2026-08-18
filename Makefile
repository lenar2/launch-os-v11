.PHONY: install check test test-migrations test-postgres test-runtime test-ai-runtime test-decision-workflow test-production-workflow test-telegram-execution migrate downgrade run-api

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e ".[dev]"

check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy
	$(PYTHON) -m pytest -m "not postgres"

test: check

test-migrations:
	$(PYTHON) -m pytest tests/test_migrations.py

test-postgres:
	PYTHON=$(PYTHON) ./scripts/run_postgres_integration.sh

test-runtime:
	PYTHON=$(PYTHON) ./scripts/run_runtime_integration.sh

test-ai-runtime:
	PYTHON=$(PYTHON) ./scripts/run_ai_runtime_integration.sh

test-decision-workflow:
	PYTHON=$(PYTHON) ./scripts/run_decision_workflow_integration.sh

test-production-workflow:
	PYTHON=$(PYTHON) ./scripts/run_production_workflow_integration.sh

test-telegram-execution:
	PYTHON=$(PYTHON) ./scripts/run_telegram_execution_integration.sh

migrate:
	$(PYTHON) -m alembic upgrade head

downgrade:
	$(PYTHON) -m alembic downgrade base

run-api:
	$(PYTHON) -m uvicorn launch_os_v11.api.main:app --reload
