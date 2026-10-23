import subprocess

import pytest
from jarviscore import BlobSnapshotStore, SourceContractError, SourceRef
from jarviscore.execution import SnapshotLimitExceeded, SnapshotLimits, capture_source
from jarviscore.storage import get_blob_storage

from software_reliability.sources import LocalSource


@pytest.fixture(autouse=True)
def runtime_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


async def capture(adapter, locator, revision=""):
    store = BlobSnapshotStore(get_blob_storage())
    return await capture_source(adapter, store, SourceRef("local", str(locator), revision))


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


async def test_directory_is_captured_as_on_disk_without_excluded_names(tmp_path):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "service.py").write_text("print('ok')\n")
    (project / "tests" / "test_service.py").write_text("assert True\n")
    (project / "repair.patch").write_text("secret answer\n")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "service.pyc").write_bytes(b"\0")

    snapshot = await capture(LocalSource(exclude={"repair.patch"}), project)

    assert [entry.path for entry in snapshot.entries] == ["service.py", "tests/test_service.py"]
    assert snapshot.resolved_revision.startswith("sha256:")


async def test_git_repository_is_captured_at_a_commit_without_uncommitted_changes(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    git(project, "init", "-q")
    (project / "app.py").write_text("committed\n")
    git(project, "add", "app.py")
    git(project, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init")
    (project / "app.py").write_text("dirty\n")
    (project / "notes.txt").write_text("untracked\n")

    snapshot = await capture(LocalSource(), project)

    assert [entry.path for entry in snapshot.entries] == ["app.py"]
    assert len(snapshot.resolved_revision) == 40


async def test_revision_requires_a_git_root_and_sources_respect_limits(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "a.txt").write_text("a" * 10)

    with pytest.raises(SourceContractError):
        await capture(LocalSource(), tmp_path / "plain", "main")
    with pytest.raises(SnapshotLimitExceeded):
        await capture(LocalSource(limits=SnapshotLimits(max_file_bytes=5)), tmp_path / "plain")
