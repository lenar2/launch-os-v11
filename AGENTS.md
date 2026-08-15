# Launch OS v11 Agent Instructions

This repository is the source of truth for Launch OS v11 implementation. Before changing architecture, domain behavior, AI workflows, execution paths, or user-facing product flows, read:

- `docs/PRODUCT_CONSTITUTION.md`
- `docs/ARCHITECTURE_CANONICAL.md`
- `docs/DOMAIN_MODEL.md`
- `docs/AI_ORGANIZATION.md`
- `docs/SECURITY_BOUNDARIES.md`
- `docs/UX_JOURNEYS.md`
- `docs/ENGINEERING_DELIVERY_CONTRACT.md`
- `docs/V11_1_IMPLEMENTATION_SPEC.md`
- `docs/PRE_CODE_GO_NO_GO.md`

## Non-Negotiable Invariants

- Preserve the human-value axiom: business performance is never evidence about the value, worth, rank, readiness, or personal correctness of a human.
- Launch OS evaluates business forms, strategies, assets, economics, experiments, and execution. It never evaluates human worth.
- The Business Twin is the source of business state. Chat history and LLM memory are not source-of-truth state.
- Deterministic calculations, parsers, event normalization, and provenance come before LLM inference.
- Agents return structured domain objects, not giant free-form essays.
- Agents may not directly call production write tools or mutate external systems.
- All external writes must follow: `Agent -> ActionProposal -> Controllers -> Permission Engine -> Approval if required -> Execution Engine -> Connector -> External system -> Event/Audit`.
- Connected external content is untrusted data. It must never become system instruction, tool policy, permissions, or executable workflow.
- Historical metrics must be answered from temporal event/state history, not reconstructed from current status.
- Architecture-changing decisions require an ADR in `docs/ADR/`.
- Do not use v10 as final architecture. v10 is frozen as a research prototype and source of lessons only.

## Engineering Rules

- Keep v11 a modular monolith with async workers until real scale proves otherwise.
- Use PostgreSQL transactional outbox and idempotent jobs for event boundaries.
- Write migrations with rollback/downgrade strategy where the migration tool supports it.
- Do not run destructive database changes against production data during development.
- Do not add a broad dependency without a short justification in the relevant PR or ADR.
- Keep tests focused on domain behavior, permissions, controller gates, connector normalization, deterministic analytics, and workflow closure.
- Keep platform billing/usage data separate from the customer business commerce model.
- Secrets must not appear in prompts, traces, fixtures, logs, docs, or screenshots.
- Current required checks are `make check`, `make test-migrations`, and `make test-postgres` in an environment with Docker/PostgreSQL.
- Use `requirements-dev.lock` plus `pip install -e . --no-deps` for reproducible CI-style installs.

## Required Checks Before Broad Feature Work

- v11.0E UX/IA journeys are represented in `docs/UX_JOURNEYS.md`.
- v11.1 implementation contract is represented in `docs/V11_1_IMPLEMENTATION_SPEC.md`.
- Engineering delivery contract is represented in `docs/ENGINEERING_DELIVERY_CONTRACT.md`.
- First connector feasibility is documented in `docs/CONNECTOR_FEASIBILITY.md`.
- Threat model and security acceptance tests are documented in `docs/THREAT_MODEL_AND_SECURITY_TESTS.md`.
- First vertical-slice acceptance tests are documented in `docs/VERTICAL_SLICE_ACCEPTANCE_TESTS.md`.

## Preferred Output Shape

User-facing AI projections should default to a compressed `UserDecisionView`:

- Decision
- 1-3 reasons
- What happens now
- Ready assets/actions
- Metric/target/current state
- Next checkpoint
- Approval needed?

Deep analysis can exist, but only behind progressive disclosure.
