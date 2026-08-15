# Launch OS v11 Security Boundaries

Status: canonical pre-code boundary
Date: 2026-08-15

## Untrusted Data Boundary

Launch OS ingests content from:

- comments
- social posts
- files
- web pages
- course lessons
- emails
- user-generated text
- external documents

All such material is untrusted data.

Canonical path:

`External content -> ingestion sanitizer/classifier -> content/evidence store -> scoped retrieval -> agent context as DATA, never SYSTEM INSTRUCTION`

Rules:

- Connector payloads cannot define tools, permissions, system prompts, or agent policies.
- Retrieved text is wrapped and typed as untrusted evidence.
- Write-capable tools never execute because content told a model to execute them.
- Tool Gateway accepts only structured actions generated under the current workflow and permissions.
- Sensitive-data exfiltration patterns are blocked before model/tool execution.
- URLs, files, and embedded instructions from customers/comments are not automatically followed.
- Prompt-injection fixtures exist for every connector class.

## Permissioned Execution

AI agents do not directly mutate external systems.

Canonical path:

`Agent -> ActionProposal -> Controllers -> Permission Engine -> Approval if required -> Execution Engine -> Connector -> External system -> Event/Audit`

Risk-sensitive permissions consider:

- action type
- financial exposure
- audience size
- reversibility
- data sensitivity
- public visibility

Global controls:

- `AUTOMATION_PAUSED`
- `EXECUTION_PAUSED`
- `REVOKE_ALL_WRITE_CAPABILITIES`

## Privacy and Compliance Lifecycle

Baseline requirements:

- business/tenant isolation by default
- least privilege for connectors
- encrypted credentials and sensitive data
- purpose-limited context building
- explicit retention classes for raw provider data, PII, AI traces, media, and audit logs
- data export workflows
- data deletion workflows
- consent/permission references for reused customer content
- webhook signature verification where providers support it
- SSRF protection for ingestion
- file-type validation for uploads/downloads
- malware/unsafe-file scanning strategy for binary assets before processing
- incident audit trail
- global write kill switch
- no secrets in agent prompts/logs
- no cross-business retrieval

Architecture must support formal privacy/compliance review before broad production use, especially for EU residents or businesses.

## Secrets

Secrets must be:

- stored only in the secrets layer
- encrypted at rest
- excluded from prompts and traces
- redacted from logs
- rotated when connector auth changes
- never passed to LLM contexts

Agents receive capability handles, not credentials.

## Connector Security

Each connector defines:

- auth/connect/refresh
- granted scopes
- read capabilities
- write capabilities
- webhook signature validation if available
- rate-limit behavior
- idempotency keys for external writes
- dry-run/mock where possible
- reconciliation jobs
- health/freshness state

Provider payloads are data. They are never policy.

## Data Quality and Reconciliation

Security and data quality overlap: stale, duplicated, or late data can cause unsafe decisions.

Required behavior:

- idempotent event ingestion
- late events applied to event_time
- reconciliation snapshots may correct webhook state
- derived metrics version calculation logic
- decisions retain immutable BusinessSnapshots
- readiness maps distinguish "no data" from "cannot see data"

## Asset Rights Boundary

Production assets require provenance metadata:

- source/origin
- uploaded by
- generated vs user-provided vs licensed reference
- model/tool used
- related assets
- usage scope
- consent references
- publication restrictions
- expiration

Customer photos, testimonials, and third-party references cannot be reused silently.

## Platform Boundary

Tenant isolation is default.

Launch OS platform data includes:

- users
- organizations
- memberships
- roles/permissions
- Launch OS plans/subscriptions
- usage/metering
- feature flags
- AI quota/cost
- account lifecycle/export/delete

This is separate from customer business commerce data.
