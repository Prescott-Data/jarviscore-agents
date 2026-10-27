"""The local desk HTTP/SSE application; no provider imports in this process."""

import asyncio
import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .framework import framework_info
from .models import TERMINAL, ApprovalDecision, ResumeRequest, RoomMessage, RoomPress, RunRequest
from .observability import Inspector, read_metrics
from .registry import AdapterRegistry
from .rooms import PROPOSAL_ID, RoomHost, room_files_dir, safe_join
from .runtime import RunManager
from .security import LocalOnlyMiddleware
from .store import BusyAgent, RunStore, desk_home

APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
#: Room files a browser may show in place: none of them can run script.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}
#: Shown in place as plain text, never as markup.
PLAIN_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json"}
# Chrome's PDF viewer is an embedded object with inline styles in a page of its own:
# the PDF's response must allow those (and being framed by the Desk) to be shown.
INLINE_CSP = "default-src 'none'; style-src 'unsafe-inline'; object-src 'self'; frame-ancestors 'self'"
PLAIN_CSP = "default-src 'none'; sandbox; frame-ancestors 'self'"
ATTACHMENT_CSP = "default-src 'none'; sandbox; frame-ancestors 'none'"


def content_disposition(kind, path):
    name = PurePosixPath(path).name
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "file"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


