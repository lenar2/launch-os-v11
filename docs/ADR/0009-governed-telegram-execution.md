# ADR 0009: Governed Telegram Execution

Status: Accepted for Phase 5 implementation
Date: 2026-08-19

## Context

Phase 4 ends with an immutable, controller-passed AssetVersion in
`READY_FOR_ACTION_PROPOSAL`. Phase 5 is the first boundary that may mutate an
external system. The canonical architecture requires:

`ActionProposal -> Controllers -> Permission Engine -> Approval -> Execution Engine -> Connector -> External system -> Event/Audit`

The existing Phase 1 persistence already contains `actions`, `approvals`,
`executions`, `publications`, and `permission_policies`. Duplicating those
entities would create two competing execution models.

Telegram Bot API writes also have an unavoidable ambiguity window: a provider
may accept a request before Launch OS persists the returned message id.

## Decision

1. `ActionProposal` is the domain/API name backed by the existing `actions`
   table. `action_proposal_details` stores immutable Phase 5 delivery context,
   including the exact production workflow, AssetVersion, connector account,
   destination, payload, and payload hash.
2. Phase 5 supports one action only: `telegram.publish_text`.
3. Five execution controllers are deterministic and independently persisted:
   Security, Privacy, Platform, Execution, and Cost.
4. Public Telegram publication always resolves to `APPROVAL_REQUIRED` under the
   v11.1 default policy. Phase 5 does not implement autopilot.
5. Approval is exact-bound to the ActionProposal and exact AssetVersion.
   Changing the final AssetVersion or action payload invalidates execution
   eligibility.
6. `EXECUTION_PAUSED`, `AUTOMATION_PAUSED`, and
   `REVOKE_ALL_WRITE_CAPABILITIES` are re-checked immediately before the
   provider call.
7. Only `TelegramExecutionHandler` / Execution Engine owns the write-capable
   connector. AI agents and production workflows never receive Telegram
   credentials or write access.
8. Telegram credentials are resolved only inside the connector from a secret
   reference. Tokens are not persisted in ActionProposal, approval, execution,
   audit, outbox, or AI trace records.
9. A successful provider response creates `Publication`,
   `ExternalReference`, `PublicationExecutionLink`, audit, and outbox records.
10. The execution job has `max_attempts=1`. A retry of a completed logical
    execution reuses the stored external reference and never sends again.
11. If a transport or response failure leaves provider outcome ambiguous, the
    execution becomes `UNKNOWN_EXTERNAL_OUTCOME`; Launch OS does not
    automatically retry the write. Reconciliation/manual resolution is
    required.
12. Phase 5 stops after confirmed publication and execution audit. Incoming
    Telegram observation, MetricVersion, Learning, and adaptation remain Phase
    6+.

## Consequences

- External authority remains separated from AI reasoning and production.
- Owner approval cannot be reused for a changed asset or destination.
- Global write controls are enforced at the final write boundary.
- Provider-specific logic is isolated behind a typed connector.
- The system does not claim exactly-once semantics that Telegram cannot
  guarantee across a process crash after provider acceptance.
- A live Telegram test channel is required before Phase 5 can be declared
  fully closed; deterministic fake-connector CI is necessary but not
  sufficient for final live acceptance.
