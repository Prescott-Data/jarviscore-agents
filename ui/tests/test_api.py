import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.models import AgentMetadata, Operation
from server.registry import AdapterRegistry
from server.store import RunStore, desk_home


class FakeAdapter:
    metadata = AgentMetadata(
        id="test-agent", name="Test agent", description="Controlled test adapter", blueprint="tests",
        operations=(
            Operation(id="work", label="Work", description="Run", allows_message=True),
            Operation(id="closed", label="Closed", description="No message"),
        ),
    )

    def __init__(self, *, hold=False, error=None, emit_error=False, artifact=None):
        self.hold, self.error, self.emit_error, self.artifact = hold, error, emit_error, artifact
        self.started, self.stopped = threading.Event(), threading.Event()
        self.release = None
        self.calls = 0
        self.last_context = None

    async def execute(self, operation, message, emit, run_context=None):
        self.calls += 1
        self.last_context = run_context
        self.release = asyncio.Event()
        try:
            await emit("status", {"message": "Collecting controlled evidence."})
            self.started.set()
            if self.hold:
                await self.release.wait()
            if self.error:
                raise RuntimeError(self.error)
            if self.emit_error:
                await emit("error", {"message": "Controlled public failure."})
            await emit("result", {"text": message or "Evidence-backed output."})
            if self.artifact:
                await emit("artifact", self.artifact)
        finally:
            self.stopped.set()


class DurableFakeAdapter(FakeAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cancelled_workflows = []

    def workflow_id_for_run(self, run_id):
        return f"desk-tests:{run_id}"

    async def cancel_durable_run(self, run_id):
        self.cancelled_workflows.append(self.workflow_id_for_run(run_id))


class ReconcileFakeAdapter(FakeAdapter):
    metadata = FakeAdapter.metadata.model_copy(update={"supports_reconciliation": True})

    async def reconcile(self, operation, message, emit, run_context=None):
        self.calls += 1
        self.last_context = run_context
        await emit("status", {"message": "Reconciling durable goal."})
        await emit("result", {
            "text": "The remaining obligation is now satisfied.",
            "obligation_status": "satisfied",
        })


def client_for(tmp_path, adapter=None, **kwargs):
    return TestClient(
        create_app(registry=AdapterRegistry([adapter or FakeAdapter()]), home=tmp_path, **kwargs),
        base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50001),
    )


def start(client, **extra):
    response = client.post("/api/runs", json={"agent_id": "test-agent", "operation": "work", **extra})
    assert response.status_code == 202, response.text
    return response.json()


def replay(client, run_id, after=None):
    headers = {"Last-Event-ID": str(after)} if after is not None else {}
    response = client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for frame in response.text.split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        lines = frame.splitlines()
        assert not any(line.startswith("event:") for line in lines)
        envelope = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert f"id: {envelope['seq']}" in lines
        assert set(envelope) == {"seq", "type", "timestamp", "data"}
        result.append(envelope)
    return result


def test_contract_sse_replay_and_reload(tmp_path, monkeypatch):
    monkeypatch.setattr("server.app.framework_info", lambda: {"framework_revision": "abc123"})
    with client_for(tmp_path) as client:
        agents = client.get("/api/agents").json()
        assert set(agents[0]) == {
            "id", "name", "description", "blueprint", "operations", "kind", "members",
            "capabilities", "supports_reconciliation", "color", "shape",
        }
        assert set(agents[0]["operations"][0]) == {
            "id", "label", "description", "allows_message",
        }
        assert client.get("/api/health").json()["framework_revision"] == "abc123"
        run = start(client, message="question")
        assert set(run) == {
            "id", "agent_id", "operation", "message", "context", "status",
            "created_at", "updated_at", "events",
        }
        events = replay(client, run["id"])
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["type"] == "completed"
        assert replay(client, run["id"], after=2) == events[2:]
        assert replay(client, run["id"], after=1000) == []
        saved = client.get(f"/api/runs/{run['id']}").json()
        assert saved["events"] == events
        assert saved["status"] == "completed"
        assert saved["updated_at"] >= saved["created_at"]
    fresh = FakeAdapter()
    with client_for(tmp_path, fresh) as client:
        assert client.get("/api/runs").json() == [saved]
        assert replay(client, run["id"]) == events
        assert fresh.calls == 0


