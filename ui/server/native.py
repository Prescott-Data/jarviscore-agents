"""Native JarvisCore execution for a trusted configured mesh factory."""

import asyncio
import inspect
import json
import re
import uuid

from .config import load_config, resolve
from .models import ArtifactResource
from .peers import PeerObserver
from .presentation import render_answer


def _output_type(payload):
    artifact_type = str(payload.get("artifact_type") or "").strip().lower()
    if artifact_type:
        return re.sub(r"[^a-z0-9_]+", "_", artifact_type).strip("_")[:80]
    if isinstance(payload.get("prep"), dict):
        return "meal_prep"
    if payload.get("meal_plan") or payload.get("restock"):
        return "household_plan"
    signatures = (
        ("events", "calendar_review"),
        ("messages", "email_triage"),
        ("dinners", "shopping_plan"),
        ("changed_files", "software_project_delivery"),
        ("targets", "verification_report"),
        ("opportunities", "opportunity_set"),
        ("options", "decision_brief"),
        ("mutation", "artifact_receipt"),
        ("steps", "action_plan"),
    )
    for key, name in signatures:
        if key in payload:
            return name
    status = str(payload.get("status") or "output").lower()
    return re.sub(r"[^a-z0-9_]+", "_", status).strip("_")[:80] or "output"


