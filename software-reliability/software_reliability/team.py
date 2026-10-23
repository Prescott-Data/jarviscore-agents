"""The Software Reliability Mesh and the Agent Desk entry points."""

from __future__ import annotations

import os
from uuid import uuid4

from jarviscore import Mesh, Pool

from software_reliability.agents import (
    DefectMiner,
    ImpactAnalyst,
    ReliabilityStrategist,
    RepairEngineer,
    RepositoryCartographer,
    ReproductionEngineer,
    RuleEngineer,
    VerificationEngineer,
)

PLANNING_BRIEF = """This Mesh is a post-shipping software quality team. For broad
repository work it establishes the executed build and test baseline, hunts for
consequential correctness, security and reliability defects, reproduces each surviving
candidate with a failing test, ranks reproduced defects, repairs the root cause of the
promoted ones and has the repair verified independently (fail before, pass after,
regressions green). The final brief reports verified findings, rejected hypotheses and
residual risk.

Plan repair and verification even when discovery may find nothing: with no reproduced
defect they settle as not applicable. A negative result is complete only after
substantial executed coverage and explicit rejected hypotheses. A source snapshot has no
history unless one is supplied; never make history a prerequisite. Narrow requests stay
narrow, and review-only or do-not-modify instructions override this method."""

# Build caches the workspace sandbox may use (it does not inherit the process
# environment). Set them on the worker, e.g. RUSTUP_HOME for Rust toolchains.
CACHE_VARIABLES = (
    "CARGO_HOME",
    "CARGO_TARGET_DIR",
    "GOCACHE",
    "GOMODCACHE",
    "GRADLE_USER_HOME",
    "NPM_CONFIG_CACHE",
    "PIP_CACHE_DIR",
    "RUSTUP_HOME",
)


def build_mesh(source_adapters: dict | None = None) -> Mesh:
    """The reliability team. ``source_adapters`` adds workspace sources beyond GitHub."""
    mesh = Mesh(
        config={
            "workspace_required": True,
            "workspace_source_adapters": dict(source_adapters or {}),
            "workspace_source_catalog": {
                "github": {
                    "description": (
                        "A GitHub repository. locator is owner/repository, even when the "
                        "goal gives a github.com URL; revision is an explicit branch, tag "
                        "or commit, otherwise empty."
                    ),
                },
            },
            "mesh_response_capability": "reliability_briefing",
            "mesh_planning_brief": PLANNING_BRIEF,
            "execution_budget": {"max_seconds": 3600, "max_tokens": 4_000_000},
            # Building and running a repository's tests takes longer than the
            # coder's default four minutes; give each coding step ten.
            "kernel_role_profiles": {
                "coder": {"wall_clock_ms": 600_000, "emergency_turn_fuse": 24},
            },
            "workspace_snapshot_limits": {
                "max_files": 10_000,
                "max_total_bytes": 250 * 1024 * 1024,
                "max_file_bytes": 20 * 1024 * 1024,
            },
            "workspace_allowed_commands": [
                "cargo", "cmake", "dotnet", "go", "gradle", "java", "javac", "make", "mvn",
                "rustc",
            ],
            "workspace_command_timeout_seconds": 600,
            "workspace_command_environment": {
                name: os.environ[name] for name in CACHE_VARIABLES if os.environ.get(name)
            },
        }
    )
    # Two cartographers: a map step may ask the team for test discovery, which the
    # cartographer itself provides.
    mesh.add(RepositoryCartographer, agent_id="software-reliability-cartographer", pool=Pool(max=2))
    mesh.add(DefectMiner, agent_id="software-reliability-defect-miner")
    mesh.add(ReproductionEngineer, agent_id="software-reliability-reproducer", pool=Pool(max=3))
    mesh.add(ImpactAnalyst, agent_id="software-reliability-impact-analyst")
    mesh.add(RepairEngineer, agent_id="software-reliability-repair-engineer", pool=Pool(max=3))
    mesh.add(
        VerificationEngineer,
        agent_id="software-reliability-verification-engineer",
        pool=Pool(max=3),
    )
    mesh.add(RuleEngineer, agent_id="software-reliability-rule-engineer")
    mesh.add(ReliabilityStrategist, agent_id="software-reliability-strategist")
    return mesh


async def submit_task(mesh: Mesh, message: str, context: dict | None = None) -> dict:
    """Run one reliability goal on a started Mesh and return its ``desk_view``."""
    goal = (message or "").strip()
    if not goal:
        raise ValueError("A reliability goal needs a message.")
    context = dict(context or {})
    workflow_id = context.pop("mesh_workflow_id", None)
    if not workflow_id and context.get("workflow_id") and context.get("step_id"):
        workflow_id = f"{context['workflow_id']}:{context['step_id']}"
    result = await mesh.execute_goal(
        goal,
        workflow_id=workflow_id or f"software-reliability-{uuid4().hex[:12]}",
        context=context,
    )
    return desk_view(result)


async def reconcile_task(mesh: Mesh, workflow_id: str, context: dict | None = None) -> dict:
    """Continue an existing goal whose obligations are still unresolved."""
    if not workflow_id:
        raise ValueError("Reconciliation needs the goal's workflow id.")
    result = await mesh.replan_goal(
        workflow_id,
        reason="Resolve the outstanding reliability obligations without repeating verified work.",
        context=dict(context or {}),
    )
    return desk_view(result)


def desk_view(result: dict) -> dict:
    """The goal result plus the fields the Agent Desk reads.

    ``status`` is ``success``, ``yield`` or ``failure`` (the goal's own status moves to
    ``goal_status``); ``output`` is the ReliabilityBrief from the final response step;
    ``yield_metadata`` describes what a waiting step needs. Every other field is the
    framework's goal result, including ``result_summary`` and ``obligation_status``.
    """
    revision = result.get("revision")
    current = [step for step in result.get("steps", []) if step.get("plan_revision") == revision]

    def envelope(matches) -> dict:
        return next((step.get("output") or {} for step in current if matches(step)), {})

    response = envelope(lambda step: step.get("effect") == "final_response")
    waiting = envelope(lambda step: step.get("status") == "waiting")
    return {
        **result,
        "goal_status": result.get("status"),
        "status": {"completed": "success", "waiting": "yield"}.get(result.get("status"), "failure"),
        "output": response.get("output"),
        "yield_metadata": waiting.get("yield_metadata", {}),
    }