def test_artifact_event_survives_persistence_and_sse_replay(tmp_path):
    artifact = {
        "schema_version": "1", "id": "sheet-1", "artifact_type": "spreadsheet",
        "title": "Acme pipeline", "url": "https://sheets.example/sheet-1",
        "provider": "workspace", "metadata": {"Rows": "18"},
    }
    with client_for(tmp_path, FakeAdapter(artifact=artifact)) as client:
        run = start(client, message="Build pipeline")
        events = replay(client, run["id"])
        saved = client.get(f"/api/runs/{run['id']}").json()

    assert [event["data"] for event in events if event["type"] == "artifact"] == [artifact]
    assert saved["events"] == events


def test_structured_source_context_is_persisted_and_forwarded(tmp_path):
    adapter = FakeAdapter()
    with client_for(tmp_path, adapter) as client:
        context = {
            "source": "contact_form",
            "lead": {"name": "Ephy Kizito", "email": "ephy@example.com"},
        }
        run = start(client, message="Accelerate this lead", source_context=context)

        expected = {
            "source_context": context,
            "owner_id": (tmp_path / "owner_id").read_text(),
        }
        assert run["context"] == expected
        assert adapter.last_context == expected | {"run_id": run["id"]}
        assert client.get(f"/api/runs/{run['id']}").json()["context"] == expected


def test_every_run_names_the_one_person_this_desk_serves(tmp_path):
    adapter = FakeAdapter()
    with client_for(tmp_path, adapter) as client:
        first = start(client, message="Plan dinners")
    with client_for(tmp_path, adapter) as client:
        second = start(client, message="Remember my partner is vegetarian")

    owner = (tmp_path / "owner_id").read_text()
    assert owner.startswith("desk-")
    assert first["context"]["owner_id"] == second["context"]["owner_id"] == owner
    assert (tmp_path / "owner_id").stat().st_mode & 0o777 == 0o600


def test_existing_run_database_gains_empty_context(tmp_path):
    database = sqlite3.connect(tmp_path / "runs.sqlite")
    database.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, "
        "operation TEXT NOT NULL, message TEXT, status TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    database.execute(
        "CREATE TABLE events (run_id TEXT NOT NULL REFERENCES runs(id), "
        "seq INTEGER NOT NULL, type TEXT NOT NULL, timestamp TEXT NOT NULL, "
        "data TEXT NOT NULL, PRIMARY KEY(run_id, seq))"
    )
    database.execute(
        "INSERT INTO runs VALUES ('old', 'test-agent', 'work', 'legacy', "
        "'completed', '2026-01-01', '2026-01-01')"
    )
    database.commit()
    database.close()

    store = RunStore(tmp_path)
    try:
        assert store.get("old")["context"] == {}
    finally:
        store.close()


def test_live_sse_duplicate_and_cancel(tmp_path):
    adapter = FakeAdapter(hold=True)
    with client_for(tmp_path, adapter) as client:
        run = start(client)
        assert adapter.started.wait(5)
        assert client.post("/api/runs", json={"agent_id": "test-agent", "operation": "closed"}).status_code == 409
        with ThreadPoolExecutor() as executor:
            stream = executor.submit(replay, client, run["id"])
            response = client.post(f"/api/runs/{run['id']}/cancel")
            assert response.json()["status"] == "cancelled"
            assert adapter.stopped.is_set()
            assert stream.result(timeout=5)[-1]["type"] == "cancelled"
        assert client.post(f"/api/runs/{run['id']}/cancel").json() == response.json()
        # Ownership is released only after cancellation has finished.
        next_run = start(client)
        client.post(f"/api/runs/{next_run['id']}/cancel")


def test_terminal_run_reconciles_in_same_history_and_replays_events(tmp_path):
    adapter = ReconcileFakeAdapter()
    with client_for(tmp_path, adapter) as client:
        run = start(client, message="Complete the goal")
        initial_events = replay(client, run["id"])
        assert initial_events[-1]["type"] == "completed"
        original_count = len(initial_events)

        reopened = client.post(f"/api/runs/{run['id']}/reconcile")
        assert reopened.status_code == 202
        assert reopened.json()["id"] == run["id"]
        assert reopened.json()["status"] == "running"
        reconciled = replay(client, run["id"], after=original_count)

        assert [event["type"] for event in reconciled] == [
            "status", "status", "result", "completed",
        ]
        assert reconciled[2]["data"]["obligation_status"] == "satisfied"
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "completed"
        assert adapter.last_context["run_id"] == run["id"]


