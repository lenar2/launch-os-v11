from __future__ import annotations

from typing import Generic, Protocol

from launch_os_v11.ai_runtime.contracts import ModelRequest, ModelResult, OutputModelT


class ModelAdapter(Protocol, Generic[OutputModelT]):
    provider_name: str

    def invoke(self, request: ModelRequest[OutputModelT]) -> ModelResult[OutputModelT]:
        """Return a typed structured result or raise a classified runtime error."""
