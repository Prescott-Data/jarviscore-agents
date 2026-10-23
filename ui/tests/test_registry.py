from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from server.models import AgentMetadata, Operation
from server.registry import AdapterRegistry


def adapter(identity, **kwargs):
    return SimpleNamespace(metadata=AgentMetadata(
        id=identity, name=identity, description="test", blueprint="example",
        operations=(Operation(id="ask", label="Ask", description="Task", allows_message=True),),
        **kwargs,
    ), execute=AsyncMock())


def test_registry_lists_each_member_and_mesh():
    registry = AdapterRegistry([
        adapter("research", capabilities=("research",), color="#456789", shape="diamond"),
        adapter("writer"), adapter("mesh", kind="mesh", members=("research", "writer")),
    ])
    rows = registry.metadata()
    assert [row["id"] for row in rows] == ["research", "writer", "mesh"]
    assert rows[-1]["members"] == ["research", "writer"]


def test_missing_mesh_member_is_configuration_error():
    with pytest.raises(ValueError, match="not a registered agent"):
        AdapterRegistry([adapter("mesh", kind="mesh", members=("missing",))]).metadata()


def test_avatar_color_is_not_arbitrary_css():
    with pytest.raises(ValidationError):
        adapter("research", color="url(https://example.org)")
