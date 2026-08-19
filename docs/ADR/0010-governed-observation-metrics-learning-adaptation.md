# ADR 0010: Governed Observation, Metrics, Learning, and Adaptation

Status: accepted pre-code Phase 6 contract
Date: 2026-08-19
Base: `591ef086145d727920f883daa6ff5aadbea77928`

## Context

Phase 5 has implemented the governed external-write boundary through Telegram. Phase 6 must close the remaining v11.1 loop:

`Publication -> Observe -> Measure -> Interpret -> Learn -> Adapt -> next Decision`

The canonical architecture requires late events to apply to event time, deterministic metric calculation, explicit attribution/causality boundaries, versioned derived metrics, cautious learning, and a next Decision that supersedes the prior Decision without rewriting history.

The current persistence foundation is intentionally incomplete for this phase:

- `BusinessEventModel` exists but does not yet carry a complete connector-event identity/coverage contract by itself.
- `MetricVersion` is required by the v11.1 canon but is not implemented.
- `LearningModel` exists but does not yet bind metric versions, interpretation class, limits, or controller provenance.
- `ExperimentRuleModel` stores `window` and thresholds as free-form strings. Those strings are useful human descriptions but are not sufficient for deterministic checkpoint evaluation.
- Existing Phase 5 live acceptance evidence must not be retrofitted to a different metric or checkpoint after publication. Experiment semantics are immutable once execution begins.

## Decision

Phase 6 will implement one governed observation/learning workflow. It will not broaden integrations.

Canonical path:

`ExternalReference/Publication -> Telegram observation cursor -> immutable connector observation -> normalized BusinessEvent -> deterministic MetricVersion -> deterministic checkpoint result -> Attribution/Learning/Stability governance -> immutable Learning -> owner-gated next Decision workflow -> successor Decision`

Telegram publication success is not an observation of audience outcome, and an observation is not automatically a learning.

## Hard Invariants

1. Raw provider payloads are untrusted data only. They cannot trigger tools, permissions, or external writes from their text.
2. Provider events are append-only and idempotent. Duplicate delivery cannot inflate metrics.
3. `event_time` is distinct from `ingested_at`/`recorded_at`. Late data applies to the source event period.
4. Missing, stale, partial, or unavailable data is never represented as numeric zero.
5. Metric arithmetic is deterministic code. An LLM never calculates metric values.
6. Every MetricVersion exposes calculation version, source window, source events, calculated_at, and coverage status.
7. Corrections or late events create a new MetricVersion or explicit invalidation. Prior metric versions are never silently rewritten.
8. Checkpoint rules are fixed in a machine-readable form before the corresponding external execution. Phase 6 may not reinterpret a historical free-form threshold after seeing an outcome.
9. Attribution is not causality. Direct lineage from a Telegram update to a `message_id` does not prove that copy or strategy caused a business outcome.
10. Learning cannot upgrade the deterministic attribution/causality ceiling established by the system.
11. A single weak trace may create a bounded learning with explicit limits; it cannot silently become a general business rule.
12. A Learning cannot directly execute or mutate an external system.
13. Adaptation creates a new Decision. It never edits the prior Decision.
14. In v11.1, starting the successor Decision from a single live trace is owner-gated. Later autonomy requires separate policy evidence and is out of scope.
15. A successor may reference `supersedes_decision_id`, but the prior approved Decision is not treated as replaced operationally until the successor reaches its required owner approval state.

## Pre-execution Checkpoint Contract

Phase 6 introduces a typed checkpoint definition that is materialized at Decision creation time, before production/execution.

The existing human-readable ExperimentRule fields remain for display/history. A new immutable machine contract binds at minimum:

- experiment ID and ExperimentRule ID
- schema version
- metric key
- publication/external-reference anchor policy
- source window anchor
- window duration
- provider delay/grace allowance where required
- success condition
- weak-signal condition
- failure condition
- coverage requirement
- attribution method
- next action for each result class
- deterministic contract hash
- created_at

Threshold conditions use typed operators and typed values, not natural-language parsing at checkpoint time.

If no valid typed checkpoint exists, external execution for a Phase-6-governed experiment fails closed before publication. Historical Phase 5 acceptance remains valid as Phase 5 evidence, but it is not silently upgraded into a Phase 6 experiment.

