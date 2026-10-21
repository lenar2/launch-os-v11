"""Server-rendered Launch Room. No chat thread, no publication button."""

from __future__ import annotations

from html import escape

from launch_os_v11.product.projection import LaunchRoomView


def render_home() -> str:
    body = """
    <form method="post" action="/launch-room">
      <label>Business <input name="business_name" required value="Northwind Studio"></label>
      <label>Offer <input name="offer_name" required value="Pilot cohort"></label>
      <label>Goal
        <textarea name="goal" required>Get a clear yes from people who already asked.</textarea>
      </label>
      <label>Audience name <input name="audience" placeholder="Leave blank if unknown"></label>
      <label>Owner note <input name="known_fact" placeholder="Optional. Not a metric."></label>
      <button type="submit">Open the launch room</button>
    </form>
    """
    return _shell("Open a launch", body)


def render_room(view: LaunchRoomView) -> str:
    questions = "".join(
        "<li><strong>"
        + escape(question.prompt)
        + "</strong> "
        + escape(question.answer)
        + "</li>"
        for question in view.questions
    )
    fields = "".join(
        "<div class='field'><span>"
        + escape(field.status)
        + "</span><b>"
        + escape(field.label)
        + "</b><p>"
        + escape(field.value)
        + "</p><small>"
        + escape(field.note)
        + "</small></div>"
        for field in view.snapshot_fields
    )
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in view.reasons)
    decision = escape(view.decision or "Not decided yet.")
    material = escape(view.material_body or "No draft yet.")
    action = view.launch_id
    body = f"""
    <p class="banner">Model intelligence: {escape(view.model_intelligence)}.
    Generation: {escape(view.generation_provenance)}.
    Publication authority: {escape(view.publication_authority)}.
    External writes: actions {view.action_count}, executions {view.execution_count},
    publications {view.publication_count}. Metrics: {view.metric_version_count}.</p>
    <p class="score">Owner questions this room can answer:
    {view.capability_answered}/{view.capability_total}.
    Baseline before this room: {view.baseline_answered}. Delta: {view.capability_delta}.</p>
    <ol class="questions">{questions}</ol>
    <section><h2>Snapshot</h2><div class="grid">{fields}</div></section>
    <section><h2>Team decision</h2><p>{decision}</p><ul>{reasons}</ul>
    <p>{escape(view.what_happens_now or "")}</p>
    <p>Approval: {escape(view.approval_state)}. {escape(view.approval_consequence)}</p></section>
    <section><h2>Draft</h2><pre>{material}</pre>
    <p>Status: {escape(view.material_status or "not started")}</p></section>
    <section><h2>What happened</h2><p>{escape(view.observation_statement)}</p></section>
    <section><h2>Adaptation</h2><p>{escape(view.adaptation_stance)}</p>
    <p>{escape(view.adaptation_statement)}</p></section>
    <div class="actions">
      {_post(action, "decision", "Ask the team")}
      {_post(action, "revision", "Request a revision", note=True)}
      {_post(action, "approve", "Approve decision, do not publish")}
      {_post(action, "materials", "Prepare the draft")}
      {_post(action, "note", "Record a note, not a metric", note=True)}
      {_post(action, "adapt", "Adapt without a measured result")}
    </div>
    <details>
      <summary>Why this is a room, not a chat</summary>
      <p>A chat-first companion was the other approach. It was rejected because a
      message is easy to mistake for permission to publish, and the job is to run
      a launch, which is an object with a goal, a snapshot, a decision, a draft,
      and an unknown result.</p>
    </details>
    """
    return _shell(view.offer_name, body)


def render_error(message: str) -> str:
    return _shell(
        "Cannot do that",
        f"<p class='error'>{escape(message)}</p><p><a href='/launch-room'>Back</a></p>",
    )


def _post(launch_id: str, action: str, label: str, *, note: bool = False) -> str:
    field = (
        '<input name="note" required '
        'placeholder="What should change? Not a publish command.">'
        if note
        else ""
    )
    return (
        f'<form method="post" action="/launch-room/{launch_id}/{action}">'
        f"{field}<button type='submit'>{escape(label)}</button></form>"
    )


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} — Launch Room</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font-family: Georgia, serif; background: #f3efe6; color: #1d1a16; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 28px 18px 64px; }}
    h1 {{ font-size: 2rem; line-height: 1.1; margin-bottom: 0.2rem; }}
    h2 {{ font-size: 1.15rem; margin: 0 0 0.6rem; }}
    .kicker {{ letter-spacing: 0.08em; text-transform: uppercase;
      font-family: sans-serif; font-size: 0.72rem; color: #6b6256; }}
    form {{ display: grid; gap: 10px; margin: 12px 0; }}
    label {{ display: grid; gap: 4px; font-family: sans-serif; font-size: 0.92rem; }}
    input, textarea, button {{ font: inherit; }}
    input, textarea {{ padding: 10px 12px; border: 1px solid #cfc6b8;
      background: #fffdf8; border-radius: 10px; }}
    textarea {{ min-height: 90px; }}
    button {{ min-height: 44px; border: 0; border-radius: 999px;
      background: #0f6e56; color: white; padding: 0 16px; cursor: pointer; }}
    .banner, .score, .error {{ padding: 12px 14px; border-radius: 12px; }}
    .banner {{ background: #fff4d8; }}
    .score {{ background: #e7f3ee; }}
    .error {{ background: #fde8e4; }}
    section {{ background: white; border-radius: 16px; padding: 16px; margin: 14px 0; }}
    .grid {{ display: grid; gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
    .field {{ border: 1px dashed #d9d0c3; border-radius: 12px; padding: 10px; }}
    .field span {{ font-family: sans-serif; font-size: 0.72rem; letter-spacing: 0.06em; }}
    pre {{ white-space: pre-wrap; font-family: sans-serif; }}
    .actions {{ display: grid; gap: 8px; }}
    .questions li {{ margin: 0.4rem 0; }}
  </style>
</head>
<body>
  <main>
    <p class="kicker">Launch Room</p>
    <h1>{escape(title)}</h1>
    {body}
  </main>
</body>
</html>"""
