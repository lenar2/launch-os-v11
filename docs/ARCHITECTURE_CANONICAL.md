# Launch OS v11 Canonical Architecture

Status: canonical pre-code architecture
Date: 2026-08-15

## Canonical Operating Loop

Launch OS v11 is complete only when this loop closes:

`CONNECT -> OBSERVE -> UNDERSTAND -> DECIDE -> CREATE -> CONTROL -> EXECUTE -> MEASURE -> LEARN -> ADAPT`

Meaning:

- CONNECT: integrations, files, and events become available.
- OBSERVE: raw evidence is normalized into facts, metrics, and events.
- UNDERSTAND: context, patterns, hypotheses, gaps, and conflicts are formed.
- DECIDE: a concrete decision is selected among alternatives.
- CREATE: briefs and production assets are created.
- CONTROL: evidence, economics, brand, manipulation, legal, security, privacy, and quality gates run.
- EXECUTE: actions are performed under deterministic permission policy.
- MEASURE: outcomes are observed through connected systems.
- LEARN: observations are cautiously promoted into patterns and learnings.
- ADAPT: new decisions supersede previous decisions when evidence warrants it.

If the product stops at recommendation, it is not v11.

## Primary Architectural Boundary

The product is a connected digital organization:

- Business Twin holds business state.
- AI Organization reasons and creates.
- Controllers constrain and can block.
- Permission Engine decides whether action is allowed or requires approval.
- Execution Engine performs external writes.
- Connectors observe and execute provider-specific operations.
- Events, metrics, and learnings update future context.

Authority must not collapse into one universal Producer.

## Initial Runtime

Use a modular monolith plus asynchronous workers and event-driven boundaries.

Initial components:

- web frontend
- FastAPI API
- worker process
- scheduler
- PostgreSQL
- pgvector
- Redis queue/cache
- S3-compatible object storage
- secrets layer
- existing reverse proxy

Do not start with microservices. Kafka, Redpanda, or NATS are not required until actual scale justifies them.

## Backend Modules

Logical modules:

- `domain`
- `application`
- `ai_runtime`
- `connectors`
- `analytics`
- `production`
- `execution`
- `platform`

`application` owns commands, queries, workflows, and projections.

`platform` owns auth, tenancy, usage, billing for Launch OS itself, feature flags, events, jobs, storage, secrets, audit, and observability.

## Event Pattern

Use PostgreSQL transactional outbox plus queue workers.

Rules:

- Event contracts are versioned.
- Jobs are idempotent.
- External writes have idempotency protection.
- Webhook events are keyed by provider and external identity.
- Snapshot imports may correct webhook-derived state.
- Corrections create new metric versions or invalidations; they do not silently rewrite prior reasoning.

## Execution Boundary

AI agents do not directly mutate external systems.

Canonical write path:

`Agent -> ActionProposal -> Controllers -> Permission Engine -> Approval if required -> Execution Engine -> Connector -> External system -> Event/Audit`

Autonomy levels:

- Suggest
- Prepare
- Execute after approval
- Limited autopilot
- Policy autopilot

Autopilot is a deterministic policy state, not an agent personality.

Global controls:

- `AUTOMATION_PAUSED`
- `EXECUTION_PAUSED`
- `REVOKE_ALL_WRITE_CAPABILITIES`

## SaaS Platform Boundary

Launch OS is also a multi-tenant SaaS product.

Minimum platform entities:

- User
- Organization
- BusinessMembership
- Role and permission
- AuthIdentity
- LaunchOSPlan
- LaunchOSSubscription
- UsageRecord
- FeatureFlag
- AIQuota
- ConnectorLimit
- BillingStatus
- AccountExport
- AccountDeletionRequest

Do not mix Launch OS billing with the customer business commerce model.

## UX Boundary

The final product is a web application, not a chat transcript.

Core areas:

- Command Center
- Launches / Launch Room
- Social / Calendar / Analytics
- Content Studio
- Audience / CRM
- Products
- Campaigns
- Analytics / Experiments
- Decisions
- Approvals
- Automations
- Integrations
- Team
- Settings

Telegram is a companion surface for notifications, approvals, urgent alerts, quick commands, and simple status.

## Implementation Sequence

- v11.0E: UX and Information Architecture.
- v11.1: Core vertical slice.
- v11.2: Eyes - Instagram read/analytics, richer Telegram analytics, GetCourse, payments, backfill, reconciliation.
- v11.3: Full Command Center and Launch Room.
- v11.4: Social OS.
- v11.5: Creative Studio.
- v11.6: CRM/Retention.
- v11.7: YouTube, Tilda, email, analytics, ads as justified.
- v11.8: broader execution and automation.
- v11.9+: policy-controlled autopilot after sufficient real traces.

Every stage must close a smaller real loop. Do not expand broad modules until the current loop reaches a real external outcome.

## v10 Status

v10 is frozen as a research prototype and Producer proof of concept.

Preserve lessons:

- authentication foundations
- existing Telegram integration
- PostgreSQL operational experience
- evidence/hypothesis/confidence concepts
- decision/artifact/outcome concepts
- constitutional guard
- real OpenAI model integration
- deployment lessons
- giant text outputs are unacceptable
- deterministic parsing must replace user/manual arithmetic
- historical data cannot be reconstructed from current status
- recommendation is insufficient without create/act/measure/learn

Do not preserve as final architecture:

- one central Producer
- chat as business state
- giant message artifacts
- manual file upload as primary source
- user performing all external execution
- LLM inference where deterministic data processing is available
