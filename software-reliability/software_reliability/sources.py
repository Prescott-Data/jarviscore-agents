"""A workspace source for a local directory, so the CLI can scan a checkout without a provider."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

from jarviscore import BlobSnapshotStore, SourceContractError, SourceRef, SourceSnapshot
from jarviscore.execution import SnapshotLimitExceeded, SnapshotLimits
from jarviscore.storage import get_blob_storage

SKIPPED = frozenset({".git", ".jarviscore", ".venv", "__pycache__", "node_modules", "target"})


class LocalSource:
    """``{"provider": "local", "locator": "<directory>", "revision": "<git revision or empty>"}``.

    A Git repository root is captured at a commit (``HEAD`` when no revision is given), so
    uncommitted changes never enter the run. Any other directory is captured as it is on
    disk. Names in ``exclude`` are left out, and ``limits`` bounds what may be captured.
    """

    def __init__(self, *, exclude=(), limits: SnapshotLimits | None = None):
        self.exclude = SKIPPED | frozenset(exclude)
        self.limits = limits or SnapshotLimits()

    async def capture(self, source: SourceRef) -> SourceSnapshot:
        root = Path(source.locator).expanduser()
        if not root.is_dir():
            raise SourceContractError(f"{source.locator!r} is not a directory")
        if (root / ".git").exists():
            revision, files = await asyncio.to_thread(self._commit, root, source.revision or "HEAD")
        elif source.revision:
            raise SourceContractError("A revision needs the root of a Git repository")
        else:
            files = await asyncio.to_thread(self._directory, root)
            revision = "sha256:" + _digest(files)
        self._check(files)
        # get_blob_storage() resolves the backend the Mesh is configured with
        # (STORAGE_BACKEND / STORAGE_BASE_PATH); Mesh has no public accessor for its own.
        store = BlobSnapshotStore(get_blob_storage())
        return await store.capture(
            source,
            revision,
            {path: content for path, (content, _) in files.items()},
            executable_paths={path for path, (_, executable) in files.items() if executable},
        )

    def _commit(self, root: Path, revision: str) -> tuple[str, dict]:
        commit = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
        archive = tarfile.open(fileobj=io.BytesIO(_git(root, "archive", commit)))
        files = {}
        for member in archive.getmembers():
            if member.isfile() and not self._excluded(member.name):
                content = archive.extractfile(member).read()
                files[member.name] = (content, bool(member.mode & 0o111))
        return commit, files

    def _directory(self, root: Path) -> dict:
        files = {}
        for directory, names, filenames in os.walk(root):
            names[:] = sorted(name for name in names if name not in self.exclude)
            for name in sorted(filenames):
                path = Path(directory, name)
                relative = path.relative_to(root).as_posix()
                if not self._excluded(relative) and path.is_file():
                    files[relative] = (path.read_bytes(), os.access(path, os.X_OK))
        return files

    def _excluded(self, path: str) -> bool:
        return any(part in self.exclude for part in Path(path).parts)

    def _check(self, files: dict) -> None:
        sizes = [len(content) for content, _ in files.values()]
        if (
            len(sizes) > self.limits.max_files
            or sum(sizes) > self.limits.max_total_bytes
            or max(sizes, default=0) > self.limits.max_file_bytes
        ):
            raise SnapshotLimitExceeded("The local source exceeds the snapshot limits")


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if completed.returncode != 0:
        raise SourceContractError(completed.stderr.decode(errors="replace").strip())
    return completed.stdout


def _digest(files: dict) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode() + b"\0" + files[path][0])
    return digest.hexdigest()
