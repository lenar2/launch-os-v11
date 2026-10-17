# Project adapter: how to reuse Owner Gate

Specify only the mapping required for this run. Do **not** launch tools on skill discovery.

| Parameter | Examples | Required rule |
|---|---|---|
| `project_id` | P034, P006, any repo/service | Name one accountable project |
| `target_outcome` | Reliable user flow, valid artifact, crash fixed | Define observable acceptance signal |
| `artifact_selector` | repo+commit/tree, file hash, container digest, deployment release | Resolve to **immutable** object |
| `execution_environment` | Mac, iPhone, Linux, mock, staging, production | State versions and authorization |
| `reproduce` | commands, UI steps, E2E and controls | Capture expected/actual, timestamps |
| `repair` | source/config/test changes | Close class across sibling boundaries |
| `freeze` | SHA-256 + exact binary/config/git tree | Recompute after changes |
| `gate` | unit/integration/E2E/performance/security | Include negative control and actual process identity |
| `rollback` | git revert, deployment rollback, restore plan | No unauthorized live writes |
| `evidence_store` | private artifact store/CI logs/Git commit | Durable, redacted, immutable-ish refs |

For a project without CI or repository, use the same sequence on a bounded named artifact (specific file/export/configuration) and manually reproducible checks. If immutable fingerprint cannot be obtained, mark `BLOCKED` instead of pretending the object is frozen.

A single explicit user request may authorize GPT's normal within-scope diagnosis and repair. Production changes or irreversible actions still require applicable authorization. **Claude/Codex require additional separate explicit permission** specifying provider, exact frozen artifact and review purpose; there is no standing authorization across projects, sessions or artifact revisions.

Examples of *explicit execution* instructions:
- `Примени Owner Gate к P034 RC V3: воспроизведи сбой переключения, исправь класс, сверь SHA и предъяви доказательства. Не вызывай Claude/Codex.`
- `Запусти Owner Gate для P006 только на стенде, без остановки платных платежей.`

Examples that **do not activate**:
- `Создай Owner Gate как навык.`
- `У нас красный тест P034.`
- `Какая версия Owner Gate?`
- `Добавился коммит в ветку.`
