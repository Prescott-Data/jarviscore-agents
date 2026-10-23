"""The Desk's room: only members act, and each person sees only what is theirs."""

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.registry import AdapterRegistry
from server.rooms import RoomHost

PEOPLE = [{"id": "ava", "name": "Ava Chen", "role": "owner"},
          {"id": "bob", "name": "Bob Iyer", "role": "editor"},
          {"id": "dana", "name": "Dana Whitfield", "role": "editor"}]


@pytest.fixture(autouse=True)
def desk_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVISCORE_DESK_HOME", str(tmp_path / "desk-home"))


class FakeRoomHost(RoomHost):
    """The host without a worker process: commands are recorded instead of sent."""

    def __init__(self):
        super().__init__("multiplayer.desk.yaml")
        self.ready, self.people, self.room = True, PEOPLE, {"room": "launch", "tenant": "acme"}
        self.sent = []

    async def _send(self, command):
        self.sent.append(command)


def client_for(tmp_path, host):
    return TestClient(create_app(registry=AdapterRegistry([]), home=tmp_path, room_host=host),
                      base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50001))


def test_a_new_request_is_addressed_to_the_room_and_a_reply_is_not(tmp_path):
    host = FakeRoomHost()
    with client_for(tmp_path, host) as client:
        asked = client.post("/api/room/messages", json={"person": "ava", "text": "draft it"})
        assert asked.status_code == 202
        root = asked.json()["message_id"]
        client.post("/api/room/messages", json={"person": "bob", "text": "shorter", "thread": root})

    first, reply = host.sent
    assert first == {"op": "message", "person": "ava", "text": "draft it", "message_id": root,
                     "thread": "", "addressed": True}
    assert reply["thread"] == root and reply["addressed"] is False
    assert [p["author"] for p in host.posts] == ["ava", "bob"], "people's messages show at once"


def test_only_members_act_in_the_room(tmp_path):
    host = FakeRoomHost()
    with client_for(tmp_path, host) as client:
        assert client.post("/api/room/messages", json={"person": "mallory", "text": "hi"}).status_code == 403
        assert client.post("/api/room/press", json={"person": "mallory", "action": "accept",
                                                     "target": "p-1"}).status_code == 403
        assert client.get("/api/room", params={"person": "mallory"}).status_code == 403
    assert host.sent == []


def test_a_confirmation_is_shown_only_to_the_person_deciding(tmp_path):
    host = FakeRoomHost()
    host._add({"id": "a-1", "thread": "m-1", "kind": "say", "author": "agent", "to": "", "text": "plan", "at": 1})
    host._add({"id": "a-2", "thread": "m-1", "kind": "confirm", "author": "agent", "to": "dana",
               "text": "Accept p-1", "decision": "d-1", "at": 2})
    with client_for(tmp_path, host) as client:
        dana = client.get("/api/room", params={"person": "dana"}).json()
        bob = client.get("/api/room", params={"person": "bob"}).json()
    assert [p["id"] for p in dana["posts"]] == ["a-1", "a-2"]
    assert [p["id"] for p in bob["posts"]] == ["a-1"]


def test_work_held_for_someone_is_hidden_from_everyone_else(tmp_path):
    host = FakeRoomHost()
    host.state = {"version": 1, "files": {}, "proposals": [
        {"id": "p-1", "title": "", "author": "writer", "asked_by": "ava", "status": "held",
         "held_for": "ava", "decided_by": "", "paths": ["plan.md"]}]}
    assert [p["id"] for p in host.view("ava")["proposals"]] == ["p-1"]
    assert host.view("bob")["proposals"] == []


def test_an_open_proposal_held_for_someone_is_hidden_from_everyone_else(tmp_path):
    # The framework keeps a held proposal "open"; only held_for marks it as private.
    host = FakeRoomHost()
    host.state = {"version": 2, "files": {}, "proposals": [
        {"id": "p-1", "title": "Use Ava's CRM notes", "author": "writer", "asked_by": "ava",
         "status": "open", "held_for": "ava", "decided_by": "", "paths": ["secret.md"],
         "base_version": 2, "revision_of": ""},
        {"id": "p-2", "title": "Tidy the plan", "author": "writer", "asked_by": "bob",
         "status": "open", "held_for": "", "decided_by": "", "paths": ["plan.md"],
         "base_version": 1, "revision_of": ""}]}
    host._add({"id": "a-1", "thread": "m-1", "kind": "proposal", "author": "agent", "to": "ava",
               "text": "Held for you", "proposal": "p-1", "held": True, "at": 1})
    with client_for(tmp_path, host) as client:
        ava = client.get("/api/room", params={"person": "ava"}).json()
        bob = client.get("/api/room", params={"person": "bob"}).json()
    assert [p["id"] for p in ava["proposals"]] == ["p-1", "p-2"]
    assert [p["id"] for p in ava["posts"]] == ["a-1"]
    assert [p["id"] for p in bob["proposals"]] == ["p-2"]
    assert bob["posts"] == []
    assert "Use Ava's CRM notes" not in str(bob) and "secret.md" not in str(bob)


