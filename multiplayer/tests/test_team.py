"""The campaign room: who the team is, and what the room starts with."""

import fakeredis
import pytest
from jarviscore import Mesh
from jarviscore.room import RoomAgent
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.storage.redis_store import RedisContextStore

from multiplayer import BRIEF, BRIEF_FILE, TEAM, Strategist, Writer, build_mesh, open_room


def test_the_mesh_is_the_room_agent_a_strategist_and_a_writer():
    mesh = build_mesh()
    kinds = [type(agent) for agent in mesh.agents]
    assert any(issubclass(kind, RoomAgent) for kind in kinds)
    assert Strategist in kinds and Writer in kinds


@pytest.fixture
async def mesh(tmp_path, monkeypatch):
    store = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path / "blobs")))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = build_mesh()
    mesh.config["p2p_enabled"] = False
    await mesh.start()
    yield mesh
    await mesh.stop()


async def test_the_room_opens_with_the_brief_and_the_team(mesh):
    room = await open_room(mesh)
    assert (await room.read(BRIEF_FILE)).decode() == BRIEF
    assert room.members() == {person.id: role for person, role in TEAM.values()}


async def test_opening_the_room_again_changes_nothing(mesh):
    first = await open_room(mesh)
    again = await open_room(mesh)
    assert again.head().version == first.head().version == 1
