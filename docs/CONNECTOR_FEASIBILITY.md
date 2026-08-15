# Connector Feasibility Matrix

Status: first-pass pre-code verification
Verified date: 2026-08-15

## Sources Checked

- Telegram Bot API: https://core.telegram.org/bots/api
- GetCourse API help: https://getcourse.ru/help/api
- GetCourse API overview: https://getcourse.io/blog/759181
- Meta Instagram Platform docs entry point: https://developers.facebook.com/docs/instagram-platform/

## v11.1 Recommendation

Use Telegram as the first execution connector.

Reason:

- It supports bot-based send and receive workflows.
- It can test the full permissioned execution path quickly.
- It avoids starting v11 with a heavier OAuth/provider-review integration.
- The handoff indicates existing Telegram infrastructure lessons from v10.

## Telegram

Priority: P0 for v11.1 execution loop

Verified capabilities from official Bot API:

- receive updates through `getUpdates` or webhooks
- JSON Update objects include message/channel post variants
- `update_id` supports deduplication/order handling
- send messages through bot methods
- store provider message IDs as external references

Important constraints:

- `getUpdates` and webhooks are mutually exclusive.
- Incoming updates are not retained indefinitely by Telegram.
- A bot can only observe messages/updates it is allowed to receive.
- Provider payloads must be treated as untrusted data.

v11.1 connector scope:

- connect bot token through secrets layer
- register target chat/channel ID
- validate readiness
- publish approved text post
- store Telegram `message_id`
- ingest updates visible to bot
- calculate basic publication metrics available from observed updates
- expose health/freshness

Open questions:

- exact v10 Telegram implementation location
- whether target surface is a channel, group, or DM
- whether the bot is admin in the publication channel

Feasibility: GO for first vertical slice.

## Instagram

Priority: P0/P1 visibility, not v11.1 execution

Current design assumption:

- Use official Meta Instagram Platform / Graph API where available.
- Require business/creator account readiness and appropriate scopes.
- Treat unavailable metrics as unavailable rather than absent.

Pre-code status:

- Official docs entry point identified.
- Full capability matrix must be re-verified before implementation because Meta docs and permissions change frequently and may require app review.

v11.2 likely scope:

- account connection readiness
- profile/media insights available under granted scope
- historical backfill where supported
- incremental sync/webhook where supported
- rate-limit aware polling

Feasibility: DEFERRED until v11.2 provider verification.

## GetCourse

Priority: P0 visibility for education/customer/payment lifecycle where used

Verified capabilities from public GetCourse docs:

- import users
- import orders/deals
- export users
- export groups
- export deals
- export payments
- callback requests for configured events

Important constraints:

- Import methods are documented as import, not operational object management.
- Export endpoints use task/export flow and filters.
- Account-specific domain and secret key handling must be modeled.
- Webhook/callback payloads must be treated as untrusted data.

v11.2 likely scope:

- account/secret configuration through secrets layer
- export users/deals/payments for backfill
- periodic reconciliation jobs
- configured callbacks for event observation
- identity graph links using email/phone/GetCourse IDs with evidence/confidence

Feasibility: GO for read/backfill/reconciliation after account-specific confirmation.

## Payments

Priority: P0 visibility, provider TBD

Status:

- Cannot verify provider-specific capabilities until the actual payment systems currently used by the business are named.

Required before implementation:

- identify provider(s)
- verify webhooks, event IDs, refunds, subscriptions, checkout/session attribution, API snapshots, rate limits, and historical export
- define source-of-truth hierarchy between payment provider and GetCourse if both contain payment/deal state

Feasibility: BLOCKED ON PROVIDER IDENTIFICATION.

## Readiness Map Required for Every Connector

Each connector/account exposes:

- connected?
- auth healthy?
- scopes granted?
- historical backfill complete?
- incremental sync healthy?
- freshness?
- read capabilities?
- write capabilities?
- known coverage gaps?
- rate-limit state?

AI agents receive the readiness map so they can distinguish:

- no event happened
- the connector is stale
- the metric is unavailable through current scope
- the account lacks write permission

## Connector Contract

Every provider implementation must support:

- auth/connect/refresh
- capability discovery or configured capability map
- initial backfill
- incremental sync
- webhook/callback handling where supported
- reconciliation
- health/freshness
- `execute(action)` for allowed write actions
- dry-run/mock where possible
- idempotency for external writes
- prompt-injection fixtures for payload classes