def _output_title(payload, output_type):
    if output_type == "meal_prep":
        return str(payload["prep"].get("dinner") or "Dinner prep")[:240]
    for key in ("title", "question"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    public_titles = {
        "calendar_review": "Calendar",
        "email_triage": "Email",
        "shopping_plan": "Meal plan and shopping list",
        "software_project_delivery": "Software project",
        "verification_report": "Verification",
        "opportunity_set": "Findings",
        "decision_brief": "Decision",
        "artifact_receipt": "Document",
        "action_plan": "Plan",
        "household_plan": "Dinners and shopping",
    }
    if output_type in public_titles:
        return public_titles[output_type]
    return output_type.replace("_", " ").title()


_INTERNAL_OUTPUT_FIELDS = {
    "owner_id", "goal_id", "campaign_id", "source_event_id",
    "objective", "success_criteria", "constraints",
    "action_id", "decision_id", "memory_id", "request_id",
    "effect", "system", "execution_state", "executed_at",
    "evidence", "evidence_refs", "mutation", "mutations", "command",
    "tool_receipt_id",
    "summary",
}

_PUBLIC_REFERENCE_FIELDS = {
    "recommendation_option_id": "recommendation_option",
}

_PUBLIC_REFERENCE_LIST_FIELDS = {
    "uncovered_target_ids": "unconfirmed_items",
}


def _reference_labels(value):
    labels = {}

    def collect(candidate):
        if isinstance(candidate, list):
            for item in candidate:
                collect(item)
            return
        if not isinstance(candidate, dict):
            return
        identifier = next(
            (
                item
                for key, item in candidate.items()
                if key.endswith("_id") and isinstance(item, str) and item
            ),
            None,
        )
        display = next(
            (
                candidate.get(key)
                for key in ("title", "name", "vendor_name", "description", "subject")
                if isinstance(candidate.get(key), str) and candidate.get(key).strip()
            ),
            None,
        )
        if identifier and display:
            labels[identifier] = display
        for item in candidate.values():
            collect(item)

    collect(value)
    return labels


def _public_output_data(payload):
    labels = _reference_labels(payload)

    def project(value):
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        public = {}
        for key, item in value.items():
            if key in _INTERNAL_OUTPUT_FIELDS:
                continue
            if key in _PUBLIC_REFERENCE_FIELDS:
                if isinstance(item, str) and item in labels:
                    public[_PUBLIC_REFERENCE_FIELDS[key]] = labels[item]
                continue
            if key in _PUBLIC_REFERENCE_LIST_FIELDS and isinstance(item, list):
                public[_PUBLIC_REFERENCE_LIST_FIELDS[key]] = [
                    labels.get(str(ref), str(ref)) for ref in item
                ]
                continue
            if key.endswith("_id") or key.endswith("_ids"):
                continue
            projected = project(item)
            if projected not in (None, "", [], {}):
                public[key] = projected
        return public

    return project(payload)


def _terminal_work_products(output):
    steps = output.get("steps") or []
    revision = int(output.get("revision") or 0)
    current = [
        step
        for step in steps
        if isinstance(step, dict)
        and (not revision or int(step.get("plan_revision") or 1) == revision)
    ] or [step for step in steps if isinstance(step, dict)]
    final_steps = [
        step
        for step in current
        if step.get("effect") == "final_response" or str(step.get("id", "")).startswith("final_response")
    ]
    terminal_ids = {
        str(dependency)
        for step in final_steps
        for dependency in step.get("depends_on", [])
    }
    # Work another delivered step consumed was an input to it, not a deliverable.
    terminal_ids -= {
        str(dependency)
        for step in current
        if str(step.get("id")) in terminal_ids
        for dependency in step.get("depends_on", [])
    }
    if not terminal_ids:
        depended_on = {
            str(dependency)
            for step in current
            for dependency in step.get("depends_on", [])
        }
        terminal_ids = {
            str(step.get("id"))
            for step in current
            if step.get("effect") != "final_response"
            and str(step.get("id")) not in depended_on
        }
    return [
        step
        for step in current
        if str(step.get("id")) in terminal_ids and step.get("status") == "completed"
    ]


def public_structured_outputs(output):
    """Project validated work products out of a framework workflow envelope."""
    payloads = []
    if isinstance(output, dict) and isinstance(output.get("steps"), list):
        for step in _terminal_work_products(output):
            envelope = step.get("output")
            payload = envelope.get("output") if isinstance(envelope, dict) else envelope
            if not isinstance(payload, dict):
                continue
            if "user_response" in payload and "progress_summary" in payload:
                continue
            payloads.append(payload)
    elif isinstance(output, dict):
        payloads.append(output)
    elif isinstance(output, list):
        payloads.extend(item for item in output if isinstance(item, dict))

    seen = set()
    projected = []
    for payload in payloads:
        artifact_receipt_fields = {
            "action_id", "goal_id", "status", "effect", "system", "summary",
            "executed_at", "evidence", "unresolved", "execution_state",
            "artifact_type", "title", "mutation",
        }
        if payload.get("mutation") and set(payload) <= artifact_receipt_fields:
            continue
        fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        output_type = _output_type(payload)
        public_data = _public_output_data(payload)
        if not public_data:
            continue
        projected.append({
            "schema_version": "1",
            "output_type": output_type,
            "title": _output_title(payload, output_type),
            "data": public_data,
        })
    return projected


def thread_id(config, member):
    """One framework workflow per desk thread, so its memory tiers accumulate."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{config.blueprint}-{member}".lower()).strip("-")
    return f"desk-{slug}"


_TOOL_ACTIONS = {
    "navigate": "Opened a page",
    "click": "Clicked on the page",
    "type_text": "Entered text",
    "fill": "Entered text",
    "get_text": "Read the page",
    "get_links": "Looked at the page links",
    "screenshot": "Looked at the page",
    "wait_for": "Waited for the page",
    "evaluate": "Inspected the page",
    "run_playwright": "Worked through the page",
    "workspace_write": "Wrote a file",
    "workspace_edit": "Edited a file",
    "workspace_read": "Read a file",
    "workspace_run": "Ran a command",
    "web_search": "Searched the web",
    "search": "Searched the web",
    "search_internet": "Searched the web",
    "search_internet_batch": "Searched the web",
    "read_web_content": "Read a web page",
    "read_url": "Read a web page",
    "fetch_url": "Read a web page",
    "ask_capability": "Asked a teammate",
    "read_workflow_step": "Reviewed earlier work",
    "read_turn_result": "Reviewed an earlier result",
}


def _tool_action(tool):
    return _TOOL_ACTIONS.get(tool) or f"Used {tool.replace('_', ' ')}"


def public_activity(event):
    """Project a private trace event to the fixed public activity vocabulary."""
    event_type = event.get("type")
    data = event.get("data") or {}
    agent = str(data.get("agent") or "Agent")[:100]
    if event_type == "step_start":
        return {
            "kind": "agent", "agent": agent, "outcome": "started",
            "summary": "Started working.",
        }
    if event_type in {"tool_start", "tool_result"}:
        tool = str(data.get("tool") or "tool")
        action = _tool_action(tool)
        started = event_type == "tool_start"
        succeeded = data.get("success") is True
        return {
            "kind": "tool", "agent": agent, "tool": tool,
            "outcome": "started" if started else "succeeded" if succeeded else "failed",
            "summary": (
                f"{action}…" if started else
                f"{action}." if succeeded else f"{action} — did not complete."
            ),
        }
    if event_type == "step_complete":
        succeeded = data.get("success") is True
        return {
            "kind": "agent", "agent": agent,
            "outcome": "succeeded" if succeeded else "failed",
            "summary": "Finished." if succeeded else "Stopped before finishing.",
        }
    if event_type == "agent_work_started":
        return {
            "kind": "agent",
            "agent": agent,
            "outcome": "started",
            "summary": "Working on its assigned requirement.",
        }
    if event_type == "semantic_decision":
        decision = str(data.get("decision") or "hold")
        summary = {
            "proceed": "Satisfied its assigned requirement.",
            "hold": "Found partial support; this path is on hold.",
            "reject": "Could not satisfy its assigned requirement; this path was rejected.",
        }.get(decision, "Completed its semantic assessment.")
        return {
            "kind": "decision",
            "agent": agent,
            "outcome": "succeeded" if decision == "proceed" else "failed",
            "summary": summary,
        }
    return None


def _present_consent_in_ui(mesh, emit):
    """Show consent links here rather than opening a browser on the server.

    The default flow assumes a terminal, which is nobody's session when the
    agent runs behind the desk: the link would be printed where no one is
    looking and a browser would open on whatever host this happens to be.
    """
    from jarviscore.auth import HostedFlowHandler

    async def present(auth_url, provider, label, connection_id, context):
        await emit("consent_required", {
            "provider": provider, "label": label, "auth_url": auth_url,
        })

    async def present_credentials(schema, provider, label, connection_id, state, context):
        await emit("credential_input_required", {
            "provider": provider, "label": label, "connection_id": connection_id,
            "state": state, "schema": schema.get("schema", schema),
        })

    for agent in mesh.agents:
        manager = getattr(agent, "_auth_manager", None) or getattr(agent, "auth_manager", None)
        if manager is not None:
            manager.flow_handler = HostedFlowHandler(present, credential_present=present_credentials)


async def run_configured(
    path, member, message, emit, execution_context=None, execution_mode="execute"
):
    from jarviscore.telemetry import TraceManager
    config = load_config(path)
    mesh = resolve(config.factory)()
    execution_context = dict(execution_context or {})
    identity = execution_context.get("workflow_id") or thread_id(config, member)
    step = execution_context.get("step_id") or f"task-{uuid.uuid4().hex[:12]}"
    context = execution_context | {"workflow_id": identity, "step_id": step}
    tracer = TraceManager(workflow_id=identity, step_id=step,
                          trace_dir=str(config.trace_dir)) if config.trace_dir else None
    await emit("status", {"message": f"Framework workflow: {identity} (step {step})."})
    loops = []
    activity_tasks = []
    observer = None
    try:
        await emit("status", {
            "message": "Connecting configured agents to durable workflow state."
        })
        await mesh.start()
        _present_consent_in_ui(mesh, emit)

        def activity_sink(event):
            public = public_activity(event)
            if public is not None:
                activity_tasks.append(asyncio.create_task(emit("activity", public)))

        appearances = getattr(config, "agents", {}) or {}

        def display_name(role):
            appearance = appearances.get(role)
            return getattr(appearance, "name", None) or role.replace("_", " ").title()

        for candidate in mesh.agents:
            # JarvisCore has no public live-activity hook yet
            candidate._trace_sink = lambda event, role=candidate.role: activity_sink({
                **event, "data": {**(event.get("data") or {}), "agent": display_name(role)},
            })
        overrides = {role: appearance.id for role, appearance in getattr(config, "agents", {}).items() if appearance.id}
        observer = PeerObserver(mesh, config.factory, emit, overrides).start()
        for agent in mesh.agents:
            run = getattr(agent, "run", None)
            if inspect.iscoroutinefunction(run):
                loops.append(asyncio.create_task(run()))
        if tracer:
            tracer.log_workflow_start(step_count=1)
        if member == "mesh":
            if execution_mode == "reconcile":
                if config.mesh_reconcile_handler is None:
                    raise ValueError("This mesh has no reconciliation handler configured.")
                workflow_id = context.get("mesh_workflow_id")
                result = await resolve(config.mesh_reconcile_handler)(
                    mesh, workflow_id, context
                )
            elif config.mesh_handler is None:
                raise ValueError("This mesh has no task handler configured.")
            else:
                result = await resolve(config.mesh_handler)(mesh, message, context)
        else:
            role, occurrence = member.rsplit(":", 1)
            agent = [candidate for candidate in mesh.agents if candidate.role == role][int(occurrence)]
            result = await agent.execute_task({"task": message, "context": context})
        await observer.flush()
        for candidate in mesh.agents:
            candidate._trace_sink = None
        if activity_tasks:
            await asyncio.gather(*activity_tasks)
        if isinstance(result, dict) and result.get("status") == "yield":
            metadata = result.get("yield_metadata") or {}
            if metadata.get("typed_outcome") == "WAITING_FOR_CONSENT":
                await emit("waiting", {
                    "provider": metadata["system"],
                    "connection_id": metadata["connection_id"],
                    "workflow_id": metadata["workflow_id"],
                    "step_id": metadata["step_id"],
                })
                return
            if metadata.get("typed_outcome") == "WAITING_FOR_APPROVAL":
                await emit("approval_required", {
                    "action_id": metadata["action_id"],
                    "action": metadata["action"],
                    "consequence": metadata["consequence"],
                })
                await emit("waiting", {
                    "provider": metadata.get("system") or "system",
                    "connection_id": metadata["action_id"],
                    "workflow_id": metadata["workflow_id"],
                    "step_id": metadata["step_id"],
                })
                return
        if not isinstance(result, dict) or result.get("status") != "success":
            if tracer:
                tracer.log_workflow_complete(status="failure", summary="Task did not complete.")
            answer = str(result.get("result_summary") or "").strip() if isinstance(result, dict) else ""
            if answer:
                # The agent's own account of an unfinished goal is what the person needs.
                await emit("result", {
                    "text": render_answer(answer, None),
                    "obligation_status": (
                        result["obligation_status"]
                        if result.get("obligation_status") in {"blocked", "incomplete"}
                        else "incomplete"
                    ),
                })
                return
            await emit("error", {"message": "This task stopped before it finished."})
            return
        output = result.get("output")
        raw_artifacts = result.get("artifacts", [])
        if not isinstance(raw_artifacts, list) or len(raw_artifacts) > 32:
            raise ValueError("Successful results may expose up to 32 artifacts.")
        artifacts = [
            ArtifactResource.model_validate(artifact).model_dump(exclude_none=True)
            for artifact in raw_artifacts
        ]
        public_result = {"text": render_answer(result.get("result_summary"), output)}
        if result.get("obligation_status") in {"satisfied", "blocked", "incomplete"}:
            public_result["obligation_status"] = result["obligation_status"]
        await emit("result", public_result)
        for structured_output in public_structured_outputs(output):
            await emit("structured_output", structured_output)
        for artifact in artifacts:
            await emit("artifact", artifact)
        tokens = result.get("tokens") or {}
        if tracer:
            if tokens.get("total") is not None:
                tracer.log_event("task_usage", {"tokens": tokens["total"]})
            tracer.log_workflow_complete(status="success", summary="Task completed.")
        reported = tokens.get("total", "unavailable")
        await emit("status", {"message": f"Framework task completed. Tokens reported: {reported}."})
    finally:
        for loop in loops:
            loop.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        try:
            if observer is not None:
                await observer.close()
        finally:
            try:
                await mesh.stop()
            except Exception:  # noqa: BLE001 - cleanup cannot invalidate persisted output
                # This worker process exits after one task. Cleanup cannot
                # retroactively invalidate an already persisted result.
                pass
