import json

import httpx
import pytest

from server import observability


@pytest.mark.asyncio
async def test_unconfigured_metrics_are_not_fabricated_zeroes():
    assert await observability.read_metrics(None) == {"status": "not_configured", "samples": []}


def test_local_trace_metrics_are_available_without_prometheus(tmp_path):
    result = observability.Inspector(tmp_path).metrics()
    assert result["status"] == "available"
    assert result["source"] == "local_traces"
    assert {sample["name"] for sample in result["samples"]} == {
        "jarviscore_workflow_tokens_total",
        "jarviscore_workflow_failures_total",
        "jarviscore_workflows_total",
    }


@pytest.mark.asyncio
async def test_prometheus_reader_uses_real_parser_and_excludes_other_names(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=(
        '# TYPE jarviscore_llm_tokens_input_total counter\n'
        'jarviscore_llm_tokens_input_total{provider="test"} 42\n'
        'process_resident_memory_bytes 512\n'
    )))
    monkeypatch.setattr(observability.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    result = await observability.read_metrics("http://localhost/metrics")
    assert result == {"status": "available", "samples": [
        {"name": "jarviscore_llm_tokens_input_total", "value": 42.0, "labels": {"provider": "test"}},
    ]}


@pytest.mark.asyncio
async def test_failed_metrics_endpoint_is_unavailable(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    monkeypatch.setattr(observability.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    assert await observability.read_metrics("http://localhost/metrics") == {"status": "unavailable", "samples": []}


def _write_trace(directory, name, lines):
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _event(workflow, step, timestamp, kind, data=None):
    return json.dumps({"workflow_id": workflow, "step_id": step, "timestamp": timestamp,
                       "type": kind, "data": data or {}})


def test_trace_reader_groups_files_by_workflow_id(tmp_path):
    _write_trace(tmp_path, "desk-alpha_task-2.jsonl", [])
    _write_trace(tmp_path, "desk-alpha_task-1.jsonl", [])
    _write_trace(tmp_path, "plain.jsonl", [])
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    runs = observability.discover_traces(tmp_path)
    assert dict(runs) == {
        "desk-alpha": [str(tmp_path / "desk-alpha_task-1.jsonl"), str(tmp_path / "desk-alpha_task-2.jsonl")],
        "plain": [str(tmp_path / "plain.jsonl")],
    }
    assert observability.discover_traces(tmp_path / "missing") == {}


def test_trace_reader_skips_blank_lines_and_keeps_unparseable_ones(tmp_path):
    broken = "{not json" + "x" * 200
    _write_trace(tmp_path, "wf_s1.jsonl", [_event("wf", "s1", "2026-01-01T00:00:00+00:00", "step_start"),
                                          "", "   ", broken])
    events = observability.load_trace_events(tmp_path / "wf_s1.jsonl")
    assert [event["type"] for event in events] == ["step_start", "unparseable_line"]
    assert events[1]["data"]["raw"] == f"{broken[:160]} [clipped: showing 160 of {len(broken)} chars]"
    assert observability.load_trace_events(tmp_path / "missing.jsonl") == []


def test_trace_summary_counts_steps_tokens_failures_and_status(tmp_path):
    _write_trace(tmp_path, "wf_s1.jsonl", [
        _event("wf", "s1", "2026-01-01T00:00:00+00:00", "workflow_start"),
        _event("wf", "s1", "2026-01-01T00:00:01+00:00", "llm_response", {"tokens": 40}),
        _event("wf", "s1", "2026-01-01T00:00:02+00:00", "llm_response", {"tokens": "***"}),
        _event("wf", "s1", "2026-01-01T00:00:03+00:00", "error_recovery"),
    ])
    _write_trace(tmp_path, "wf_s2.jsonl", [
        _event("wf", "s2", "2026-01-01T00:00:04+00:00", "llm_response", {"tokens": 2}),
        _event("wf", "s2", "2026-01-01T00:00:05+00:00", "step_failed"),
        _event("wf", "s2", "2026-01-01T00:00:12.5+00:00", "workflow_complete", {"status": "failed"}),
        "garbage",
    ])
    summary = observability.summarize_trace(observability.discover_traces(tmp_path)["wf"])
    assert summary == {"steps": 2, "events": 8, "tokens": 42, "failures": 2, "status": "failed",
                       "started": "2026-01-01 00:00:00", "duration": "12.5s"}
    assert observability.summarize_trace([]) == {"steps": 0, "events": 0, "tokens": 0, "failures": 0,
                                                 "status": "unknown", "started": "?", "duration": ""}


def test_inspector_lists_and_reads_workflows_from_local_reader(tmp_path):
    _write_trace(tmp_path, "desk-sales_desk:abcdef123456_task-1.jsonl", [
        _event("desk-sales_desk:abcdef123456", "task-1", "2026-01-01T00:00:01+00:00", "llm_response",
               {"tokens": 7, "prompt": "secret"}),
        _event("desk-sales_desk:abcdef123456", "task-1", "2026-01-01T00:00:00+00:00", "step_start"),
    ])
    inspector = observability.Inspector(tmp_path)
    [workflow] = inspector.workflows()
    assert workflow["id"] == "desk-sales_desk:abcdef123456"
    assert workflow["tokens"] == 7 and workflow["steps"] == 1 and workflow["events"] == 2
    events = inspector.events("desk-sales_desk:abcdef123456")
    assert [event["type"] for event in events] == ["step_start", "llm_response"]
    assert events[1]["data"] == {"tokens": 7}
    with pytest.raises(KeyError):
        inspector.events("unknown")
