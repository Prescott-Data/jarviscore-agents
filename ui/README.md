# The JarvisCore Desk

A local web app for running and watching JarvisCore agents: send a task to one agent or
the whole Mesh, follow its live activity, read results and artifacts, approve what waits
for a person, and reopen past tasks. For a multiplayer blueprint it becomes a **room**:
people pick who they are, talk to the team's agents in threads, review proposals as diffs
or formatted previews, open files (PDFs included) and confirm decisions.

It runs on your machine only: the server refuses non-loopback and cross-origin requests,
and credentials stay in the env file you pass it, never in the browser.

## Run it

Python 3.12, Node.js 20 or later, and Redis. From the repository root:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r ui/requirements.txt -e gtm       # or any blueprint: -e multiplayer, ...
(cd ui/frontend && npm ci && npm run build)      # once, and after frontend changes
cd ui && python -m server --config gtm.desk.yaml --env-file ../.env
```

Open http://127.0.0.1:8765. Each blueprint has its config here:
[gtm](gtm.desk.yaml), [personal-intelligence](personal-intelligence.desk.yaml),
[software-reliability](software-reliability.desk.yaml) and [multiplayer](multiplayer.desk.yaml).

History is kept under `~/.jarviscore/desk` (set `JARVISCORE_DESK_HOME` to change it).

## Connect Your Own Mesh

Install your agent project in the desk's Python environment, then point a local YAML file at
a synchronous `build_mesh()` factory returning an unstarted JarvisCore `Mesh`. Keep factory
construction free of network calls; the worker calls `mesh.start()` when a task arrives.
The sidebar discovers every instance, including multiple instances of the same role.

```yaml
name: My Agent Workspace
factory: my_agents:build_mesh
blueprint: my-project
mesh_handler: my_agents:submit_task
working_dir: ./runtime
agents:
    researcher:
        name: Researcher
        color: "#397b72"
        shape: circle