def test_a_used_confirmation_is_recorded_as_confirmed(tmp_path):
    host = FakeRoomHost()
    host._add({"id": "a-2", "thread": "m-1", "kind": "confirm", "author": "agent", "to": "dana",
               "text": "Accept p-1", "decision": "d-1", "at": 2})
    with client_for(tmp_path, host) as client:
        pressed = client.post("/api/room/press", json={"person": "dana", "action": "confirm",
                                                       "target": "d-1", "thread": "m-1"})
        assert pressed.status_code == 202
    assert host.sent[-1] == {"op": "press", "person": "dana", "action": "confirm",
                             "target": "d-1", "thread": "m-1"}
    assert host.posts[0]["resolved"] == "confirmed"


def test_a_desk_without_a_room_says_so(tmp_path):
    with TestClient(create_app(registry=AdapterRegistry([]), home=tmp_path),
                    base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50001)) as client:
        assert client.get("/api/room").status_code == 404
        assert client.get("/api/workspace").json()["room"] is False


def test_the_conversation_survives_a_restart(tmp_path):
    host = FakeRoomHost()
    with client_for(tmp_path, host) as client:
        root = client.post("/api/room/messages", json={"person": "ava", "text": "draft it"}).json()["message_id"]
    host._add({"id": "c1", "thread": root, "kind": "confirm", "author": "agent", "to": "ava",
               "text": "Accept p-1?", "decision": "d-1", "at": 1.0})

    import asyncio
    asyncio.run(host.press("ava", "confirm", "d-1", root))
    again = FakeRoomHost()

    assert [p["id"] for p in again.posts] == [root, "c1"]
    assert again.posts[1]["resolved"] == "confirmed"
    assert again.view("bob")["posts"] == [again.posts[0]], "private posts stay private after a restart"


# ── Files that are not text ──────────────────────────────────────────────────

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def cache(host, folder, path, content):
    from server.rooms import room_files_dir

    target = room_files_dir(host.home) / folder / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def shared_state():
    return {"version": 3, "files": {"brief.pdf": "(42 bytes)"}, "binary": {"brief.pdf": 42}, "proposals": [
        {"id": "p-open", "title": "", "author": "writer", "asked_by": "bob", "status": "open",
         "held_for": "", "decided_by": "", "paths": ["deck.pdf"], "files": []},
        {"id": "p-held", "title": "", "author": "writer", "asked_by": "ava", "status": "open",
         "held_for": "ava", "decided_by": "", "paths": ["secret.pdf"], "files": []}]}


def test_a_pdf_in_the_room_is_served_to_be_shown_in_place(tmp_path):
    host = FakeRoomHost()
    host.state = shared_state()
    cache(host, "v3", "docs/brief.pdf", PDF)
    with client_for(tmp_path, host) as client:
        shown = client.get("/api/room/raw", params={"person": "bob", "path": "docs/brief.pdf"})
        page = client.get("/")
    assert shown.status_code == 200 and shown.content == PDF
    assert shown.headers["content-type"] == "application/pdf"
    assert shown.headers["content-disposition"].startswith('inline; filename="brief.pdf"')
    assert shown.headers["x-content-type-options"] == "nosniff"
    policy = shown.headers["content-security-policy"]
    assert "script-src" not in policy and "default-src 'none'" in policy and "frame-ancestors 'self'" in policy
    assert "object-src 'none'" in page.headers["content-security-policy"], "the app keeps its own policy"
    assert host.view("bob")["binary"] == {"brief.pdf": 42}


def test_a_pdf_in_an_open_proposal_is_served_to_whoever_may_see_it(tmp_path):
    host = FakeRoomHost()
    host.state = shared_state()
    cache(host, "p-open", "deck.pdf", PDF)
    cache(host, "p-held", "secret.pdf", PDF)
    with client_for(tmp_path, host) as client:
        get = lambda person, path, proposal: client.get(  # noqa: E731
            "/api/room/raw", params={"person": person, "path": path, "proposal": proposal})
        assert get("dana", "deck.pdf", "p-open").content == PDF
        assert get("ava", "secret.pdf", "p-held").content == PDF
        assert get("bob", "secret.pdf", "p-held").status_code == 403
        assert get("bob", "deck.pdf", "p-gone").status_code == 404
        assert get("bob", "deck.pdf", "").status_code == 404, "a proposal's file is not the room's"


def test_only_members_get_the_room_files(tmp_path):
    host = FakeRoomHost()
    host.state = shared_state()
    cache(host, "v3", "brief.pdf", PDF)
    with client_for(tmp_path, host) as client:
        assert client.get("/api/room/raw", params={"person": "mallory", "path": "brief.pdf"}).status_code == 403


