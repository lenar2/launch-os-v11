from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from launch_os_v11.ai_runtime.contracts import (
    ModelRequest,
    ModelResult,
    ModelResultKind,
    OutputModelT,
    ProviderMetadata,
)
from launch_os_v11.ai_runtime.errors import (
    AIConfigurationError,
    AIPermanentProviderError,
    AITransientProviderError,
)


class OpenAIResponsesAdapter:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model_name: str,
        client: Any | None = None,
    ) -> None:
        if client is None and not api_key:
            raise AIConfigurationError("OpenAI adapter requires OPENAI_API_KEY")
        self.model_name = model_name
        self._client = client or OpenAI(api_key=api_key, max_retries=0)

    def invoke(self, request: ModelRequest[OutputModelT]) -> ModelResult[OutputModelT]:
        started_at = datetime.now(tz=UTC)
        start_monotonic = perf_counter()
        try:
            response = self._client.responses.parse(
                model=request.selected_model_name,
                instructions=request.system_instructions,
                input=[
                    {
                        "role": "user",
                        "content": request.structured_context,
                    }
                ],
                text_format=request.output_type,
                store=False,
            )
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise AITransientProviderError(_safe_error(exc)) from exc
        except APIStatusError as exc:
            if _is_transient_status(exc.status_code):
                raise AITransientProviderError(_safe_error(exc)) from exc
            raise AIPermanentProviderError(_safe_error(exc)) from exc
        except APIError as exc:
            raise AIPermanentProviderError(_safe_error(exc)) from exc
        except ValidationError as exc:
            completed_at = datetime.now(tz=UTC)
            metadata = ProviderMetadata(
                provider_name=self.provider_name,
                model_name=request.selected_model_name,
                response_id=None,
                token_usage={},
                latency_ms=int((perf_counter() - start_monotonic) * 1000),
                started_at=started_at,
                completed_at=completed_at,
            )
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason=exc.errors()[0]["msg"],
                metadata=metadata,
            )

        completed_at = datetime.now(tz=UTC)
        metadata = ProviderMetadata(
            provider_name=self.provider_name,
            model_name=request.selected_model_name,
            response_id=_response_id(response),
            token_usage=_token_usage(response),
            latency_ms=int((perf_counter() - start_monotonic) * 1000),
            started_at=started_at,
            completed_at=completed_at,
        )
        refusal = _extract_refusal(response)
        if refusal is not None:
            return ModelResult(
                kind=ModelResultKind.REFUSAL,
                parsed_output=None,
                refusal=refusal,
                incomplete_reason=None,
                invalid_output_reason=None,
                metadata=metadata,
            )
        incomplete_reason = _incomplete_reason(response)
        if incomplete_reason is not None:
            return ModelResult(
                kind=ModelResultKind.INCOMPLETE,
                parsed_output=None,
                refusal=None,
                incomplete_reason=incomplete_reason,
                invalid_output_reason=None,
                metadata=metadata,
            )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason="OpenAI response did not include parsed structured output",
                metadata=metadata,
            )
        if not isinstance(parsed, request.output_type):
            return ModelResult(
                kind=ModelResultKind.INVALID_OUTPUT,
                parsed_output=None,
                refusal=None,
                incomplete_reason=None,
                invalid_output_reason="OpenAI parsed output type did not match requested schema",
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


def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


def _safe_error(error: BaseException) -> str:
    if isinstance(error, APIStatusError):
        return f"{error.__class__.__name__}: provider status {error.status_code}"
    return f"{error.__class__.__name__}: provider request failed"


def _response_id(response: Any) -> str | None:
    value = getattr(response, "id", None) or getattr(response, "_request_id", None)
    if isinstance(value, str):
        return value
    return None


def _token_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    result: dict[str, int] = {}
    for source_name, target_name in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, source_name, None)
        if isinstance(value, int):
            result[target_name] = value
    return result


def _extract_refusal(response: Any) -> str | None:
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return None
    for item in output:
        content = getattr(item, "content", None)
        if not isinstance(content, list):
            continue
        for part in content:
            part_type = getattr(part, "type", None)
            refusal = getattr(part, "refusal", None)
            if part_type == "refusal" and isinstance(refusal, str):
                return refusal
    return None


def _incomplete_reason(response: Any) -> str | None:
    if getattr(response, "status", None) != "incomplete":
        return None
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    if isinstance(reason, str):
        return reason
    return "incomplete"
