import os
import subprocess
import sys

import pytest
from jarviscore import AutoAgent

from personal_intelligence.agent import PERSONAL_SYSTEMS, PersonalIntelligenceAgent
from personal_intelligence.team import build_mesh, reconcile_task, submit_task


class FakeMesh:
    """Records the public Mesh calls the Desk handlers make."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute_goal(self, goal, *, workflow_id=None, context=None):
        self.calls.append(("execute_goal", goal, workflow_id, context))
        return self.result

    async def resolve_hitl(self, workflow_id, action_id, *, decision, resolved_by=""):
        self.calls.append(("resolve_hitl", workflow_id, action_id, decision, resolved_by))
        return self.result

    async def replan_goal(self, workflow_id, *, reason, context=None):
        self.calls.append(("replan_goal", workflow_id, reason, context))
        return self.result


def completed(summary="Here is your briefing.", obligation_status="satisfied"):
    return {
        "workflow_id": "wf-1",
        "status": "completed",
        "obligation_status": obligation_status,
        "result_summary": summary,
        "steps": [],
    }


def waiting(metadata):
    return {
        "workflow_id": "wf-1",
        "status": "waiting",
        "result_summary": "",
        "steps": [
            {"id": "s1", "status": "completed", "output": {"output": "done"}},
            {"id": "s2", "status": "waiting", "output": {"yield_metadata": metadata}},
        ],
    }


def test_the_agent_is_one_generalist_autoagent_that_may_use_connected_apps():
    assert issubclass(PersonalIntelligenceAgent, AutoAgent)
    assert PersonalIntelligenceAgent.requires_auth is True
    assert PersonalIntelligenceAgent.default_kernel_role is None
    work = PersonalIntelligenceAgent.capability_contracts["personal_intelligence"]
    assert work["systems"] == PERSONAL_SYSTEMS
    assert {"browser", "gmail", "google_calendar"} <= set(PERSONAL_SYSTEMS)
    briefing = PersonalIntelligenceAgent.capability_contracts["personal_briefing"]
    assert briefing["effects"] == ["final_response"]


def test_the_mesh_runs_one_pooled_agent_with_per_person_memory():
    mesh = build_mesh()

    assert [type(agent) for agent in mesh.agents] == [PersonalIntelligenceAgent]
    assert set(mesh.agents[0].capabilities) == {"personal_intelligence", "personal_briefing"}
    assert mesh.config["memory_scope_field"] == "owner_id"
    assert mesh.config["mesh_response_capability"] == "personal_briefing"
    assert set(mesh.get_diagnostics()["pools"]) == {"personal-intelligence-agent"}


def test_importing_the_blueprint_leaves_the_environment_alone():
    code = (
        "import os; before = dict(os.environ); "
        "import personal_intelligence.team, personal_intelligence.channels.telegram; "
        "assert dict(os.environ) == before, set(os.environ) ^ set(before)"
    )
    env = {key: value for key, value in os.environ.items() if key != "JARVISCORE_PROFILES_DIR"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


async def test_a_goal_runs_once_per_message_and_returns_the_answer():
    mesh = FakeMesh(completed())
    context = {
        "mesh_workflow_id": "desk-thread:run-1",
        "source_context": {"owner_id": "telegram:7", "campaign_id": "chat:42"},
    }

    result = await submit_task(mesh, "  Compare two laptops for me.  ", context)

    assert result["status"] == "success"
    assert result["result_summary"] == "Here is your briefing."
    assert result["obligation_status"] == "satisfied"
    assert result["output"]["workflow_id"] == "wf-1"
    (call,) = mesh.calls
    assert call[:3] == ("execute_goal", "Compare two laptops for me.", "desk-thread:run-1")
    assert call[3]["owner_id"] == "telegram:7"
    assert call[3]["campaign_id"] == "chat:42"
    assert "mesh_workflow_id" not in call[3]


async def test_a_redelivered_channel_message_maps_to_the_same_goal():
    context = {"owner_id": "o", "campaign_id": "c", "source_event_id": "e"}
    first, second = FakeMesh(completed()), FakeMesh(completed())
    await submit_task(first, "Plan the week.", dict(context))
    await submit_task(second, "Plan the week.", dict(context))
    assert first.calls[0][2] == second.calls[0][2]


async def test_an_empty_message_is_refused():
    with pytest.raises(ValueError):
        await submit_task(FakeMesh(completed()), "   ", {})


async def test_an_action_awaiting_approval_yields_to_the_person():
    mesh = FakeMesh(waiting({
        "typed_outcome": "WAITING_FOR_APPROVAL",
        "action_id": "act-1",
        "action": "Place the order",
        "consequence": "Charges the saved card",
        "system": "browser",
    }))

    result = await submit_task(mesh, "Order the groceries.", {})

    assert result["status"] == "yield"
    wait = result["yield_metadata"]
    assert (wait["action_id"], wait["workflow_id"], wait["step_id"]) == ("act-1", "wf-1", "s2")
    assert wait["consequence"] == "Charges the saved card"


async def test_an_app_waiting_for_consent_yields_its_connection():
    mesh = FakeMesh(waiting({
        "typed_outcome": "WAITING_FOR_CONSENT",
        "connection_id": "conn-1",
        "system": "gmail",
    }))

    result = await submit_task(mesh, "Triage my inbox.", {})

    assert result["status"] == "yield"
    assert result["yield_metadata"]["connection_id"] == "conn-1"
    assert result["yield_metadata"]["step_id"] == "s2"


async def test_an_unconnected_app_without_a_consent_link_is_reported_plainly():
    mesh = FakeMesh(waiting({"typed_outcome": "YIELD_AUTH_REQUIRED", "system": "google_calendar"}))

    result = await submit_task(mesh, "Book time with the plumber.", {})

    assert result["status"] == "failure"
    assert result["obligation_status"] == "blocked"
    assert "Google Calendar" in result["result_summary"]


async def test_the_persons_decision_resumes_the_waiting_action():
    mesh = FakeMesh(completed("Ordered. Order number FC-1001."))
    context = {
        "_resume": True,
        "mesh_workflow_id": "wf-1",
        "hitl_decision": {"action_id": "act-1", "decision": "approve", "resolved_by": "owner-1"},
    }

    result = await submit_task(mesh, "Order the groceries.", context)

    assert mesh.calls == [("resolve_hitl", "wf-1", "act-1", "approve", "owner-1")]
    assert result["result_summary"] == "Ordered. Order number FC-1001."


async def test_a_completed_connection_continues_the_same_goal():
    mesh = FakeMesh(completed())
    context = {"_resume": True, "mesh_workflow_id": "wf-1", "connection_id": "conn-1",
               "system": "gmail"}

    await submit_task(mesh, "Triage my inbox.", context)

    ((name, workflow_id, reason, _context),) = mesh.calls
    assert (name, workflow_id) == ("replan_goal", "wf-1")
    assert "gmail" in reason


async def test_an_unfinished_goal_keeps_the_agents_account():
    mesh = FakeMesh({
        "workflow_id": "wf-1",
        "status": "failed",
        "obligation_status": "blocked",
        "result_summary": "The shop was closed; nothing was ordered.",
        "steps": [],
    })

    result = await submit_task(mesh, "Order the groceries.", {})

    assert result["status"] == "failure"
    assert result["result_summary"] == "The shop was closed; nothing was ordered."
    assert result["obligation_status"] == "blocked"


async def test_a_planning_failure_reports_its_reason():
    mesh = FakeMesh({"workflow_id": "wf-1", "status": "failed", "error": "No model configured",
                     "result_summary": "", "steps": []})

    result = await submit_task(mesh, "Plan a trip.", {})

    assert result == {"status": "failure", "output": mesh.result, "error": "No model configured"}


async def test_reconcile_continues_the_named_goal():
    mesh = FakeMesh(completed())

    result = await reconcile_task(mesh, "wf-1", {"owner_id": "o"})

    assert result["status"] == "success"
    assert mesh.calls[0][0:2] == ("replan_goal", "wf-1")
    with pytest.raises(ValueError):
        await reconcile_task(mesh, "", {})
