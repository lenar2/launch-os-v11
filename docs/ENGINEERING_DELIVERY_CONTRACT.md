# Engineering Delivery Contract

Status: canonical pre-code engineering gate
Date: 2026-08-15

## Purpose

This contract defines how Launch OS v11 code is allowed to begin and ship. It exists to prevent scope explosion, irreversible architecture drift, unsafe migrations, and untested AI/execution paths.

## Repository Rules

- `main` is protected conceptually, even in local development.
- Feature work happens on short-lived branches.
- Architecture changes require an ADR in `docs/ADR/`.
- v10 remains frozen; do not migrate v11 against a v10 production database during development.
- Day-1 canonical docs must be committed before feature code.
- Broad feature modules wait until the v11.1 closed loop passes acceptance.

## Environments

Required before production pilot:

- local development
- staging
- production

Staging must support:

- isolated database
- test Telegram channel or sandbox-equivalent publication target
- test secrets
- recorded/mock connector fixtures
- migration rehearsal
- rollback rehearsal

## CI Gate

CI must run:

- lint checks
- type checks
- domain unit tests
- deterministic analytics tests
- permission/controller tests
- connector normalization contract tests
- workflow integration tests
- AI schema/grounding evals
- security regression tests

No code path may require real production credentials in CI.

## Test Layers

Domain unit tests:

- entities
- value objects
- policy decisions
- epistemic status transitions
- identity graph rules

Deterministic analytics tests:

- late-arriving events
- metric versioning
- timezone windows
- reconciliation corrections
- causality class boundaries

Permission/controller tests:

- approval-required paths
- hard blocks
- conditional revisions
- global pause/revoke controls
- constitutional and manipulation violations

Connector contract tests:

- provider payload normalization
- duplicate event handling
- webhook/callback verification where supported
- stale readiness state
- dry-run/mock writes

Workflow integration tests:

- v11.1 vertical slice
- execution idempotency
- learning to next decision

AI evals:

- schema validity
- grounded evidence usage
- no person-worth inference
- no LLM arithmetic where deterministic calculation exists
- untrusted data prompt-injection fixtures

End-to-end staging:

- owner approval flow
- Telegram test publication
- observed result
- metric update
- next decision

## Migration Discipline

Every migration must define:

- purpose
- affected tables/indexes
- expected runtime
- rollback/downgrade strategy where supported
- data backfill plan if needed
- safety checks for production

Rules:

- migrations are reviewed before production use
- destructive changes require explicit approval and rollback plan
- large data backfills run as jobs, not request handlers
- schema changes that affect audit/history require extra review

## Release and Rollback

Before production deployment:

- staging tests pass
- migrations rehearsed
- database backup exists
- rollback procedure is written
- feature flags default to off for risky paths
- global write kill switch is verified

Rollback must preserve:

- audit trail
- approvals
- execution records
- external reference records
- BusinessSnapshot immutability

## Observability

Minimum telemetry:

- request logs with secret redaction
- job logs with idempotency keys
- connector health/freshness
- outbox lag
- worker failure/retry counts
- execution success/failure
- controller verdict distribution
- AI cost/usage by organization
- eval failures

AI traces must not contain secrets and must respect tenant isolation.

## Feature Flags

Feature flags are required for:

- each write-capable connector
- policy autopilot
- broad AI workflow changes
- experimental model routing changes
- new billing/usage limits
- high-risk ingestion processors

Feature flags do not bypass controller or permission checks.

## Done Means Closed Loop

v11.1 is not done because screens exist. It is done when the first closed loop passes:

`CreateLaunch -> BusinessSnapshot -> Decision -> controllers -> checkpoint -> CreativeBrief -> Asset -> review -> Approval -> Telegram publication -> observed result -> metric update -> Learning -> next Decision`

Until then, do not add another broad module.