## Telegram Observation Contract

v11.1 uses the existing Bot API connector and adds read-side observation through one configured update transport.

For the first vertical slice, long polling with `getUpdates` is acceptable when no webhook is configured. Polling and webhook modes must not run simultaneously for one bot account.

Persist per connector account:

- observation mode
- last durably processed Telegram `update_id`
- last successful poll/ingest time
- freshness state
- gap/coverage state
- relevant allowed update classes

For the Phase 6 Telegram slice, subscribe explicitly to the update classes needed by the metric, including reaction updates when reactions are used. Reaction updates require the bot to have the provider permissions required by Telegram.

The polling commit rule is:

1. request updates after the last durably processed cursor;
2. persist raw observations and normalized events transactionally/idempotently;
3. advance the durable local cursor only after persistence succeeds;
4. provider redelivery is safe because provider-event identity is unique.

The connector must expose stale/gap conditions. Telegram update retention limits make freshness part of metric truth.

## Connector Observation

A connector observation is immutable and contains at minimum:

- organization/business scope
- connector account ID
- provider
- provider event identity (`update_id` for Telegram)
- provider event type
- external object identity (`message_id` when present)
- `event_time`
- `ingested_at`
- raw payload or durable raw source reference
- payload hash
- provenance/trust class

Uniqueness for Telegram is scoped to connector account + `update_id`.

The raw observation is then normalized into `BusinessEventModel`. The normalized BusinessEvent retains a durable reference to its raw observation/source provenance.

## MetricVersion

Phase 6 adds `MetricVersion` as an append-only derived fact.

Minimum fields:

