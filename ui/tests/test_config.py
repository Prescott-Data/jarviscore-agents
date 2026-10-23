from types import SimpleNamespace

import pytest

from server import config


def test_factory_lists_all_instances_and_optional_mesh_handler(tmp_path, monkeypatch):
    path = tmp_path / "desk.yaml"
    path.write_text('factory: example:build\nagents:\n  research:\n    color: "#1758f5"\n')
    members = [SimpleNamespace(role="research", capabilities=["search"]) for _ in range(2)]
    monkeypatch.setattr(config, "resolve", lambda _: lambda: SimpleNamespace(agents=members))
    loaded, registry = config.configured_registry(path)
    rows = registry.metadata()
    assert len(rows) == 3
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["color"] == "#1758f5"
    assert rows[-1]["kind"] == "mesh" and rows[-1]["operations"] == []
    path.write_text('factory: example:build\nmesh_handler: example:submit\ntrace_dir: traces\n')
    loaded, registry = config.configured_registry(path)
    assert registry.metadata()[-1]["operations"][0]["allows_message"]
    assert loaded.trace_dir == tmp_path / "traces"


def test_the_mesh_conversation_carries_the_configured_product_name(tmp_path, monkeypatch):
    path = tmp_path / "desk.yaml"
    members = [SimpleNamespace(role="research", capabilities=["search"])]
    monkeypatch.setattr(config, "resolve", lambda _: lambda: SimpleNamespace(agents=members))
    path.write_text("factory: example:build\n")
    assert config.configured_registry(path)[1].metadata()[-1]["name"] == "Mesh"
    path.write_text("factory: example:build\nmesh_name: Personal Intelligence\n")
    assert config.configured_registry(path)[1].metadata()[-1]["name"] == "Personal Intelligence"


def test_bad_configuration_fails_before_execution(tmp_path):
    path = tmp_path / "desk.yaml"
    path.write_text('factory: "os:system(hello)"\n')
    with pytest.raises(ValueError):
        config.load_config(path)


def test_unconfigured_agent_colors_vary_and_explicit_colors_are_preserved(tmp_path, monkeypatch):
    path = tmp_path / "desk.yaml"
    path.write_text('factory: example:build\nagents:\n  research:\n    name: Research\n')
    members = [SimpleNamespace(role=role, capabilities=[role])
               for role in ("research", "writer", "reviewer", "analyst")]
    monkeypatch.setattr(config, "resolve", lambda _: lambda: SimpleNamespace(agents=members))
    _, registry = config.configured_registry(path)
    colors = [row["color"] for row in registry.metadata() if row["kind"] == "agent"]
    assert len(set(colors)) == 4
    assert colors == list(config.AGENT_COLORS[:4])
    path.write_text('factory: example:build\nagents:\n  writer:\n    color: "#123456"\n')
    _, registry = config.configured_registry(path)
    assert registry.metadata()[1]["color"] == "#123456"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://user:password@localhost/metrics", "https://host/metrics?token=secret"])
def test_metrics_url_cannot_carry_executable_scheme_or_credentials(url):
    with pytest.raises(ValueError):
        config.DeskConfig(factory="example:build", metrics_url=url)
