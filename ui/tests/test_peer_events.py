from types import SimpleNamespace

import pytest

from server.models import AgentMetadata, Operation, clean_event
from server.registry import AdapterRegistry
from server.runtime import RunManager
from server.store import RunStore


def metadata(identity):
    return AgentMetadata(id=identity, name=identity, description="test", blueprint="test",
                         operations=(Operation(id="ask", label="Ask", description="Test"),))


@pytest.mark.asyncio
async def test_peer_batch_is_redacted_persisted_and_replayable(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_TOKEN", "secret-value")

    async def execute(operation, message, emit):
        await emit("peer_message", {"recipient_id": "receiver", "messages": [
            {"sender_id": "researcher", "text": "Evidence: secret-value"},
            {"sender_id": "reviewer", "text": "Checked the account notes."},
        ]})

    registry = AdapterRegistry([SimpleNamespace(metadata=metadata(identity), execute=execute)
                                for identity in ("receiver", "researcher", "reviewer")])
    store = RunStore(tmp_path)
    manager = RunManager(store, registry)
    try:
        run = manager.start("receiver", "ask", None)
        await manager.tasks[run["id"]]
        saved = store.get(run["id"])
        assert saved["status"] == "completed"
        event = next(item for item in saved["events"] if item["type"] == "peer_message")
        assert event["data"]["messages"][0]["text"] == "Evidence: [redacted]"
        assert len(event["data"]["messages"]) == 2
        assert store.events(run["id"], event["seq"] - 1)[0] == event
    finally:
        await manager.close()
        store.close()


@pytest.mark.parametrize("data", [
    {"recipient_id": "receiver", "messages": []},
    {"recipient_id": "receiver", "messages": [{"sender_id": "source", "text": 123}]},
    {"recipient_id": "receiver", "messages": [{"sender_id": "source", "text": "hello", "token": "hidden"}]},
])
def test_invalid_peer_contract_is_refused(data):
    with pytest.raises(ValueError):
        clean_event("peer_message", data, lambda value: value)


@pytest.mark.asyncio
async def test_unknown_peer_is_not_presented_as_a_real_agent(tmp_path):
    async def execute(operation, message, emit):
        await emit("peer_message", {"recipient_id": "receiver", "messages": [
            {"sender_id": "invented", "text": "not a real peer"},
        ]})

    store = RunStore(tmp_path)
    manager = RunManager(store, AdapterRegistry([SimpleNamespace(metadata=metadata("receiver"), execute=execute)]))
    try:
        run = manager.start("receiver", "ask", None)
        await manager.tasks[run["id"]]
        saved = store.get(run["id"])
        assert saved["status"] == "failed"
        assert not any(event["type"] == "peer_message" for event in saved["events"])
    finally:
        await manager.close()
        store.close()
