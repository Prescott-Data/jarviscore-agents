"""The Personal Intelligence Mesh and its Agent Desk entry points."""

import hashlib
from uuid import uuid4

from jarviscore import Mesh, Pool

from personal_intelligence.agent import PersonalIntelligenceAgent

PLANNING_BRIEF = """This Mesh works for one person on goals in their own words:
decisions to research, plans to make, errands to run and commitments to keep.
Split broad work into independent parts that can run in parallel, then one
briefing. Facts come from current sources, the browser or the person's connected
apps; a search that finds nothing is a valid result when it was thorough.
Keep each step to the effect and system it needs. Signing in grants access, not
consent: sending, booking, buying, paying and deleting wait for the person's
approval. The person's explicit constraints override this method."""


def build_mesh() -> Mesh:
    mesh = Mesh(
        config={
            # One node: the Desk worker or channel process drives the goal.
            "p2p_enabled": False,
            # A person is present to approve consequential actions.
            "hitl_enabled": True,
            # Each person has their own memory.
            "memory_scope_field": "owner_id",
            "mesh_response_capability": "personal_briefing",
            "mesh_planning_brief": PLANNING_BRIEF,
            # Errands that wait on a browser and an approval outlast the 15-minute default.
            "execution_budget": {"max_seconds": 1_800},
        }
    )
    # Up to three members so independent parts of a goal run at the same time.
    mesh.add(PersonalIntelligenceAgent, agent_id="personal-intelligence-agent", pool=Pool(max=3))
    return mesh


def workflow_identity(context=None) -> str:
    """A stable goal id for a redelivered message, otherwise a fresh one."""
    context = dict(context or {})
    if context.get("mesh_workflow_id"):
        return str(context["mesh_workflow_id"])
    parts = [str(context.get(key) or "") for key in ("owner_id", "campaign_id", "source_event_id")]
    if all(parts):
        return f"personal-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:24]}"
    return f"personal-{uuid4().hex[:12]}"


async def submit_task(mesh, message, context=None) -> dict:
    """Run a goal for the person, or continue one they answered."""
    task = (message or "").strip()
    if not task:
        raise ValueError("A personal intelligence task needs a message.")
    context = dict(context or {})
    decision = context.get("hitl_decision")
    if context.get("_resume") and (decision or context.get("connection_id")):
        workflow_id = context.get("mesh_workflow_id") or context["workflow_id"]
        if isinstance(decision, dict):
            result = await mesh.resolve_hitl(
                workflow_id,
                decision["action_id"],
                decision=decision["decision"],
                resolved_by=str(decision.get("resolved_by") or ""),
            )
        else:
            system = context.get("system") or "the app"
            result = await mesh.replan_goal(
                workflow_id,
                reason=f"The person connected {system}. Continue the goal with that access.",
                context=context,
            )
        return desk_result(result)
    source = context.get("source_context")
    if isinstance(source, dict):
        for key in ("owner_id", "campaign_id", "source_event_id"):
            if source.get(key) and not context.get(key):
                context[key] = source[key]
    workflow_id = workflow_identity(context)
    context.pop("mesh_workflow_id", None)
    result = await mesh.execute_goal(task, workflow_id=workflow_id, context=context)
    return desk_result(result)


async def reconcile_task(mesh, workflow_id, context=None) -> dict:
    """Continue a goal the person asked to pick up again."""
    if not workflow_id:
        raise ValueError("Goal reconciliation requires a workflow identity.")
    result = await mesh.replan_goal(
        workflow_id,
        reason=(
            "The person asked to continue. Check current state, keep what is already "
            "done, do not repeat completed actions, and finish what remains."
        ),
        context=dict(context or {}),
    )
    return desk_result(result)


_ANSWER_KEY = {"WAITING_FOR_APPROVAL": "action_id", "WAITING_FOR_CONSENT": "connection_id"}


def _waits(result):
    for step in result.get("steps") or []:
        if step.get("status") == "waiting":
            yield step, (step.get("output") or {}).get("yield_metadata") or {}


def desk_result(result: dict) -> dict:
    """Map a Mesh goal result to the Agent Desk result contract."""
    status = result.get("status")
    summary = str(result.get("result_summary") or "").strip()
    if status == "completed" and summary:
        return {
            "status": "success",
            "output": result,
            "result_summary": summary,
            "obligation_status": result.get("obligation_status"),
        }
    if status == "waiting":
        for step, metadata in _waits(result):
            key = _ANSWER_KEY.get(metadata.get("typed_outcome"))
            if key and metadata.get(key):
                wait = {**metadata, "workflow_id": result["workflow_id"], "step_id": step["id"]}
                return {"status": "yield", "output": result, "yield_metadata": wait}
        for _step, metadata in _waits(result):
            if metadata.get("typed_outcome") == "YIELD_AUTH_REQUIRED" and metadata.get("system"):
                app = str(metadata["system"]).replace("_", " ").title()
                needs = f"I need access to your {app} account. Connect {app}, then continue."
                return {
                    "status": "failure",
                    "output": None,
                    "error": needs,
                    "result_summary": needs,
                    "obligation_status": "blocked",
                }
        return {"status": "yield", "output": result}
    response = {
        "status": "failure",
        "output": result,
        "error": result.get("error") or "The task stopped before it finished.",
    }
    if summary:
        response["result_summary"] = summary
        response["obligation_status"] = result.get("obligation_status") or "incomplete"
    return response
