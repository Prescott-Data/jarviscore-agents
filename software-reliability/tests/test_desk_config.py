from pathlib import Path

import yaml

from software_reliability.team import build_mesh

CONFIG = Path(__file__).resolve().parents[2] / "ui" / "software-reliability.desk.yaml"


def test_desk_config_matches_the_mesh_roster_and_handlers():
    config = yaml.safe_load(CONFIG.read_text())
    agents = {agent.role: agent.agent_id for agent in build_mesh().agents}

    assert config["factory"] == "software_reliability.team:build_mesh"
    assert config["mesh_handler"] == "software_reliability.team:submit_task"
    assert config["mesh_reconcile_handler"] == "software_reliability.team:reconcile_task"
    assert config["required_framework_version"] == ">=3.0.1,<4"
    assert {role: item["id"] for role, item in config["agents"].items()} == agents
