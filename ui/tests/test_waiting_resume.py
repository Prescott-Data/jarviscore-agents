"""OAuth is a durable run state, not a five-minute tool timeout."""

import pytest

from server.models import AgentMetadata, Operation
from server.registry import AdapterRegistry
from server.runtime import RunManager
from server.store import RunStore


class WaitingAdapter:
    metadata = AgentMetadata(
        id="mail-agent", name="Mail agent", description="Mail", blueprint="test",
        operations=(Operation(id="task", label="Task", description="Task", allows_message=True),),
    )

    def __init__(self):
        self.contexts = []

    async def execute(self, operation, message, emit, run_context=None):
        self.contexts.append(dict(run_context or {}))
        if not run_context.get("_resume"):
            await emit("consent_required", {
                "provider": "gmail", "label": "Gmail",
                "auth_url": "https://accounts.google.com/consent",
            })
            await emit("waiting", {
                "provider": "gmail", "connection_id": "conn-1",
                "workflow_id": "wf-1", "step_id": "step-1",
            })
            return
        await emit("result", {"text": "Mailbox processed after access was approved."})


class ApprovalAdapter(WaitingAdapter):
    async def execute(self, operation, message, emit, run_context=None):
        self.contexts.append(dict(run_context or {}))
        action_id = "a" * 64
        decision = (run_context or {}).get("hitl_decision")
        if decision is None:
            await emit("approval_required", {
                "action_id": action_id, "action": "Delete message m-1",
                "consequence": "Permanently deletes the message.",
            })
            await emit("waiting", {
                "provider": "gmail", "connection_id": action_id,
                "workflow_id": "wf-1", "step_id": "step-1",
            })
            return
        if decision["decision"] == "approve":
            await emit("result", {"text": "Message deleted after approval."})
        else:
            await emit("result", {"text": "You declined, so the message was kept."})


@pytest.mark.asyncio
async def test_waiting_survives_worker_exit_and_resumes_the_same_run(tmp_path):
    adapter = WaitingAdapter()
    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([adapter]))
    try:
        run = manager.start("mail-agent", "task", "process my mailbox")
        await manager.tasks[run["id"]]

        waiting = store.get(run["id"])
        assert waiting["status"] == "waiting"
        assert waiting["message"] == "process my mailbox"
        assert [event["type"] for event in waiting["events"]][-2:] == [
            "consent_required", "waiting",
        ]

        resumed = manager.resume(run["id"], "conn-1")
        assert resumed["id"] == run["id"]
        await manager.tasks[run["id"]]

        finished = store.get(run["id"])
        assert finished["status"] == "completed"
        assert any(event["type"] == "result" for event in finished["events"])
        assert adapter.contexts[1] == {
            "owner_id": store.owner_id,
            "provider": "gmail", "connection_id": "conn-1",
            "workflow_id": "wf-1", "step_id": "step-1",
            "run_id": run["id"], "_resume": True, "system": "gmail",
        }
    finally:
        await manager.close()
        store.close()


@pytest.mark.asyncio
async def test_wrong_callback_cannot_resume_a_waiting_run(tmp_path):
    adapter = WaitingAdapter()
    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([adapter]))
    try:
        run = manager.start("mail-agent", "task", "process my mailbox")
        await manager.tasks[run["id"]]
        with pytest.raises(RuntimeError, match="does not belong"):
            manager.resume(run["id"], "another-connection")
        assert store.get(run["id"])["status"] == "waiting"
    finally:
        await manager.close()
        store.close()


@pytest.mark.asyncio
async def test_approval_is_bound_to_the_pending_action_and_resumes_same_run(tmp_path):
    adapter = ApprovalAdapter()
    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([adapter]))
    try:
        run = manager.start("mail-agent", "task", "delete m-1")
        await manager.tasks[run["id"]]
        action_id = "a" * 64

        with pytest.raises(RuntimeError, match="does not belong"):
            await manager.approve(run["id"], "b" * 64, False)
        assert store.get(run["id"])["status"] == "waiting"

        resumed = await manager.approve(run["id"], action_id, True)
        assert resumed["id"] == run["id"]
        await manager.tasks[run["id"]]
        assert store.get(run["id"])["status"] == "completed"
        assert adapter.contexts[1]["hitl_decision"] == {
            "action_id": action_id, "decision": "approve", "resolved_by": store.owner_id,
        }
        assert "_approved_actions" not in adapter.contexts[1]
        assert adapter.contexts[1]["run_id"] == run["id"]
    finally:
        await manager.close()
        store.close()


@pytest.mark.asyncio
async def test_declining_is_a_decision_the_agent_reports_on(tmp_path):
    adapter = ApprovalAdapter()
    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([adapter]))
    try:
        run = manager.start("mail-agent", "task", "delete m-1")
        await manager.tasks[run["id"]]

        await manager.approve(run["id"], "a" * 64, False)
        await manager.tasks[run["id"]]

        finished = store.get(run["id"])
        assert finished["status"] == "completed"
        assert adapter.contexts[1]["hitl_decision"]["decision"] == "reject"
        assert finished["events"][-2]["data"]["text"] == "You declined, so the message was kept."
        decided = [event for event in finished["events"] if event["type"] == "approval_decided"]
        assert [event["data"] for event in decided] == [{"action_id": "a" * 64, "approved": False}]
    finally:
        await manager.close()
        store.close()
