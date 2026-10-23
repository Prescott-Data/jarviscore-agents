"""The Desk contract: build_mesh, submit_task, reconcile_task and the result view."""

import pytest

from gtm.team import build_mesh, desk_view, reconcile_task, submit_task


def _goal(status, **extra):
    return {
        "workflow_id": "desk-1:run-1",
        "status": status,
        "obligation_status": extra.pop("obligation_status", "satisfied"),
        "revision": 1,
        "result_summary": extra.pop("result_summary", ""),
        "steps": extra.pop("steps", []),
        **extra,
    }


def _step(step_id, status, effect="read", **output):
    return {"id": step_id, "status": status, "effect": effect, "plan_revision": 1,
            "output": {"tokens": {"total": 10}, **output}}


def test_the_mesh_is_built_without_starting_anything():
    mesh = build_mesh()
    assert [agent.role for agent in mesh.agents] == ["gtm_agent"]


def test_a_completed_goal_is_a_success_with_the_responses_output_and_evidence():
    evidence = [{"tool": "web_search", "status": "success"}]
    view = desk_view(_goal(
        "completed",
        result_summary="Hold: no verified contact yet.",
        steps=[
            _step("research", "completed", output={"decision": "hold"}),
            _step("final_response", "completed", effect="final_response",
                  output={"decision": "hold", "summary": "Hold."}, evidence=evidence),
        ],
    ))
    assert view["status"] == "success"
    assert view["result_summary"] == "Hold: no verified contact yet."
    assert view["output"] == {"decision": "hold", "summary": "Hold."}
    assert view["evidence"] == evidence
    assert view["obligation_status"] == "satisfied"
    assert view["tokens"] == {"total": 20}


def test_a_goal_waiting_for_approval_yields_with_the_actions_metadata():
    waiting = {"typed_outcome": "WAITING_FOR_APPROVAL", "action_id": "a1",
               "action": "gmail_send_email", "consequence": "Sends one email."}
    view = desk_view(_goal("waiting", steps=[
        _step("send", "waiting", effect="notify", yield_metadata=waiting),
    ]))
    assert view["status"] == "yield"
    assert view["yield_metadata"] == waiting


def test_a_failed_goal_is_a_failure_that_keeps_its_explanation():
    view = desk_view(_goal("failed", obligation_status="blocked",
                           result_summary="Blocked: HubSpot is not connected.",
                           error="Mesh planning failed"))
    assert view["status"] == "failure"
    assert view["result_summary"] == "Blocked: HubSpot is not connected."
    assert view["error"] == "Mesh planning failed"


class GoalRecorder:
    """Stands in for a started Mesh: records the goal API calls the handlers make."""

    def __init__(self):
        self.calls = []

    async def execute_goal(self, goal, *, workflow_id, context):
        self.calls.append(("execute_goal", goal, workflow_id, context))
        return _goal("completed", result_summary="Done.")

    async def replan_goal(self, workflow_id, *, reason, context):
        self.calls.append(("replan_goal", workflow_id, context))
        return _goal("completed", result_summary="Continued.")


async def test_submit_task_runs_the_desk_message_as_a_goal_under_the_desks_id():
    mesh = GoalRecorder()
    result = await submit_task(mesh, " Brief me on Globex ", {
        "mesh_workflow_id": "desk-1:run-1", "workflow_id": "desk-1", "step_id": "run-1",
    })
    assert result["status"] == "success"
    _, goal, workflow_id, context = mesh.calls[0]
    assert (goal, workflow_id) == ("Brief me on Globex", "desk-1:run-1")
    assert "mesh_workflow_id" not in context


async def test_reconcile_task_continues_the_same_goal():
    mesh = GoalRecorder()
    result = await reconcile_task(mesh, "desk-1:run-1", {"workflow_id": "desk-1"})
    assert result["result_summary"] == "Continued."
    assert mesh.calls[0][:2] == ("replan_goal", "desk-1:run-1")


async def test_an_empty_request_is_refused():
    with pytest.raises(ValueError):
        await submit_task(GoalRecorder(), "  ", {})
