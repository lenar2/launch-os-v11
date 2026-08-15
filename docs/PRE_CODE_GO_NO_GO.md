# Pre-Code Go/No-Go Checklist

Status: v11.1 scaffolding allowed, broad feature work blocked
Date: 2026-08-15

## Current Verdict

Architecture: GO.

Repository source-of-truth docs: GO.

v11.1 vertical-slice scaffolding: GO.

Broad feature implementation: NO-GO until the v11.1 closed loop passes.

Production pilot: NO-GO until engineering delivery, security, staging, backup/restore, connector credentials, and rollback requirements are operational.

## Completed Pre-Code Gates

- Product Constitution coherent.
- Product class and boundary coherent.
- Business Twin/domain model documented.
- AI Organization and Controllers documented.
- Technical architecture documented.
- Human-value axiom embedded beyond prompts.
- Execution/permission separation defined.
- Prompt-injection/untrusted-data boundary documented.
- Data reconciliation and late-event rules documented.
- Causality boundary documented.
- Asset rights/provenance requirement documented.
- SaaS platform boundary documented.
- Engineering delivery contract documented.
- v11.0E UX/Information Architecture documented.
- v11.1 implementation spec documented.
- First connector feasibility documented for Telegram.
- Threat model and security acceptance tests written.
- First vertical-slice acceptance tests written.
- ADRs created for core irreversible choices.
- AGENTS.md created for future Codex sessions.

## Open Before Provider Implementation

- Verify exact v10 Telegram implementation details if reused.
- Confirm whether Telegram publication target is channel, group, or DM.
- Confirm bot admin/write permissions for the target Telegram surface.
- Re-verify Meta Instagram capabilities immediately before v11.2 implementation.
- Confirm GetCourse account domain, API key flow, callback configuration, and export limits.
- Identify actual payment provider(s) before payment connector design.
- Define source-of-truth hierarchy when GetCourse and payment provider data overlap.

## Open Before Production Pilot

- Create protected git workflow.
- Add CI.
- Add staging environment.
- Add migration tool and rollback discipline.
- Add database backup and restore test.
- Add secrets layer.
- Add audit logging.
- Add feature flag system.
- Add security regression suite as executable tests.
- Add agent/controller eval harness.
- Add connector fixtures.
- Verify global execution pause in staging.

## Scope Control Rule

The next engineering step is not "build the dashboard." The next engineering step is the narrow v11.1 closed loop:

`CreateLaunch -> BusinessSnapshot -> Decision -> controllers -> checkpoint -> CreativeBrief -> Asset -> review -> Approval -> Telegram publication -> observed result -> metric update -> Learning -> next Decision`

Do not add Instagram, GetCourse, payments, CRM, Creative Studio breadth, or autopilot until that loop closes.
