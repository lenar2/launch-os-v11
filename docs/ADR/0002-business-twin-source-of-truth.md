# ADR 0002: Business Twin Is Source of Truth

Status: accepted
Date: 2026-08-15

## Context

v10 proved that chat memory, uploaded files, and giant AI outputs cannot safely represent the real state of a business. Launch OS v11 must answer historical, operational, and decision questions from durable business state with provenance.

## Decision

The Business Twin is the source of business state.

The LLM is never source of truth for:

- facts
- metrics
- current connector state
- historical state
- permissions
- approvals
- executions
- customer identity
- asset approval
- business commerce

Every important fact or metric retains source, timestamp/period, provenance, epistemic status, derivation, freshness, and business scope.

## Consequences

Benefits:

- deterministic analytics are possible
- historical questions can be answered correctly
- decisions can be audited
- late data can correct metric versions without erasing prior reasoning
- AI context can be purpose-limited and grounded

Costs:

- more domain modeling before features feel fast
- ingestion and reconciliation must be built early

## Guardrails

- Do not store important business state only in chat messages.
- Do not let model confidence promote hypotheses into facts.
- Decisions must reference immutable BusinessSnapshots.
- Metrics must expose calculation version and calculated_at.
