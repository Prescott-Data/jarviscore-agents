"""Cancellable isolated-worker adapter shared by configured desks."""

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import get_args

from ..models import Emit, EventType, PublicRunError
from ..store import desk_home

_WORKER_EVENT_KINDS = frozenset(get_args(EventType))


class ProcessAdapter:
    worker_module = "server.configured_worker"
    timeout_seconds = None

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home is not None else desk_home()

    def working_directory(self):
        return self.home / "runtime"

    async def execute_worker(self, arguments: list[str], emit: Emit, initial=None) -> None:
        working = self.working_directory()
        working.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        env["PYTHON_DOTENV_DISABLED"] = "1"
        env["JARVISCORE_DESK_HOME"] = str(self.home)
        logs = self.home / "logs" / "workers"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        stderr = os.open(
            logs / f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{id(arguments)}.log",
            os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600,
        )
        creation = asyncio.create_task(asyncio.create_subprocess_exec(
            sys.executable, "-m", self.worker_module, *arguments,
            cwd=working, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=stderr,
            start_new_session=True, limit=1048576,
        ))
        process = None
        try:
            process = await asyncio.shield(creation)
            if initial is not None:
                process.stdin.write((json.dumps(initial) + "\n").encode("utf-8"))
                await process.stdin.drain()
            await emit("status", {"message": "Isolated agent runtime ready."})
            async def relay():
                while line := await process.stdout.readline():
                    try:
                        frame = json.loads(line)
                        kind, data = frame["type"], frame["data"]
                        if set(frame) != {"type", "data"} or kind not in _WORKER_EVENT_KINDS:
                            raise ValueError("Invalid frame")
                    except (ValueError, TypeError, KeyError):
                        raise PublicRunError("The agent worker returned an invalid event.") from None
                    await emit(kind, data)
                    process.stdin.write(b"ack\n")
                    await process.stdin.drain()
                if await process.wait() != 0:
                    raise PublicRunError(
                        "The agent worker failed. Check its installed dependencies and "
                        "explicit launcher configuration; raw logs are not exposed."
                    )
            if self.timeout_seconds is None:
                await relay()
            else:
                async with asyncio.timeout(self.timeout_seconds):
                    await relay()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise PublicRunError("The configured worker observation limit was reached.") from None
        finally:
            if process is None:
                process = await creation
            os.close(stderr)
            await self._stop(process)

    async def _cancel_workflow(self, workflow_id: str) -> None:
        def cancel() -> None:
            from jarviscore.config import Settings
            from jarviscore.storage import RedisContextStore

            store = RedisContextStore(Settings())
            if store.enabled:
                store.cancel_workflow(workflow_id, reason="Desk run cancelled")

        await asyncio.to_thread(cancel)

    async def cancel_durable_run(self, run_id: str) -> None:
        """Explicit user cancellation owns the durable workflow transition."""
        workflow_id_for_run = getattr(self, "workflow_id_for_run", None)
        if callable(workflow_id_for_run):
            workflow_id = workflow_id_for_run(run_id)
            if workflow_id:
                await self._cancel_workflow(workflow_id)

    @staticmethod
    async def _stop(process):
        if process.returncode is not None:
            await process.wait()
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except PermissionError:
            if process.returncode is None:
                process.terminate()
        except ProcessLookupError:
            pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                pass
        try:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
        except PermissionError:
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
