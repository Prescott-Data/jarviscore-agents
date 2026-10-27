"""The Desk's room: one long-lived room worker, and what each person may see.

The worker (``server.room_worker``) runs the JarvisCore RoomConversation; this
process keeps the conversation's posts and the room's state for the browser.
A post meant for one person (a confirmation, a private note, held work) is only
ever sent to that person's view.
"""

import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from .store import desk_home

MAX_POSTS = 2000
#: How the room says a card was settled: "<name> approved: …", "<name> connected …; the work goes on."
DECIDED = re.compile(r"^(?P<by>.+?) (?P<decision>approved|declined): ")
CONNECTED = re.compile(r"^(?P<by>.+?) connected (?P<provider>.+); the work goes on\.$")
#: A proposal id names its cache folder; it can never look like a version folder.
PROPOSAL_ID = re.compile(r"^(?!v\d+$)[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def room_files_dir(home):
    """Where the room worker keeps the bytes of the room's files for the server to serve."""
    return Path(home) / "runtime" / "room-files"


def safe_join(root, path):
    """``root / path`` for a room-relative path, or None for anything that could leave ``root``."""
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path or path.startswith("/"):
        return None
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return Path(root).joinpath(*parts)


class RoomHost:
    def __init__(self, config_path, home=None):
        self.config_path = str(Path(config_path).expanduser().resolve())
        self.home = Path(home) if home is not None else desk_home()
        self.process = None
        self.reader = None
        self.people = []
        self.room = {}
        self.state = {"version": 0, "files": {}, "binary": {}, "proposals": []}
        # The conversation outlives this process: posts are kept on disk and read back.
        self.posts_file = self.home / "rooms" / f"{Path(self.config_path).stem}.posts.jsonl"
        self.posts = self._load_posts()
        self.errors = []
        self.ready = False
        self.revision = 0
        self.changed = asyncio.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        working = self.home / "runtime"
        working.mkdir(parents=True, exist_ok=True, mode=0o700)
        logs = self.home / "logs" / "workers"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        env["PYTHON_DOTENV_DISABLED"] = "1"
        env["JARVISCORE_DESK_HOME"] = str(self.home)
        self._stderr = os.open(logs / f"room-{time.strftime('%Y%m%dT%H%M%S')}.log",
                               os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "server.room_worker", self.config_path,
            cwd=working, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=self._stderr,
            start_new_session=True, limit=4 * 1048576,
        )
        self.reader = asyncio.create_task(self._read())

    async def close(self):
        if self.reader:
            self.reader.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
        if getattr(self, "_stderr", None) is not None:
            os.close(self._stderr)
            self._stderr = None

    async def _read(self):
        while line := await self.process.stdout.readline():
            try:
                frame = json.loads(line)
                kind, data = frame["type"], frame["data"]
            except (ValueError, KeyError, TypeError):
                continue
            if kind == "ready":
                self.ready, self.people, self.room = True, data["people"], data
            elif kind == "room":
                self.state = data
            elif kind == "post":
                self._settle(data)
                self._add(data)
            elif kind == "error":
                self.errors = (self.errors + [{"at": time.time(), **data}])[-20:]
            self._bump()
        self.ready = False
        self.errors.append({"at": time.time(), "message": "The room worker stopped."})
        self._bump()

    def _bump(self):
        self.revision += 1
        self.changed.set()
        self.changed = asyncio.Event()

    def _load_posts(self):
        try:
            lines = self.posts_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        posts = []
        for line in lines:
            try:
                posts.append(json.loads(line))
            except ValueError:
                continue  # a line cut short by a crash
        return posts[-MAX_POSTS:]

    def _save_posts(self):
        self.posts_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.posts_file.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in self.posts),
                             encoding="utf-8")
        os.replace(temporary, self.posts_file)

    def _settle(self, post):
        """Mark the approval or connection card a post settles, so everyone sees it decided."""
        text = str(post.get("text") or "")
        decided, connected = DECIDED.match(text), CONNECTED.match(text)
        if post.get("kind") != "say" or not (decided or connected):
            return
        kind = "approval" if decided else "connect"
        changed = False
        for earlier in self.posts:
            if earlier.get("kind") == kind and earlier.get("thread") == post.get("thread") \
                    and not earlier.get("resolved"):
                earlier["resolved"] = decided.group("decision") if decided else "connected"
                earlier["resolved_by"] = (decided or connected).group("by")
                changed = True
        if changed:
            self._save_posts()

    def _add(self, post):
        if len(self.posts) >= MAX_POSTS:
            self.posts = (self.posts + [post])[-MAX_POSTS:]
            self._save_posts()
            return
        self.posts.append(post)
        self.posts_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.posts_file.open("a", encoding="utf-8") as out:
            out.write(json.dumps(post, ensure_ascii=False) + "\n")

    # ── What people do ───────────────────────────────────────────────────────

    def person(self, person_id):
        if not any(p["id"] == person_id for p in self.people):
            raise KeyError(person_id)
        return person_id

    async def _send(self, command):
        if not self.ready or self.process is None or self.process.returncode is not None:
            raise RuntimeError("The room is not running.")
        self.process.stdin.write((json.dumps(command) + "\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def say(self, person_id, text, thread=None):
        self.person(person_id)
        message_id = f"m-{uuid.uuid4().hex[:12]}"
        root = thread or message_id
        self._add({"id": message_id, "thread": root, "kind": "message", "author": person_id,
                   "to": "", "text": text, "at": time.time()})
        self._bump()
        # A new conversation in the room is addressed to its agent; replies in a
        # thread the room started reach it on their own.
        await self._send({"op": "message", "person": person_id, "text": text,
                          "message_id": message_id, "thread": thread or "",
                          "addressed": thread is None})
        return message_id

    async def press(self, person_id, action, target, thread):
        self.person(person_id)
        await self._send({"op": "press", "person": person_id, "action": action,
                          "target": target, "thread": thread or ""})
        if action in ("confirm", "cancel"):
            # The decision is made (or dropped) once; its prompt stays as a record.
            for post in self.posts:
                if post.get("kind") == "confirm" and post.get("decision") == target:
                    post["resolved"] = "confirmed" if action == "confirm" else "cancelled"
            self._save_posts()
            self._bump()

    # ── What a person sees ───────────────────────────────────────────────────

    def view(self, person_id):
        visible = [p for p in self.posts if not p.get("to") or p["to"] == person_id]
        # A held proposal stays "open"; its non-empty held_for names the only person who may see it.
        held = {p["id"] for p in self.state.get("proposals", [])
                if p.get("held_for") and p["held_for"] != person_id}
        proposals = [p for p in self.state.get("proposals", []) if p["id"] not in held]
        return {
            "ready": self.ready, "revision": self.revision,
            "room": {"id": self.room.get("room", ""), "tenant": self.room.get("tenant", "")},
            "people": self.people, "me": person_id,
            "version": self.state.get("version", 0), "files": self.state.get("files", {}),
            "binary": self.state.get("binary", {}),
            "proposals": proposals, "posts": visible, "errors": self.errors[-3:],
        }