@pytest.mark.parametrize("emit_error", [False, True])
def test_error_is_terminal_and_raw_exceptions_are_not_exposed(tmp_path, emit_error):
    adapter = FakeAdapter(error=None if emit_error else "SECRET .env credential dump", emit_error=emit_error)
    with client_for(tmp_path, adapter) as client:
        run = start(client)
        events = replay(client, run["id"])
        assert any(event["type"] == "error" for event in events)
        assert events[-1]["data"] == {"status": "failed"}
        response = client.get(f"/api/runs/{run['id']}")
        assert response.json()["status"] == "failed"
        assert "SECRET" not in response.text
        assert ".env" not in response.text


def test_restart_marks_non_durable_run_interrupted_without_rerun(tmp_path):
    store = RunStore(tmp_path)
    run = store.create("test-agent", "work", None)
    store.append(run["id"], "result", {"text": "Already delivered."})
    store.close()  # Simulate process death without graceful manager cleanup.
    adapter = FakeAdapter()
    with client_for(tmp_path, adapter) as client:
        saved = client.get(f"/api/runs/{run['id']}").json()
        assert saved["status"] == "interrupted"
        assert "non-durable run" in saved["events"][-2]["data"]["message"]
        assert saved["events"][-1]["data"] == {"status": "interrupted"}
        assert len(replay(client, run["id"], after=2)) == 2
        assert adapter.calls == 0
    with client_for(tmp_path) as client:
        assert client.get(f"/api/runs/{run['id']}").json() == saved


def test_graceful_shutdown_interrupts_not_repeats(tmp_path):
    adapter = FakeAdapter(hold=True)
    with client_for(tmp_path, adapter) as client:
        run = start(client)
        assert adapter.started.wait(5)
    assert adapter.stopped.is_set()
    with client_for(tmp_path) as client:
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "interrupted"


def test_durable_run_is_relaunched_after_graceful_restart(tmp_path):
    holding = DurableFakeAdapter(hold=True)
    with client_for(tmp_path, holding) as client:
        run = start(client)
        assert holding.started.wait(5)

    saved = RunStore(tmp_path)
    try:
        assert saved.get(run["id"])["status"] == "running"
    finally:
        saved.close()

    resumed = DurableFakeAdapter()
    with client_for(tmp_path, resumed) as client:
        events = replay(client, run["id"])
        assert resumed.calls == 1
        assert resumed.last_context["run_id"] == run["id"]
        assert any(
            event["data"].get("message")
            == "Server restarted. Resuming the durable workflow."
            for event in events
            if event["type"] == "status"
        )
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "completed"


