# ADR 0007: Governed Decision Workflow

Status: accepted
Date: 2026-08-17

## Context

Phase 3 activates the governed decision workflow on top of the accepted Phase 2A
durable runtime and Phase 2B provider-neutral AI runtime. The canonical
correction is that the Chief Growth Producer produces a `DecisionCandidate`, not
a final `Decision`. A final `Decision` may be materialized only after
independent controller review accepts the candidate.

## Decision

Add a durable Phase 3 workflow state machine:

- `DecisionWorkflow` tracks snapshot, revision count, status, final decision,
  final approval, and correlation/causation identifiers.
- `SpecialistContribution` stores typed specialist outputs against an immutable
  `BusinessSnapshot` and exact `AgentRun`.
- `DecisionCandidate` stores Chief output as versioned candidate history.
- `ControllerReview` stores independent controller output against the exact
  candidate, snapshot, and `AgentRun`.
- `DecisionApproval` binds approval to exact `Decision` object id, object version
  id, object version, and action type.
- `workflow.advance`, `ai.run_agent`, and `ai.run_controller` run through the
  existing PostgreSQL Job -> Redis wakeup -> Worker -> Handler spine.
- Revision loops are bounded by `LAUNCH_OS_MAX_DECISION_REVISION_ROUNDS`
  defaulting to 2.
- Positive typed agent authorities are allowlisted in code. Specialists cannot
  acquire Chief or Controller authority, Chief cannot review candidates, and
  Controllers cannot create recommendations or candidates.
- Model routing writes a safe trace of requested, selected, and actual
  provider/model values; mismatches fail before promoting output.

## Consequences

Positive:

- Candidate history is append-only and survives revision.
- Controller `BLOCK` prevents final `Decision` materialization.
- Controller `REVISE` creates a new candidate version instead of overwriting the
  old candidate.
- Final approval is stale if a later decision version supersedes the approved
  object/version/action binding.
- Redis remains only a job wakeup transport and no external write path is added.

Tradeoffs:

- Phase 3 still uses deterministic fake adapter coverage in CI. Live OpenAI
  acceptance remains an operator-run check outside CI.
- `DecisionWorkflow` is an internal runtime state row and may be advanced by the
  worker, while contribution, candidate, review, and approval rows preserve
  durable history.

## Non-Scope

This ADR does not authorize frontend, Telegram publication, external connectors,
Action or Execution creation, asset production, specialist expansion beyond the
Phase 3 canonical set, autopilot, microservices, live OpenAI calls in CI, or any
v10 database interaction.