```

```bash
.venv/bin/python -m pip install -e /path/to/your-agent-project
.venv/bin/python -m server --config /path/to/desk.yaml --port 8765
```

Individual tasks call the selected instance's `execute_task()` with the framework task envelope.
The optional asynchronous `submit_task(mesh, message, context)` is your mesh-wide task entry:
reuse your project's JarvisCore workflow/goal handling there and return its result envelope.
There is no UI router agent and no automatic broadcast to every peer. Without this handler the
Mesh item shows its members, but its composer is disabled. Each task gets a started mesh and
peer receive loops where supplied by the agents, then shuts down cleanly. This is task execution,
not a persistent conversational session or a substitute for application memory.

API callers may include structured trigger data alongside the task text:

```json
{
    "agent_id": "gtm-mesh",
    "operation": "task",
    "message": "Accelerate this lead.",
    "source_context": {"lead": {"name": "Example Lead", "email": "lead@example.com"}}
}
```

The Desk redacts known secrets, persists this data for resume, and passes it to the Mesh under
the `source_context` key. Callers cannot use it to set framework authority such as effects,
systems, execution contracts, workflow IDs, or step IDs.

## User-visible artifacts

An agent or Mesh handler can return typed work products alongside its prose answer. Keep the
programmatic `output` unchanged for downstream agents and add an `artifacts` list to the success
envelope:

```json
{
    "status": "success",
    "result_summary": "The pitch deck and follow-up draft are ready.",
    "output": {"...": "the normal structured agent result"},
    "artifacts": [
        {
            "schema_version": "1",
            "id": "provider-resource-id",
            "artifact_type": "presentation",
            "title": "Acme pitch deck",
            "url": "https://provider.example/presentation/123",
            "provider": "example_workspace",
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "description": "Account-specific sales collateral.",
            "metadata": {"Status": "Created"}
        },
        {
            "schema_version": "1",
            "id": "draft-id",
            "artifact_type": "email",
            "title": "Acme follow-up",
            "provider": "example_mail",
            "metadata": {"To": "buyer@example.com", "Status": "Draft"},
            "preview": {"kind": "text", "text": "The exact authored email body."}
        }
    ]
}
```

Supported `artifact_type` values are `document`, `presentation`, `spreadsheet`, `pdf`, `email`,
`image`, `audio`, `video`, `archive` and `file`. Preview kinds are `text`, `image` and `pdf`.
URLs must be HTTPS. Text previews are rendered as text rather than HTML; media previews use a
sandboxed viewer and retain an explicit provider-open action. The Desk validates, redacts,
persists and replays each artifact as its own public event. It never guesses artifacts from prose
or arbitrary URL-shaped fields. Adapters should emit this list only from an authoritative,
provider-confirmed result.

The [configuration template](desk.example.yaml) includes per-role names, colors and shapes
(`circle`, `rounded`, `diamond`, `hexagon`). Omitted colors cycle through a varied palette;
explicit colors are preserved. Individual agents and Mesh appear as equal rows in a flat
sidebar; Mesh uses a composite member avatar, not an expandable folder. The header uses the
official JarvisCore wordmark followed by Agents. UI text uses the system's Helvetica Neue
(generic sans-serif fallback where unavailable); no proprietary font files are bundled.
The default agent mark in [brand assets](frontend/public/brand/)
is derived from the JarvisCore monogram; the original is included too. Configuration is trusted
local code, not an HTTP upload. Credentials stay in the launcher environment or explicit env file.

## Tasks, Inspect and Telemetry

The **Task history** clock in the main header opens saved submissions and their result/activity
transcripts for the selected agent or Mesh. History is not listed in the sidebar, and reopening
a task does not run it again. It is separate from agent memory and the framework's shared work ledger.
Tasks submitted through this desk's API appear in every connected browser automatically.
A desk-wide SSE stream replays persisted changes after reconnecting, without rerunning agents.
Updates preserve selected history and unsent drafts; a new task opens automatically only when
its agent is selected and the pane has neither a selected task nor a draft. Standalone CLI
runs and tests using another history directory are not imported into desk task history.
The selected agent, task and action are restored from the URL fragment after a browser reload;
task text and credentials are not placed in the URL. Stale IDs are checked against the current
roster/history before display. A neutral loading placeholder is used until the identity is known.
**Inspect** reads actual JSONL records using the same reader as `jarviscore inspect`, defaulting
to `working_dir/traces`. Set `trace_dir` to inspect another local trace directory. The browser
shows event types, step identifiers and numeric telemetry; prompts, credentials and raw model
reasoning are intentionally not exposed. Refresh inspection to read new records.

Set `metrics_url: http://127.0.0.1:9090/metrics` for an existing JarvisCore Prometheus endpoint.
The **Telemetry** tab fetches actual `jarviscore_*` samples; it does not start a metrics server or
invent values when one is unavailable. Enable the framework's Prometheus extra in the agent
runtime as needed. Persistent cross-process aggregation belongs in your Prometheus deployment.

Validation:

```bash
.venv/bin/python -m pip install "ruff>=0.15"
.venv/bin/python -m ruff check server tests
.venv/bin/python -m pytest tests -q
npm --prefix frontend run lint
npm --prefix frontend exec -- playwright install chromium --only-shell
npm --prefix frontend test
```

CI runs the same gates. The frontend lints with type-aware `typescript-eslint`
plus the React hooks rules, so hook and promise mistakes fail the build rather than
reaching a browser. Colors, radii, layout sizes and z-indexes are CSS custom properties
declared once in [style.css](frontend/src/style.css); rules are not restated per selector.

The browser suite starts its own server on port 8766 with isolated temporary history and a
test-only offline validation adapter. It tests desktop/mobile layouts, cross-client updates,
and reconnect replay without paid model calls. These tests do not create runs in the live desk.

## Develop

```bash
pip install "ruff>=0.15"
ruff check server tests
python -m pytest tests -q
npm --prefix frontend run lint
npm --prefix frontend exec -- playwright install chromium --only-shell
npm --prefix frontend test
```

CI runs the same checks. The browser suite starts its own server on port 8766 with a
temporary history and an offline adapter, so it makes no model calls and leaves no runs
in your Desk.

To work on JarvisCore itself alongside the Desk, install your checkout editable
(`pip install -e /path/to/jarviscore-framework`) and pass `--framework-source` with the
same path. `/api/health` reports the framework version and where it was imported from.
