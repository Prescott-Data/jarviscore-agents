import asyncio

import pytest

from server.peers import PeerObserver


@pytest.mark.asyncio
async def test_real_peer_request_and_response_emit_registered_identities():
    from jarviscore import Mesh
    from jarviscore.profiles.customagent import CustomAgent

    class Researcher(CustomAgent):
        role = "researcher"
        capabilities = ["research"]

        async def on_peer_request(self, message):
            return {"status": "success", "output": "Account evidence is ready."}

    class Reviewer(CustomAgent):
        role = "reviewer"
        capabilities = ["review"]

    mesh = Mesh(config={"p2p_enabled": False})
    researcher, reviewer = mesh.add(Researcher), mesh.add(Reviewer)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    mesh._inject_peer_clients()
    observer = PeerObserver(mesh, "test:mesh", emit).start()
    listener = asyncio.create_task(researcher.run())
    try:
        result = await reviewer.peers.request("researcher", {"query": "Check the account evidence."}, timeout=2)
        assert result["output"] == "Account evidence is ready."
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
        await observer.close()
    assert len(events) == 2
    assert [data["messages"][0]["text"] for _, data in events] == [
        "Check the account evidence.", "Account evidence is ready.",
    ]
    assert events[0][1]["recipient_id"] == observer.identities[researcher.agent_id]
    assert events[1][1]["recipient_id"] == observer.identities[reviewer.agent_id]
    assert events[1][1]["messages"][0]["sender_id"] == observer.identities[researcher.agent_id]


@pytest.mark.asyncio
async def test_nested_native_mesh_delegate_is_observed_without_replacing_execution():
    from jarviscore import Mesh
    from jarviscore.profiles.customagent import CustomAgent

    class Source(CustomAgent):
        role = "source"
        capabilities = ["evidence"]

        async def execute_task(self, task):
            return {"status": "success", "output": "Verified evidence."}

    class Consumer(CustomAgent):
        role = "consumer"
        capabilities = ["briefing"]

        async def execute_task(self, task):
            return await self._mesh.delegate(to="source", task="Supply account evidence")

    mesh = Mesh(config={"p2p_enabled": False})
    source, consumer = mesh.add(Source), mesh.add(Consumer)
    events = []

    async def emit(kind, data):
        events.append(data)

    observer = PeerObserver(mesh, "test:mesh", emit).start()
    try:
        result = await consumer.execute_task({"task": "Prepare a brief"})
        await observer.flush()
        assert result["output"] == "Verified evidence."
        assert len(events) == 2
        assert events[0]["recipient_id"] == observer.identities[source.agent_id]
        assert events[1]["recipient_id"] == observer.identities[consumer.agent_id]
    finally:
        await observer.close()


def test_a_failed_peer_reply_is_not_shown_as_what_the_peer_said():
    from server.peers import public_payload

    gate = "Completion gate 'browser_observation' unsatisfied after 3 identical attempts"
    failed = {"status": "failure", "error": gate, "result_summary": gate}
    blocked = {"status": "blocked", "result_summary": "FreshCart shows no order yet."}

    assert public_payload(failed, "response") == "Stopped before finishing."
    assert public_payload(blocked, "response") == "FreshCart shows no order yet."


def test_identical_peer_observations_are_deduplicated():
    class Agent:
        role = "peer"
        agent_id = "peer-1"

    class Mesh:
        agents = [Agent()]

    observer = PeerObserver(Mesh(), "test:mesh", lambda *_: None)
    event = {"recipient_id": "peer", "messages": [
        {"sender_id": "sender", "text": "Same delivery"},
    ]}
    observer.record(event)
    observer.record(event)

    assert observer.queue.get_nowait() == event
    assert observer.queue.empty()


def build_worker_peer_mesh():
    from jarviscore import Mesh
    from jarviscore.profiles.customagent import CustomAgent

    class Evidence(CustomAgent):
        role = "evidence"
        capabilities = ["account_evidence"]

        async def on_peer_request(self, message):
            return {"status": "success", "output": "Evidence checked by the native peer."}

    class Brief(CustomAgent):
        role = "brief"
        capabilities = ["briefing"]

        async def execute_task(self, task):
            return await self.peers.request("evidence", {"query": task["task"]}, timeout=2)

    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(Evidence)
    mesh.add(Brief)
    return mesh


def test_real_worker_delivers_peer_events_before_final_result(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import configured_registry

    path = tmp_path / "desk.yaml"
    path.write_text(
        "factory: tests.test_peer_observer:build_worker_peer_mesh\n"
        f"working_dir: {tmp_path / 'runtime'}\n"
        "agents:\n  evidence:\n    id: evidence-peer\n  brief:\n    id: briefing-peer\n"
    )
    config, registry = configured_registry(path, home=tmp_path / "desk")
    with TestClient(create_app(config=config, registry=registry, home=tmp_path / "desk"),
                    base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50123)) as client:
        run = client.post("/api/runs", json={
            "agent_id": "briefing-peer", "operation": "task", "message": "Check renewal evidence.",
        }).json()
        client.get(f"/api/runs/{run['id']}/events")
        saved = client.get(f"/api/runs/{run['id']}").json()
        assert saved["status"] == "completed", saved
        peer_events = [event for event in saved["events"] if event["type"] == "peer_message"]
        assert len(peer_events) == 2
        assert peer_events[0]["data"]["recipient_id"] == "evidence-peer"
        assert peer_events[1]["data"]["recipient_id"] == "briefing-peer"
        assert peer_events[1]["data"]["messages"][0]["text"] == "Evidence checked by the native peer."
        final = next(event for event in saved["events"] if event["type"] == "result")
        assert peer_events[-1]["seq"] < final["seq"]
