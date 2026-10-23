"""Observe delivery on local PeerClients; preserve the framework's routing and queues."""

import asyncio
import time
from contextvars import ContextVar

from .config import public_agent_id
from .presentation import render_output


def public_message(message):
    return public_payload(message.data, message.type.value)


def public_payload(payload, kind):
    if isinstance(payload, str):
        return render_output(payload)
    if not isinstance(payload, dict):
        return "Structured peer message received."
    if kind == "response" and str(payload.get("status") or "success").lower() not in {
        "success", "completed", "complete", "waiting", "yield", "hitl", "blocked",
    }:
        # A failure's error is the runtime's account, not something the peer said.
        return "Stopped before finishing."
    fields = {
        "request": ("query", "task"),
        "response": ("result_summary", "output", "result"),
        "notify": ("message", "text"),
    }.get(kind, ())
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return render_output(value)
        if isinstance(value, dict | list) and value:
            return render_output(value)
    return "Structured peer message received."


class PeerObserver:
    def __init__(self, mesh, factory, emit, id_overrides=None):
        self.mesh, self.emit = mesh, emit
        self.identities = {}
        counts = {}
        for agent in mesh.agents:
            count = counts.get(agent.role, 0)
            counts[agent.role] = count + 1
            override = (id_overrides or {}).get(agent.role)
            self.identities[agent.agent_id] = override or public_agent_id(factory, agent.role, count)
        self.queue = asyncio.Queue(maxsize=1024)
        self.originals = []
        self.executors = []
        self.current_agent = ContextVar("desk_peer_agent", default=None)
        self.dropped = 0
        self.recent = {}

    def start(self):
        self.loop = asyncio.get_running_loop()
        self.publisher = asyncio.create_task(self.publish())
        for agent in self.mesh.agents:
            original_execute = agent.execute_task
            self.executors.append((agent, original_execute))
            agent.execute_task = self.execution(original_execute, self.identities[agent.agent_id])
            peers = getattr(agent, "peers", None)
            if peers is None:
                continue
            original = peers._deliver_message
            self.originals.append((peers, original))
            peers._deliver_message = self.receiver(original, self.identities[agent.agent_id])
        return self

    def execution(self, original, recipient):
        async def execute(task):
            sender = self.current_agent.get()
            delegated = sender is not None and sender != recipient
            if delegated:
                self.record({"recipient_id": recipient, "messages": [
                    {"sender_id": sender, "text": public_payload(task, "request")},
                ]})
            token = self.current_agent.set(recipient)
            try:
                result = await original(task)
                if delegated:
                    self.record({"recipient_id": sender, "messages": [
                        {"sender_id": recipient, "text": public_payload(result, "response")},
                    ]})
                return result
            finally:
                self.current_agent.reset(token)
        return execute

    def receiver(self, original, recipient):
        async def receive(message):
            await original(message)
            sender = self.identities.get(message.sender)
            if sender is not None:
                event = {"recipient_id": recipient, "messages": [
                    {"sender_id": sender, "text": public_message(message)},
                ]}
                self.loop.call_soon_threadsafe(self.record, event)
        return receive

    def record(self, event):
        fingerprint = (
            event.get("recipient_id"),
            tuple(
                (message.get("sender_id"), message.get("text"))
                for message in event.get("messages", [])
            ),
        )
        now = time.monotonic()
        if now - self.recent.get(fingerprint, float("-inf")) < 2:
            return
        self.recent[fingerprint] = now
        if len(self.recent) > 256:
            self.recent = {
                key: seen for key, seen in self.recent.items() if now - seen < 2
            }
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1

    async def publish(self):
        while True:
            event = await self.queue.get()
            try:
                if event is None:
                    return
                await self.emit("peer_message", event)
            finally:
                self.queue.task_done()

    async def flush(self):
        await asyncio.sleep(0)
        drain = asyncio.create_task(self.queue.join())
        try:
            await asyncio.wait((drain, self.publisher), return_when=asyncio.FIRST_COMPLETED)
            if self.publisher.done():
                await self.publisher
            await drain
        finally:
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)

    async def close(self):
        for peers, original in self.originals:
            peers._deliver_message = original
        for agent, original in self.executors:
            agent.execute_task = original
        await asyncio.sleep(0)
        put = asyncio.create_task(self.queue.put(None))
        try:
            await asyncio.wait((put, self.publisher), return_when=asyncio.FIRST_COMPLETED)
            if self.publisher.done():
                await self.publisher
            else:
                await put
                await self.publisher
            if self.dropped:
                await self.emit("status", {
                    "message": f"Peer activity buffer full: {self.dropped} events were not recorded.",
                })
        finally:
            put.cancel()
            self.publisher.cancel()
            await asyncio.gather(put, self.publisher, return_exceptions=True)
