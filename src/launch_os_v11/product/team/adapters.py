"""Test-double specialists and the two unconnected real transports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from launch_os_v11.product.team.contracts import (
    TEST_DOUBLE,
    ArtifactView,
    Assignment,
    SpecialistOutput,
)


class ModelUnavailable(Exception):
    """The selected transport has no authorized runtime."""


class TransientTeamError(Exception):
    """The worker may retry this assignment."""


class SpecialistExecutor(Protocol):
    provenance: str

    def execute(self, assignment: Assignment) -> SpecialistOutput:
        """Return one structured result. Do not perform an external action."""


class ModelInvocationExecutor:
    provenance = "MODEL_INVOCATION_NOT_CONNECTED"

    def execute(self, assignment: Assignment) -> SpecialistOutput:
        del assignment
        raise ModelUnavailable(
            "No model provider is connected. REAL_MODEL_EXECUTION=NOT_YET_PROVEN."
        )


class ChatBridgeExecutor:
    provenance = "CHAT_BRIDGE_NOT_CONNECTED"

    def execute(self, assignment: Assignment) -> SpecialistOutput:
        del assignment
        raise ModelUnavailable(
            "No persistent chat bridge is connected. REAL_MODEL_EXECUTION=NOT_YET_PROVEN."
        )


class TestDoubleExecutor:
    """Deterministic stand-in. Outputs change when their inputs change."""

    provenance = TEST_DOUBLE

    def execute(self, assignment: Assignment) -> SpecialistOutput:
        builder = _BUILDERS.get(assignment.role_id, _added_role)
        body = builder(assignment)
        return SpecialistOutput(body=body, quality=_quality(body), provenance=TEST_DOUBLE)


def _quality(body: Mapping[str, object]) -> str:
    conflicts = body.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        return "BLOCKED"
    if body.get("verdict") == "BLOCKED":
        return "BLOCKED"
    return "PASS_WITH_UNKNOWNS"


def _ids(assignment: Assignment) -> dict[str, str]:
    return {role: item.artifact_id for role, item in assignment.inputs.items()}


def _body(assignment: Assignment, role: str) -> Mapping[str, object]:
    return assignment.inputs[role].body


def _weeks(value: object) -> int:
    if isinstance(value, int):
        return value
    return -1


def _audience(assignment: Assignment) -> dict[str, object]:
    return {
        "known": ["The founder said the audience already exists."],
        "unknown": ["audience size", "willingness to pay", "reply rate"],
        "demand": "UNKNOWN",
        "size": "UNKNOWN",
        "input_ids": _ids(assignment),
    }


def _offer(assignment: Assignment) -> dict[str, object]:
    audience = _body(assignment, "audience")
    return {
        "wording": assignment.constraints.offer_wording,
        "price_assumption_cents": assignment.constraints.budget_cents // 10,
        "price_status": "ASSUMPTION",
        "audience_unknowns": audience.get("unknown"),
        "audience_artifact_id": assignment.inputs["audience"].artifact_id,
        "promise": "A reviewable course for the existing audience. It promises no outcome.",
        "input_ids": _ids(assignment),
    }


def _strategy(assignment: Assignment) -> dict[str, object]:
    offer = _body(assignment, "offer")
    weeks = assignment.constraints.weeks
    return {
        "weeks": weeks,
        "budget_cents": assignment.constraints.budget_cents,
        "offer_wording": offer.get("wording"),
        "mechanism": f"{weeks}-week sequence for the existing audience",
        "audience_size": "UNKNOWN",
        "input_ids": _ids(assignment),
    }


def _editorial(assignment: Assignment) -> dict[str, object]:
    strategy = _body(assignment, "strategy")
    offer = _body(assignment, "offer")
    weeks = _weeks(strategy.get("weeks"))
    wording = offer.get("wording")
    text = wording if isinstance(wording, str) else "UNKNOWN"
    pieces = [f"Week {index}: {text}" for index in range(1, weeks + 1)]
    return {
        "weeks": weeks,
        "pieces": pieces,
        "first_material": pieces[0] if pieces else "UNKNOWN",
        "ready_for_owner_review": True,
        "publication_authority": "NOT_GRANTED",
        "input_ids": _ids(assignment),
    }


def _creative(assignment: Assignment) -> dict[str, object]:
    editorial = _body(assignment, "editorial")
    first = editorial.get("first_material")
    return {
        "concept": f"Plain proof, not a promise. First piece: {first}",
        "editorial_artifact_id": assignment.inputs["editorial"].artifact_id,
        "input_ids": _ids(assignment),
    }


def _funnel(assignment: Assignment) -> dict[str, object]:
    offer = _body(assignment, "offer")
    strategy = _body(assignment, "strategy")
    return {
        "steps": ["existing audience", "one reviewed sales page", "payment UNKNOWN"],
        "offer_wording": offer.get("wording"),
        "weeks": strategy.get("weeks"),
        "input_ids": _ids(assignment),
    }


def _finance(assignment: Assignment) -> dict[str, object]:
    strategy = _body(assignment, "strategy")
    offer = _body(assignment, "offer")
    return {
        "budget_cents": assignment.constraints.budget_cents,
        "weeks": strategy.get("weeks"),
        "revenue": "UNKNOWN",
        "assumption": "The budget is a ceiling, not a forecast.",
        "price_assumption_cents": offer.get("price_assumption_cents"),
        "input_ids": _ids(assignment),
    }


def _operations(assignment: Assignment) -> dict[str, object]:
    finance = _body(assignment, "finance")
    weeks = assignment.constraints.weeks
    return {
        "weeks": weeks,
        "budget_cents": finance.get("budget_cents"),
        "calendar": [f"Week {index}" for index in range(1, weeks + 1)],
        "ready_for_external_delivery": False,
        "blockers": ["owner approval", "reply rate is UNKNOWN"],
        "input_ids": _ids(assignment),
    }


def _review(assignment: Assignment) -> dict[str, object]:
    conflicts = _conflicts(assignment.inputs, assignment.constraints.budget_cents)
    return {
        "conflicts": conflicts,
        "checked_ids": _ids(assignment),
        "input_ids": _ids(assignment),
    }


def _producer(assignment: Assignment) -> dict[str, object]:
    review = _body(assignment, "review")
    conflicts = review.get("conflicts")
    blocked = isinstance(conflicts, list) and bool(conflicts)
    decision = (
        "Blocked until the conflicts are resolved. Nothing will be published."
        if blocked
        else "Keep the plan unpublished and ask the owner to review the first piece."
    )
    return {
        "decision": decision,
        "conflicts": conflicts if isinstance(conflicts, list) else [],
        "unknowns": ["audience size", "revenue", "reply rate"],
        "publication_authority": "NOT_GRANTED",
        "input_ids": _ids(assignment),
    }


def _critic(assignment: Assignment) -> dict[str, object]:
    packet = {
        role: {"id": item.artifact_id, "version": item.version, "body": dict(item.body)}
        for role, item in assignment.inputs.items()
        if role != "producer"
    }
    conflicts = _conflicts(assignment.inputs, assignment.constraints.budget_cents)
    return {
        "verdict": "BLOCKED" if conflicts else "PASS_WITH_UNKNOWNS",
        "conflicts": conflicts,
        "packet_roles": sorted(packet),
        "copied_author_verdict": False,
        "unknowns": ["audience size", "revenue", "reply rate"],
        "input_ids": _ids(assignment),
    }


def _added_role(assignment: Assignment) -> dict[str, object]:
    return {
        "summary": f"{assignment.role_id} read {sorted(assignment.inputs)}",
        "unknown": ["This added role has no specialized test double."],
        "input_ids": _ids(assignment),
    }


def _conflicts(inputs: Mapping[str, ArtifactView], budget_cents: int) -> list[str]:
    found: list[str] = []
    if "strategy" not in inputs or "finance" not in inputs or "editorial" not in inputs:
        return found
    strategy_weeks = _weeks(inputs["strategy"].body.get("weeks"))
    editorial_weeks = _weeks(inputs["editorial"].body.get("weeks"))
    finance_weeks = _weeks(inputs["finance"].body.get("weeks"))
    finance_budget = inputs["finance"].body.get("budget_cents")
    if editorial_weeks != strategy_weeks:
        found.append("editorial duration does not match strategy")
    if finance_weeks != strategy_weeks:
        found.append("finance duration does not match strategy")
    if finance_budget != budget_cents:
        found.append("finance budget does not match the founder constraint")
    for item in inputs.values():
        if _promises(item.body):
            found.append(f"{item.role_id} states an unsupported promise")
            break
    return found


def _promises(body: Mapping[str, object]) -> bool:
    text = " ".join(str(value).lower() for value in body.values())
    return "guaranteed" in text or "guarantee" in text


_BUILDERS = {
    "audience": _audience,
    "offer": _offer,
    "strategy": _strategy,
    "editorial": _editorial,
    "creative": _creative,
    "funnel": _funnel,
    "finance": _finance,
    "operations": _operations,
    "review": _review,
    "producer": _producer,
    "critic": _critic,
}
