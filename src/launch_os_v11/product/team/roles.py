"""Launch-team registry.

Adding a specialist is a new RoleSpec. Review, producer, and critic reads are
derived from the specialist list so the queue does not need a new core.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RoleSpec:
    role_id: str
    title: str
    responsibility: str
    reads: tuple[str, ...]
    constraints: tuple[str, ...]
    tools: tuple[str, ...]
    kind: str


SPECIALISTS: tuple[RoleSpec, ...] = (
    RoleSpec(
        "audience",
        "Market & Audience Intelligence",
        "Separate known audience facts from UNKNOWN demand.",
        (),
        (),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "offer",
        "Product & Offer Strategy",
        "State the offer and mark price as an assumption.",
        ("audience",),
        ("offer_wording", "budget_cents"),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "strategy",
        "Launch Strategy",
        "Choose a sequence that fits the stated weeks and budget.",
        ("audience", "offer"),
        ("weeks", "budget_cents"),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "editorial",
        "Content & Editorial",
        "Plan the pieces the sequence actually has time for.",
        ("offer", "strategy"),
        ("weeks",),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "creative",
        "Creative Direction",
        "Shape the first piece without adding an unstated promise.",
        ("editorial",),
        (),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "funnel",
        "Funnel & Sales Architecture",
        "Name the path from the existing audience to a reviewed offer.",
        ("offer", "strategy"),
        (),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "finance",
        "Financial & Performance Intelligence",
        "Keep the budget ceiling and refuse an invented revenue number.",
        ("offer", "strategy", "funnel"),
        ("budget_cents",),
        ("founder_brief",),
        "specialist",
    ),
    RoleSpec(
        "operations",
        "Launch Operations & Delivery",
        "Turn the sequence into a calendar and name the blockers.",
        ("strategy", "editorial", "finance"),
        ("weeks",),
        ("founder_brief",),
        "specialist",
    ),
)


def catalog(*extra: RoleSpec) -> tuple[RoleSpec, ...]:
    specialists = SPECIALISTS + extra
    specialist_ids = tuple(role.role_id for role in specialists)
    review = RoleSpec(
        "review",
        "Cross-Specialist Review",
        "Check specialist outputs against each other before synthesis.",
        specialist_ids,
        (),
        ("artifact_packet",),
        "review",
    )
    producer = RoleSpec(
        "producer",
        "AI Executive Producer",
        "Integrate the reviewed work and stop before any external action.",
        specialist_ids + ("review",),
        (),
        ("artifact_packet",),
        "producer",
    )
    critic = RoleSpec(
        "critic",
        "Independent Launch Critic",
        "Judge a frozen specialist packet. The producer verdict is not evidence.",
        ("producer",),
        (),
        ("frozen_packet",),
        "critic",
    )
    return specialists + (review, producer, critic)


def by_id(roles: tuple[RoleSpec, ...]) -> dict[str, RoleSpec]:
    return {role.role_id: role for role in roles}


def affected_roles(
    roles: tuple[RoleSpec, ...],
    changed_fields: set[str],
) -> set[str]:
    changed = {
        role.role_id
        for role in roles
        if set(role.constraints) & changed_fields
    }
    growing = True
    while growing:
        growing = False
        for role in roles:
            if role.role_id in changed:
                continue
            if any(dependency in changed for dependency in role.reads):
                changed.add(role.role_id)
                growing = True
    return changed


def with_extra(role: RoleSpec) -> tuple[RoleSpec, ...]:
    return catalog(replace(role, kind="specialist"))
