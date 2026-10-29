"""Server-rendered Launch Room. No chat thread, no publication button."""

from __future__ import annotations

from html import escape

from launch_os_v11.product.projection import FieldView, LaunchRoomView


def render_home() -> str:
    body = """
    <p class="banner">This is a local room for the browser that opens it.
    The team text is a synthetic script, not a live model.
    Nothing here publishes.</p>
    <form method="post" action="/launch-room">
      <label>Business
        <input name="business_name" required value="Northwind Studio">
      </label>
      <label>Offer <input name="offer_name" required value="Pilot cohort"></label>
      <label>Goal
        <textarea name="goal" required>Get a clear yes from people who already asked.</textarea>
      </label>
      <label>Audience name
        <input name="audience" placeholder="Leave blank if unknown">
      </label>
      <label>A fact you already know
        <input name="known_fact" placeholder="Optional. Not a metric.">
      </label>
      <button id="open-room" type="submit">Open the launch room</button>
    </form>
    """
    return _shell("Open a launch", body)


def render_room(view: LaunchRoomView, team_html: str = "") -> str:
    known = _fields(view, {"OWNER_STATED", "KNOWN"})
    assumed = _fields(view, {"ASSUMPTION"})
    unknown = _fields(view, {"UNKNOWN"})
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in view.reasons)
    alternatives = "".join(f"<li>{escape(item)}</li>" for item in view.alternatives)
    assumptions = "".join(f"<li>{escape(item)}</li>" for item in view.assumptions)
    decision = escape(view.decision or "Not decided yet.")
    draft = view.material_body or ""
    editor = ""
    if view.material_body is not None:
        editor = (
            f'<form method="post" action="/launch-room/{view.launch_id}/draft">'
            f'<textarea id="draft-body" name="body" required>{escape(draft)}</textarea>'
            '<button id="save-draft" type="submit">Save this draft</button></form>'
            f"<p>Draft version {view.draft_version}. Saving does not publish.</p>"
        )
    body = f"""
    <p id="next-step" class="score">{escape(view.next_step)}</p>
    <p class="banner">Model intelligence: {escape(view.model_intelligence)}.
    Generation: {escape(view.generation_provenance)}.
    This is not a live model. Publication authority: {escape(view.publication_authority)}.
    Actions {view.action_count}, executions {view.execution_count},
    publications {view.publication_count}. Metrics: {view.metric_version_count}.</p>
    <section id="known"><h2>Known</h2><div class="grid">{known}</div></section>
    <section id="assumption"><h2>Assumption</h2>
      <div class="grid">{assumed}</div>
      <ul>{assumptions}</ul>
    </section>
    <section id="unknown"><h2>Unknown</h2><div class="grid">{unknown}</div>
      <p>{escape(view.observation_statement)}</p>
    </section>
    <section><h2>Team decision</h2><p id="decision">{decision}</p>
      <ul>{reasons}</ul>
      <h2>Not selected</h2><ul id="alternatives">{alternatives}</ul>
      <p>{escape(view.what_happens_now or "")}</p>
      <p>Approval: {escape(view.approval_state)}. {escape(view.approval_consequence)}</p>
    </section>
    <section><h2>Draft</h2>
      <pre id="draft-text">{escape(draft or "No draft yet.")}</pre>
      <p>Status: {escape(view.material_status or "not started")}</p>
      {editor}
    </section>
    {team_html}
    <div class="actions">
      {_post(view.launch_id, "decision", "Ask the team", button_id="ask-team")}
      {_post(view.launch_id, "revision", "Request a revision", note=True)}
      {_post(view.launch_id, "approve", "Approve decision, do not publish", button_id="approve")}
      {_post(view.launch_id, "materials", "Prepare the draft", button_id="prepare-draft")}
      {_post(view.launch_id, "note", "Record a note, not a metric", note=True)}
      {_post(view.launch_id, "adapt", "Adapt without a measured result")}
    </div>
    """
    return _shell(view.offer_name, body)


def render_error(message: str) -> str:
    return _shell(
        "Cannot do that",
        f"<p class='error'>{escape(message)}</p><p><a href='/launch-room'>Back</a></p>",
    )


def _fields(view: LaunchRoomView, statuses: set[str]) -> str:
    rows = [field for field in view.snapshot_fields if field.status in statuses]
    return "".join(_field(field) for field in rows)


def _field(field: FieldView) -> str:
    return (
        "<div class='field'><span>"
        + escape(field.status)
        + "</span><b>"
        + escape(field.label)
        + "</b><p>"
        + escape(field.value)
        + "</p><small>"
        + escape(field.note)
        + "</small></div>"
    )


def _post(
    launch_id: str,
    action: str,
    label: str,
    *,
    note: bool = False,
    button_id: str = "",
) -> str:
    field = ""
    if note:
        field_id = "revision-note" if action == "revision" else ""
        extra = f' id="{field_id}"' if field_id else ""
        field = (
            f"<input{extra} name='note' required "
            "placeholder='What should change? Not a publish command.'>"
        )
    ident = f" id='{button_id}'" if button_id else ""
    return (
        f'<form method="post" action="/launch-room/{launch_id}/{action}">'
        f"{field}<button{ident} type='submit'>{escape(label)}</button></form>"
    )


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} — Launch Room</title>
  <style>
    body {{ margin: 0; font-family: Georgia, serif; background: #f4f0e8; color: #1c1915; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 28px 18px 72px; }}
    h1 {{ font-size: 2rem; line-height: 1.1; }}
    h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
    form {{ display: grid; gap: 8px; margin: 10px 0; }}
    label {{ display: grid; gap: 4px; font-family: sans-serif; font-size: 0.92rem; }}
    input, textarea, button {{ font: inherit; }}
    input, textarea {{ padding: 10px 12px; border: 1px solid #d0c6b8; border-radius: 10px; }}
    textarea {{ min-height: 110px; }}
    button {{ min-height: 44px; border: 0; border-radius: 999px; background: #0f6e56;
      color: white; padding: 0 16px; cursor: pointer; }}
    .banner, .score, .error {{ padding: 12px 14px; border-radius: 12px; }}
    .banner {{ background: #fff4d6; }}
    .score {{ background: #e7f4ee; font-size: 1.15rem; }}
    .error {{ background: #fde8e4; }}
    section {{ background: white; border-radius: 16px; padding: 16px; margin: 14px 0; }}
    .grid {{ display: grid; gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
    .field {{ border: 1px dashed #ddd4c6; border-radius: 12px; padding: 10px; }}
    pre {{ white-space: pre-wrap; font-family: sans-serif; }}
  </style>
</head>
<body>
  <main>
    <p>Launch Room</p>
    <h1>{escape(title)}</h1>
    {body}
  </main>
</body>
</html>"""
