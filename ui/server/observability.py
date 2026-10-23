"""Read configured framework flight records without exposing prompts or credentials."""

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from .security import Redactor


async def read_metrics(url):
    if not url:
        return {"status": "not_configured", "samples": []}
    from prometheus_client.parser import text_string_to_metric_families

    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1048576:
                        raise ValueError("Metrics response exceeds limit")
                    chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8")
        samples = []
        redactor = Redactor()
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                if sample.name.startswith("jarviscore_") and math.isfinite(sample.value):
                    labels = {key: redactor.text(value) for key, value in sample.labels.items()
                              if key in {"provider", "model", "status", "le"}}
                    samples.append({"name": sample.name, "value": sample.value, "labels": labels})
        return {"status": "available", "samples": samples}
    except (httpx.HTTPError, ValueError, UnicodeError):
        return {"status": "unavailable", "samples": []}


RAW_LINE_LIMIT = 160


def _clip(value, limit=RAW_LINE_LIMIT):
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [clipped: showing {limit} of {len(text)} chars]"


def _parse_timestamp(raw):
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def discover_traces(trace_dir):
    """Map workflow id to its trace files, named {workflow_id}_{step_id}.jsonl."""
    runs = defaultdict(list)
    root = Path(trace_dir)
    if not root.is_dir():
        return runs
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".jsonl"):
            continue
        stem = path.name[: -len(".jsonl")]
        workflow_id = stem.rsplit("_", 1)[0] if "_" in stem else stem
        runs[workflow_id].append(str(path))
    return runs


def load_trace_events(path):
    """Read one JSON event per line, keeping unreadable lines visible."""
    events = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"type": "unparseable_line", "data": {"raw": _clip(line)}})
    except OSError:
        pass
    return events


def summarize_trace(paths):
    first = last = None
    steps = set()
    tokens = failures = total = 0
    status = "unknown"
    for path in paths:
        for event in load_trace_events(path):
            total += 1
            moment = _parse_timestamp(event.get("timestamp", ""))
            if moment is not None:
                if first is None or moment < first:
                    first = moment
                if last is None or moment > last:
                    last = moment
            if event.get("step_id"):
                steps.add(event["step_id"])
            kind = event.get("type", "")
            data = event.get("data", {}) or {}
            if kind == "llm_response":
                try:
                    tokens += int(data.get("tokens", 0) or 0)
                except (ValueError, TypeError):
                    pass
            elif kind in ("step_failed", "error_recovery"):
                failures += 1
            elif kind == "workflow_complete":
                status = str(data.get("status", "complete"))
    return {
        "steps": len(steps),
        "events": total,
        "tokens": tokens,
        "failures": failures,
        "status": status,
        "started": first.strftime("%Y-%m-%d %H:%M:%S") if first else "?",
        "duration": f"{(last - first).total_seconds():.1f}s" if first is not None else "",
    }


class Inspector:
    def __init__(self, trace_dir=None):
        self.root = Path(trace_dir).resolve() if trace_dir else None

    def workflows(self):
        if self.root is None:
            return []
        return [{
            "id": identity,
            "display_name": self.display_name(identity),
            "reference": self.reference(identity),
            **summarize_trace(paths),
        }
                for identity, paths in discover_traces(self.root).items()
                if all(Path(path).resolve().is_relative_to(self.root) for path in paths)]

    @staticmethod
    def display_name(identity):
        thread = str(identity).split(":", 1)[0].removeprefix("desk-")
        return thread.replace("_", " ").replace("-", " ").title()

    @staticmethod
    def reference(identity):
        parts = str(identity).split(":")
        return parts[-1][:8] if len(parts) > 1 else str(identity)[:12]

    def metrics(self):
        workflows = self.workflows()
        return {
            "status": "available",
            "source": "local_traces",
            "samples": [
                {
                    "name": "jarviscore_workflow_tokens_total",
                    "value": sum(item["tokens"] for item in workflows),
                    "labels": {},
                },
                {
                    "name": "jarviscore_workflow_failures_total",
                    "value": sum(item["failures"] for item in workflows),
                    "labels": {},
                },
                {
                    "name": "jarviscore_workflows_total",
                    "value": len(workflows),
                    "labels": {},
                },
            ],
        }

    def events(self, identity):
        if self.root is None:
            raise KeyError(identity)
        paths = discover_traces(self.root).get(identity)
        if not paths or not all(Path(path).resolve().is_relative_to(self.root) for path in paths):
            raise KeyError(identity)
        events = []
        for path in paths:
            for event in load_trace_events(path):
                data = event.get("data") or {}
                public = {key: value for key, value in data.items()
                          if key in {"tokens", "latency_ms", "cost_usd", "step_count", "count"}
                          and isinstance(value, (int, float))}
                events.append({"type": str(event.get("type", "unknown")),
                               "timestamp": str(event.get("timestamp", "")),
                               "step_id": str(event.get("step_id", "")), "data": public})
        return sorted(events, key=lambda event: event["timestamp"])
