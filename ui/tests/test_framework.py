import json
from types import SimpleNamespace

import pytest

from server import framework
from server.__main__ import parser


def test_provenance_resolves_import_source_and_git_not_environment(tmp_path, monkeypatch):
    (tmp_path / ".git").write_text("worktree marker")
    monkeypatch.setenv("JARVISCORE_FRAMEWORK_REVISION", "untrusted-label")
    monkeypatch.setattr(framework, "distribution", lambda _: SimpleNamespace(
        version="1.5.1", read_text=lambda _: json.dumps({"dir_info": {"editable": True}}),
    ))
    monkeypatch.setattr(framework.importlib.util, "find_spec", lambda _: SimpleNamespace(
        origin=str(tmp_path / "jarviscore" / "__init__.py"),
    ))
    answers = iter(["real-commit", "feat/gtm-framework-integration", " M jarviscore/file.py"])
    monkeypatch.setattr(framework.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=next(answers),
    ))
    info = framework.framework_info()
    assert info["framework_version"] == "1.5.1"
    assert info["framework_source"] == str(tmp_path)
    assert info["framework_editable"] is True
    assert info["framework_revision"] == "real-commit"
    assert info["framework_branch"] == "feat/gtm-framework-integration"
    assert info["framework_dirty"] is True


def test_provenance_prefers_editable_metadata_for_imported_source(tmp_path, monkeypatch):
    (tmp_path / ".git").write_text("worktree marker")
    legacy = SimpleNamespace(version="1.10.0", read_text=lambda _: None)
    editable = SimpleNamespace(
        version="1.10.0",
        read_text=lambda _: json.dumps({
            "dir_info": {"editable": True}, "url": tmp_path.as_uri(),
        }),
    )
    monkeypatch.setattr(framework, "distribution", lambda _: legacy)
    monkeypatch.setattr(framework, "distributions", lambda **_: [legacy, editable])
    monkeypatch.setattr(framework.importlib.util, "find_spec", lambda _: SimpleNamespace(
        origin=str(tmp_path / "jarviscore" / "__init__.py"),
    ))
    monkeypatch.setattr(framework.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout="current",
    ))

    info = framework.framework_info()

    assert info["framework_source"] == str(tmp_path)
    assert info["framework_editable"] is True


@pytest.mark.parametrize("editable,source", [(False, "expected"), (True, "other")])
def test_source_guard_refuses_wheel_or_wrong_checkout(tmp_path, monkeypatch, editable, source):
    monkeypatch.setattr(framework, "framework_info", lambda: {
        "framework_source": str(tmp_path / source), "framework_editable": editable,
    })
    with pytest.raises(ValueError, match="source mismatch"):
        framework.require_framework_source(tmp_path / "expected")


def test_source_guard_accepts_matching_version_and_refuses_stale_metadata(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.5.1"\n')
    info = {"framework_source": str(tmp_path), "framework_editable": True,
            "framework_version": "1.5.1"}
    monkeypatch.setattr(framework, "framework_info", lambda: info)
    assert framework.require_framework_source(tmp_path) == info
    info["framework_version"] = "1.4.1"
    with pytest.raises(ValueError, match="metadata is stale"):
        framework.require_framework_source(tmp_path)


def test_launcher_accepts_explicit_framework_source(tmp_path):
    assert parser().parse_args(["--framework-source", str(tmp_path)]).framework_source == tmp_path


def test_commit_guard_accepts_ancestor_and_rejects_other_checkout(monkeypatch):
    info = {
        "framework_source": "/framework", "framework_editable": True,
        "framework_revision": "current",
    }
    monkeypatch.setattr(framework, "framework_info", lambda: info)
    monkeypatch.setattr(framework.subprocess, "run", lambda *args, **kwargs: None)
    assert framework.require_framework_commit("a" * 40) == info

    def rejected(*args, **kwargs):
        raise framework.subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(framework.subprocess, "run", rejected)
    with pytest.raises(ValueError, match="does not contain required commit"):
        framework.require_framework_commit("b" * 40)


def test_version_guard_accepts_a_release_in_range_and_names_a_mismatch(monkeypatch):
    info = {"framework_version": "2.1.0", "framework_editable": False}
    monkeypatch.setattr(framework, "framework_info", lambda: info)
    assert framework.require_framework_version(">=2.1.0,<3") == info

    info["framework_version"] = "1.14.1"
    with pytest.raises(ValueError, match="requires JarvisCore >=2.1.0,<3; 1.14.1 is installed"):
        framework.require_framework_version(">=2.1.0,<3")

    info["framework_version"] = None
    with pytest.raises(ValueError, match="not installed"):
        framework.require_framework_version(">=2.1.0,<3")
