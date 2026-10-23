from types import SimpleNamespace

import pytest

from server.models import AgentMetadata, Operation, PublicRunError
from server.registry import AdapterRegistry
from server.runtime import RunManager
from server.store import RunStore


@pytest.mark.asyncio
@pytest.mark.parametrize("reported", [True, False])
async def test_a_failed_run_shows_one_error(tmp_path, reported):
    async def execute(operation, message, emit):
        if reported:
            await emit("error", {"message": "ModuleNotFoundError: No module named 'blueprint'"})
        raise PublicRunError("The agent worker failed.")

    metadata = AgentMetadata(id="agent", name="Agent", description="test", blueprint="test",
                             operations=(Operation(id="ask", label="Ask", description="Test"),))
    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([SimpleNamespace(metadata=metadata, execute=execute)]))
    try:
        run = manager.start("agent", "ask", None)
        await manager.tasks[run["id"]]
        saved = store.get(run["id"])
        errors = [event["data"]["message"] for event in saved["events"] if event["type"] == "error"]
        assert saved["status"] == "failed"
        assert errors == (["ModuleNotFoundError: No module named 'blueprint'"] if reported
                          else ["The agent worker failed."])
    finally:
        await manager.close()
        store.close()


def test_all_subscribers_keep_their_notification_across_new_changes(tmp_path):
    store = RunStore(tmp_path)
    try:
        manager = RunManager(store, AdapterRegistry())
        first_subscriber = manager.updates
        second_subscriber = manager.updates
        manager.notify_updates()
        next_change = manager.updates
        assert first_subscriber.is_set() and second_subscriber.is_set()
        assert not next_change.is_set()
        manager.notify_updates()
        assert next_change.is_set()
        assert first_subscriber.is_set()
    finally:
        store.close()


def test_global_revisions_replay_changes_across_runs_and_restarts(tmp_path):
    store = RunStore(tmp_path)
    try:
        assert store.revision() == 0
        first = store.create("one", "task", "First task")
        cursor = store.revision()
        second = store.create("two", "task", "Second task")
        store.append(first["id"], "result", {"text": "First result"})
        store.finish(second["id"], "completed")
        changes = store.changed_runs(cursor, store.revision())
        assert {run["id"] for run in changes} == {first["id"], second["id"]}
        assert next(run for run in changes if run["id"] == second["id"])["status"] == "completed"
        latest = store.revision()
        assert store.changed_runs(latest, latest) == []
    finally:
        store.close()
    restored = RunStore(tmp_path)
    try:
        assert restored.revision() == latest
        assert len(restored.changed_runs(0, latest)) == 2
    finally:
        restored.close()
