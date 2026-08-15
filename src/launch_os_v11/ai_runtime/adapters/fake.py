from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic

from pydantic import ValidationError

from launch_os_v11.ai_runtime.contracts import (
    ModelRequest,
    ModelResult,
    ModelResultKind,
    OutputModelT,
    ProviderMetadata,
)
from launch_os_v11.ai_runtime.errors import (
    AIPermanentProviderError,
    AITransientProviderError,
)


@dataclass(frozen=True)
class FakeAdapterScriptStep:
    kind: ModelResultKind | str
    payload: dict[str, object] | None = None
    refusal: str | None = None
    incomplete_reason: str | None = None
    invalid_output_reason: str | None = None
    error_message: str = "scripted provider failure"


class FakeModelAdapter(Generic[OutputModelT]):
    provider_name = "fake"

    def __init__(
        self,
        *,
        model_name: str = "fake-structured-model",
        script: list[FakeAdapterScriptStep] | None = None,
    ) -> None:
        self.model_name = model_name
        self._script = list(script or [])
        self.calls: list[ModelRequest[OutputModelT]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: ModelRequest[OutputModelT]) -> ModelResult[OutputModelT]:
        self.calls.append(request)
        started_at = datetime.now(tz=UTC)
        completed_at = datetime.now(tz=UTC)
        step = self._script.pop(0) if self._script else _default_success_step()
        metadata = ProviderMetadata(
            provider_name=self.provider_name,
            model_name=self.model_name,
            response_id=f"fake-response-{self.call_count}",
            token_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            latency_ms=0,
            started_at=started_at,
            completed_at=completed_at,
        )
        if step.kind == "transient_error":
            raise AITransientProviderError(step.error_message)
        if step.kind == "permanent_error":
            raise AIPermanentProviderError(step.error_message)
        if step.kind == ModelResultKind.REFUSAL:
            return ModelResult(
                kind=ModelResultKind.REFUSAL,
                parsed_output=None,
                refusal=step.refusal or "fake refusal",
                incomplete_reason=None,
                invalid_output_reason=None,
                metadata=metadata,
            )
        if step.kind == ModelResultKind.INCOMPLETE:
            return ModelResult(
                kind=ModelResultKind.INCOMPLETE,
                parsed_output=None,
                refusal=None,
                incomplete_reason=step.incomplete_reason or "fake incomplete response",
                invalid_output_reason=None,
                metadata=metadata,
            )
        if step.kind == ModelResultKind.INVALID_OUTPUT:
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason=step.invalid_output_reason or "fake invalid output",
                metadata=metadata,
            )
        try:
            parsed = request.output_type.model_validate(step.payload or {})
        except ValidationError as exc:
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason=exc.errors()[0]["msg"],
                metadata=metadata,
            )
        return ModelResult(
            kind=ModelResultKind.PARSED,
            parsed_output=parsed,
            refusal=None,
            incomplete_reason=None,
            invalid_output_reason=None,
            metadata=metadata,
        )


def _default_success_step() -> FakeAdapterScriptStep:
    return FakeAdapterScriptStep(
        kind=ModelResultKind.PARSED,
        payload={
            "schema_name": "RuntimeProbeOutput",
            "schema_version": 1,
            "message": "fake runtime probe completed",
            "facts_used": [],
            "hypotheses": [],
            "unknowns": [],
            "confidence": 0.5,
        },
    )
