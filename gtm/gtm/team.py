"""The GTM mesh and its JarvisCore Desk handlers.

``build_mesh`` constructs the roster without starting agents or contacting
providers. The Desk worker starts the mesh, calls ``submit_task`` (or
``reconcile_task``) and renders the returned dict.
"""

from __future__ import annotations

from uuid import uuid4

from jarviscore import Mesh

from gtm.agents import GTMAgent


def build_mesh() -> Mesh:
    mesh = Mesh(config={
        "p2p_enabled": False,
        # Provider credentials come from the Nexus vault (`jarviscore nexus register`).
        "nexus_enabled": True,
        "hitl_enabled": True,
        "mesh_response_capability": "action_briefing",
    })
    mesh.add(GTMAgent, agent_id="gtm-agent")
    return mesh


async def submit_task(mesh: Mesh, message: str, context: dict | None = None) -> dict:
    """Run one Desk request as a durable Mesh goal."""
    goal = (message or "").strip()
    if not goal:
        raise ValueError("A mesh task needs a message.")
    context = dict(context or {})
    workflow_id = context.pop("mesh_workflow_id", None) or f"gtm-{uuid4().hex[:12]}"
    result = await mesh.execute_goal(goal, workflow_id=workflow_id, context=context)
    return desk_view(result)


async def reconcile_task(mesh: Mesh, workflow_id: str, context: dict | None = None) -> dict:
    """Continue an existing goal whose obligations are still unresolved."""
    if not workflow_id:
        raise ValueError("Goal reconciliation requires a workflow identity.")
    result = await mesh.replan_goal(
        workflow_id,
        reason=(
            "The person asked to continue. Resolve what is still open from current "
            "provider state; do not repeat completed actions."
        ),
        context=dict(context or {}),
    )
    return desk_view(result)


def desk_view(goal: dict) -> dict:
    """The Desk's view of a ``Mesh.execute_goal`` result.

    The Desk reads ``status`` as ``success``/``yield``/anything else. A goal
    reports ``completed``/``waiting``/``failed``/``cancelled`` and keeps each
    step's envelope in ``steps``; the user-facing ``output`` and ``evidence``
    are the final response step's, and a pause carries the waiting step's
    ``yield_metadata``.
    """
    steps = [
        step for step in goal.get("steps", [])
        if int(step.get("plan_revision", 1)) == int(goal.get("revision") or 1)
    ]
    response = next(
        (step.get("output") or {} for step in reversed(steps)
         if step.get("effect") == "final_response"),
        {},
    )
    view = {
        "workflow_id": goal.get("workflow_id"),
        "result_summary": goal.get("result_summary") or response.get("result_summary") or "",
        "output": response.get("output"),
        "evidence": response.get("evidence", []),
        "obligation_status": goal.get("obligation_status"),
        "tokens": {"total": sum(
            int(((step.get("output") or {}).get("tokens") or {}).get("total") or 0)
            for step in goal.get("steps", [])
        )},
    }
    status = goal.get("status")
    if status == "completed":
        return {**view, "status": "success"}
    if status == "waiting":
        waiting = next(
            (step.get("output") or {} for step in steps if step.get("status") == "waiting"), {}
        )
        return {**view, "status": "yield", "yield_metadata": waiting.get("yield_metadata", {})}
    return {**view, "status": "failure", "error": goal.get("error") or f"The goal {status}."}
