"""Long-lived worker for a Desk room: runs a JarvisCore RoomConversation.

The Desk server never imports the framework; this process does. It reads
commands as JSON lines on stdin and writes frames as JSON lines on stdout:

  in:  {"op": "message", "person", "text", "message_id", "thread", "addressed"}
       {"op": "press", "person", "action", "target", "thread"}
  out: {"type": "ready" | "post" | "room" | "error", "data": {...}}

Who a person is comes from the server, which only accepts the room's members.
"""

import asyncio
import itertools
import json
import logging
import mimetypes
import os
import shutil
import sys
import time

from .config import load_config, resolve
from .rooms import PROPOSAL_ID, room_files_dir, safe_join
from .store import desk_home

log = logging.getLogger("desk.room")


def emit(kind, data):
    sys.stdout.write(json.dumps({"type": kind, "data": data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def make_surface():
    from jarviscore.room import ChatSurface

    class DeskSurface(ChatSurface):
        """The Desk's room page: every post goes to the browser, private ones to one person."""

        key = "desk"

        def __init__(self):
            self._ids = itertools.count(1)

        def _post(self, thread, kind, *, to=None, **fields):
            post_id = f"agent-{next(self._ids)}-{int(time.time() * 1000)}"
            emit("post", {"id": post_id, "thread": thread or post_id, "kind": kind,
                          "author": "agent", "to": to.id if to else "", "at": time.time(),
                          **fields})
            return post_id

        async def say(self, thread, text, *, detail="", code="", to=None):
            return self._post(thread, "say", to=to, text=text, detail=detail, code=code)

        async def notice(self, thread, text, *, to):
            return self._post(thread, "notice", to=to, text=text)

        async def show_proposal(self, thread, text, diff, proposal_id, *, to=None, held=False):
            return self._post(thread, "proposal", to=to, text=text, code=diff,
                              proposal=proposal_id, held=held)

        async def confirm(self, thread, decision, *, to):
            return self._post(thread, "confirm", to=to, text=decision.get("summary", ""),
                              decision=decision.get("id", ""))

    return DeskSurface()


#: The new text of a proposal's file is sent along (for a formatted preview) up to this size.
PREVIEW_LIMIT = 200_000


def is_document(path):
    """A file shown as itself (a PDF, a picture, an office file), never as text, even if it decodes."""
    kind = mimetypes.guess_type(path)[0] or ""
    return (kind == "application/pdf" or kind.startswith(("audio/", "video/", "application/vnd."))
            or (kind.startswith("image/") and kind != "image/svg+xml")
            or kind in ("application/zip", "application/msword", "application/octet-stream"))


def as_text(path, content):
    """The file's text, or None when it is not text."""
    if is_document(path):
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def write_files(directory, files):
    """Write each file once under ``directory``; content that is already there is kept."""
    for path, content in files.items():
        target = safe_join(directory, path)
        if target is None:
            log.warning("not caching a room file with an unsafe path: %r", path)
            continue
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
        temporary.write_bytes(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)


class RoomFiles:
    """The room's file bytes on disk, so the Desk server can serve what is not text.

    The head is kept at ``v<version>/<path>`` (older versions are dropped), and each
    open proposal's new files at ``<proposal id>/<path>``: a proposal never changes,
    so it is written once and remembered.
    """

    def __init__(self, home):
        self.root = room_files_dir(home)
        self.version = None
        self.proposals = {}

    async def head(self, version, files):
        if version == self.version:
            return
        await asyncio.to_thread(self._write_head, version, files)
        self.version = version

    def _write_head(self, version, files):
        current = f"v{version}"
        write_files(self.root / current, files)
        for old in self.root.glob("v*"):
            if old.name != current and old.name[1:].isdigit() and old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

    async def proposal(self, room, proposal):
        if proposal.id in self.proposals:
            return self.proposals[proposal.id]
        if proposal.status != "open" or not PROPOSAL_ID.match(proposal.id):
            return []
        changes = await room.diff(proposal.id)
        new = {change.path: change.after for change in changes if change.after is not None}
        await asyncio.to_thread(write_files, self.root / proposal.id, new)
        listed = []
        for change in changes:
            if change.after is None:
                listed.append({"path": change.path, "size": 0, "binary": False, "deleted": True})
                continue
            text = as_text(change.path, change.after)
            entry = {"path": change.path, "size": len(change.after), "binary": text is None}
            if text is not None and len(change.after) <= PREVIEW_LIMIT:
                entry["text"] = text
            listed.append(entry)
        self.proposals[proposal.id] = listed
        return listed


async def room_state(room, cache=None):
    head = room.head()
    contents = await room.files()
    files, binary = {}, {}
    for path, content in sorted(contents.items()):
        text = as_text(path, content)
        if text is None:
            files[path] = f"({len(content)} bytes)"
            binary[path] = len(content)
        else:
            files[path] = text
    proposals = []
    for p in room.proposals():
        listed = []
        if cache is not None:
            try:
                listed = await cache.proposal(room, p)
            except Exception:  # noqa: BLE001 - the room still shows; only the links are missing
                log.exception("could not cache the files of proposal %s", p.id)
                cache.proposals[p.id] = []
        proposals.append(
            {"id": p.id, "title": p.title, "author": p.author, "asked_by": p.asked_by,
             "status": p.status, "held_for": p.held_for, "decided_by": p.decided_by,
             "paths": p.paths, "base_version": getattr(p, "base_version", 0),
             "revision_of": getattr(p, "revision_of", ""), "files": listed})
    if cache is not None:
        try:
            await cache.head(head.version, contents)
        except Exception:  # noqa: BLE001
            log.exception("could not cache the room's files")
    return {"version": head.version, "files": files, "binary": binary, "proposals": proposals}


async def run(path):
    from jarviscore.auth.people import Person
    from jarviscore.room import RoomAgent, RoomConversation

    config = load_config(path)
    mesh = resolve(config.factory)()
    await mesh.start()
    room = await resolve(config.room_factory)(mesh)
    agent = next(a for a in mesh.agents if isinstance(a, RoomAgent))
    people = {pid: Person(room.tenant, pid, room.name_of(pid)) for pid in room.members()}

    cache = RoomFiles(desk_home())
    conversation = RoomConversation(room, agent, make_surface(), poll_interval=0.5)
    await conversation.start()
    following = asyncio.create_task(conversation.follow())

    async def publish_room():
        emit("room", await room_state(room, cache))

    emit("ready", {
        "room": room.id, "tenant": room.tenant,
        "people": [{"id": pid, "name": p.display, "role": room.members()[pid]}
                   for pid, p in people.items()],
    })
    await publish_room()

    async def watch_room():
        seen = None
        while True:
            state = await room_state(room, cache)
            marker = (state["version"], tuple((p["id"], p["status"]) for p in state["proposals"]))
            if marker != seen:
                seen = marker
                emit("room", state)
            await asyncio.sleep(1.0)

    watcher = asyncio.create_task(watch_room())
    tasks = set()

    async def handle(command):
        person = people.get(command.get("person", ""))
        if person is None:
            emit("error", {"message": "That person is not a member of this room."})
            return
        try:
            if command["op"] == "message":
                await conversation.hear(
                    person, command["text"], message_id=command["message_id"],
                    thread=command.get("thread") or None,
                    addressed=bool(command.get("addressed")),
                )
            elif command["op"] == "press":
                await conversation.press(person, command["action"], command["target"],
                                         command.get("thread") or None)
        except Exception as exc:  # noqa: BLE001 - surfaced to the page, logged in full
            log.exception("room command failed")
            emit("error", {"message": f"{type(exc).__name__}: {exc}"})
        await publish_room()

    reader = asyncio.StreamReader()
    await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    try:
        while line := await reader.readline():
            try:
                command = json.loads(line)
            except ValueError:
                continue
            task = asyncio.create_task(handle(command))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        for task in (following, watcher, *tasks):
            task.cancel()
        await conversation.close()
        await mesh.stop()


def main():
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        asyncio.run(run(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001
        emit("error", {"message": f"The room could not start: {type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
