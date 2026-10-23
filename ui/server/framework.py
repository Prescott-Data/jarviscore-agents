"""Installed runtime provenance, resolved without importing agent providers."""

import importlib.util
import json
import subprocess
import tomllib
from importlib.metadata import PackageNotFoundError, distribution, distributions
from pathlib import Path
from urllib.parse import unquote, urlparse


def framework_info():
    info = {
        "framework_version": None,
        "framework_source": None,
        "framework_editable": False,
        "framework_revision": None,
        "framework_branch": None,
        "framework_dirty": None,
    }
    try:
        installed = distribution("jarviscore-framework")
    except PackageNotFoundError:
        return info
    info["framework_version"] = installed.version
    origin = json.loads(installed.read_text("direct_url.json") or "{}")
    info["framework_editable"] = origin.get("dir_info", {}).get("editable", False)
    spec = importlib.util.find_spec("jarviscore")
    if spec is None or spec.origin is None:
        return info
    source = Path(spec.origin).resolve().parent.parent
    info["framework_source"] = str(source)
    if not info["framework_editable"]:
        for candidate in distributions(name="jarviscore-framework"):
            candidate_origin = json.loads(candidate.read_text("direct_url.json") or "{}")
            parsed_url = urlparse(candidate_origin.get("url", ""))
            candidate_source = (
                Path(unquote(parsed_url.path)).resolve()
                if parsed_url.scheme == "file" else None
            )
            if (
                candidate_origin.get("dir_info", {}).get("editable", False)
                and candidate_source == source
            ):
                info["framework_version"] = candidate.version
                info["framework_editable"] = True
                break
    if not (source / ".git").exists():
        return info

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(source), *args], check=True, capture_output=True,
            text=True, timeout=5,
        ).stdout.strip()

    try:
        info["framework_revision"] = git("rev-parse", "HEAD")
        info["framework_branch"] = git("branch", "--show-current")
        info["framework_dirty"] = bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def require_framework_source(expected: Path):
    expected = expected.expanduser().resolve()
    info = framework_info()
    if info["framework_source"] != str(expected) or not info["framework_editable"]:
        raise ValueError(
            "Framework source mismatch: install the requested checkout editable "
            "in this interpreter before starting the desk."
        )
    with (expected / "pyproject.toml").open("rb") as project:
        source_version = tomllib.load(project)["project"]["version"]
    if info["framework_version"] != source_version:
        raise ValueError("Framework version metadata is stale; reinstall the editable checkout.")
    return info


def require_framework_version(specifier: str):
    """Require an installed JarvisCore, released or editable, within ``specifier``."""
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    info = framework_info()
    installed = info.get("framework_version")
    if not installed:
        raise ValueError("JarvisCore is not installed in this interpreter.")
    if Version(installed) not in SpecifierSet(specifier):
        raise ValueError(
            f"This desk requires JarvisCore {specifier}; {installed} is installed."
        )
    return info


def require_framework_commit(required: str):
    """Require an editable framework checkout containing a known local commit."""
    info = framework_info()
    source = info.get("framework_source")
    if not source or not info.get("framework_editable") or not info.get("framework_revision"):
        raise ValueError("This desk requires an editable JarvisCore framework checkout.")
    try:
        subprocess.run(
            ["git", "-C", source, "merge-base", "--is-ancestor", required, "HEAD"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(
            f"The installed JarvisCore checkout does not contain required commit {required}."
        ) from None
    return info
