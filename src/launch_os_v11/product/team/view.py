"""Owner-facing team section. It does not expose the job queue as the product."""

from __future__ import annotations

from html import escape

from launch_os_v11.product.team.contracts import REAL_MODEL_EXECUTION, TeamSnapshot


def render_team_section(launch_id: str, snapshot: TeamSnapshot | None) -> str:
    if snapshot is None:
        body = (
            "<p id='team-status'>The launch team has not started.</p>"
            f"{_start_form(launch_id)}"
        )
    else:
        rows = "".join(
            "<li id='team-"
            + escape(role.role_id)
            + "'><b>"
            + escape(role.title)
            + "</b> "
            + escape(role.state)
            + (" v" + str(role.version) if role.version else "")
            + " — "
            + escape(role.summary)
            + "</li>"
            for role in snapshot.roles
        )
        conflicts = "".join(f"<li>{escape(item)}</li>" for item in snapshot.conflicts)
        needs = "".join(f"<li>{escape(item)}</li>" for item in snapshot.needs_owner)
        materials = "".join(f"<li>{escape(item)}</li>" for item in snapshot.materials)
        body = (
            f"<p id='team-status'>{escape(snapshot.status)}. "
            f"Provenance: {escape(snapshot.provenance)}. "
            f"REAL_MODEL_EXECUTION={escape(snapshot.real_model_execution)}.</p>"
            f"<p id='team-next'>{escape(snapshot.ready_step)}</p>"
            f"<ul id='team-roles'>{rows}</ul>"
            f"<h3>Conflicts</h3><ul id='team-conflicts'>{conflicts}</ul>"
            f"<h3>Needs the owner</h3><ul>{needs}</ul>"
            f"<h3>Materials</h3><ul id='team-materials'>{materials}</ul>"
            f"{_change_form(launch_id)}"
        )
    return (
        "<section id='launch-team'><h2>Launch team</h2>"
        f"<p class='banner'>REAL_MODEL_EXECUTION={REAL_MODEL_EXECUTION}. "
        "A test double is not a live model. Nothing here publishes.</p>"
        f"{body}</section>"
    )


def _start_form(launch_id: str) -> str:
    return (
        f'<form method="post" action="/launch-room/{launch_id}/team">'
        '<button id="run-launch-team" type="submit">Run the launch team</button></form>'
    )


def _change_form(launch_id: str) -> str:
    return (
        f'<form method="post" action="/launch-room/{launch_id}/team-change">'
        '<label>Budget cents <input id="team-budget" name="budget_cents"></label>'
        '<label>Weeks <input id="team-weeks" name="weeks"></label>'
        '<label>Offer wording <input id="team-offer-wording" name="offer_wording"></label>'
        '<button id="apply-team-change" type="submit">'
        "Apply the constraint change</button></form>"
    )
