from __future__ import annotations

from pydantic import BaseModel, SecretStr

from launch_os_v11.ai_runtime.adapters.base import ModelAdapter
from launch_os_v11.ai_runtime.context import ContextBuilder
from launch_os_v11.ai_runtime.contracts import ModelCapability
from launch_os_v11.ai_runtime.errors import AIConfigurationError
from launch_os_v11.ai_runtime.job_handler import AgentRunJobHandler
from launch_os_v11.ai_runtime.registry import AgentRegistry, default_agent_registry
from launch_os_v11.ai_runtime.router import ModelRoute, ModelRouter
from launch_os_v11.platform.config import Settings
from launch_os_v11.runtime.contracts import JOB_TYPE_AI_RUN_AGENT, JOB_TYPE_AI_RUN_CONTROLLER
from launch_os_v11.runtime.handlers import JobHandler, default_handler_registry


def compose_handler_registry(
    *,
    settings: Settings,
    registry: AgentRegistry | None = None,
    model_router: ModelRouter | None = None,
    context_builder: ContextBuilder | None = None,
) -> dict[str, JobHandler]:
    handlers = default_handler_registry()
    if not settings.ai_team_enabled and model_router is None:
        return handlers
    ai_handler = AgentRunJobHandler(
        registry=registry or default_agent_registry(),
        context_builder=context_builder or ContextBuilder(),
        model_router=model_router or model_router_from_settings(settings),
    )
    handlers[JOB_TYPE_AI_RUN_AGENT] = ai_handler
    handlers[JOB_TYPE_AI_RUN_CONTROLLER] = ai_handler
    return handlers


def model_router_from_settings(settings: Settings) -> ModelRouter:
    if not settings.ai_team_enabled:
        raise AIConfigurationError("feature flag v11_ai_team is disabled")
    provider = settings.ai_model_provider
    if provider != "openai":
        raise AIConfigurationError("LAUNCH_OS_AI_MODEL_PROVIDER must be 'openai' for live routing")
    model_name = settings.ai_openai_text_model
    if not model_name:
        raise AIConfigurationError("LAUNCH_OS_AI_OPENAI_TEXT_MODEL is required")
    api_key = _secret_value(settings.openai_api_key)
    from launch_os_v11.ai_runtime.adapters.openai import OpenAIResponsesAdapter

    adapter = OpenAIResponsesAdapter(api_key=api_key, model_name=model_name)
    return ModelRouter(
        routes={
            ModelCapability.DEEP_REASONING: ModelRoute(
                capability=ModelCapability.DEEP_REASONING,
                provider_name=adapter.provider_name,
                model_name=model_name,
            ),
            ModelCapability.STANDARD_REASONING: ModelRoute(
                capability=ModelCapability.STANDARD_REASONING,
                provider_name=adapter.provider_name,
                model_name=model_name,
            ),
            ModelCapability.FAST_STRUCTURED_CLASSIFICATION: ModelRoute(
                capability=ModelCapability.FAST_STRUCTURED_CLASSIFICATION,
                provider_name=adapter.provider_name,
                model_name=model_name,
            ),
            ModelCapability.CREATIVE_COPY: ModelRoute(
                capability=ModelCapability.CREATIVE_COPY,
                provider_name=adapter.provider_name,
                model_name=model_name,
            ),
        },
        adapters={adapter.provider_name: adapter},
    )


def fake_model_router(adapter: ModelAdapter[BaseModel]) -> ModelRouter:
    model_name = getattr(adapter, "model_name", "fake-structured-model")
    return ModelRouter(
        routes={
            capability: ModelRoute(
                capability=capability,
                provider_name=adapter.provider_name,
                model_name=model_name,
            )
            for capability in ModelCapability
        },
        adapters={adapter.provider_name: adapter},
    )


def _secret_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    return value.get_secret_value()
