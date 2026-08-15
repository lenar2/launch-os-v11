# Launch OS v11

Status: pre-code canonical handoff converted into repository docs.

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
- Codebase creation: ready for v11.1 vertical-slice scaffolding.
- Broad feature implementation: not yet.

First build target:

`CreateLaunch -> BusinessSnapshot -> Decision -> controllers -> checkpoint -> CreativeBrief -> Asset -> review -> Approval -> Telegram publication -> observed result -> metric update -> Learning -> next Decision`

Do not expand broad modules until this loop closes in staging.

## Development

Install dependencies:

`python3 -m pip install -r requirements-dev.lock && python3 -m pip install -e . --no-deps`

For dependency refresh during development, `make install` resolves from `pyproject.toml`; update `requirements-dev.lock` in a clean virtual environment when accepted.

Run checks:

`make check`

Run PostgreSQL 16 integration checks with Docker:

`make test-postgres`

Run Phase 2A PostgreSQL + Redis runtime integration checks with Docker:

`make test-runtime`

Run migrations locally against the configured `LAUNCH_OS_DATABASE_URL`:

`make migrate`

Rollback to base:

`make downgrade`

Run the API skeleton:

`make run-api`

Run local worker/scheduler processes through Docker Compose:

`docker compose -f docker-compose.local.yml --profile runtime up worker scheduler`

Local PostgreSQL and Redis are described in `docker-compose.local.yml`. PostgreSQL integration uses `docker-compose.integration.yml`. Staging-only compose is in `docker-compose.staging.yml`. No production compose or production secrets are present.
