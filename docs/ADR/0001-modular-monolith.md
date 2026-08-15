# ADR 0001: Modular Monolith First

Status: accepted
Date: 2026-08-15

## Context

Launch OS v11 needs strong domain boundaries, background workflows, event processing, connector sync, AI orchestration, and permissioned execution. It does not yet have scale evidence requiring distributed services.

Starting with microservices would increase deployment, observability, transaction, and data-consistency complexity before product behavior is proven.

## Decision

Build v11 as a modular monolith with asynchronous workers and event-driven boundaries.

Initial runtime:

- web frontend
- FastAPI API
- worker
- scheduler
- PostgreSQL
- pgvector
- Redis queue/cache
- S3-compatible object storage
- secrets layer
- reverse proxy

Use PostgreSQL transactional outbox for cross-module event publication.

## Consequences

Benefits:

- simpler local development and deployment
- easier refactoring while domain boundaries settle
- transactional consistency for core workflows
- lower operational load during pilot phase

Costs:

- strict module boundaries must be enforced by discipline and tests
- scaling individual workloads may require extraction later

## Guardrails

- Keep module boundaries explicit.
- Version event contracts.
- Keep jobs idempotent.
- Record ADRs before extracting services or adding infrastructure such as Kafka/Redpanda/NATS.
