from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Generic, TypeAlias, TypeVar

from pydantic import BaseModel

from launch_os_v11.ai_runtime.errors import AIContractError

JsonObject: TypeAlias = dict[str, object]


class ModelCapability(StrEnum):
    DEEP_REASONING = "DEEP_REASONING"
    STANDARD_REASONING = "STANDARD_REASONING"
    FAST_STRUCTURED_CLASSIFICATION = "FAST_STRUCTURED_CLASSIFICATION"
    CREATIVE_COPY = "CREATIVE_COPY"
    VISION = "VISION"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    SPEECH_TO_TEXT = "SPEECH_TO_TEXT"
    EMBEDDINGS = "EMBEDDINGS"


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    FAILED = "FAILED"


class ModelResultKind(StrEnum):
    PARSED = "PARSED"
    REFUSAL = "REFUSAL"
    INCOMPLETE = "INCOMPLETE"
    INVALID_OUTPUT = "INVALID_OUTPUT"


OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


@dataclass(frozen=True)
class ProviderMetadata:
    provider_name: str
    model_name: str
    response_id: str | None
    token_usage: dict[str, int]
    latency_ms: int | None
    started_at: datetime
    completed_at: datetime

    def safe_dict(self) -> JsonObject:
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "response_id": self.response_id,
            "token_usage": dict(self.token_usage),
            "latency_ms": self.latency_ms,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass(frozen=True)
class ModelRequest(Generic[OutputModelT]):
    capability: ModelCapability
    system_instructions: str
    instruction_version: str
    structured_context: str
    context_manifest: JsonObject
    context_hash: str
    output_type: type[OutputModelT]
    correlation_id: str | None
    causation_id: str | None
    safe_generation_policy: str | None = None


@dataclass(frozen=True)
class ModelResult(Generic[OutputModelT]):
    kind: ModelResultKind
    parsed_output: OutputModelT | None
    refusal: str | None
    incomplete_reason: str | None
    invalid_output_reason: str | None
    metadata: ProviderMetadata


@dataclass(frozen=True)
class AgentContract:
    contract_key: str
    contract_version: int
    role_name: str
    mission: str
    allowed_context_types: tuple[str, ...]
    required_context_types: tuple[str, ...]
    output_schema_name: str
    output_schema_version: int
    output_model: type[BaseModel]
    model_capability: ModelCapability
    authority_boundaries: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    required_controller_types: tuple[str, ...]
    abstention_policy: str
    escalation_policy: str
    instruction_version: str
    system_instructions: str
    eval_suite_identifier: str

    def __post_init__(self) -> None:
        _validate_contract(self)

    @property
    def fingerprint(self) -> str:
        payload = self.definition_payload()
        payload["output_schema"] = self.output_model.model_json_schema()
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def definition_payload(self) -> JsonObject:
        return {
            "contract_key": self.contract_key,
            "contract_version": self.contract_version,
            "role_name": self.role_name,
            "mission": self.mission,
            "allowed_context_types": list(self.allowed_context_types),
            "required_context_types": list(self.required_context_types),
            "output_schema_name": self.output_schema_name,
            "output_schema_version": self.output_schema_version,
            "model_capability": self.model_capability.value,
            "authority_boundaries": list(self.authority_boundaries),
            "prohibited_actions": list(self.prohibited_actions),
            "required_controller_types": list(self.required_controller_types),
            "abstention_policy": self.abstention_policy,
            "escalation_policy": self.escalation_policy,
            "instruction_version": self.instruction_version,
            "system_instructions": self.system_instructions,
            "eval_suite_identifier": self.eval_suite_identifier,
        }

    def immutable_projection(self) -> MappingProxyType[str, object]:
        return MappingProxyType(self.definition_payload())


def _validate_contract(contract: AgentContract) -> None:
    required_strings = {
        "contract_key": contract.contract_key,
        "role_name": contract.role_name,
        "mission": contract.mission,
        "output_schema_name": contract.output_schema_name,
        "abstention_policy": contract.abstention_policy,
        "escalation_policy": contract.escalation_policy,
        "instruction_version": contract.instruction_version,
        "system_instructions": contract.system_instructions,
        "eval_suite_identifier": contract.eval_suite_identifier,
    }
    missing = [name for name, value in required_strings.items() if not value.strip()]
    if missing:
        raise AIContractError(f"incomplete agent contract fields: {', '.join(sorted(missing))}")
    if contract.contract_version < 1:
        raise AIContractError("agent contract version must be positive")
    if contract.output_schema_version < 1:
        raise AIContractError("output schema version must be positive")
    if not contract.allowed_context_types:
        raise AIContractError("agent contract must declare allowed context types")
    if not set(contract.required_context_types).issubset(set(contract.allowed_context_types)):
        raise AIContractError("required context types must be a subset of allowed context types")
    if not contract.authority_boundaries:
        raise AIContractError("agent contract must declare authority boundaries")
    if not contract.prohibited_actions:
        raise AIContractError("agent contract must declare prohibited actions")
    if not contract.required_controller_types:
        raise AIContractError("agent contract must declare required controller types")

    write_authority_markers = {
        "CAN_WRITE",
        "EXTERNAL_WRITE",
        "CONNECTOR_WRITE",
        "EXECUTION_WRITE",
        "HAS_CREDENTIALS",
        "TOOL_WRITE",
        "DIRECT_CONNECTOR",
    }
    normalized_boundaries = {value.strip().upper() for value in contract.authority_boundaries}
    if normalized_boundaries & write_authority_markers:
        raise AIContractError(
            "agent contract cannot grant write, connector, or credential authority"
        )

    joined_actions = " ".join(contract.prohibited_actions).lower()
    for required_prohibition in ("external write", "connector", "credential"):
        if required_prohibition not in joined_actions:
            raise AIContractError(
                "agent contract must explicitly prohibit external writes, "
                "connectors, and credentials"
            )
