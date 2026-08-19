# Launch OS v11

Status: canonical architecture with governed implementation phases in progress.

Launch OS v11 is an AI-native operating system for growth, launches, content, social media, sales, and retention for expert, creator, and education businesses. It maintains a connected Business Twin, coordinates specialist AI capabilities and independent controllers, creates real assets, executes approved actions through permissioned connectors, observes outcomes, and learns from real traces.

Start here:

- `docs/PRODUCT_CONSTITUTION.md`
- `docs/ARCHITECTURE_CANONICAL.md`
- `docs/DOMAIN_MODEL.md`
- `docs/AI_ORGANIZATION.md`
- `docs/SECURITY_BOUNDARIES.md`
- `docs/UX_JOURNEYS.md`
- `docs/ENGINEERING_DELIVERY_CONTRACT.md`
- `docs/V11_1_IMPLEMENTATION_SPEC.md`
- `docs/PRE_CODE_GO_NO_GO.md`
- `AGENTS.md`

Current implementation posture:

- Architecture: ready.
- Phase 0/1 domain and persistence foundation: implemented and accepted.
- Phase 2A durable async runtime: implemented and accepted.
- Phase 2B governed AI runtime foundation: implemented and accepted behind explicit runtime contracts and deterministic fake-adapter CI coverage.
- Phase 3 governed business decision workflow: implemented and accepted.
- Phase 4 governed production workflow: implemented and accepted for one Telegram-ready text asset, with version-bound truth/brand/constitutional/manipulation/legal/quality/rights review and no external write.
- Phase 5 governed Telegram execution: implemented and accepted, including one live owner-approved publication to a dedicated Telegram test channel, persisted external message ID, audit/outbox evidence, secret redaction, and duplicate-job protection.
- Phase 6 governed observation, deterministic MetricVersion, checkpoint interpretation, bounded learning, and owner-gated successor Decision adaptation: implementation in progress under ADR 0010. Closure requires PostgreSQL/Redis acceptance and a fresh live Telegram observation trace; the Phase 5 publication is not retrofitted into a Phase 6 experiment.

First build target:

`CreateLaunch -> BusinessSnapshot -> Decision -> controllers -> checkpoint -> CreativeBrief -> Asset -> review -> Approval -> Telegram publication -> observed result -> metric update -> Learning -> next Decision`

Do not expand broad modules until this loop closes in staging.

## Development

Install dependencies:

`python3 -m pip install -r requirements-dev.lock && python3 -m pip install -e . --no-deps`

Run checks:

`make check`

Run PostgreSQL 16 integration checks with Docker:

`make test-postgres`

Run Phase 2A PostgreSQL + Redis runtime integration checks with Docker:

`make test-runtime`

Run Phase 2B governed AI runtime PostgreSQL + Redis integration checks with Docker and the deterministic fake adapter:

`make test-ai-runtime`

Run Phase 3 governed decision workflow integration:

`make test-decision-workflow`

Run Phase 4 governed production workflow integration:

`make test-production-workflow`

Run Phase 5 governed Telegram execution integration with the deterministic fake connector:

`make test-telegram-execution`

Run Phase 6 governed observation/learning integration:

`make test-phase6-learning`

Run migrations locally against the configured `LAUNCH_OS_DATABASE_URL`:

`make migrate`

Rollback to base:

`make downgrade`

Run the API skeleton:

`make run-api`

Run local worker/scheduler processes through Docker Compose:

`docker compose -f docker-compose.local.yml --profile runtime up worker scheduler`

Local PostgreSQL and Redis are described in `docker-compose.local.yml`. PostgreSQL integration uses `docker-compose.integration.yml`. Staging-only compose is in `docker-compose.staging.yml`. No production compose or production secrets are present.
