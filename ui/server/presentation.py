"""Turn a model or framework result envelope into something a person can read.

Agents return whatever their role produced: a bare string, a research envelope,
a ``{"message": ...}`` wrapper, sometimes a JSON document inside a string. None
of that is presentation, and showing it raw is how a desk ends up displaying
``{"response": "Hello!"}`` with escaped unicode to the person who asked.

The rule here is the one production assistants use: normalise at the boundary
into prose plus named sections, and let the renderer only ever draw that. The
normaliser never invents, summarises or drops content — unrecognised fields are
still shown, under their own heading, so nothing is quietly swallowed.
"""

from __future__ import annotations

import json

# Text-bearing keys in the order a reader wants them, across the shapes agents
# actually return (framework research envelope, chat-style wrappers, our own).
PROSE_KEYS = (
    "selection", "summary", "qualification_summary", "message", "response", "answer", "reply",
    "final_answer", "text", "content", "body", "output", "result", "data",
)

TITLES = {
    "evidence": "Evidence",
    "questions": "Questions",
    "next_steps": "Next steps",
    "recommendations": "Recommendations",
    "risks": "Risks",
    "sources": "Sources",
    "citations": "Sources",
    "required_setup": "Required setup",
    "blocked_reason": "Why this is blocked",
    "api_specs": "API specs",
    "qualification_summary": "Qualification",
    "fit_reasons": "Why this fits",
    "disqualifiers": "Disqualifiers",
    "contacts": "Verified contact paths",
    "outreach_draft": "Proposed outreach",
    "unresolved": "Unresolved facts",
    "recent_changes": "Recent changes",
    "commitments": "Open commitments",
    "agenda": "Proposed agenda",
    "changes": "Proposed CRM changes",
    "pipeline_risks": "Pipeline risks",
    "forecast": "Forecast",
    "execution_state": "Execution state",
}

# Runtime bookkeeping. Real for debugging, never an answer to a person's question.
TELEMETRY_KEYS = frozenset({
    "success", "execution_time", "elapsed_ms", "files_created", "files_modified",
    "git_branch", "error_type", "candidate_id", "mode", "length", "tokens",
    "cost_usd", "step_id", "workflow_id", "status", "crm_system", "snapshot_at",
    "execution_state",
})

NOTHING_RETURNED = "The agent finished without returning any content."

MAX_DEPTH = 4


def _humanize(key: str) -> str:
    return TITLES.get(key) or key.replace("_", " ").strip().capitalize()


def _is_empty(value) -> bool:
    return value is None or (isinstance(value, str | list | dict | tuple) and not value)


def _decode(text: str):
    """A JSON document that arrived as a string is data, not prose."""
    stripped = text.strip()
    if stripped.startswith("```"):
        body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = body.rsplit("```", 1)[0].strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict | list) else None


def _evidence_line(item) -> str:
    if not isinstance(item, dict):
        return f"- {item}"
    pointer = item.get("pointer") or item.get("url") or item.get("kind") or "source"
    confidence = item.get("confidence")
    quote = str(item.get("supports") or item.get("quote") or item.get("text") or "").strip()
    heading = f"- {pointer}" + (f" (confidence: {confidence})" if confidence else "")
    return f"{heading}\n  {quote}" if quote else heading


def _bullets(key: str, values: list, depth: int) -> str:
    if key in {"evidence", "sources", "citations"}:
        return "\n".join(_evidence_line(item) for item in values)
    lines = []
    for item in values:
        if isinstance(item, dict):
            fields = []
            for field, value in item.items():
                visible_empty = field in {"current_value", "proposed_value"} and value in (None, "")
                if field in TELEMETRY_KEYS or (_is_empty(value) and not visible_empty):
                    continue
                body = "(empty)" if visible_empty else render_output(value, depth + 1).replace("\n", " ").strip()
                if body:
                    fields.append(f"**{_humanize(field)}:** {body}")
            rendered = "\n".join(fields)
        else:
            rendered = render_output(item, depth + 1) if isinstance(item, list) else str(item)
        lines.append("- " + rendered.replace("\n", "\n  ").strip())
    return "\n".join(lines)


def render_output(output, depth: int = 0) -> str:
    """Prose first, then every remaining field under a heading of its own."""
    if isinstance(output, str):
        decoded = _decode(output) if depth < MAX_DEPTH else None
        return render_output(decoded, depth + 1) if decoded is not None else output.strip()
    if isinstance(output, list):
        return _bullets("", output, depth)
    if not isinstance(output, dict):
        return str(output)
    blocks, used = [], set()
    for key in PROSE_KEYS:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            blocks.append(render_output(value, depth + 1) if depth < MAX_DEPTH else value.strip())
            used.add(key)
        elif isinstance(value, dict | list) and value and depth < MAX_DEPTH:
            blocks.append(render_output(value, depth + 1))
            used.add(key)

    for key, value in output.items():
        visible_empty = key in {"current_value", "proposed_value"} and value in (None, "")
        if key in used or key in TELEMETRY_KEYS or (_is_empty(value) and not visible_empty):
            continue
        body = ("(empty)" if visible_empty
                else _bullets(key, value, depth) if isinstance(value, list)
                else render_output(value, depth + 1) if isinstance(value, dict)
                else str(value).strip())
        if not body:
            continue
        blocks.append(f"## {_humanize(key)}\n{body}" if depth == 0 else f"**{_humanize(key)}:** {body}")

    rendered = "\n\n".join(block for block in blocks if block.strip())
    if rendered or depth or not output:
        return rendered
    return NOTHING_RETURNED


def render_answer(summary, output) -> str:
    """Only the agent's answer belongs in the conversation.

    RESULT is an inter-agent/data contract and stays on the saved run for
    downstream consumers and inspection. Turning its keys into Markdown
    headings made execution state look like something the agent had said.
    """
    lead = (summary or "").strip()
    return lead or render_output(output)
