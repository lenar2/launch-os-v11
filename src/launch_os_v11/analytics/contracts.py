from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictPhase6Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TypedThreshold(_StrictPhase6Model):
    operator: Literal["GTE", "GT", "LTE", "LT", "EQ"]
    value: float = Field(ge=0)


class Phase6CheckpointSpec(_StrictPhase6Model):
    schema_version: Literal[1] = 1
    metric_key: Literal["telegram_reaction_changes"] = "telegram_reaction_changes"
    window_seconds: int = Field(ge=1, le=86400)
    grace_seconds: int = Field(ge=0, le=3600)
    success: TypedThreshold
    weak_signal: TypedThreshold
    failure: TypedThreshold
    coverage_requirement: Literal["COMPLETE"] = "COMPLETE"
    attribution_method: Literal["telegram_message_lineage"] = "telegram_message_lineage"
    next_action_on_success: str = Field(min_length=1)
    next_action_on_weak_signal: str = Field(min_length=1)
    next_action_on_failure: str = Field(min_length=1)

    @model_validator(mode="after")
    def _first_slice_thresholds_are_deterministic(self) -> Phase6CheckpointSpec:
        if self.success.operator != "GTE" or self.weak_signal.operator != "GTE":
            raise ValueError("reaction-count success and weak-signal thresholds must use GTE")
        if self.failure.operator != "EQ" or self.failure.value != 0:
            raise ValueError("reaction-count failure threshold must be EQ 0")
        if not self.success.value > self.weak_signal.value > 0:
            raise ValueError("success must be greater than weak signal, which must be positive")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def contract_hash(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
