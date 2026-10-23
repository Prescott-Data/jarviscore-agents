import json

from server.presentation import render_answer, render_output


def test_chat_shows_the_agent_answer_not_result_fields():
    structured = {
        "provider": "google_drive",
        "connection_status": "not_connected",
        "can_list_files": False,
    }
    assert render_answer("Google Drive needs to be connected first.", structured) == (
        "Google Drive needs to be connected first."
    )


def test_chat_falls_back_for_old_results_without_a_summary():
    assert "Count" in render_answer("", {"count": 3})


def test_chat_style_wrappers_become_prose_not_json():
    assert render_output({"response": "Hello! How can I help you today?"}) == \
        "Hello! How can I help you today?"
    assert render_output('{"response": "Hello!"}') == "Hello!"
    assert render_output('```json\n{"message": "Hi \\u2014 I\'m the Communicator."}\n```') == \
        "Hi — I'm the Communicator."
    assert render_output("Already prose.") == "Already prose."


def test_research_envelope_shows_prose_then_named_sections_and_drops_nothing():
    rendered = render_output({
        "api_specs": [], "libraries": [],
        "evidence": [{"kind": "search_snippet", "pointer": "https://sifted.eu/x",
                      "quote": "Monzo cut engineering roles.", "confidence": "medium"}],
        "summary": "No procurement trigger this week.",
        "next_steps": ["Send the efficiency angle", "Re-check the board on Monday"],
    })
    assert rendered.startswith("No procurement trigger this week.")
    assert "## Evidence" in rendered
    assert "- https://sifted.eu/x (confidence: medium)\n  Monzo cut engineering roles." in rendered
    assert "## Next steps\n- Send the efficiency angle" in rendered
    # Empty framework fields are not shown as noise.
    assert "api_specs" not in rendered and "libraries" not in rendered


def test_structured_output_uses_readable_sections_without_runtime_state():
    rendered = render_output({
        "status": "research_incomplete", "account_name": "Acme",
        "qualification_summary": "Acme fits the RevOps ICP.",
        "evidence": [{
            "kind": "source", "pointer": "https://example.com/acme",
            "supports": "Acme is hiring a VP of Revenue Operations.",
        }],
        "unresolved": [{"fact": "Economic buyer", "blocks": "Sending outreach"}],
        "next_action": "Verify the economic buyer",
    })
    assert rendered.startswith("Acme fits the RevOps ICP.")
    assert "Acme is hiring a VP of Revenue Operations." in rendered
    assert "## Unresolved" in rendered
    assert "**Fact:** Economic buyer\n  **Blocks:** Sending outreach" in rendered
    assert "research_incomplete" not in rendered


def test_empty_sections_are_omitted_from_structured_output():
    rendered = render_output({
        "status": "no_meeting", "meeting": None, "participants": [],
        "recent_changes": ["Gmail and Calendar returned no BMC matches."],
        "commitments": [], "agenda": [], "questions": [], "evidence": [],
        "unresolved": [{"fact": "HubSpot access", "blocks": "CRM verification"}],
    })
    assert rendered.startswith("## Recent changes")
    assert "Gmail and Calendar returned no BMC matches." in rendered
    assert "no_meeting" not in rendered


def test_machine_only_report_does_not_become_chat_copy():
    rendered = render_output({
        "status": "ready_for_review", "crm_system": "hubspot",
        "snapshot_at": "2026-09-08T11:17:52.362961Z",
        "changes": [], "pipeline_risks": [], "execution_state": "not_executed",
    })
    assert rendered == "The agent finished without returning any content."
    assert "ready_for_review" not in rendered
    assert "hubspot" not in rendered and "not_executed" not in rendered


def test_crm_change_shows_an_empty_before_value():
    rendered = render_output({
        "changes": [{
            "record_type": "deal", "record_id": "deal-1", "field": "owner",
            "current_value": "", "proposed_value": "owner-2",
        }],
    })
    assert "**Current value:** (empty)" in rendered
    assert "**Proposed value:** owner-2" in rendered


def test_unrecognised_fields_are_kept_under_their_own_heading():
    rendered = render_output({"status": "blocked", "blocked_reason": "Chromium missing",
                              "required_setup": ["pip install playwright"]})
    assert "## Status" not in rendered
    assert "## Why this is blocked\nChromium missing" in rendered
    assert "## Required setup\n- pip install playwright" in rendered
    assert "{" not in rendered


def test_nested_and_odd_shapes_stay_readable_and_bounded():
    assert render_output({"result": {"message": "Nested prose."}}) == "Nested prose."
    assert render_output(["one", "two"]) == "- one\n- two"
    assert render_output(42) == "42"
    assert render_output({}) == ""
    deep = {"output": {"output": {"output": {"output": {"output": "floor"}}}}}
    assert "floor" in render_output(deep)
    assert render_output({"questions": [{"q": "Who attends?"}]}) == \
        "## Questions\n- **Q:** Who attends?"


def test_selection_trail_leads_and_no_escaped_unicode_survives():
    rendered = render_output({"selection": "## How the desk assigned this\n- pipeline_builder owns it.",
                              "summary": "Three accounts \u2014 approach Monzo first."})
    assert rendered.index("How the desk assigned this") < rendered.index("Three accounts")
    assert "—" in rendered and "\\u" not in json.dumps(rendered).replace("\\u2014", "—")


def test_execution_telemetry_is_never_presented_as_the_answer():
    envelope = {"success": True, "files_created": [], "files_modified": [], "git_branch": None,
                "stdout": "", "data": None, "error": None, "error_type": None,
                "execution_time": 1.83}
    assert render_output(envelope) == "The agent finished without returning any content."
    # Real output is still the answer, with the bookkeeping left out.
    assert render_output({**envelope, "stdout": "1,412 contacts"}) == "## Stdout\n1,412 contacts"
    assert render_output({**envelope, "data": {"summary": "1,412 contacts."}}) == "1,412 contacts."
