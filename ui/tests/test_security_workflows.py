import json

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.models import AgentMetadata, Operation, clean_event
from server.native import public_activity
from server.registry import AdapterRegistry


class CredentialAdapter:
    metadata = AgentMetadata(
        id="credential-agent", name="Credential agent", description="Test",
        blueprint="test",
        operations=(Operation(id="task", label="Task", description="Task"),),
    )

    async def execute(self, operation, message, emit, run_context=None):
        if not (run_context or {}).get("_resume"):
            await emit("credential_input_required", {
                "provider": "demo", "label": "Demo", "connection_id": "conn-1",
                "state": "signed-state", "schema": {
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["api_key"],
                },
            })
            await emit("waiting", {
                "provider": "demo", "connection_id": "conn-1",
                "workflow_id": "wf", "step_id": "step",
            })
            return
        await emit("result", {"text": "Credential accepted."})


class GatewayResponse:
    status_code = 200

    @staticmethod
    def json():
        return {"connection_id": "conn-1"}


class GatewayClient:
    submitted = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, path, json):
        type(self).submitted = (path, json)
        return GatewayResponse()


def test_credentials_go_directly_to_nexus_and_never_enter_run_events(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setattr("httpx.AsyncClient", GatewayClient)
    app = create_app(
        registry=AdapterRegistry([CredentialAdapter()]), home=tmp_path,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50001)) as client:
        run = client.post("/api/runs", json={
            "agent_id": "credential-agent", "operation": "task",
        }).json()
        run_id = run["id"]
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "waiting"

        assert client.post(
            f"/api/runs/{run_id}/credentials",
            json={"credentials": {"api_key": "short"}},
        ).status_code == 422
        secret = "secret-key-123"
        response = client.post(
            f"/api/runs/{run_id}/credentials",
            json={"credentials": {"api_key": secret}},
        )
        assert response.status_code == 200
        assert GatewayClient.submitted == (
            "/v1/capture-credential",
            {"state": "signed-state", "credentials": {"api_key": secret}},
        )
        final = client.get(f"/api/runs/{run_id}").json()
        assert final["id"] == run_id
        assert secret not in json.dumps(final)


def test_public_activity_discards_private_trace_content():
    secret = "secret-token-and-private-reasoning"
    thinking = public_activity({"type": "thinking", "data": {"content": secret}})
    tool = public_activity({
        "type": "tool_result",
        "data": {"tool": "nexus_call", "success": True, "output": secret, "arguments": secret},
    })
    decision = public_activity({
        "type": "semantic_decision",
        "data": {"agent": "Pipeline Builder", "decision": "reject"},
    })
    started = public_activity({
        "type": "agent_work_started",
        "data": {"agent": "Pipeline Builder", "summary": secret},
    })

    assert thinking is None
    assert tool == {
        "kind": "tool",
        "agent": "Agent",
        "tool": "nexus_call",
        "outcome": "succeeded",
        "summary": "Used nexus call.",
    }
    assert secret not in json.dumps(tool)
    assert started == {
        "kind": "agent",
        "agent": "Pipeline Builder",
        "outcome": "started",
        "summary": "Working on its assigned requirement.",
    }
    assert secret not in json.dumps(started)
    assert decision == {
        "kind": "decision",
        "agent": "Pipeline Builder",
        "outcome": "failed",
        "summary": "Could not satisfy its assigned requirement; this path was rejected.",
    }
    assert clean_event("activity", decision, lambda value: value) == decision

    def test_artifact_event_is_typed_bounded_and_redacted():
        artifact = clean_event("artifact", {
            "schema_version": "1",
            "id": "draft-123",
            "artifact_type": "email",
            "title": "Private launch note",
            "provider": "gmail",
            "metadata": {"To": "buyer@example.com", "Subject": "Private launch"},
            "preview": {"kind": "text", "text": "Hello private buyer"},
        }, lambda value: value.replace("Private", "[redacted]").replace("private", "[redacted]"))

        assert artifact["title"] == "[redacted] launch note"
        assert artifact["metadata"]["Subject"] == "[redacted] launch"
        assert artifact["preview"]["text"] == "Hello [redacted] buyer"

        with pytest.raises(ValueError, match="HTTPS URL"):
            clean_event("artifact", {
                "id": "unsafe-pdf", "artifact_type": "pdf", "title": "Report",
                "preview": {"kind": "pdf", "url": "http://example.com/report.pdf"},
            }, lambda value: value)


    def test_result_event_preserves_typed_obligation_status_and_redacts_text():
        assert clean_event("result", {
            "text": "Private outcome", "obligation_status": "blocked",
        }, lambda value: value.replace("Private", "[redacted]")) == {
            "text": "[redacted] outcome", "obligation_status": "blocked",
        }
        with pytest.raises(ValueError):
            clean_event("result", {
                "text": "Outcome", "obligation_status": "completed",
            }, lambda value: value)

        with pytest.raises(ValueError, match="HTTPS origin"):
            clean_event("artifact", {
                "id": "empty-host", "artifact_type": "document", "title": "Report",
                "url": "https://",
            }, lambda value: value)
