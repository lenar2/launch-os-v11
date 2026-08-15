# ADR 0003: Write Actions Through Execution Engine

Status: accepted
Date: 2026-08-15

## Context

Launch OS v11 will connect to external systems and eventually have "hands." If agents can directly mutate external systems, prompt injection, hallucination, permission errors, and unclear accountability become unacceptable risks.

## Decision

Agents may not directly call production write tools.

All writes follow:

`Agent -> ActionProposal -> Controllers -> Permission Engine -> Approval if required -> Execution Engine -> Connector -> External system -> Event/Audit`

Autonomy is represented by deterministic policy, not by agent self-description.

## Consequences

Benefits:

- external actions are auditable
- permissions are deterministic
- approvals cannot be bypassed by prompt content
- write kill switches work globally
- prompt-injection blast radius is reduced

Costs:

- more workflow code is required before the first publication
- simple actions require domain objects and policy evaluation

## Guardrails

- Agents receive no credentials.
- Tool Gateway accepts structured action intents only.
- Write-capable paths fail closed on invalid structured output.
- Execution records provider IDs, idempotency keys, request/response summaries, and audit metadata.
- Global execution pause blocks all writes.
