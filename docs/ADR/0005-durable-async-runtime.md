# ADR 0005: Durable Async Runtime Spine

Status: accepted
Date: 2026-08-15

## Context

Phase 2A needs durable asynchronous execution without starting Phase 2B AI runtime,
connectors, Telegram publication, frontend, or microservices.

Launch OS v11 canonical architecture requires PostgreSQL transactional outbox,
idempotent jobs, Redis queue/cache, worker, and scheduler. Redis must not become
the system of record for domain/runtime state.

## Decision

Use PostgreSQL `jobs` as the durable source of truth for runtime state and Redis
as a lightweight wakeup/delivery transport that carries only `job_id`.

Runtime semantics:

- PostgreSQL stores job status, attempts, leases, retry schedule, idempotency,
  errors, tenant scope, correlation, and causation.
- Redis delivery is at-least-once and may duplicate or lose messages.
- Duplicate Redis delivery is safe because workers must atomically claim the
  PostgreSQL job before running a handler.
- Lost Redis messages are repaired by the scheduler/reconciliation loop scanning
  due PostgreSQL jobs.
- Expired `RUNNING` leases are recovered back to retryable state or terminal
  failure when attempts are exhausted.
- `outbox.dispatch` and `runtime.probe` are the only executable Phase 2A
  handlers.
- AI, controller, workflow, Telegram, experiment, and learning job identifiers
  are registered as reserved contracts only.

## Dependency

Use `redis-py`, already present in the project dependency set, for Redis access.
Do not add Kafka, Celery, NATS, Redpanda, or a generic automation builder for
Phase 2A.

## Consequences

Positive:

- Job state survives Redis loss and worker crashes.
- Worker execution is idempotent at the job claim boundary.
- Outbox dispatch can be retried without creating multiple logical jobs.
- The design keeps the modular monolith intact.

Tradeoffs:

- Redis messages are not treated as durable work records.
- Scheduler reconciliation is required for liveness.
- Handlers must be explicit, registered, and tenant scoped.

## Non-Scope

This ADR does not authorize AI agent execution, controller logic, Telegram
publishing, external connectors, frontend work, autopilot, or microservices.
