from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from launch_os_v11.domain.scope import TenantScope

JOB_TYPE_AI_RUN_AGENT: Final = "ai.run_agent"
JOB_TYPE_AI_RUN_CONTROLLER: Final = "ai.run_controller"
JOB_TYPE_WORKFLOW_ADVANCE: Final = "workflow.advance"
JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH: Final = "execution.telegram_publish"
JOB_TYPE_EXPERIMENT_CHECKPOINT: Final = "experiment.checkpoint"
JOB_TYPE_LEARNING_EVALUATE: Final = "learning.evaluate"
JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES: Final = "connector.telegram.observe_updates"
JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION: Final = (
    "analytics.normalize_connector_observation"
)
JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION: Final = "analytics.calculate_metric_version"
JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT: Final = "learning.interpret_checkpoint"
JOB_TYPE_LEARNING_RUN_GOVERNED: Final = "learning.run_governed_learning"
JOB_TYPE_OUTBOX_DISPATCH: Final = "outbox.dispatch"
JOB_TYPE_RUNTIME_PROBE: Final = "runtime.probe"

PHASE6_JOB_TYPES: Final[frozenset[str]] = frozenset(
    {
        JOB_TYPE_CONNECTOR_TELEGRAM_OBSERVE_UPDATES,
        JOB_TYPE_ANALYTICS_NORMALIZE_CONNECTOR_OBSERVATION,
        JOB_TYPE_ANALYTICS_CALCULATE_METRIC_VERSION,
        JOB_TYPE_LEARNING_INTERPRET_CHECKPOINT,
        JOB_TYPE_LEARNING_RUN_GOVERNED,
    }
)

CANONICAL_JOB_TYPES: Final[frozenset[str]] = frozenset(
    {
        JOB_TYPE_AI_RUN_AGENT,
        JOB_TYPE_AI_RUN_CONTROLLER,
        JOB_TYPE_WORKFLOW_ADVANCE,
        JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
        JOB_TYPE_EXPERIMENT_CHECKPOINT,
        JOB_TYPE_LEARNING_EVALUATE,
        *PHASE6_JOB_TYPES,
        JOB_TYPE_OUTBOX_DISPATCH,
    }
)

RESERVED_JOB_TYPES: Final[frozenset[str]] = CANONICAL_JOB_TYPES - {
    JOB_TYPE_AI_RUN_AGENT,
    JOB_TYPE_AI_RUN_CONTROLLER,
    JOB_TYPE_WORKFLOW_ADVANCE,
    JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
    *PHASE6_JOB_TYPES,
    JOB_TYPE_OUTBOX_DISPATCH,
}
EXECUTABLE_JOB_TYPES: Final[frozenset[str]] = frozenset(
    {
        JOB_TYPE_AI_RUN_AGENT,
        JOB_TYPE_AI_RUN_CONTROLLER,
        JOB_TYPE_WORKFLOW_ADVANCE,
        JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
        *PHASE6_JOB_TYPES,
        JOB_TYPE_OUTBOX_DISPATCH,
        JOB_TYPE_RUNTIME_PROBE,
    }
)
REGISTERED_JOB_TYPES: Final[frozenset[str]] = CANONICAL_JOB_TYPES | {JOB_TYPE_RUNTIME_PROBE}


@dataclass(frozen=True)
class RuntimeJobContext:
    organization_id: str
    business_id: str
    job_id: str
    job_type: str
    attempt_count: int
    correlation_id: str | None
    causation_id: str | None

    @property
    def scope(self) -> TenantScope:
        return TenantScope(
            organization_id=self.organization_id,
            business_id=self.business_id,
        )
