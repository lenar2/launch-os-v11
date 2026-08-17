from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel

from launch_os_v11.ai_runtime.adapters.base import ModelAdapter
from launch_os_v11.ai_runtime.contracts import ModelCapability
from launch_os_v11.ai_runtime.errors import AIConfigurationError


@dataclass(frozen=True)
class ModelRoute:
    capability: ModelCapability
    provider_name: str
    model_name: str


@dataclass(frozen=True)
class ResolvedModelRoute:
    route: ModelRoute
    adapter: ModelAdapter[BaseModel]


class ModelRouter:
    def __init__(
        self,
        *,
        routes: dict[ModelCapability, ModelRoute],
        adapters: dict[str, ModelAdapter[BaseModel]],
    ) -> None:
        for capability, route in routes.items():
            if route.capability != capability:
                raise AIConfigurationError(
                    f"model route capability mismatch for {capability.value}"
                )
        self._routes = MappingProxyType(dict(routes))
        self._adapters = MappingProxyType(dict(adapters))

    def resolve(self, capability: ModelCapability) -> ResolvedModelRoute:
        route = self._routes.get(capability)
        if route is None:
            raise AIConfigurationError(
                f"no model route configured for capability {capability.value}"
            )
        adapter = self._adapters.get(route.provider_name)
        if adapter is None:
            raise AIConfigurationError(f"no adapter configured for provider {route.provider_name}")
        return ResolvedModelRoute(route=route, adapter=adapter)

    def route_matrix(self) -> dict[str, dict[str, str]]:
        return {
            capability.value: {
                "provider": route.provider_name,
                "model": route.model_name,
            }
            for capability, route in self._routes.items()
        }
