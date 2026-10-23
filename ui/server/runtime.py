"""Run ownership, persistence-before-delivery and cooperative cancellation."""

import asyncio
import inspect
import json
import logging

from .models import TERMINAL, PublicRunError, clean_event
from .security import Redactor

logger = logging.getLogger(__name__)


class RunManager:
    def __init__(self, store, registry):
        self.store, self.registry = store, registry
        self.redactor = Redactor()
        self.tasks: dict[str, asyncio.Task] = {}
        self.signals: dict[str, asyncio.Event] = {}
        self.stopping = False
        self.updates = asyncio.Event()

    def start(self, agent_id, operation, message, context=None):
        public_context = json.loads(
            self.redactor.text(json.dumps(context or {}, ensure_ascii=False))
        )
        public_context["owner_id"] = self.store.owner_id
        run = self.store.create(
            agent_id,
            operation,
            self.redactor.text(message) if message is not None else None,
            public_context,
        )
        run_id = run["id"]
        self.signals[run_id] = asyncio.Event()
        self.notify_updates()
        task = asyncio.create_task(self._execute(
            run_id, agent_id, operation, message, public_context | {"run_id": run_id}
        ))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return run

    async def _execute(
        self, run_id, agent_id, operation, message, run_context=None,
        adapter_method="execute",
    ):
        had_error = False
        waiting = False

        async def emit(kind, data):
            nonlocal had_error, waiting
            public = clean_event(kind, data, self.redactor.text)
            if kind == "peer_message":
                identities = [public["recipient_id"], *(item["sender_id"] for item in public["messages"])]
                if any(identity not in self.registry.adapters for identity in identities):
                    raise ValueError("Peer event refers to an unregistered agent.")
            self.store.append(run_id, kind, public)
            self.notify_updates()
            had_error |= kind == "error"
            waiting |= kind == "waiting"
            self.signal(run_id).set()
            await asyncio.sleep(0)  # Let cancellation/subscribers run between emissions.

        try:
            adapter = self.registry.adapters[agent_id]
            execute = getattr(adapter, adapter_method)
            if "run_context" in inspect.signature(execute).parameters:
                await execute(operation, message, emit, run_context=run_context)
            else:
                await execute(operation, message, emit)
        except asyncio.CancelledError:
            if not self.stopping:
                self.store.finish(
                    run_id,
                    "cancelled",
                    "Run cancelled; its worker has stopped.",
                )
        except Exception as exc:  # noqa: BLE001 - adapter isolation: any adapter failure is a failed run, never a dead desk.
            logger.exception("Adapter execution failed for run %s", run_id)
            public = str(exc) if isinstance(exc, PublicRunError) else (
                "Run failed. Provider and adapter logs are not exposed by the desk."
            )
            # The worker's own error is more specific than the adapter's exit-code failure.
            self.store.finish(run_id, "failed", None if had_error else self.redactor.text(public))
        else:
            if waiting:
                self.store.pause(run_id)
            else:
                self.store.finish(run_id, "failed" if had_error else "completed")
        finally:
            self.signal(run_id).set()
            self.notify_updates()

    def notify_updates(self):
        signal = self.updates
        self.updates = asyncio.Event()
        signal.set()

    def signal(self, run_id):
        return self.signals.setdefault(run_id, asyncio.Event())

    async def cancel(self, run_id):
        run = self.store.get(run_id)
        adapter = self.registry.adapters[run["agent_id"]]
        cancel_durable = getattr(adapter, "cancel_durable_run", None)
        if callable(cancel_durable):
            await cancel_durable(run_id)
        task = self.tasks.get(run_id)
        if task is not None and not task.done():
            # Repeated/concurrent cancel requests must not interrupt worker cleanup.
            if not task.cancelling():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Covers cancellation before the task's first instruction executed.
        run = self.store.get(run_id)
        if run["status"] not in TERMINAL:
            self.store.finish(run_id, "cancelled", "Run cancelled before execution.")
            self.signal(run_id).set()
        self.notify_updates()
        return self.store.get(run_id)

    def reconcile(self, run_id):
        run = self.store.get(run_id)
        if run is None:
            raise RuntimeError("Run not found.")
        adapter = self.registry.adapters[run["agent_id"]]
        if not callable(getattr(adapter, "reconcile", None)):
            raise RuntimeError("This agent does not support goal reconciliation.")
        reopened = self.store.reopen(run_id)
        context = dict(reopened.get("context") or {}) | {"run_id": run_id}
        task = asyncio.create_task(self._execute(
            run_id, reopened["agent_id"], reopened["operation"], reopened["message"],
            context, adapter_method="reconcile",
        ))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        self.notify_updates()
        return self.store.get(run_id)

    def recover(self, runs):
        """Reattach observers to durable workflows left running by a restart."""
        for run in runs:
            run_id = run["id"]
            adapter = self.registry.adapters[run["agent_id"]]
            if not callable(getattr(adapter, "workflow_id_for_run", None)):
                self.store.finish(
                    run_id,
                    "interrupted",
                    "Server restarted before this non-durable run finished.",
                )
                continue
            context = dict(run.get("context") or {}) | {"run_id": run_id}
            self.store.append(
                run_id,
                "status",
                {"message": "Server restarted. Resuming the durable workflow."},
            )
            task = asyncio.create_task(self._execute(
                run_id,
                run["agent_id"],
                run["operation"],
                run["message"],
                context,
            ))
            self.tasks[run_id] = task
            task.add_done_callback(
                lambda _, rid=run_id: self.tasks.pop(rid, None)
            )

    def resume(self, run_id, connection_id):
        resumed = self.store.resume(run_id, connection_id)
        context = dict(resumed.get("context") or {}) | dict(resumed["resume"])
        context["run_id"] = run_id
        context["_resume"] = True
        context["system"] = context["provider"]
        self.signals.setdefault(run_id, asyncio.Event()).set()
        self.notify_updates()
        task = asyncio.create_task(self._execute(
            run_id,
            resumed["agent_id"],
            resumed["operation"],
            resumed["message"],
            context,
        ))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return self.store.get(run_id)

    async def approve(self, run_id, action_id, approved):
        resumed = self.store.resume(
            run_id, action_id,
            "Approved. Resuming the task." if approved
            else "Declined. The task continues without that action.",
            decision={"action_id": action_id, "approved": bool(approved)},
        )
        context = dict(resumed["resume"])
        context.update({
            "run_id": run_id, "_resume": True, "system": context["provider"],
            "hitl_decision": {
                "action_id": action_id,
                "decision": "approve" if approved else "reject",
                "resolved_by": str((resumed.get("context") or {}).get("owner_id") or ""),
            },
        })
        task = asyncio.create_task(self._execute(
            run_id, resumed["agent_id"], resumed["operation"], resumed["message"], context,
        ))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        self.notify_updates()
        return self.store.get(run_id)

    async def close(self):
        self.stopping = True
        self.notify_updates()
        tasks = list(self.tasks.items())
        for run_id, _ in tasks:
            run = self.store.get(run_id)
            adapter = (
                self.registry.adapters[run["agent_id"]]
                if run else None
            )
            durable = callable(getattr(adapter, "workflow_id_for_run", None))
            if run and run["status"] == "running" and durable:
                self.store.append(
                    run_id,
                    "status",
                    {"message": "Server stopping. Durable workflow remains active."},
                )
        for _, task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for run_id, _ in tasks:
            run = self.store.get(run_id)
            adapter = (
                self.registry.adapters[run["agent_id"]]
                if run else None
            )
            durable = callable(getattr(adapter, "workflow_id_for_run", None))
            if run and run["status"] == "running" and not durable:
                self.store.finish(
                    run_id,
                    "interrupted",
                    "Server stopped before this non-durable run finished.",
                )
            self.signal(run_id).set()
