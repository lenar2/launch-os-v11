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
