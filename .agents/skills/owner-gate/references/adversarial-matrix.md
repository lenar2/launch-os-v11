# Owner Gate — adversarial matrix (canonical ten axes)

Use once on a **frozen exact object** after GPT-owned defect reproduction and repair. For each axis capture: falsifiable invariant, candidate SHA, test/probe, environment, observed raw result, evidence ref, `TESTED`/`NOT_TESTED`/`FAIL`, and adjacent boundaries. A checklist tick without an executed or observed probe is not proof.

| Canonical key | Adversarial challenge | Typical falsifier |
|---|---|---|
| `CROSS_BOUNDARY_SYMMETRY` | Can a sibling boundary accept what the hardened path rejects? | Same malformed/ambiguous input accepted by alternate path |
| `PUBLIC_API_MISUSE` | Can a reasonable caller omit a required step or misuse an easy API? | Documented API lets unverified state reach consumer |
| `SKIPPED_VERIFIER_PATH` | Does `weak valid state → skip verification → privileged consumer` succeed? | Unverified object accepted at stronger boundary |
| `HOSTILE_VALID_INPUTS` | Check subclasses/aliases, duplicate identifiers, Unicode, empty/extreme/shape-valid values, cycles where relevant. | Formally accepted input violates contract |
| `MUTATION_TOCTOU_CONCURRENCY` | Mutate payload before/during/after check; concurrent requests; lost ack, retries. | Check/use gap, duplicate effect, stale state |
| `RESOURCE_SAFETY` | Enforce bounded size/depth/time/log amplification. | Exhaustion or amplified error/output |
| `DETERMINISM_RUNTIME_REPLAY` | Replay under specified runtime, time, locale, ordering, platform versions. | Divergent outcome for same declared conditions |
| `SCHEMA_DOCS_CODE_PARITY` | Compare schema, validator, public API, docs and actual runtime. | Mismatch in accepted domain/guarantees |
| `EVOLUTION_BREAKING_CHANGE` | Identify smallest likely next feature/extension that violates foundation assumptions. | Present design forces unplanned semantic break |
| `MOST_LIKELY_INTEGRATOR_MISUSE` | Have a competent integrator follow the most plausible wrong assumption. | Dangerous outcome not prevented by API/validation |

Additional scenario-dependent cross-checks:
- **False green:** negative-control test must fail on known-bad predecessor; assert the suite is actually running on this object and that failed commands are not hidden by `|| true` or swallowed errors.
- **Packaging/deployment:** source commit, build image/binary, running process, config, server and UI may differ; measure actual executing object instead of assuming deployment.
- **Error and recovery:** partial failure, cancellation, timeout, duplicate/lost acknowledgment, retry/idempotence, eventual convergence and rollback.
- **Security/privacy:** privilege boundary, identity/auth, secrets disclosure, compromised input. Use safe fixtures; do not run destructive payloads in production.
- **Live services:** real user journey only when authorized. Report test/staging status separately from production E2E.

Severity/repair decision uses canonical classifications from the current Factory protocol. `CURRENT_DEFECT` must be fixed before owner READY; `FOUNDATION_RISK` must be fixed before the capability that triggers it and is considered material by the canonical validator unless repaired. `QUALITY_GAP` is not a license for endless refinement; `EXPECTED_FUTURE_GATE` is not a current bug; `FALSE_POSITIVE` must be rejected with evidence.
