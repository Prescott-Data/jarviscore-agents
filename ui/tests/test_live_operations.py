import pytest
from fastapi.testclient import TestClient

from server.adapters.gtm_team import default_gtm_registry
from server.app import create_app


@pytest.mark.parametrize("identity", ["gtm-agent", "gtm-mesh"])
def test_development_actions_are_not_available_in_live_desk(tmp_path, identity):
    config, registry = default_gtm_registry(tmp_path)
    with TestClient(
        create_app(home=tmp_path, config=config, registry=registry),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50001),
    ) as client:
        agents = client.get("/api/agents").json()
        assert {agent["id"] for agent in agents} == {"gtm-agent", "gtm-mesh"}
        assert all(
            operation["id"] == "task"
            for agent in agents
            for operation in agent["operations"]
        )
        for operation in ("sample", "watch"):
            response = client.post("/api/runs", json={"agent_id": identity, "operation": operation})
            assert response.status_code == 422
        assert client.get("/api/runs").json() == []
