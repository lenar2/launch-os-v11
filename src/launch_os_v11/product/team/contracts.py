"""Shared assignment contract for every specialist transport."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

REAL_MODEL_EXECUTION = "NOT_YET_PROVEN"
TEST_DOUBLE = "TEST_DOUBLE"


@dataclass(frozen=True)
class LaunchConstraints:
    budget_cents: int
    weeks: int
    offer_wording: str

    def to_json(self) -> dict[str, object]:
        return {
            "budget_cents": self.budget_cents,
            "weeks": self.weeks,
            "offer_wording": self.offer_wording,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> LaunchConstraints:
        budget = payload.get("budget_cents")
        weeks = payload.get("weeks")
        wording = payload.get("offer_wording")
        if not isinstance(budget, int) or not isinstance(weeks, int):
            raise ValueError("constraints are incomplete")
        if not isinstance(wording, str) or not wording.strip():
            raise ValueError("offer wording is required")
        return cls(budget_cents=budget, weeks=weeks, offer_wording=wording.strip())


@dataclass(frozen=True)
class ArtifactView:
    artifact_id: str
    role_id: str
    version: int
    body: Mapping[str, object]


@dataclass(frozen=True)
class Assignment:
    role_id: str
    responsibility: str
    tools: tuple[str, ...]
    intent: str
    constraints: LaunchConstraints
    inputs: Mapping[str, ArtifactView]


@dataclass(frozen=True)
class SpecialistOutput:
    body: dict[str, object]
    quality: str
    provenance: str


@dataclass(frozen=True)
class RoleStatus:
    role_id: str
    title: str
    state: str
    version: int | None
    summary: str


@dataclass(frozen=True)
class TeamSnapshot:
    status: str
    provenance: str
    real_model_execution: str
    roles: tuple[RoleStatus, ...]
    conflicts: tuple[str, ...]
    needs_owner: tuple[str, ...]
    materials: tuple[str, ...]
    ready_step: str
