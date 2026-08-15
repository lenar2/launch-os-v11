# ADR 0006: Provider-Neutral Governed AI Runtime

Status: accepted
Date: 2026-08-16

## Context

Phase 2B needs the first AI execution foundation without starting Phase 3
business specialists, controllers, external connectors, Telegram publication,
frontend, recursive orchestration, or live model calls in CI.

Launch OS v11 must not become a GPT wrapper. The Business Twin and durable
domain/runtime records remain the source of truth. AI output is a structured
candidate artifact stored on `AgentRun`; it is not automatically promoted into
Facts, Evidence, Decisions, Actions, Approvals, Executions, or Learnings.

## Decision

Add a provider-neutral AI runtime boundary under `launch_os_v11.ai_runtime`:

- `AgentContract` defines a versioned role, scoped context policy, model
  capability, strict output schema, authority boundaries, prohibited actions,
  controller requirements, instruction version, and eval suite identifier.
- Agents request `ModelCapability`, not provider model names.
- `ModelRouter` deterministically maps capability to a configured provider route
  in the composition root. It does not inspect prompts and does not make
  business strategy decisions.
- `ModelAdapter` accepts typed requests and returns typed structured results,
  refusal, incomplete, or invalid-output outcomes with safe provider metadata.
- The OpenAI adapter uses the Responses API typed parsing path
  `client.responses.parse(..., text_format=PydanticModel)`.
- OpenAI requests set `store=False` and send no hosted tools, function tools, web
  search, file search, MCP tools, connector permissions, or credentials.
- The `ai.run_agent` handler executes through the existing durable Phase 2A
  `Job -> Redis wakeup -> Worker -> Handler` spine. PostgreSQL remains the
  durable source of truth; Redis carries only `job_id`.
- Context is built by a deterministic `ContextBuilder` from allowlisted,
  tenant-scoped canonical objects and stores a manifest/hash. External/user data
  remains explicitly marked as untrusted DATA.
- CI uses a deterministic fake adapter. CI must not require `OPENAI_API_KEY` and
  must not perform live OpenAI calls.

## State Semantics

`AgentRun` states:

- `QUEUED`: durable run and durable job exist.
- `RUNNING`: a worker attempt is building context or invoking the adapter.
- `RETRY_WAIT`: a classified transient provider/runtime failure is waiting for
  the Phase 2A retry schedule.
- `SUCCEEDED`: strict structured output was parsed and persisted.
- `REFUSED`: provider refusal was persisted as a distinct outcome.
- `INVALID_OUTPUT`: incomplete or malformed structured output was persisted as a
  distinct outcome.
- `FAILED`: permanent configuration/provider/runtime failure.

Job states stay the Phase 2A durable runtime states. Refusal and invalid output
are successful job processing outcomes because the handler reached a durable
terminal `AgentRun` result; transient/permanent exceptions map to retry/failed
job states.

## Security Boundaries

- Agent contracts cannot grant write, connector, execution, tool, or credential
  authority.
- AI runtime does not import connector or execution packages.
- Only the OpenAI provider adapter imports the OpenAI SDK.
- API keys live only in settings/environment secret boundaries and are never put
  into job payload, Redis, context, database trace, or logs.
- Context manifests store source references and hashes, not raw prompt blobs.
- Untrusted external text cannot alter system instructions, tools, provider
  routing, permissions, or AgentContract contents.

## Dependency

Add the official `openai` Python SDK with a narrow version bound for the
provider adapter. Do not add the OpenAI Agents SDK as orchestration authority in
Phase 2B: Launch OS already has a governed durable runtime, controller gates, and
domain-specific permission architecture. A generic agent orchestration authority
would blur those boundaries before Phase 3 has explicit approval.

## Consequences

Positive:

- Provider choice is isolated from agent contracts.
- Structured output is validated before persistence.
- Duplicate Redis delivery after a committed terminal result does not re-invoke
  the adapter.
- Transient failures reuse the existing durable retry/backoff machinery.
- The fake adapter gives deterministic CI coverage without live AI calls.

Tradeoffs:

- There remains an at-least-once provider-call crash window: if a process exits
  after the provider call but before the terminal `AgentRun`/`Job` commit,
  recovery may re-run the same job. Phase 2B does not claim exactly-once network
  invocation.
- Phase 2B stores structured AI output only on `AgentRun`; promotion into
  Decisions, Evidence, Actions, or Learnings requires later governed workflows.

## Non-Scope

This ADR does not authorize Phase 3 decision workflow, Chief Growth Producer,
specialist prompts, controllers, BusinessSnapshot builder, asset production,
frontend, Telegram publication, external connectors, autopilot, recursive
multi-agent loops, hosted OpenAI tools, vector search, production deployment, or
v10 migration/import.