_CONNECTED = """<!doctype html><html><head><meta charset="utf-8"><title>Connected</title>
<style>body{margin:0;display:grid;place-items:center;height:100vh;font:15px/1.5 Inter,-apple-system,
BlinkMacSystemFont,sans-serif;color:#1d2433;background:#f6f8fb}div{text-align:center}
b{display:block;font-size:20px;margin:10px 0 4px}small{color:#64748b}
i{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:50%;font-style:normal;
font-size:22px;color:#fff;background:#2f7f74}.failed i{background:#b42318}</style></head>
<body class="__STATE__"><div><i>__ICON__</i><b>__MESSAGE__</b>
<small>You can close this window; the work goes on.</small></div>
<script>setTimeout(function(){window.close()},1600)</script></body></html>"""

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Desk not built</title>
<body style="font:16px/1.5 system-ui;max-width:640px;margin:64px auto;padding:0 24px">
<h1>The Desk's browser app is not built yet</h1>
<p>Build it once (Node.js 20 or later), then reload this page:</p>
<pre style="background:#f3f4f6;padding:12px 16px;border-radius:8px">cd ui/frontend
npm ci
npm run build</pre></body>"""


def create_app(*, registry=None, home=None, static_dir=None, load_entry_points=False, config=None,
               room_config=None, room_host=None):
    home = Path(home).expanduser().resolve() if home is not None else desk_home()
    static_dir = Path(static_dir) if static_dir else Path(__file__).resolve().parents[1] / "static"
    if registry is None:
        registry = AdapterRegistry()
        if load_entry_points:
            registry.load_installed()
    inspector = Inspector(config.trace_dir if config else None)

    @asynccontextmanager
    async def lifespan(app):
        store = RunStore(home)
        host = room_host or (RoomHost(room_config, home) if room_config else None)
        try:
            manager = RunManager(store, registry)
            manager.recover(store.recover())
            app.state.manager = manager
            app.state.room = host
            if host is not None and room_host is None:
                await host.start()
            yield
        finally:
            if host is not None and room_host is None:
                await host.close()
            if hasattr(app.state, "manager"):
                await app.state.manager.close()
            store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnlyMiddleware)

    @app.middleware("http")
    async def safe_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
        # Only a room file sets its own (narrower) policy; everything else gets the app's.
        response.headers.setdefault("Content-Security-Policy", APP_CSP)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default response includes raw request input.
        return JSONResponse({"detail": "Invalid request body or parameters."}, 422)

    def manager(request):
        return request.app.state.manager

    def get_run(request, run_id):
        run = manager(request).store.get(run_id)
        if run is None:
            raise HTTPException(404, "Run not found.")
        return run

    @app.get("/api/health")
    async def health():
        return {"status": "ok", **await asyncio.to_thread(framework_info)}

    @app.get("/api/agents")
    async def agents():
        return registry.metadata()

    @app.get("/api/workspace")
    async def workspace():
        return {"name": config.name if config else "JarvisCore Agents",
                "configured": config is not None,
                "room": bool(config and config.room_factory), "inspection": inspector.root is not None,
                "metrics_url": config.metrics_url if config else None}

    def room(request):
        host = getattr(request.app.state, "room", None)
        if host is None:
            raise HTTPException(404, "This desk has no room.")
        return host

    def member(host, person):
        try:
            return host.person(person)
        except KeyError:
            raise HTTPException(403, "Only the room's members can act in it.") from None

    @app.get("/api/room")
    async def room_view(request: Request, person: str = ""):
        host = room(request)
        if not person and host.people:
            person = host.people[0]["id"]
        if person:
            member(host, person)
        return host.view(person)

    @app.get("/api/room/stream")
    async def room_stream(request: Request, person: str):
        host = room(request)
        member(host, person)

        async def changes():
            seen = -1
            while True:
                if host.revision != seen:
                    seen = host.revision
                    yield f"data: {json.dumps(host.view(person), ensure_ascii=False)}\n\n"
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(host.changed.wait(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"

        return StreamingResponse(changes(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
        })

    @app.get("/api/room/raw")
    async def room_raw(request: Request, person: str, path: str, proposal: str = ""):
        host = room(request)
        member(host, person)
        root = room_files_dir(host.home)
        if proposal:
            found = next((p for p in host.state.get("proposals", []) if p.get("id") == proposal), None)
            if found is None or not PROPOSAL_ID.match(proposal):
                raise HTTPException(404, "No such proposal.")
            if found.get("held_for") and found["held_for"] != person:
                raise HTTPException(403, "That proposal is not shared with you.")
            directory = root / proposal
        else:
            directory = root / f"v{int(host.state.get('version', 0))}"
        target = safe_join(directory, path)
        if target is None:
            raise HTTPException(404, "File not found.")
        target = target.resolve()
        if not target.is_relative_to(directory.resolve()) or not target.is_file():
            raise HTTPException(404, "File not found.")
        kind = mimetypes.guess_type(PurePosixPath(path).name)[0] or "application/octet-stream"
        if kind in INLINE_TYPES:
            disposition, policy = "inline", INLINE_CSP
        elif kind in PLAIN_TYPES:
            kind, disposition, policy = "text/plain; charset=utf-8", "inline", PLAIN_CSP
        else:
            # HTML, SVG and anything else that could run in the Desk's origin is only downloaded.
            disposition, policy = "attachment", ATTACHMENT_CSP
        return FileResponse(target, media_type=kind, headers={
            "Content-Disposition": content_disposition(disposition, path),
            "Content-Security-Policy": policy,
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        })

    @app.post("/api/room/messages", status_code=202)
    async def room_message(body: RoomMessage, request: Request):
        host = room(request)
        member(host, body.person)
        try:
            return {"message_id": await host.say(body.person, body.text, body.thread)}
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None

    @app.post("/api/room/press", status_code=202)
    async def room_press(body: RoomPress, request: Request):
        host = room(request)
        member(host, body.person)
        try:
            await host.press(body.person, body.action, body.target, body.thread)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None
        return {"ok": True}

    @app.get("/api/inspect")
    async def inspect_workflows():
        return {"configured": inspector.root is not None,
                "workflows": await asyncio.to_thread(inspector.workflows)}

    @app.get("/api/metrics")
    async def metrics():
        metrics_url = config.metrics_url if config else None
        if metrics_url:
            return await read_metrics(metrics_url)
        return await asyncio.to_thread(inspector.metrics)

    @app.get("/api/inspect/{workflow_id}")
    async def inspect_events(workflow_id: str):
        try:
            return {"events": await asyncio.to_thread(inspector.events, workflow_id)}
        except KeyError:
            raise HTTPException(404, "Workflow not found in configured traces.") from None

    @app.get("/api/runs")
    async def runs(request: Request):
        return manager(request).store.list()

    @app.post("/api/runs", status_code=202)
    async def start(body: RunRequest, request: Request):
        adapter = registry.adapters.get(body.agent_id)
        if adapter is None:
            raise HTTPException(404, "Unknown agent.")
        operation = next((op for op in adapter.metadata.operations if op.id == body.operation), None)
        if operation is None:
            raise HTTPException(422, "Unknown operation.")
        if body.message is not None and not operation.allows_message:
            raise HTTPException(422, "This operation does not accept a message.")
        try:
            return manager(request).start(
                body.agent_id,
                body.operation,
                body.message,
                {"source_context": body.source_context} if body.source_context else {},
            )
        except BusyAgent:
            raise HTTPException(409, "This agent already has a running run.") from None

    @app.get("/api/runs/stream")
    async def run_updates(request: Request):
        raw = request.headers.get("last-event-id", "0")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 18:
            raise HTTPException(400, "Last-Event-ID must be a non-negative revision.")
        runtime = manager(request)

        async def changes():
            after, first = int(raw), True
            while not runtime.stopping:
                signal = runtime.updates
                revision = runtime.store.revision()
                if after > revision:
                    after = 0
                changed = runtime.store.changed_runs(after, revision)
                if changed or first:
                    yield f"id: {revision}\ndata: {json.dumps({'runs': changed}, ensure_ascii=False)}\n\n"
                after, first = revision, False
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(signal.wait(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"

        return StreamingResponse(changes(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
        })

    @app.get("/api/runs/{run_id}")
    async def run(run_id: str, request: Request):
        return get_run(request, run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request):
        get_run(request, run_id)
        return await manager(request).cancel(run_id)

    @app.post("/api/runs/{run_id}/reconcile", status_code=202)
    async def reconcile(run_id: str, request: Request):
        get_run(request, run_id)
        try:
            return manager(request).reconcile(run_id)
        except BusyAgent:
            raise HTTPException(409, "This agent already has a running run.") from None
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/runs/{run_id}/resume")
    async def resume(run_id: str, body: ResumeRequest, request: Request):
        get_run(request, run_id)
        try:
            return manager(request).resume(run_id, body.connection_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/runs/{run_id}/credentials")
    async def capture_credentials(run_id: str, request: Request):
        run = get_run(request, run_id)
        if run["status"] != "waiting":
            raise HTTPException(409, "This run is not waiting for credentials.")
        capture = next(
            (event for event in reversed(run["events"])
             if event["type"] == "credential_input_required"),
            None,
        )
        waiting = next(
            (event for event in reversed(run["events"]) if event["type"] == "waiting"),
            None,
        )
        if capture is None or waiting is None:
            raise HTTPException(409, "This run has no credential request.")
        try:
            body = await request.json()
            credentials = body["credentials"]
            if not isinstance(credentials, dict):
                raise ValueError
            from jsonschema import Draft202012Validator
            schema = dict(capture["data"]["schema"])
            schema.setdefault("additionalProperties", False)
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(credentials)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(422, "Credential fields do not match the requested schema.") from None
        except Exception as exc:
            from jsonschema import SchemaError, ValidationError
            if isinstance(exc, (SchemaError, ValidationError)):
                raise HTTPException(422, "Credential fields do not match the requested schema.") from None
            raise

        import httpx
        gateway = os.environ.get("NEXUS_GATEWAY_URL")
        if not gateway:
            raise HTTPException(503, "Credential storage is unavailable.")
        async with httpx.AsyncClient(base_url=gateway, timeout=30) as client:
            response = await client.post(
                "/v1/capture-credential",
                json={"state": capture["data"]["state"], "credentials": credentials},
            )
        if response.status_code != 200:
            # Never echo the provider response: validation services sometimes
            # include submitted values in their error body.
            raise HTTPException(422, "The provider rejected those credentials.")
        connection_id = response.json().get("connection_id")
        if not connection_id or connection_id != waiting["data"]["connection_id"]:
            raise HTTPException(502, "Nexus returned an unexpected connection.")
        return manager(request).resume(run_id, connection_id)

    @app.post("/api/runs/{run_id}/approval")
    async def approve(run_id: str, body: ApprovalDecision, request: Request):
        get_run(request, run_id)
        try:
            return await manager(request).approve(run_id, body.action_id, body.approved)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request):
        get_run(request, run_id)
        cursor = request.headers.get("last-event-id", "0")
        if not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 18:
            raise HTTPException(400, "Last-Event-ID must be a non-negative sequence number.")
        after = int(cursor)
        runtime = manager(request)

        async def stream():
            nonlocal after
            signal = runtime.signal(run_id)
            while True:
                # Clear BEFORE querying durable events; never lose an emission between reads.
                signal.clear()
                batch = runtime.store.events(run_id, after)
                terminal = runtime.store.get(run_id)["status"] in TERMINAL
                for event in batch:
                    after = event["seq"]
                    yield f"id: {after}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if terminal:
                    return
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(signal.wait(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform",
        })

    @app.get("/connected", response_class=HTMLResponse)
    async def connected(status: str = "", provider: str = ""):
        # Where someone lands after connecting an account in its provider's consent page.
        ok = status in ("", "success")
        name = re.sub(r"[^A-Za-z0-9 _-]", "", provider.replace("-", " ").replace("_", " ")).title()
        message = (f"{name or 'Your account'} is connected." if ok
                   else "The connection was not completed.")
        return HTMLResponse(_CONNECTED.replace("__MESSAGE__", message)
                            .replace("__STATE__", "ok" if ok else "failed")
                            .replace("__ICON__", "✓" if ok else "✕"))

    @app.get("/{asset_path:path}")
    async def asset(asset_path: str):
        if asset_path == "api" or asset_path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found.")
        asset_path = asset_path or "index.html"
        # Accept /app.js and /static/app.js; never expose sibling sources or dotfiles.
        if asset_path.startswith("static/"):
            asset_path = asset_path[len("static/"):]
        relative = Path(asset_path)
        root = static_dir.resolve()
        if relative.is_absolute() or any(part.startswith(".") for part in relative.parts):
            raise HTTPException(404, "Asset not found.")
        target = (root / relative).resolve()
        allowed = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp",
                   ".ico", ".woff", ".woff2", ".ttf"}
        if not target.is_relative_to(root) or target.suffix not in allowed or not target.is_file():
            if relative.name == "index.html" and not (root / "index.html").is_file():
                # A fresh clone: the browser app has not been built yet.
                return HTMLResponse(_NOT_BUILT, status_code=503)
            raise HTTPException(404, "Frontend asset not available.")
        return FileResponse(target)

    return app
