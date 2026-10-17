# Evidence contract & Factory compatibility

Owner Gate is an execution procedure. It does not mint third-party audit authority.

## Required evidence bundle

1. **Authority:** exact user's instruction, scope, `run_id`, time, environment permissions and separately approved external delegation, if any.
2. **Identity:** before/after immutable artifact refs (git commit/tree, SHA-256 binary/file, config/deployment/runtime version). If SHA-256 unavailable, document blocker; do not use mutable tags as proof.
3. **Reproduction:** observed inputs, expected and actual outputs, negative controls, environment, reproduction rate only if genuinely measured, raw logs, command exit statuses and source refs. Report failures that cannot be reproduced as unknown, not fixed.
4. **Causality and class:** falsifiers, adjacent boundary inventory, canonical finding classification, mechanism, smallest coherent repair batch.
5. **Adversarial:** all ten canonical axes; explicit `NOT_TESTED` where verification lacked access. Coverage assertions should name observed probes.
6. **Re-freeze and rerun:** all gate results on the exact successor candidate, not the predecessor. Include hashes/checksums for evidence files where practical.
7. **Honest conclusion:** `BLOCKED`, `REWORK_REQUIRED`, or `NO_KNOWN_MATERIAL_DEFECTS_READY_FOR_EXTERNAL_AUDIT`, with residual unknowns, non-claims and human approval state.

Evidence should be a durable file/ref within the project's authorized storage, not merely an assistant claim. Redact secrets and PII. Claim independent identity/attestation only when the transport actually supports it.

## Existing canonical OutcomeOwner closure v1

When governed by AI Factory, issue the **existing** `ai-factory.outcome-owner-closure.v1` receipt using the canonical current schema/validator in `lenar2/ai-factory-evidence/governor/control_plane`. Its exact required keys:

`schema`, `artifact_ref`, `outcome_owner_ref`, `promises`, `non_claims`, `axes_checked`, `findings`, `symmetry_check`, `most_likely_integrator_misuse`, `breaking_change_search`, `repair_batch_ref`, `gate_evidence_refs`, `self_status`.

The ten `axes_checked` enum values match `adversarial-matrix.md`. Canonical `self_status` options are **only**:
- `REWORK_REQUIRED`
- `NO_KNOWN_MATERIAL_DEFECTS_READY_FOR_EXTERNAL_AUDIT`

This canonical validator currently requires exactly ten axes and an evidence ref; refuses READY with unrepaired material findings. A `BLOCKED` run should **not** fabricate a canonical receipt to bypass the validator. Instead record a blocked run manifest or textual blocker and leave closure unissued.

## Delegation & reconciliation

If the user grants a specific external review after self-ready, use the existing `ai-factory.delegated-task-completion.v1` contract: task ID, target state, expected evidence, provider/thread, exact artifact, idempotency key, recovery, durable result and post-result reconciliation.

A result is not complete on `DELIVERED`, `RUNNING`, `RESULT_READY` or `RESULT_CAPTURED`. A timeout is not proof of non-delivery: reobserve before retry, and do not create duplicates. The external review result must be independently triaged by GPT. No assumption of independent model identity merely from a chat message.

## Authority boundaries

- Owner self-check may justify **READY_FOR_EXTERNAL_AUDIT**, never `INDEPENDENT_PASS`.
- External review (after approval) may contribute evidence, but only Factory governance/human policy promotes final result.
- Audit skill creation/installation does not count as any project's validation.
