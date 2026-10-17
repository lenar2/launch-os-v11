# Owner Gate — portable AI Factory skill

A **manual-only** portable Agent Skill for GPT as engineering OutcomeOwner. It does **not** install an automatic audit, start a project task, call Claude/Codex, create CI, set timers or deploy anything.

## Install / reuse

Copy this directory to your agent's local skills directory (for example `skills/owner-gate/` or `.agents/skills/owner-gate/` according to the platform's supported convention), keeping `SKILL.md` and `references/`. Place it in one shared repository or copy into different project workspaces. No project-specific hardcoded values are required. Merely installing the skill is inert.

Then explicitly instruct GPT, for example:

`Примени Owner Gate к P034 для артефакта <точный ref>. Сам воспроизведи дефекты, исправь класс, проведи adversarial-проверку и запиши доказательства. Claude и Codex не вызывать.`

The user should grant separate specific approval before a Claude or Codex review:

`Разрешаю Claude [или Codex] проверить замороженный артефакт <SHA> по scope <...> после твоего Owner Gate. Других моделей не запускать.`

## Files

- `SKILL.md` — operative instructions and explicit activation guard.
- `references/adversarial-matrix.md` — ten canonical axes + project-specific negative controls.
- `references/project-adapter.md` — apply across repos, clients, bots and services.
- `references/evidence-and-compatibility.md` — receipts + compatibility with Factory governance.
- `templates/owner-gate-run.example.json` — clearly inert, example-only non-evidence manifest.
- `templates/owner-gate-report.md` — human-readable report template.
- `tests/test_package.py` — package-level static guard tests; **not** a project audit.

## Compatibility

Built to be additive to `AI Factory OutcomeOwner Closure Protocol v1` and `Delegated Task Completion Contract v1` in the private `lenar2/ai-factory-evidence` repository. Canonical receipts must use the repository's current validator and schema, not a locally guessed PASS rule.

## Scope of this delivery

Creation of a reusable skill package only. No Factory project artifacts were audited; no production changes, branch commits, external-review delegation or scheduled checks were executed.