def test_explicit_cancel_terminalizes_durable_workflow(tmp_path):
    adapter = DurableFakeAdapter(hold=True)
    with client_for(tmp_path, adapter) as client:
        run = start(client)
        assert adapter.started.wait(5)
        cancelled = client.post(f"/api/runs/{run['id']}/cancel").json()

    assert cancelled["status"] == "cancelled"
    assert adapter.cancelled_workflows == [f"desk-tests:{run['id']}"]


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"},
    {"Host": "localhost.evil.example"},
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://127.0.0.1:9999"},
    {"Origin": "http://localhost:8765"},
    {"Origin": "http://127.0.0.1:8765/"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_origin_and_host_rejected(tmp_path, headers):
    with client_for(tmp_path) as client:
        response = client.post("/api/runs", json={"agent_id": "test-agent", "operation": "work"}, headers=headers)
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
        assert client.get("/api/runs").json() == []


def test_same_origin_and_no_origin_allowed_but_remote_client_denied(tmp_path):
    with client_for(tmp_path) as client:
        response = client.post("/api/runs", json={"agent_id": "test-agent", "operation": "work"},
                               headers={"Origin": "http://127.0.0.1:8765"})
        assert response.status_code == 202
        replay(client, response.json()["id"])
    with TestClient(create_app(home=tmp_path), base_url="http://127.0.0.1:8765",
                    client=("192.0.2.1", 50001)) as client:
        assert client.get("/api/health").status_code == 403


def test_returning_from_a_consent_screen_is_allowed(tmp_path):
    """The provider redirects the person back here after they approve.

    That arrives as a cross-site top-level navigation. It can read nothing
    back, so it cannot drive the API, and refusing it strands the person on a
    JSON error at the exact moment the flow succeeded.
    """
    navigation = {
        "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
    }
    with client_for(tmp_path) as client:
        response = client.get("/?connection_id=abc&provider=slack&status=success", headers=navigation)
        assert response.status_code == 200


@pytest.mark.parametrize("headers", [
    # A cross-site fetch can read the response: still refused.
    {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},
    # A cross-site embed is not a navigation the person made: still refused.
    {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"},
])
def test_cross_site_reads_and_embeds_remain_refused(tmp_path, headers):
    with client_for(tmp_path) as client:
        assert client.get("/api/runs", headers=headers).status_code == 403


def test_validation_never_echoes_inputs_or_accepts_execution_paths(tmp_path):
    with client_for(tmp_path) as client:
        for body in (
            {"agent_id": "test-agent", "operation": "work", "command": "cat .env SECRET"},
            {"agent_id": "test-agent", "operation": "work", "path": "/etc/passwd"},
            {"agent_id": "test-agent", "operation": "closed", "message": "SECRET"},
            {"agent_id": "test-agent", "operation": "work", "message": {"token": "SECRET"}},
            {"agent_id": "test-agent", "operation": "; cat .env SECRET"},
        ):
            response = client.post("/api/runs", json=body)
            assert response.status_code == 422
            assert "SECRET" not in response.text
        assert client.post("/api/runs", json={"agent_id": "../../bad", "operation": "work"}).status_code == 404
        assert client.post("/api/runs", content="SECRET").status_code == 422
        assert client.post("/api/runs", content="a" * 32769).status_code == 413
        assert client.get("/api/runs/missing").status_code == 404
        assert client.get("/api/runs/missing/events").status_code == 404
        assert client.post("/api/runs/missing/cancel").status_code == 404
        run = start(client)
        for cursor in ("-1", "abc", "1.5", "9" * 30):
            assert client.get(f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": cursor}).status_code == 400
            assert client.get("/api/runs/stream", headers={"Last-Event-ID": cursor}).status_code == 400


def test_known_secret_redaction_before_sqlite(tmp_path, monkeypatch):
    secret = "test-secret-that-must-never-be-persisted"
    monkeypatch.setenv("DEMO_API_KEY", secret)
    with client_for(tmp_path) as client:
        run = start(client, message=f"Question {secret}")
        assert secret not in json.dumps(run)
        assert secret not in json.dumps(replay(client, run["id"]))
        assert "[redacted]" in client.get("/api/runs").text
    assert secret.encode() not in (tmp_path / "runs.sqlite").read_bytes()


def test_static_files_and_traversal_are_confined(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><h1>Desk</h1>")
    (static / "app.js").write_text("console.log('desk')")
    (static / ".env").write_text("SECRET")
    outside = tmp_path / "outside.js"
    outside.write_text("SECRET")
    (static / "escape.js").symlink_to(outside)
    with client_for(tmp_path / "history", static_dir=static) as client:
        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        for path in ("/.env", "/static/.env", "/escape.js", "/%2e%2e/outside.js", "/api/nonsense", "/app.js.map"):
            response = client.get(path)
            assert response.status_code == 404
            assert "SECRET" not in response.text
    with client_for(tmp_path / "other", static_dir=tmp_path / "absent") as client:
        missing = client.get("/")
        assert missing.status_code == 503 and "npm run build" in missing.text, "says how to build it"
        assert client.get("/app.js").status_code == 404
        assert client.get("/api/health").status_code == 200


def test_single_history_writer_and_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVISCORE_DESK_HOME", str(tmp_path))
    assert desk_home() == tmp_path
    store = RunStore(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="already"):
            RunStore(tmp_path)
    finally:
        store.close()
    assert (tmp_path / "runs.sqlite").stat().st_mode & 0o777 == 0o600


def test_registry_opt_in_entrypoints_and_duplicate_contract(monkeypatch):
    adapter = FakeAdapter()
    registry = AdapterRegistry([adapter])
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(adapter)
    entry = Mock(name="entry")
    entry.name = "test-adapter"
    entry.load.return_value = lambda: adapter
    discovered = Mock(return_value=[entry])
    monkeypatch.setattr("server.registry.entry_points", discovered)
    installed = AdapterRegistry()
    assert not discovered.called
    installed.load_installed()
    discovered.assert_called_once_with(group="jarviscore_agents.ui")
    assert installed.metadata() == registry.metadata()


def test_launcher_rejects_network_binding():
    from server.__main__ import parser

    assert parser().parse_args([]).host == "127.0.0.1"
    assert parser().parse_args([]).port == 8765
    with pytest.raises(SystemExit):
        parser().parse_args(["--host", "0.0.0.0"])

