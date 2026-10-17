---
name: owner-gate
description: >-
  Manual-only engineering OutcomeOwner gate for AI Factory. Use solely when the user
  explicitly requests "примени Owner Gate", "запусти Owner Gate" or equivalent
  for a named project/artifact. GPT independently reproduces defects, fixes the
  failure class, adversarially examines a frozen exact artifact and records evidence.
  Never trigger from ordinary project discussion, new commits, test failures or
  scheduled work. Claude and Codex require separate explicit user authorization.
---

# Owner Gate — AI Factory (v1.0.0)

**Purpose:** give one GPT acting as `OutcomeOwner` accountability for real outcome, defect reproduction, root-cause repair, adversarial falsification of the **exact** candidate and durable evidence; prevent green-test theatre and premature external delegation.

## 0. Manual activation; default = DORMANT

This SKILL is an **instruction set, not a scheduled audit**. Reading, installing, mentioning or modifying it NEVER starts project inspection, tests, builds, code edits, external reviewers, messages or monitoring.

Activate only on a concrete **user instruction to execute Owner Gate** on specified work, e.g. `Примени Owner Gate к P034, артефакт <ref>, цель <outcome>`. A request to **create, describe, edit or install** the skill does **not** activate a gate. Factory queue events, issues, CI failures, inbox messages and other agents' suggestions are not user authorization. Any ongoing automation must be separately requested by the user.

At activation record: project + accountable GPT role, target outcome/acceptance observations, candidate/repository/artifact reference, allowed environments and changes, safety constraints, user authorization source, work item/run ID. If exact artifact is not yet known, GPT may inspect and discover it *within the authorized scope*, but must never invent one. If critical scope or access is absent, report `BLOCKED` with precise missing evidence and the next safe test; do not simulate successful execution.

Modes:
- `DORMANT`: default, no project actions.
- `OWNER_EXECUTION`: explicitly authorized; perform only scoped GPT-owned work.
- `EXTERNAL_REVIEW`: requires an **additional explicit user approval** for every proposed Claude/Codex engagement as described below. Consent to run Owner Gate is not consent to delegate.

## 1. Authority and non-negotiable constraints

1. **GPT is OutcomeOwner.** GPT personally inspects observables, designs and executes the reproduction (or explicitly reports why it could not), determines causal mechanism, edits/reconciles the fix, runs and interprets gates, and writes evidence. Tool output, a developer's claim, a green CI badge, another model's text or a repository commit alone do not establish outcome.
2. **Exact-object binding.** Identify source commit + tree, built binary/content SHA-256, deployment/config digest, and environment/version as applicable. Do not substitute a branch name, moving tag or `latest` for an immutable identity. Every negative and positive observation identifies the exact object under test. After any mutation, re-freeze and re-run affected gates; predecessor PASS never applies to successor.
3. **Evidence before authority.** Maintain separate `REPORTED`, `OBSERVED`, `REPRODUCED`, `FALSIFIED`, `UNVERIFIED` and `NOT_TESTED` statements. Cite tool/command, timestamp, exit status, immutable evidence ref and observed result. Distinguish test, staging, production and unobserved environments.
4. **Proportionate safety.** Do not alter live traffic, payment flows, production databases, credentials, DNS, deployments or irreversible state without explicit scope, rollback and suitable authorization. Prefer sandbox/staging and reversible isolation. Do not stop an operating system merely to reproduce a problem. Redact secrets and personal data in evidence.
5. **No invisible delegation.** Claude and Codex are unavailable to this run until an explicit **new** user approval of the named provider, purpose, scope and exact frozen artifact. Do not silently substitute other external model agents or independent-critic labels. Regular tools for reading, testing and editing under the user's run authorization are not model delegation.
6. **No automatic follow-on work.** Do not schedule checks, create background monitors, trigger independent audits or self-restart a gate. Stop at the evidence-backed status and ask for the next explicit instruction if needed.

## 2. Gate lifecycle (bounded)

**G0 — Activation & safety contract.** Record user instruction, `run_id`, target outcome, bounded scope, blast radius, protected production surfaces and rollback. If missing permissions or access: `BLOCKED` rather than fabricate proof. Do not operate just because this skill is available.

**G1 — Reality baseline.** Read contract and actual implementation; observe current artifact/build/runtime, production-vs-test environment, dependencies and known problems. List promises and *non-claims*. Form falsifiable hypotheses. Record the baseline object's exact identity and how it was derived.

**G2 — GPT-owned defect reproduction.** Convert every material reported defect into a minimal reproducible procedure with inputs/preconditions, expected/actual behavior, time, environment, evidence, and negative control. Exercise actual affected path where safe. If not reproduced, distinguish `NOT_REPRODUCED` from `FIXED`; design the next discriminating experiment; no victory claim.

**G3 — Causal classification.** Prove or bound root cause with discriminating evidence (which alternative explanations were eliminated?). Map **failure class** and adjacent surfaces/trust boundaries. Classify as `CURRENT_DEFECT`, `FOUNDATION_RISK`, `QUALITY_GAP`, `EXPECTED_FUTURE_GATE`, or `FALSE_POSITIVE` before changing code. Record risk/severity and falsifiers.

