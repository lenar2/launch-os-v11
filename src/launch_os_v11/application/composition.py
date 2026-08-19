from __future__ import annotations

from launch_os_v11.ai_runtime.composition import compose_handler_registry as compose_ai_handlers
from launch_os_v11.ai_runtime.context import ContextBuilder
from launch_os_v11.ai_runtime.errors import AIConfigurationError
from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.ai_runtime.router import ModelRouter
from launch_os_v11.analytics.phase6 import phase6_handler_registry
from launch_os_v11.application.phase6 import Phase6DecisionWorkflowAdvanceHandler
from launch_os_v11.application.production_workflow import ProductionWorkflowAdvanceHandler
from launch_os_v11.application.workflow_dispatcher import WorkflowAdvanceDispatcher
from launch_os_v11.connectors.telegram_observation import (
    TelegramHttpObservationConnector,
    TelegramObservationConnector,
)
from launch_os_v11.execution.contracts import TelegramConnector
from launch_os_v11.execution.service import TelegramExecutionHandler
from launch_os_v11.execution.telegram import SettingsSecretResolver, TelegramHttpConnector
from launch_os_v11.platform.config import Settings
from launch_os_v11.production.context import ProductionContextBuilder
from launch_os_v11.production.registry import phase4_agent_registry
from launch_os_v11.runtime.contracts import (
    JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH,
    JOB_TYPE_WORKFLOW_ADVANCE,
)
from launch_os_v11.runtime.handlers import JobHandler
from launch_os_v11.runtime.transport import JobQueue


def compose_application_handler_registry(
    *,
    settings: Settings,
    queue: JobQueue,
    registry: AgentRegistry | None = None,
    model_router: ModelRouter | None = None,
    context_builder: ContextBuilder | None = None,
    telegram_connector: TelegramConnector | None = None,
    telegram_observation_connector: TelegramObservationConnector | None = None,
) -> dict[str, JobHandler]:
    actual_registry = registry or phase4_agent_registry()
    actual_context_builder = context_builder or ProductionContextBuilder()
    handlers = compose_ai_handlers(
        settings=settings,
        registry=actual_registry,
        model_router=model_router,
        context_builder=actual_context_builder,
    )
    actual_telegram_connector = telegram_connector or TelegramHttpConnector(
        secret_resolver=SettingsSecretResolver(settings)
    )
    handlers[JOB_TYPE_EXECUTION_TELEGRAM_PUBLISH] = TelegramExecutionHandler(
        connector=actual_telegram_connector
    )
    actual_observation_connector = (
        telegram_observation_connector
        or TelegramHttpObservationConnector(settings=settings)
    )
    handlers.update(
        phase6_handler_registry(
            queue=queue,
            telegram_observation_connector=actual_observation_connector,
        )
    )
    if not settings.launch_workflow_enabled and model_router is None:
        return handlers
    if not settings.ai_team_enabled and model_router is None:
        raise AIConfigurationError(
            "Phase 3-6 governed workflows require the governed AI runtime"
        )
    decision_handler = Phase6DecisionWorkflowAdvanceHandler(
        registry=actual_registry,
        queue=queue,
    )
    production_handler = ProductionWorkflowAdvanceHandler(
        registry=actual_registry,
        queue=queue,
    )
    handlers[JOB_TYPE_WORKFLOW_ADVANCE] = WorkflowAdvanceDispatcher(
        decision_handler=decision_handler,
        production_handler=production_handler,
    )
    return handlers
