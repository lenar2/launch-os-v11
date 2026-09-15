# ADR 0011: Disabled Business Outcome Instrumentation

Date: 2026-08-28

Status: Accepted

## Context

Phase 6 learning established an evidence gap for the proposed 30-second Telegram
reaction-change experiment. The observed data supports only a bounded failure signal for
that exact reaction metric and window. It does not support revenue impact, sales impact,
audience preference, or a causal business outcome claim.

Launch OS needs a governed way to represent stronger downstream business outcomes before
asking the owner to approve real data collection, external connectors, or production
experiments.

## Decision

Add a disabled, non-live business outcome instrumentation capability inside the modular
monolith:

- `OutcomeIngestionContract` defines allowed canonical business outcome event contracts.
- `OutcomeMetricDefinition` defines metric semantics, eligible population, denominator,
  observation window, attribution method, limitations, and data availability.
- `OutcomeMetricVersion` stores append-only calculated metric versions with source window,
  included `BusinessEvent` ids, calculation version, derivation hash, evidence link, and an
  explicit `synthetic_non_live` boundary.
- `OutcomeEconomicLink` stores append-only hypothetical/assumption/unknown economic
  interpretation in integer cents. In this disabled layer `supports_go` is hard-locked to
  `false` in both service logic and database constraints; synthetic or self-supplied
  economics cannot satisfy the real 3x authority gate.
- `OutcomeExperimentProposal` stores a disabled owner-review proposal artifact without
  creating a `Decision`, `Approval`, `Execution`, `Publication`, or external write.

Synthetic internal observations may be ingested into canonical `BusinessEvent` rows only
when the ingestion contract is `DISABLED_NON_LIVE`. Contracts require strict closed object
schemas (`additionalProperties=false`), payloads are validated against those schemas, and
raw identity fields, aliases, and secret-like payloads are rejected before persistence.
The disabled instrumentation schema contains no `ACTIVE` status; future live activation
requires a separate governed migration/service decision rather than mutating this layer.

## Consequences

Launch OS can now validate the internal chain:

synthetic observation fixture -> canonical `BusinessEvent` -> provenance/evidence ->
metric version -> economic link -> `Learning` -> disabled experiment proposal.

The capability does not activate real data collection, connect real external sources,
publish to Telegram, contact users, approve decisions, or execute production actions.

The next owner-only gate is activation of real data collection or connection of a real
business outcome data source, including any required privacy/legal decision.