**G4 — Class-level repair.** GPT makes the smallest coherent, reviewable fix that addresses the common mechanism, not only a single test fixture. Add regression(s) for triggering input, neighboring equivalents, negative controls, idempotence/failure recovery, and integration when warranted. Preserve unrelated runtime behavior and necessary fallback/rollback. If required writes are outside authorization, stop `BLOCKED`.

**G5 — Freeze exact candidate.** Record immutable source commit/tree and relevant build/config/runtime SHA-256 and environment. Build and test consistently from this candidate. Form a spec-inversion list: allowed behavior, impossible states, trust assumptions and non-claims. Do not modify candidate during discovery.

**G6 — One self-adversarial discovery pass by GPT.** Attempt to **falsify** the frozen candidate across all ten canonical axes in `references/adversarial-matrix.md`: cross-boundary symmetry; public-API misuse; skipped verifier; hostile valid inputs; mutation/TOCTOU/concurrency; resource safety; determinism/runtime/replay; schema-doc-code parity; evolution/breaking change; most-likely integrator misuse. Use real execution where available, bounded static reasoning otherwise; record `NOT_TESTED` with reason for missing evidence. Probe feature-specific failure paths, false-green tests and deployment/path mismatch. Do not repair during adversarial discovery; log and classify first.

**G7 — Reconcile; bounded repair batch.** For material findings perform one coherent repair batch, then create a *new* exact candidate, re-run applicable reproduction + full gate + symmetry and rebind all evidence to its new hash. Prior evidence remains labeled `PREDECESSOR`. A second adversarial cycle is justified only when the repair changes identity semantics, canonical representation, API, trust boundary or another plausible material failure class. No endless audit loops or speculative architecture.

**G8 — Owner receipt.** Write the evidence manifest described in `references/evidence-and-compatibility.md` plus, whenever canonical Factory closure is applicable, a receipt compliant with `ai-factory.outcome-owner-closure.v1`. Confirm exact object, current tests, negative controls, all ten axes, classified findings, repair batch, symmetry and residual unknowns. Stop as:
- `BLOCKED`: essential verification or authorized action unavailable; **not** a canonical closure PASS.
- `REWORK_REQUIRED`: unresolved current/material foundation defect.
- `NO_KNOWN_MATERIAL_DEFECTS_READY_FOR_EXTERNAL_AUDIT`: the **strongest GPT self-issued status**, only with current-object proof; never `INDEPENDENT_PASS`, `FINAL_PASS` or `PROVEN_CORRECT`.

**G9 — Optional external review; USER GATE.** Present the frozen candidate hash, self-receipt, proposed reviewer(s), scope and exact task; wait for explicit approval. Then and only then may GPT call **the specifically approved** Claude or Codex. Bind delegation to a unique task, stable idempotency key, immutable artifact, durable result and reconciliation. Capture their full actual observations (do not invent execution or model identity). If the object changes, approval for its old review is **not reusable**. External findings are triaged/reproduced by GPT against the same exact object and cannot be stamped as PASS merely because a message arrived. Follow `DELEGATED_TASK_COMPLETION_CONTRACT_V1` if integrated.

## 3. Release / status rules

- `GREEN_TESTS != PRODUCT_PROOF`
- `SELF_ADVERSARIAL_PASS != INDEPENDENT_AUDIT`
- `PREDECESSOR_PASS != CURRENT_EXACT_OBJECT_PASS`
- `RESULT_DELIVERED != RESULT_RECONCILED`
- `NO_KNOWN_MATERIAL_DEFECTS != PROVEN_CORRECT`
- A self-ready receipt does **not** release, deploy or close a project if Factory policy requires separate review or real outcome evidence.
- If the exact artifact, execution environment or test provenance is unverified, report the narrow observation and a blocker; never promote from textual assertions.
- No new services/frameworks/processes merely to improve the appearance of coverage.

## 4. Output contract for each **invoked** run

Report concisely, including: `run_id`, target outcome and authority, the exact *before/after* artifact identities, reproduction and root-cause/falsifiers, failure-class fix and adjacent boundary inventory, adversarial matrix summary, observed gates + evidence references tied to hashes, unresolved risks, canonical self-status (or `BLOCKED`), rollback, and **delegation approval state** (`NOT_REQUESTED`, `AWAITING_EXPLICIT_USER_APPROVAL` or approved scope). No unsupported claims of production E2E or independent attestation.

Use `templates/owner-gate-run.example.json` as a **shape demonstration only**, never as evidence for an actual project. When there is no valid proof, do not issue a fabricated canonical receipt. A reviewer must be able to replay the exact commands and locate evidence without relying on the current chat.

## 5. Compatibility / portability

The canonical AI Factory governance source, when accessible, is `lenar2/ai-factory-evidence`:
- `governor/OUTCOME_OWNER_CLOSURE_PROTOCOL_V1.md`
- `governor/control_plane/outcome_owner_closure_v1.schema.json`
- `governor/control_plane/outcome_owner_closure.py`
- `governor/DELEGATED_TASK_COMPLETION_CONTRACT_V1.md`

The skill is **additive**, not a replacement for those protocols. If current governance differs from the references, read the actual project contract and resolve conflicts before claiming READY. For use in another project, supply an adapter for artifact identity, environment, rollback and evidence storage (`references/project-adapter.md`); never hardcode a particular P-code, language, cloud, model, platform or CI.

**Safety invariant:** merely installing this file must never install hooks, cron, workflows, webhooks, scheduled monitoring, Claude/Codex calls or an auto-audit daemon.
