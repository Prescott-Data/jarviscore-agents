from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server import native
from server.configured_worker import failure_frame
from server.models import clean_event
from server.observability import Inspector
from server.security import Redactor


@pytest.mark.parametrize("event_type,data,kind,outcome", [
    ("step_start", {}, "agent", "started"),
    ("tool_start", {"tool": "read"}, "tool", "started"),
    ("tool_result", {"tool": "read", "success": True}, "tool", "succeeded"),
    ("tool_result", {"tool": "read", "success": False}, "tool", "failed"),
    ("step_complete", {"success": True}, "agent", "succeeded"),
    ("step_complete", {"success": False}, "agent", "failed"),
])
def test_native_kernel_activity_is_shared_without_private_evidence(event_type, data, kind, outcome):
    event = {
        "type": event_type,
        "data": {**data, "agent": "field_research", "args": {"secret": "private"},
                 "result": "private evidence", "summary": "private evidence"},
    }
    public = native.public_activity(event)
    assert public["kind"] == kind
    assert public["agent"] == "field_research"
    assert public["outcome"] == outcome
    assert "private" not in str(public)


def test_configured_worker_failure_frame_is_redacted():
    frame = failure_frame(
        RuntimeError("request failed with token ghp_abcdefghijklmnopqrstuvwxyz123456"),
        Redactor().text,
    )

    assert "RuntimeError" in frame
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in frame


def test_structured_output_redacts_nested_secret_values(monkeypatch):
    monkeypatch.setenv("TEST_API_TOKEN", "secret-structured-value")
    redactor = Redactor()

    output = clean_event("structured_output", {
        "schema_version": "1",
        "output_type": "email_triage",
        "title": "Latest email",
        "data": {
            "messages": [{
                "subject": "Account update",
                "debug": {"token": "secret-structured-value"},
            }],
        },
    }, redactor.text)

    assert output["data"]["messages"][0]["debug"]["token"] == "[redacted]"


@pytest.mark.asyncio
async def test_individual_task_reaches_exact_instance_and_mesh_handler_sees_all(tmp_path, monkeypatch):
    agents = [SimpleNamespace(agent_id=f"member-{index}", role="same-role", execute_task=AsyncMock(return_value={
        "status": "success", "output": "result", "tokens": {"total": 15},
    })) for index in range(2)]
    mesh = SimpleNamespace(agents=agents, start=AsyncMock(), stop=AsyncMock())
    handler = AsyncMock(return_value={"status": "success", "output": "mesh result"})
    monkeypatch.setattr(native, "load_config", lambda _: SimpleNamespace(
        factory="mesh", mesh_handler="handler", trace_dir=tmp_path, blueprint="gtm",
        agents={"same-role": SimpleNamespace(id=None, name="Research Partner")},
    ))
    monkeypatch.setattr(native, "resolve", lambda reference: (lambda: mesh) if reference == "mesh" else handler)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async def execute_with_native_trace(task):
        agents[1]._trace_sink({"type": "step_start", "data": {}})
        return {"status": "success", "output": "result", "tokens": {"total": 15}}

    agents[1].execute_task.side_effect = execute_with_native_trace
    await native.run_configured("config", "same-role:1", "Help with evidence", emit)
    agents[0].execute_task.assert_not_awaited()
    agents[1].execute_task.assert_awaited_once()
    assert next(data for kind, data in events if kind == "activity")["agent"] == "Research Partner"
    await native.run_configured("config", "mesh", "A shared task", emit)
    assert handler.call_args.args[0] is mesh
    assert handler.call_args.args[1] == "A shared task"
    assert mesh.stop.await_count == 2
    workflows = Inspector(tmp_path).workflows()
    assert len(workflows) == 2
    assert all(row["status"] == "success" for row in workflows)
    assert all(row["display_name"].startswith("Gtm") for row in workflows)
    assert all(row["reference"] for row in workflows)

    # A thread keeps one framework workflow so its memory tiers accumulate;
    # each task is a separate step inside it.
    first = agents[1].execute_task.call_args.args[0]["context"]
    await native.run_configured("config", "same-role:1", "A follow-up", emit)
    second = agents[1].execute_task.call_args.args[0]["context"]
    assert first["workflow_id"] == second["workflow_id"] == "desk-gtm-same-role-1"
    assert first["step_id"] != second["step_id"]
    assert handler.call_args.args[2]["workflow_id"] == "desk-gtm-mesh"
    assert (
        "status", {"message": "Connecting configured agents to durable workflow state."}
    ) in events


