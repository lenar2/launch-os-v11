# ADR 0008: Governed Production Workflow

Status: Accepted
Date: 2026-08-18

## Context

Phase 3 creates and exact-version approves a governed business Decision. v11.1 next requires one real production asset without collapsing strategy, brief, draft, review, approval, or publication into a single model response.

The canonical creative pipeline requires:

`Decision -> Content/Creative Strategy -> CreativeBrief -> Production -> Brand/Truth/Quality Control -> Approval -> Publication`

Phase 4 must stop before ActionProposal and external execution.

## Decision

Implement Phase 4 as a durable production workflow on the existing PostgreSQL Job -> Redis job_id -> generic Worker -> governed AI runtime spine.

The workflow:

1. verifies an `APPROVED_FOR_PRODUCTION` Decision and exact matching `DecisionApproval`;
2. runs Content Director and materializes a separate `ContentStrategy`;
3. materializes a separate `CreativeBrief`;
4. runs a narrow Telegram Writer and materializes an immutable `AssetVersion`;
5. records honest creator identity and rights/provenance;
6. reviews each exact version with Evidence, Brand, Constitutional, Manipulation, Legal/Claims, Production Quality, and Rights/Provenance controllers;
7. creates a new AssetVersion on revision rather than overwriting;
8. stops at `READY_FOR_ACTION_PROPOSAL`.

`PASS_WITH_CONDITIONS` with mandatory conditions is revision-required. The default maximum asset revision count is two.

## Authority

Content Director may propose content strategy only.

Telegram Writer may propose an asset draft only.

Asset controllers may review an exact AssetVersion only.

AI outputs remain AgentRuns until application services validate and materialize permitted production objects. No production agent or controller may create an ActionProposal, approval, publication, connector call, or external write.

## Creator identity

The legacy `asset_versions.created_by_user_id` becomes nullable. A one-to-one `asset_version_creators` record carries typed `USER`, `AGENT`, or `SYSTEM` identity. AI-generated Phase 4 versions bind to the exact writer AgentRun; no fake user is created.

## Rights and provenance

Every AssetVersion has version-bound rights/provenance. Generated text records the originating AgentRun and actual provider/model trace. User-provided, licensed, or derived content requires explicit permission scope where applicable.

## Consequences

- Strategy, CreativeBrief, Asset, AssetVersion, approval, and Publication remain separate.
- Controller results never transfer from one AssetVersion to another.
- Phase 4 can produce a real Telegram-ready text asset while external-write count remains zero.
- Phase 5 can later consume only a production-ready exact AssetVersion through ActionProposal -> Permission Engine -> approval -> Execution Engine.
