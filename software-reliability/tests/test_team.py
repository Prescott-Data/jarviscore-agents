import pytest

from software_reliability.team import (
    PLANNING_BRIEF,
    build_mesh,
    desk_view,
    reconcile_task,
    submit_task,
)


class FakeMesh:
    """Stands in for a started Mesh: records the goal and returns a canned result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute_goal(self, goal, *, workflow_id, context):
        self.calls.append(("execute_goal", goal, workflow_id, context))
        return self.result

    async def replan_goal(self, workflow_id, *, reason, context):
        self.calls.append(("replan_goal", workflow_id, reason, context))
        return self.result


BRIEF = {"status": "no_verified_findings", "commit_sha": "abc123", "findings": []}


def completed(revision=1):
    return {
        "workflow_id": "wf-1",
        "status": "completed",
        "obligation_status": "satisfied",
        "revision": revision,
        "result_summary": "No consequential defect survived validation.",
        "steps": [
            {"id": "old-brief", "plan_revision": 1, "effect": "final_response",
             "status": "completed", "output": {"output": {"stale": True}}},
            {"id": "discover", "plan_revision": revision, "effect": "read",
             "status": "completed", "output": {"output": {"status": "incomplete"}}},
            {"id": "brief", "plan_revision": revision, "effect": "final_response",
             "status": "completed", "output": {"output": BRIEF}},
        ],
    }


def test_mesh_has_the_eight_roles_and_a_source_backed_policy():
    mesh = build_mesh()

    assert {agent.role for agent in mesh.agents} == {
        "repository_cartographer", "defect_miner", "reproduction_engineer", "impact_analyst",
        "repair_engineer", "verification_engineer", "rule_engineer", "reliability_strategist",
    }
    assert mesh.config["workspace_required"] is True
    assert mesh.config["mesh_planning_brief"] == PLANNING_BRIEF
    assert mesh.config["mesh_response_capability"] == "reliability_briefing"
    assert "github" in mesh.config["workspace_source_catalog"]


def test_build_caches_come_from_the_worker_environment_only(monkeypatch):
    monkeypatch.delenv("CARGO_HOME", raising=False)
    monkeypatch.setenv("RUSTUP_HOME", "/opt/rustup")
    monkeypatch.setenv("SECRET_TOKEN", "must-not-pass")

    environment = build_mesh().config["workspace_command_environment"]

    assert environment == {"RUSTUP_HOME": "/opt/rustup"}


def test_extra_source_adapters_are_registered():
    adapter = object()
    assert build_mesh({"local": adapter}).config["workspace_source_adapters"] == {"local": adapter}


async def test_submit_task_runs_the_goal_and_returns_the_current_brief():
    mesh = FakeMesh(completed(revision=2))

    result = await submit_task(mesh, "  Run a deep reliability scan.  ", {"tenant": "acme"})

    _, goal, workflow_id, context = mesh.calls[0]
    assert goal == "Run a deep reliability scan."
    assert workflow_id.startswith("software-reliability-")
    assert context == {"tenant": "acme"}
    assert result["status"] == "success"
    assert result["goal_status"] == "completed"
    assert result["output"] == BRIEF
    assert result["result_summary"] == "No consequential defect survived validation."
    assert result["obligation_status"] == "satisfied"


async def test_submit_task_keeps_desk_workflow_identity():
    mesh = FakeMesh(completed())

    await submit_task(mesh, "Scan", {"workflow_id": "thread-7", "step_id": "task-3"})
    await submit_task(mesh, "Scan", {"mesh_workflow_id": "explicit-1", "step_id": "x"})

    assert mesh.calls[0][2] == "thread-7:task-3"
    assert mesh.calls[1][2] == "explicit-1"
    assert "mesh_workflow_id" not in mesh.calls[1][3]


async def test_submit_task_requires_a_goal():
    with pytest.raises(ValueError):
        await submit_task(FakeMesh(completed()), "  ")


async def test_reconcile_task_continues_the_named_goal():
    mesh = FakeMesh(completed())

    result = await reconcile_task(mesh, "wf-1", {"tenant": "acme"})

    assert mesh.calls[0][0:2] == ("replan_goal", "wf-1")
    assert result["status"] == "success"
    with pytest.raises(ValueError):
        await reconcile_task(mesh, "")


def test_waiting_goal_yields_with_the_waiting_step_metadata():
    metadata = {"typed_outcome": "WAITING_FOR_APPROVAL", "action_id": "a-1"}
    result = desk_view({
        "status": "waiting",
        "revision": 1,
        "steps": [{"plan_revision": 1, "status": "waiting",
                   "output": {"yield_metadata": metadata}}],
    })

    assert result["status"] == "yield"
    assert result["yield_metadata"] == metadata


def test_failed_goal_is_a_failure_that_keeps_the_framework_result():
    result = desk_view({"status": "failed", "error": "planning failed", "revision": 0,
                        "steps": [], "obligation_status": "blocked"})

    assert result["status"] == "failure"
    assert result["goal_status"] == "failed"
    assert result["error"] == "planning failed"
    assert result["output"] is None