def test_inspection_excludes_sensitive_trace_contents(tmp_path):
    import json

    (tmp_path / "workflow_step.jsonl").write_text(json.dumps({
        "type": "llm_response", "timestamp": "2026-09-05T00:00:00Z", "step_id": "step",
        "data": {"tokens": 12, "content_preview": "private text", "api_key": "secret"},
    }) + "\n")
    inspector = Inspector(tmp_path)
    assert inspector.events("workflow")[0]["data"] == {"tokens": 12}
    with pytest.raises(KeyError):
        inspector.events("../../secret")


def build_test_mesh():
    from jarviscore import Mesh
    from jarviscore.profiles.customagent import CustomAgent

    class TestMember(CustomAgent):
        role = "test_member"
        capabilities = ["test_echo"]

        async def execute_task(self, task):
            return {"status": "success", "output": "Native member received: " + task["task"]}

    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(TestMember)
    return mesh


async def submit_test_task(mesh, message, context):
    return await mesh.run_task(agent="test_member", task=message, context=context)


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_retract_a_persisted_result(tmp_path, monkeypatch):
    agent = SimpleNamespace(
        agent_id="member-0", role="member", execute_task=AsyncMock(return_value={
            "status": "success", "output": {"status": "no_changes"},
            "result_summary": "", "tokens": {},
        }),
    )
    mesh = SimpleNamespace(
        agents=[agent], start=AsyncMock(), stop=AsyncMock(side_effect=RuntimeError("cleanup")),
    )
    monkeypatch.setattr(native, "load_config", lambda _: SimpleNamespace(
        factory="mesh", mesh_handler=None, trace_dir=tmp_path, blueprint="gtm",
    ))
    monkeypatch.setattr(native, "resolve", lambda _: lambda: mesh)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    await native.run_configured("config", "member:0", "Inspect pipeline", emit)

    assert any(kind == "result" for kind, _ in events)
    assert not any(kind == "error" for kind, _ in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("summary", ["Found two of the three homes you asked for.", ""])
async def test_an_unfinished_goal_shows_the_agents_answer_not_a_trace_hint(
    tmp_path, monkeypatch, summary,
):
    result = {"status": "failure", "error": "internal", "result_summary": summary,
              "obligation_status": "incomplete", "tokens": {}}
    agent = SimpleNamespace(
        agent_id="member-0", role="member", execute_task=AsyncMock(return_value=result),
    )
    mesh = SimpleNamespace(agents=[agent], start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(native, "load_config", lambda _: SimpleNamespace(
        factory="mesh", mesh_handler=None, trace_dir=tmp_path, blueprint="gtm",
    ))
    monkeypatch.setattr(native, "resolve", lambda _: lambda: mesh)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    await native.run_configured("config", "member:0", "Find three homes", emit)

    shown = [(kind, data) for kind, data in events if kind in {"result", "error"}]
    if summary:
        assert shown == [("result", {"text": summary, "obligation_status": "incomplete"})]
    else:
        assert shown == [("error", {"message": "This task stopped before it finished."})]
    assert not any("trace" in str(data).lower() for _, data in shown)


@pytest.mark.asyncio
async def test_native_result_emits_explicit_artifacts_without_parsing_output(tmp_path, monkeypatch):
    result = {
        "status": "success",
        "obligation_status": "blocked",
        "output": {"document_url": "https://ignored.example/untyped"},
        "result_summary": "The requested collateral is ready.",
        "artifacts": [{
            "schema_version": "1", "id": "doc-123", "artifact_type": "document",
            "title": "Acme pitch deck", "url": "https://docs.example/doc-123",
            "provider": "google_docs", "metadata": {"Status": "Created"},
        }],
        "tokens": {},
    }
    agent = SimpleNamespace(
        agent_id="member-0", role="member", execute_task=AsyncMock(return_value=result),
    )
    mesh = SimpleNamespace(agents=[agent], start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(native, "load_config", lambda _: SimpleNamespace(
        factory="mesh", mesh_handler=None, trace_dir=tmp_path, blueprint="gtm",
    ))
    monkeypatch.setattr(native, "resolve", lambda _: lambda: mesh)
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    await native.run_configured("config", "member:0", "Build collateral", emit)

    assert [(kind, data.get("id")) for kind, data in events if kind == "artifact"] == [
        ("artifact", "doc-123"),
    ]
    assert next(data for kind, data in events if kind == "result")["obligation_status"] == (
        "blocked"
    )
    assert not any(
        kind == "artifact" and data.get("url") == "https://ignored.example/untyped"
        for kind, data in events
    )
    structured = next(data for kind, data in events if kind == "structured_output")
    assert structured == {
        "schema_version": "1",
        "output_type": "output",
        "title": "Output",
        "data": {"document_url": "https://ignored.example/untyped"},
    }


def test_explicit_artifact_replaces_bare_mutation_receipt_card():
    outputs = native.public_structured_outputs({
        "action_id": "artifact-1",
        "goal_id": "goal-1",
        "status": "executed",
        "effect": "write",
        "summary": "Created Sunday prep.",
        "executed_at": "2026-10-03T06:00:00Z",
        "evidence": [],
        "unresolved": [],
        "execution_state": "executed",
        "artifact_type": "document",
        "title": "Sunday prep",
        "mutation": {"tool_receipt_id": "tool:1", "path": "output/sunday.md"},
    })

    assert outputs == []


def test_workflow_projection_exposes_work_products_not_internal_envelopes():
    outputs = native.public_structured_outputs({
        "status": "completed",
        "revision": 1,
        "steps": [
            {
                "id": "goal",
                "status": "completed",
                "plan_revision": 1,
                "output": {"status": "success", "output": {
                    "owner_id": "owner-1",
                    "objective": "Review my calendar.",
                    "success_criteria": ["Return every event."],
                }},
            },
            {
                "id": "calendar",
                "status": "completed",
                "plan_revision": 1,
                "depends_on": ["goal"],
                "output": {"status": "success", "output": {
                    "status": "executed",
                    "summary": "Read two events.",
                    "goal_id": "goal-1",
                    "events": [
                        {"event_id": "event-1", "title": "Stand-up"},
                        {"event_id": "event-2", "title": "Review"},
                    ],
                }},
            },
            {
                "id": "final_response",
                "status": "completed",
                "plan_revision": 1,
                "effect": "final_response",
                "depends_on": ["calendar"],
                "output": {"status": "success", "output": {
                    "status": "ready",
                    "user_response": "You have two events.",
                    "progress_summary": "Calendar read.",
                }},
            },
        ],
    })

    assert outputs == [{
        "schema_version": "1",
        "output_type": "calendar_review",
        "title": "Calendar",
        "data": {
            "status": "executed",
            "events": [{"title": "Stand-up"}, {"title": "Review"}],
        },
    }]


def test_work_consumed_by_a_later_step_is_not_shown_as_its_own_result():
    def step(step_id, depends_on, output, effect="propose"):
        return {
            "id": step_id, "status": "completed", "plan_revision": 1,
            "effect": effect, "depends_on": depends_on,
            "output": {"status": "success", "output": output},
        }

    week = [{"day": "2026-10-05", "recipe": "Chicken fajitas"}]
    milk = [{"name": "Milk", "packs": 2}]
    outputs = native.public_structured_outputs({
        "status": "completed",
        "revision": 1,
        "steps": [
            step("plan", [], {"status": "done", "meal_plan": week}),
            step("restock", ["plan"], {"status": "done", "meal_plan": week, "restock": milk}),
            step("order", ["restock"], {"status": "executed", "summary": "Ordered."}, "write"),
            step("record", ["restock", "order"], {
                "status": "done", "meal_plan": week, "restock": milk,
                "recorded": ["Order FC-1 recorded."],
            }),
            step("final_response", ["record", "plan", "restock", "order"], {
                "status": "ready", "user_response": "Ordered.", "progress_summary": "Done.",
            }, "final_response"),
        ],
    })

    assert [output["data"].get("recorded") for output in outputs] == [["Order FC-1 recorded."]]


def test_decision_projection_resolves_recommendation_reference_to_title():
    outputs = native.public_structured_outputs({
        "decision_id": "decision-1",
        "goal_id": "goal-1",
        "decision_owner_id": "owner-1",
        "question": "Weekdays or weekend?",
        "status": "ready",
        "summary": "Weekdays recommended.",
        "options": [
            {"option_id": "weekday", "title": "Two weekday sessions"},
            {"option_id": "weekend", "title": "One weekend session"},
        ],
        "recommendation_option_id": "weekday",
        "rationale": "Two occasions better fit consistency.",
    })

    assert outputs[0]["output_type"] == "decision_brief"
    assert outputs[0]["data"]["recommendation_option"] == "Two weekday sessions"
    assert "recommendation_option_id" not in outputs[0]["data"]
    assert "decision_id" not in outputs[0]["data"]


def test_software_delivery_projection_keeps_quality_not_receipt_internals():
    outputs = native.public_structured_outputs({
        "project_id": "project-1",
        "status": "delivered",
        "title": "Customer portal",
        "summary": "Built and verified the portal.",
        "project_root": ".",
        "deliverables": ["Responsive customer portal"],
        "changed_files": ["src/app.tsx"],
        "mutations": [{
            "tool_receipt_id": "tool:workflow:step-1:1",
            "path": "src/app.tsx",
            "sha256": "a" * 64,
            "bytes": 100,
            "observed_at": "2026-09-25T00:00:00Z",
        }],
        "checks": [{
            "name": "Browser acceptance",
            "kind": "browser",
            "required": True,
            "status": "passed",
            "summary": "Desktop and mobile flows pass.",
            "command": {
                "tool_receipt_id": "tool:workflow:step-1:2",
                "command": ["npx", "playwright", "test"],
                "exit_code": 0,
                "duration_ms": 100,
                "observed_at": "2026-09-25T00:00:00Z",
            },
        }],
        "residual_risks": ["Production hosting is not configured."],
    })

    assert outputs == [{
        "schema_version": "1",
        "output_type": "software_project_delivery",
        "title": "Customer portal",
        "data": {
            "status": "delivered",
            "title": "Customer portal",
            "project_root": ".",
            "deliverables": ["Responsive customer portal"],
            "changed_files": ["src/app.tsx"],
            "checks": [{
                "name": "Browser acceptance",
                "kind": "browser",
                "required": True,
                "status": "passed",
            }],
            "residual_risks": ["Production hosting is not configured."],
        },
    }]


def test_public_projection_resolves_references_and_removes_internal_contract_fields():
    outputs = native.public_structured_outputs({
        "status": "completed",
        "revision": 1,
        "steps": [
            {
                "id": "research",
                "status": "completed",
                "plan_revision": 1,
                "output": {"status": "success", "output": {
                    "goal_id": "goal-1",
                    "status": "ready",
                    "summary": "Candidate shops found.",
                    "opportunities": [{"opportunity_id": "shop-1", "title": "Foodmarket"}],
                }},
            },
            {
                "id": "verify",
                "status": "completed",
                "plan_revision": 1,
                "depends_on": ["research"],
                "output": {"status": "success", "output": {
                    "goal_id": "goal-1",
                    "status": "partial",
                    "summary": "Some items remain unconfirmed.",
                    "targets": [
                        {
                            "target_id": "paneer", "description": "Paneer",
                            "status": "unknown", "source_name": "Foodmarket",
                            "evidence": [{"pointer": "https://example.test"}],
                        },
                        {
                            "target_id": "okra", "description": "Fresh okra",
                            "status": "confirmed", "source_name": "Foodmarket",
                            "location": "Village Market, Nairobi",
                            "evidence": [{"pointer": "https://example.test"}],
                        },
                    ],
                    "next_checks": ["Call Foodmarket before travelling."],
                    "evidence": [{"pointer": "https://example.test"}],
                }},
            },
            {
                "id": "final_response",
                "status": "completed",
                "plan_revision": 1,
                "effect": "final_response",
                "depends_on": ["verify"],
            },
        ],
    })

    assert len(outputs) == 1
    assert outputs[0]["output_type"] == "verification_report"
    assert outputs[0]["data"] == {
        "status": "partial",
        "targets": [
            {"description": "Paneer", "status": "unknown", "source_name": "Foodmarket"},
            {
                "description": "Fresh okra", "status": "confirmed",
                "source_name": "Foodmarket", "location": "Village Market, Nairobi",
            },
        ],
        "next_checks": ["Call Foodmarket before travelling."],
    }


@pytest.mark.asyncio
async def test_native_reconciliation_uses_existing_workflow_handler(tmp_path, monkeypatch):
    mesh = SimpleNamespace(agents=[], start=AsyncMock(), stop=AsyncMock())
    reconcile = AsyncMock(return_value={
        "status": "success", "obligation_status": "satisfied",
        "output": {"status": "reconciled"}, "result_summary": "Goal satisfied.",
        "tokens": {}, "artifacts": [],
    })
    monkeypatch.setattr(native, "load_config", lambda _: SimpleNamespace(
        factory="mesh", mesh_handler="submit", mesh_reconcile_handler="reconcile",
        trace_dir=tmp_path, blueprint="gtm",
    ))
    monkeypatch.setattr(
        native, "resolve",
        lambda reference: (lambda: mesh) if reference == "mesh" else reconcile,
    )
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    await native.run_configured(
        "config", "mesh", "Original goal", emit,
        execution_context={
            "workflow_id": "desk-gtm-mesh", "step_id": "run-1",
            "mesh_workflow_id": "desk-gtm-mesh:run-1",
        },
        execution_mode="reconcile",
    )

    reconcile.assert_awaited_once()
    assert reconcile.call_args.args[1] == "desk-gtm-mesh:run-1"
    assert next(data for kind, data in events if kind == "result") == {
        "text": "Goal satisfied.", "obligation_status": "satisfied",
    }


def test_configured_mesh_over_actual_worker_subprocess(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import configured_registry

    path = tmp_path / "desk.yaml"
    path.write_text(
        "factory: tests.test_native:build_test_mesh\n"
        "mesh_handler: tests.test_native:submit_test_task\n"
        f"working_dir: {tmp_path / 'runtime'}\n"
    )
    config, registry = configured_registry(path, home=tmp_path / "desk")
    with TestClient(create_app(config=config, registry=registry, home=tmp_path / "desk"),
                    base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50123)) as client:
        for identity in (registry.metadata()[0]["id"], "mesh"):
            run = client.post("/api/runs", json={
                "agent_id": identity, "operation": "task", "message": "Offline integration check",
            }).json()
            events = client.get(f"/api/runs/{run['id']}/events")
            saved = client.get(f"/api/runs/{run['id']}").json()
            assert saved["status"] == "completed", (saved, events.text)
            assert "Native member received: Offline integration check" in events.text
        traces = client.get("/api/inspect").json()
        assert len(traces["workflows"]) == 2
