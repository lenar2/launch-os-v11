# v11.1 Vertical-Slice Acceptance Tests

Status: pre-code acceptance contract
Date: 2026-08-15

## Objective

These tests define the first acceptable Launch OS v11 loop. They can begin as documented acceptance tests and should become executable end-to-end or workflow integration tests as soon as the skeleton exists.

## VS-001: Create Business and Launch

Given an owner has an organization
When they create a business with timezone, goal, product, offer, Telegram channel, and launch target
Then the Business Twin stores those objects with provenance
And no field represents human worth/readiness/rank.

## VS-002: Connector Readiness Is Visible

Given Telegram is connected and payment provider is not configured
When the Launch Room opens
Then Telegram readiness is healthy
And payment visibility is shown as unavailable/provider TBD
And the system does not infer zero payments.

## VS-003: BusinessSnapshot Is Immutable

Given a launch workflow starts
When `CreateBusinessSnapshot` runs
Then the Decision workflow receives the snapshot ID
And later business edits do not mutate that snapshot.

## VS-004: Specialist Contributions Are Structured

Given a BusinessSnapshot exists
When Business/Product Analyst and Telegram Strategist run
Then each returns a schema-valid contribution
And evidence, assumptions, unknowns, and recommendations are separate fields.

## VS-005: Decision Has Selected Action

Given specialist contributions are available
When Chief Growth Producer creates the Decision
Then Decision includes selected_action, alternatives, evidence used, assumptions, expected effect, risk class, reversibility, checkpoint, and required assets/actions.

## VS-006: Controller Reviews Can Block

Given a Decision includes a constitutional hard violation
When controllers run
Then Constitutional Controller returns BLOCK
And no CreativeBrief or ActionProposal is created from that Decision.

## VS-007: Anti-Paralysis Allows Low-Risk Action

Given useful but non-critical information is missing
And the proposed Telegram post is low-cost and reversible
When Anti-Analysis-Paralysis Controller reviews
Then it does not block
And the missing information is recorded as InformationNeed.

## VS-008: Experiment Rules Are Fixed Before Execution

Given a Decision proceeds
When Experiment Lead creates the checkpoint
Then baseline, metric, window, attribution method, success/weak/failure thresholds, and next actions are stored before publication.

## VS-009: CreativeBrief and Asset Version Are Created

Given a valid Decision and checkpoint
When production runs
Then CreativeBrief is created
And AssetVersion 1 is generated
And rights/provenance metadata exists.

## VS-010: Asset Review Blocks Unsupported Claim

Given AssetVersion 1 contains an unsupported claim
When Evidence and Legal/Claims controllers review it
Then the asset review returns REVISE or BLOCK
And the unsupported claim cannot be approved.

## VS-011: Approval Is Required

Given AssetVersion 1 passes review
When ActionProposal is created for Telegram publication
Then Permission Engine marks approval_required
And owner approval is required before execution.

## VS-012: Telegram Publication Uses Execution Engine

Given owner approval exists
When execution runs
Then Execution Engine calls Telegram connector
And no agent directly calls Telegram
And audit records action, approval, idempotency key, and external reference.

## VS-013: Duplicate Execution Does Not Duplicate Telegram Message

Given Telegram publication succeeded
When the same execution job retries
Then no second Telegram message is sent
And the original external message reference is reused.

## VS-014: Observation Creates BusinessEvent

Given a Telegram message was published
When connector observation receives available update/message data
Then BusinessEvent is stored with provider, external ID, event_time, ingestion_time, and provenance.

## VS-015: MetricVersion Is Calculated Deterministically

Given observed Telegram events exist
When metric calculation runs
Then MetricVersion stores calculation_version, calculated_at, source window, and derived values
And no LLM arithmetic is used.

## VS-016: Attribution Class Is Explicit

Given a Telegram post preceded sales movement but payment attribution is unavailable
When checkpoint interpretation runs
Then the result is not stated as causal
And evidence class is `UNKNOWN`, `CORRELATION`, or `STRONG_OBSERVATIONAL_EVIDENCE` only if supported.

## VS-017: Learning Controller Creates Learning

Given metric results and checkpoint thresholds exist
When Learning Controller runs
Then it creates a Learning object with evidence references, interpretation class, confidence, and limits.

## VS-018: Next Decision Supersedes Previous Decision

Given Learning exists
When the next Decision is created
Then it references the Learning
And supersedes the prior Decision without overwriting it.

## VS-019: UserDecisionView Is Compressed

Given a Decision is ready for owner display
When Command Center renders it
Then it shows Decision, 1-3 reasons, what happens now, ready assets/actions, metric/target/current state, next checkpoint, and approval needed
And deep analysis is behind progressive disclosure.

## VS-020: Global Pause Stops Execution

Given owner enables `REVOKE_ALL_WRITE_CAPABILITIES`
When any approved publication job runs
Then execution is blocked
And the UI shows write capabilities revoked.

## Completion Gate

v11.1 is accepted only when VS-001 through VS-020 pass in staging against a Telegram test channel or sandbox-equivalent channel.
