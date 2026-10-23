import asyncio
import json
import os
import signal
import socket
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from server.adapters.gtm import GTMAdapter
from server.app import create_app
from server.models import PublicRunError
from server.registry import AdapterRegistry
from server.worker import run_sample


@pytest.mark.asyncio
async def test_actual_gtm_fixture_source_and_state_are_deterministic(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Sample must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    first, second = [], []

    async def emit_first(kind, data):
        first.append((kind, data))

    async def emit_second(kind, data):
        second.append((kind, data))

    await run_sample(emit_first)
    await run_sample(emit_second)
    assert first == second
    text = "\n".join(data.get("text", data.get("message", "")) for _, data in first)
    assert "Fixture-data preview" in text
    assert "1 new, 1 changed, 2 unchanged" in text
    assert "12 to 88" in text
    for field in ("title:", "url:", "dated:", "significance: not assessed", "because:"):
        assert field in text


def test_sample_over_real_subprocess_and_http(tmp_path):
    with TestClient(create_app(home=tmp_path, registry=AdapterRegistry([GTMAdapter(tmp_path)])), base_url="http://127.0.0.1:8765",
                    client=("127.0.0.1", 50001)) as client:
        agents = client.get("/api/agents").json()
        assert agents[0]["id"] == "gtm-account-expert"
        assert [op["id"] for op in agents[0]["operations"]] == ["sample", "watch"]
        response = client.post("/api/runs", json={"agent_id": "gtm-account-expert", "operation": "sample"})
        assert response.status_code == 202
        run_id = response.json()["id"]
        events = client.get(f"/api/runs/{run_id}/events")
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed", run
        from importlib.metadata import version

        assert f"Worker runtime: JarvisCore {version('jarviscore-framework')}" in events.text
        assert "1 new, 1 changed, 2 unchanged" in events.text
        assert not (tmp_path / "gtm" / "accounts").exists()


@pytest.mark.asyncio
async def test_cleanup_does_not_signal_an_already_exited_worker(monkeypatch):
    process = Mock(pid=987654, returncode=0)
    process.wait = AsyncMock(return_value=0)
    kill = Mock(side_effect=PermissionError("process group no longer owned"))
    monkeypatch.setattr(os, "killpg", kill)
    await GTMAdapter._stop(process)
    kill.assert_not_called()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_reaps_direct_worker_when_group_signalling_is_denied(monkeypatch):
    process = Mock(pid=987654, returncode=None)

    async def reaped():
        process.returncode = -signal.SIGTERM
        return process.returncode

    process.wait = AsyncMock(side_effect=reaped)
    monkeypatch.setattr(os, "killpg", Mock(side_effect=PermissionError("group denied")))
    await GTMAdapter._stop(process)
    process.terminate.assert_called_once()
    process.wait.assert_awaited()


@pytest.mark.asyncio
async def test_subprocess_cancel_kills_group_and_reaps(tmp_path, monkeypatch):
    process = Mock(pid=987654, returncode=None)
    started = asyncio.Event()

    async def read_forever():
        started.set()
        await asyncio.Event().wait()

    process.stdout.readline = read_forever
    process.stdin.write = Mock()
    process.stdin.drain = AsyncMock()
    process.wait = AsyncMock(return_value=-signal.SIGTERM)
    spawn = AsyncMock(return_value=process)
    kill = Mock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(os, "killpg", kill)
    adapter = GTMAdapter(tmp_path)
    cancel_workflow = AsyncMock()
    monkeypatch.setattr(adapter, "_cancel_workflow", cancel_workflow)
    task = asyncio.create_task(adapter.execute_worker(
        ["watch"],
        AsyncMock(),
        initial={"context": {"mesh_workflow_id": "wf-cancelled"}},
    ))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_any_call(process.pid, signal.SIGTERM)
    kill.assert_any_call(process.pid, signal.SIGKILL)
    cancel_workflow.assert_not_awaited()
    assert process.wait.await_count >= 1
    assert spawn.call_args.kwargs["start_new_session"] is True
    assert "shell" not in spawn.call_args.kwargs


@pytest.mark.asyncio
async def test_worker_ack_only_after_public_event_persisted(tmp_path, monkeypatch):
    process = Mock(pid=987654, returncode=0)
    process.stdout.readline = AsyncMock(side_effect=[
        b'{"type":"result","data":{"text":"Actual report"}}\n', b"",
    ])
    process.stdin.drain = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(os, "killpg", Mock())

    async def emit(kind, data):
        if kind == "result":
            process.stdin.write.assert_not_called()

    await GTMAdapter(tmp_path).execute("watch", None, emit)
    process.stdin.write.assert_called_once_with(b"ack\n")


@pytest.mark.asyncio
async def test_worker_activity_crosses_the_process_protocol(tmp_path, monkeypatch):
    process = Mock(pid=987654, returncode=0)
    activity = {
        "kind": "tool", "tool": "nexus_call", "outcome": "succeeded",
        "summary": "nexus_call completed.",
    }
    process.stdout.readline = AsyncMock(side_effect=[
        (json.dumps({"type": "activity", "data": activity}) + "\n").encode(), b"",
    ])
    process.stdin.drain = AsyncMock()
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(os, "killpg", Mock())
    emitted = []

    async def emit(kind, data):
        emitted.append((kind, data))

    await GTMAdapter(tmp_path).execute("watch", None, emit)

    assert ("activity", activity) in emitted
    process.stdin.write.assert_called_once_with(b"ack\n")


@pytest.mark.asyncio
async def test_gtm_rejects_arbitrary_operations_and_messages(tmp_path):
    adapter = GTMAdapter(tmp_path)
    for operation, message in (("../../script", None), ("watch", "cat .env"), ("ask", "question")):
        with pytest.raises(PublicRunError):
            await adapter.execute(operation, message, AsyncMock())


class FakeMesh:
    """The Mesh boundary only: the Account Expert answers every change with "note"."""

    calls: list = []

    def __init__(self, config=None):
        pass

    def add(self, cls, pool=None):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass

    async def fanout(self, workflow_id, *, agent, items, task, concurrency):
        from types import SimpleNamespace

        results = []
        for item in items:
            prompt = task(item)
            FakeMesh.calls.append(prompt)
            ids = [line.split("- id: ", 1)[1].strip() for line in prompt.splitlines() if "- id: " in line]
            results.append({"item": item, "status": "success", "output": {"judgements": [
                {"id": change_id, "significance": "note", "because": "Controlled model judgement."}
                for change_id in ids
            ]}})
        return SimpleNamespace(results=results)


@pytest.mark.asyncio
async def test_actual_watch_desk_source_baseline_then_assessment(tmp_path, monkeypatch):
    # Real load_watchlist, GreenhouseSource, run_desk, diff and commit; only the
    # network transport and the Mesh/model boundary are replaced.
    from server.worker import prepare_gtm, run_watch

    prepare_gtm()
    from gtm import desk
    from gtm.sources import ats

    jobs = [{"id": 101, "title": "Operations Lead", "location": {"name": "London"},
             "absolute_url": "https://example.org/jobs/101", "updated_at": "2026-09-05T09:00:00Z"}]
    monkeypatch.setattr(ats, "_fetch", AsyncMock(side_effect=lambda _: {"jobs": jobs}))
    monkeypatch.setattr(desk, "Mesh", FakeMesh)
    FakeMesh.calls = []
    events = []
    state_path = tmp_path / "gtm" / "accounts" / "monzo.json"

    async def emit(kind, data):
        if kind == "result" and not events:
            assert not state_path.exists()
        events.append((kind, data))

    await run_watch(emit, tmp_path)
    assert state_path.exists()
    assert FakeMesh.calls == []
    text = json.dumps(events)
    assert "Collecting Monzo: greenhouse" in text
    assert "Collected 1 observations" in text
    assert "baseline, not news" in text
    assert "significance: not assessed" in text
    events.clear()
    await run_watch(emit, tmp_path)
    assert FakeMesh.calls == []
    assert "Nothing changed" in json.dumps(events)
    jobs[0]["title"] = "Head of Operations"
    events.clear()
    await run_watch(emit, tmp_path)
    assert len(FakeMesh.calls) == 1
    text = json.dumps(events)
    assert "judged 1 changes for Monzo" in text
    assert "significance: note" in text
    assert "Controlled model judgement" in text


@pytest.mark.asyncio
async def test_watch_does_not_commit_before_result_acknowledgement(tmp_path, monkeypatch):
    from server.worker import prepare_gtm, run_watch

    prepare_gtm()
    from gtm import desk
    from gtm.sources import ats

    monkeypatch.setattr(ats, "_fetch", AsyncMock(return_value={"jobs": [
        {"id": 1, "title": "Role", "location": {"name": "London"}}
    ]}))
    monkeypatch.setattr(desk, "Mesh", FakeMesh)

    async def disconnected(kind, data):
        if kind == "result":
            raise ConnectionError("No persistence acknowledgement")

    with pytest.raises(ConnectionError):
        await run_watch(disconnected, tmp_path)
    assert not (tmp_path / "gtm" / "accounts" / "monzo.json").exists()