def test_a_room_file_path_cannot_leave_the_cache(tmp_path):
    host = FakeRoomHost()
    host.state = shared_state()
    cache(host, "v3", "brief.pdf", PDF)
    cache(host, "p-open", "deck.pdf", PDF)
    (host.home / "owner_secret").write_text("no")
    with client_for(tmp_path, host) as client:
        for path, proposal in [("../p-open/deck.pdf", ""), ("../../../owner_secret", ""),
                               ("/etc/passwd", ""), ("./brief.pdf", ""), ("a//b", ""),
                               ("..\\brief.pdf", ""), ("deck.pdf", "../v3"), ("brief.pdf", "v3")]:
            got = client.get("/api/room/raw", params={"person": "ava", "path": path, "proposal": proposal})
            assert got.status_code == 404, (path, proposal)


def test_html_and_svg_are_only_downloaded(tmp_path):
    host = FakeRoomHost()
    host.state = shared_state()
    cache(host, "v3", "page.html", b"<script>alert(1)</script>")
    cache(host, "v3", "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    cache(host, "v3", "notes.md", b"# Notes")
    with client_for(tmp_path, host) as client:
        page = client.get("/api/room/raw", params={"person": "ava", "path": "page.html"})
        logo = client.get("/api/room/raw", params={"person": "ava", "path": "logo.svg"})
        notes = client.get("/api/room/raw", params={"person": "ava", "path": "notes.md"})
    for response in (page, logo):
        assert response.headers["content-disposition"].startswith("attachment;")
        assert "sandbox" in response.headers["content-security-policy"]
    assert notes.headers["content-type"].startswith("text/plain")
    assert notes.headers["content-disposition"].startswith("inline;")


class FakeChange:
    def __init__(self, path, before, after):
        self.path, self.before, self.after = path, before, after


class FakeProposal:
    def __init__(self, id, status, changes, held_for=""):
        self.id, self.status, self.held_for, self._changes = id, status, held_for, changes
        self.title, self.author, self.asked_by, self.decided_by = "t", "writer", "ava", ""
        self.base_version, self.revision_of = 1, ""
        self.paths = sorted(c.path for c in changes)


class FakeRoom:
    def __init__(self, version, files, proposals):
        self.version, self._files, self._proposals, self.diffs = version, files, proposals, 0

    def head(self):
        return type("Head", (), {"version": self.version})()

    async def files(self, version=None):
        return dict(self._files)

    def proposals(self):
        return list(self._proposals)

    async def diff(self, proposal_id):
        self.diffs += 1
        return next(p for p in self._proposals if p.id == proposal_id)._changes


def test_the_worker_keeps_the_room_files_for_the_desk(tmp_path):
    import asyncio

    from server.room_worker import RoomFiles, room_state
    from server.rooms import room_files_dir

    home = tmp_path / "home"
    proposals = [
        FakeProposal("p-1", "open", [FakeChange("deck/plan.pdf", None, PDF),
                                     FakeChange("notes.md", b"old", b"# New"),
                                     FakeChange("gone.md", b"bye", None)]),
        FakeProposal("p-2", "accepted", [FakeChange("old.pdf", None, PDF)]),
        FakeProposal("p-3", "open", [FakeChange("../escape.pdf", None, PDF)]),
    ]
    room = FakeRoom(2, {"brief.pdf": PDF + b"\xff", "plan.md": b"# Plan"}, proposals)
    files = RoomFiles(home)

    state = asyncio.run(room_state(room, files))
    root = room_files_dir(home)
    assert state["files"]["plan.md"] == "# Plan"
    assert state["binary"] == {"brief.pdf": len(PDF) + 1}
    assert (root / "v2" / "brief.pdf").read_bytes() == PDF + b"\xff"
    assert (root / "p-1" / "deck" / "plan.pdf").read_bytes() == PDF
    assert not (root / "p-1" / "gone.md").exists()
    assert not (root / "p-2").exists(), "only open proposals are written"
    assert not (tmp_path / "home" / "runtime" / "escape.pdf").exists()
    first = state["proposals"][0]["files"]
    assert first == [
        {"path": "deck/plan.pdf", "size": len(PDF), "binary": True},
        {"path": "notes.md", "size": 5, "binary": False, "text": "# New"},
        {"path": "gone.md", "size": 0, "binary": False, "deleted": True},
    ]
    assert state["proposals"][1]["files"] == []

    room.version, room._files = 3, {"brief.pdf": PDF}
    asyncio.run(room_state(room, files))
    assert room.diffs == 2, "a proposal never changes, so it is read once"
    assert (root / "v3" / "brief.pdf").read_bytes() == PDF
    assert not (root / "v2").exists(), "older versions are dropped"


def test_a_large_proposal_file_is_listed_without_its_text(tmp_path):
    import asyncio

    from server.room_worker import PREVIEW_LIMIT, RoomFiles, room_state

    big = b"x" * (PREVIEW_LIMIT + 1)
    room = FakeRoom(1, {}, [FakeProposal("p-1", "open", [FakeChange("big.md", None, big)])])
    state = asyncio.run(room_state(room, RoomFiles(tmp_path)))
    assert state["proposals"][0]["files"] == [{"path": "big.md", "size": len(big), "binary": False}]