- organization/business scope
- metric key
- subject type and subject ID (Publication for the first slice)
- source provider/account
- version number
- value and value type
- availability status: `AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, or `STALE`
- coverage status
- source window start/end
- included BusinessEvent IDs
- excluded-event rule/version
- calculation version
- calculated_at
- previous/superseded MetricVersion reference where applicable
- derivation hash

A value of `0` is legal only when the calculation has sufficient source coverage to prove zero for the defined metric/window. Otherwise the version is unavailable/partial/stale and has no fabricated numeric zero.

For the first live Telegram Phase 6 acceptance, use a Telegram-native metric that the Bot API can actually observe. Do not claim impressions/views/sales if the current connector scope does not provide them.

A suitable minimal acceptance metric is a bounded publication reaction signal, such as observed reaction-change activity for the exact published `message_id`, with source coverage explicitly recorded. This metric is an engagement signal only; it is not a sales or causal metric.

## Checkpoint Interpretation

Checkpoint interpretation is deterministic-first.

Inputs:

- immutable typed checkpoint definition
- exact MetricVersion
- coverage/freshness state
- experiment identity

Result classes:

- `SUCCESS`
- `WEAK_SIGNAL`
- `FAILURE`
- `INSUFFICIENT_DATA`

The interpreter stores an immutable ExperimentResult binding the exact rule contract and MetricVersion used. `INSUFFICIENT_DATA` is mandatory when coverage requirements are not met.

No LLM may choose a different threshold after seeing the result.

## Attribution and Causality Boundary

Phase 6 separates:

- deterministic lineage attribution: an observed Telegram event belongs to an exact provider account / chat / `message_id` / Publication;
- business causality: whether the publication strategy caused downstream behavior.

The first can be direct and deterministic. The second remains bounded by the canonical causality classes:

- `DIRECT_DETERMINISTIC_ATTRIBUTION`
- `EXPERIMENTAL_CAUSAL_EVIDENCE`
- `STRONG_OBSERVATIONAL_EVIDENCE`
- `CORRELATION`
- `UNKNOWN`

A reaction attached to the exact Telegram message proves reaction activity on that message. It does not by itself prove that wording caused engagement or that engagement caused sales.

## Governed Learning

The Learning stage uses the canonical controller matrix:

- Attribution Controller
- Learning Controller
- Stability Controller

Deterministic inputs are fixed before model interpretation:

- exact experiment/rule contract
- exact MetricVersion(s)
- exact ExperimentResult
- source BusinessEvents and provenance
- current connector coverage/freshness
- deterministic causality ceiling

The Learning Controller may produce a schema-valid interpretation, but it may not alter metric arithmetic, invent observations, change checkpoint thresholds, or upgrade the causality ceiling.

The Stability Controller checks whether the evidence is too narrow, stale, incomplete, contradictory, or single-trace to support generalization.

Materialized Learning binds at minimum:

- prior Decision ID
- Experiment ID
- ExperimentResult ID
- MetricVersion IDs
- evidence/source references
- bounded statement
- interpretation/result class
- causality class
- confidence
- explicit limits
- controller review provenance
- created_at

A valid bounded learning may state that evidence is insufficient. `INSUFFICIENT_DATA` is not converted into success or failure.

## Adaptation

Adaptation reuses the governed Decision workflow rather than inventing a separate autonomous policy agent.

The next BusinessSnapshot may include immutable references to the accepted Learning and exact MetricVersion(s). A successor Decision:

- has its own new immutable BusinessSnapshot;
- references the Learning used;
- sets `supersedes_decision_id` to the prior Decision;
- has a new selected action and normal controller review;
- keeps the prior Decision/history unchanged;
- passes the existing owner decision approval boundary before becoming the operational successor for production.

For v11.1, owner initiation is required to start this successor workflow from the first live learning trace. A provider event, metric calculation, or Learning alone cannot automatically trigger an external action.

## Phase 6 Jobs

Minimum asynchronous jobs:

- `connector.telegram.observe_updates`
- `analytics.normalize_connector_observation`
- `analytics.calculate_metric_version`
- `learning.interpret_checkpoint`
- `learning.run_governed_learning`

Successor Decision creation reuses the existing DecisionWorkflow runtime rather than introducing a new agent execution path.

All jobs are tenant-scoped and idempotent.

## Phase 6 Acceptance Contract

Phase 6 must make VS-014 through VS-018 executable while preserving all earlier gates.

Required integration evidence:

1. A new test Decision has a machine-readable checkpoint fixed before publication.
2. The governed Phase 4/5 path publishes an approved test asset and stores its Telegram `message_id`.
3. Telegram produces at least one real update relevant to the configured metric after observation subscription is active.
4. Duplicate delivery of the same Telegram `update_id` creates one raw observation and one normalized BusinessEvent only.
5. `event_time` and `ingested_at` are independently persisted.
6. A deterministic MetricVersion is created for the exact Publication/message lineage.
7. A late/duplicate fixture proves no silent historical rewrite or metric inflation.
8. A stale/incomplete coverage fixture proves missing data is not converted to zero.
9. Checkpoint interpretation uses the pre-execution typed rule and creates one immutable ExperimentResult.
10. Attribution/Learning/Stability governance creates a bounded Learning with exact evidence/metric provenance and limits.
11. The Learning does not overclaim causality.
12. Owner explicitly starts the successor Decision workflow from the Learning.
13. The successor Decision references the Learning, has `supersedes_decision_id`, and the prior Decision remains historically intact.
14. Existing Phase 0-5 tests remain green.

Live acceptance must use a fresh Phase 6 test experiment. The already executed Phase 5 publication must not have its original metric/window/thresholds rewritten after the fact merely to make the Phase 6 gate convenient.

## Security Requirements

- Telegram payloads remain untrusted external content.
- No connector token is persisted in observations, BusinessEvents, metrics, Learning, prompts, traces, outbox, or audit.
- Cross-tenant provider events fail closed.
- Oversized/unexpected provider payloads are bounded before AI context use.
- Provider text that resembles commands is stored as data only.
- Learning agents receive only scoped normalized evidence and capability handles, never credentials.

## Non-Scope

Phase 6 does not add:

- Instagram analytics
- GetCourse/payment attribution
- Telegram MTProto/full channel statistics
- broad historical backfill
- autonomous ad spend
- policy autopilot
- causal claims from temporal sequence
- a general-purpose analytics warehouse
- a second execution connector

## Closure

Phase 6 is closed only when one new real Telegram test trace reaches:

`approved Publication -> real connector observation -> BusinessEvent -> deterministic MetricVersion -> checkpoint result -> governed Learning -> owner-started successor Decision`

and the successor Decision preserves immutable history and supersession lineage.

At that point the v11.1 vertical slice has closed the canonical loop through `ADAPT`.