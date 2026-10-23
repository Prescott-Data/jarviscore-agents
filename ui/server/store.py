"""Single-writer SQLite history, with atomic status/event transitions."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import TERMINAL


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def desk_home() -> Path:
    return Path(os.environ.get("JARVISCORE_DESK_HOME", "~/.jarviscore/desk")).expanduser().resolve()


def desk_owner_id(home: Path) -> str:
    """The one person this local Desk serves; agents scope cross-session memory to it."""
    path = home / "owner_id"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        owner = f"desk-{uuid4().hex}"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            handle.write(owner)
        return owner


class BusyAgent(Exception):
    pass


class RunStore:
    def __init__(self, home: Path):
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = (home / "server.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another desk server is already using this history.") from None
        path = home / "runs.sqlite"
        self.owner_id = desk_owner_id(home)
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, operation TEXT NOT NULL,
                message TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_agent ON runs(agent_id)
                WHERE status = 'running';
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                type TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(run_id, seq)
            );
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
        if "context" not in columns:
            self.db.execute(
                "ALTER TABLE runs ADD COLUMN context TEXT NOT NULL DEFAULT '{}'"
            )

    def close(self) -> None:
        self.db.close()
        self.lock.close()

    def _event(self, run_id: str, kind: str, data: dict, now: str) -> None:
        self.db.execute(
            "INSERT INTO events VALUES (?, (SELECT COALESCE(MAX(seq),0)+1 FROM events "
            "WHERE run_id=?), ?, ?, ?)",
            (run_id, run_id, kind, now, json.dumps(data, ensure_ascii=False)),
        )
        self.db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now, run_id))

    def create(
        self,
        agent_id: str,
        operation: str,
        message: str | None,
        context: dict | None = None,
    ) -> dict:
        run_id, now = uuid4().hex, timestamp()
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO runs "
                    "(id, agent_id, operation, message, status, created_at, updated_at, context) "
                    "VALUES (?, ?, ?, ?, 'running', ?, ?, ?)",
                    (
                        run_id,
                        agent_id,
                        operation,
                        message,
                        now,
                        now,
                        json.dumps(context or {}, ensure_ascii=False),
                    ),
                )
                self._event(run_id, "status", {"message": "Run started."}, now)
        except sqlite3.IntegrityError:
            raise BusyAgent from None
        return self.get(run_id)

    def append(self, run_id: str, kind: str, data: dict) -> None:
        with self.db:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise RuntimeError("Cannot append to a terminal run.")
            self._event(run_id, kind, data, timestamp())

    def pause(self, run_id: str) -> None:
        with self.db:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise RuntimeError("Only a running run can wait.")
            self.db.execute(
                "UPDATE runs SET status='waiting', updated_at=? WHERE id=?",
                (timestamp(), run_id),
            )

    def reopen(self, run_id: str) -> dict:
        """Start a new execution epoch on the same durable Desk conversation."""
        now = timestamp()
        try:
            with self.db:
                row = self.db.execute(
                    "SELECT status FROM runs WHERE id=?", (run_id,)
                ).fetchone()
                if row is None or row["status"] not in TERMINAL:
                    raise RuntimeError("Only a terminal run can be reconciled.")
                self.db.execute(
                    "UPDATE runs SET status='running', updated_at=? WHERE id=?",
                    (now, run_id),
                )
                self._event(
                    run_id, "status",
                    {"message": "Goal reconciliation started."}, now,
                )
        except sqlite3.IntegrityError:
            raise BusyAgent from None
        return self.get(run_id)

    def resume(
        self, run_id: str, connection_id: str,
        message: str = "Access approved. Resuming the task.",
        decision: dict | None = None,
    ) -> dict:
        row, waiting = self.waiting_context(run_id, connection_id)
        now = timestamp()
        with self.db:
            self.db.execute("UPDATE runs SET status='running', updated_at=? WHERE id=?", (now, run_id))
            if decision is not None:
                self._event(run_id, "approval_decided", decision, now)
            self._event(run_id, "status", {"message": message}, now)
        resumed = dict(row)
        resumed["context"] = json.loads(resumed.get("context") or "{}")
        return resumed | {
            "status": "running",
            "events": self.events(run_id),
            "resume": waiting["data"],
        }

    def waiting_context(self, run_id: str, connection_id: str):
        """Return the pending wait only when its opaque identity matches."""
        events = self.events(run_id)
        waiting = next((e for e in reversed(events) if e["type"] == "waiting"), None)
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "waiting" or waiting is None:
            raise RuntimeError("This run is not waiting for a decision.")
        if waiting["data"]["connection_id"] != connection_id:
            raise RuntimeError("This decision does not belong to this run.")
        return row, waiting

    def finish(self, run_id: str, status: str, message: str | None = None) -> None:
        if status not in TERMINAL:
            raise ValueError("Invalid terminal status")
        now = timestamp()
        with self.db:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] in TERMINAL:
                return
            if message:
                kind = "error" if status == "failed" else "status"
                self._event(run_id, kind, {"message": message}, now)
            self._event(
                run_id, "cancelled" if status == "cancelled" else "completed",
                {"status": status}, now,
            )
            self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def recover(self) -> list[dict]:
        rows = self.db.execute("SELECT id FROM runs WHERE status='running'").fetchall()
        return [self.get(row["id"]) for row in rows]

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        rows = self.db.execute(
            "SELECT seq,type,timestamp,data FROM events WHERE run_id=? AND seq>? ORDER BY seq",
            (run_id, after),
        )
        return [dict(row) | {"data": json.loads(row["data"])} for row in rows]

    def get(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["context"] = json.loads(run.get("context") or "{}")
        return run | {"events": self.events(run_id)}

    def list(self) -> list[dict]:
        return [self.get(row["id"]) for row in self.db.execute(
            "SELECT id FROM runs ORDER BY created_at DESC, id DESC"
        ).fetchall()]

    def revision(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(rowid), 0) FROM events").fetchone()[0]

    def changed_runs(self, after: int, through: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT run_id FROM events WHERE rowid > ? AND rowid <= ? "
            "GROUP BY run_id ORDER BY MAX(rowid)", (after, through),
        ).fetchall()
        return [self.get(row["run_id"]) for row in rows]
