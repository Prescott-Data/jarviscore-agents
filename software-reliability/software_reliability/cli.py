"""Command line: scan a local or GitHub repository, or run the demo and benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from software_reliability.demo import DEMO_REPOSITORY, benchmark_main
from software_reliability.demo import main as demo_main
from software_reliability.sources import LocalSource
from software_reliability.team import build_mesh, submit_task

SCAN_GOAL = "Run a deep reliability scan of this repository."
DEMO_GOAL = (
    "Find the most consequential defect in this repository, reproduce it with a failing "
    "test, repair its root cause and verify the repair."
)


async def run(goal: str, workspace_source: dict, source_adapters: dict | None = None) -> dict:
    """Start the Mesh, run one goal against ``workspace_source`` and stop."""
    mesh = build_mesh(source_adapters)
    await mesh.start()
    try:
        return await submit_task(mesh, goal, {"workspace_source": workspace_source})
    finally:
        await mesh.stop()


def scan_local(path: Path, revision: str, goal: str, exclude=()) -> dict:
    source = {"provider": "local", "locator": str(path.resolve()), "revision": revision}
    return asyncio.run(run(goal, source, {"local": LocalSource(exclude=exclude)}))


def scan_github(repository: str, ref: str, goal: str) -> dict:
    return asyncio.run(run(goal, {"provider": "github", "locator": repository, "revision": ref}))


REPORTED = (
    "workflow_id", "status", "goal_status", "obligation_status", "result_summary", "output",
    "error",
)


def report(result: dict) -> str:
    shown = {key: result[key] for key in REPORTED if result.get(key) is not None}
    return json.dumps(shown, indent=2, default=str)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="software-reliability")
    commands = result.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="Scan a local directory or Git repository")
    scan.add_argument("repository", type=Path)
    scan.add_argument("--commit", default="", help="Git revision (default: HEAD)")
    scan.add_argument("--goal", default=SCAN_GOAL)
    github = commands.add_parser("scan-github", help="Scan a GitHub repository through Nexus")
    github.add_argument("repository", help="owner/repository")
    github.add_argument("--ref", default="main")
    github.add_argument("--goal", default=SCAN_GOAL)
    demo = commands.add_parser("demo", help="Run the authorization-bypass fixture")
    demo.add_argument(
        "--live", action="store_true", help="Give the fixture to the Mesh and a real model"
    )
    commands.add_parser("benchmark", help="Score the deterministic benchmark corpus")
    return result


def main(argv: list[str] | None = None) -> None:
    arguments = parser().parse_args(argv)
    if arguments.command == "benchmark":
        benchmark_main()
    elif arguments.command == "demo" and not arguments.live:
        demo_main()
    elif arguments.command == "demo":
        print(report(scan_local(DEMO_REPOSITORY, "", DEMO_GOAL, exclude={"repair.patch"})))
    elif arguments.command == "scan-github":
        print(report(scan_github(arguments.repository, arguments.ref, arguments.goal)))
    else:
        print(report(scan_local(arguments.repository, arguments.commit, arguments.goal)))
