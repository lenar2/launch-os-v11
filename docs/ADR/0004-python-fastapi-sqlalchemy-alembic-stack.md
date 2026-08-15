# ADR 0004: Python FastAPI, SQLAlchemy, Alembic, and Pydantic Settings

Status: accepted
Date: 2026-08-15

## Context

Phase 0 and Phase 1 need a working modular monolith skeleton, object-based domain persistence, migrations, local PostgreSQL/Redis configuration, CI checks, and environment-variable driven configuration. The canonical architecture names FastAPI, PostgreSQL, Redis, and a modular monolith.

The first implementation phase must avoid microservices, production secrets, external connectors, AI runtime execution, and broad dependencies.

## Decision

Use:

- FastAPI for the thin HTTP application skeleton and health endpoints.
- SQLAlchemy 2.x ORM/Core for persistence mappings and repositories.
- Alembic for versioned migrations and downgrade checks.
- Pydantic Settings for environment-variable driven configuration.
- Pytest for tests, Ruff for linting, and mypy for type checks.

Use PostgreSQL as the intended local/staging database through Docker Compose, while keeping the initial migration compatible with SQLite so CI and local machines without Docker can still verify migration upgrade/downgrade behavior without production infrastructure.

## Consequences

Benefits:

- aligns with the canonical runtime
- supports transactional outbox in the same database transaction
- gives explicit migration history and rollback tests
- keeps the FastAPI boundary thin and testable
- avoids production secret usage

Costs:

- SQLAlchemy models must be kept aligned with domain objects and migrations
- SQLite compatibility limits some PostgreSQL-specific types in the initial migration

## Guardrails

- Domain code must not import FastAPI, AI runtime, or connectors.
- Repositories must require tenant/business scope for business-scoped records.
- Environment variables configure runtime behavior; production secrets are not present in the repo.
- Docker Compose files are for local/staging only.
- Any future provider-specific connector or AI runtime dependency requires a separate ADR or documented justification.
