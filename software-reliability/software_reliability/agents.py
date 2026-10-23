"""The eight software-reliability roles, built on JarvisCore's public AutoAgent API."""

from __future__ import annotations

from typing import ClassVar

from jarviscore import AutoAgent
from pydantic import ValidationError

from software_reliability import prompts
from software_reliability.contracts import (
    FindingPortfolio,
    PatchArtifact,
    PriorityAssessment,
    ReliabilityBrief,
    RepositoryMap,
    ReproductionEvidence,
    RuleArtifact,
    VerificationReport,
)

INSPECT = ["workspace_list", "workspace_read", "workspace_search"]
RUN = ["workspace_run"]


class ReliabilityAgent(AutoAgent):
    """A role whose steps declare the tools they must use and whose results honour its contract.

    ``output_schema`` types the role's ``done`` result. Its validators also carry the
    domain rules a JSON schema cannot express, such as "reproduced needs a failing run",
    so a result that breaks them is reported as a failure rather than passed downstream.
    """

    default_kernel_role = "coder"
    required_tools: ClassVar[dict[str, list[list[str]]]] = {}

    def step_context(self, context: dict) -> dict:
        """Add the capability's required tool groups to the step's execution contract."""
        groups = self.required_tools.get(str(context.get("capability") or ""))
        if not groups:
            return context
        contract = {**(context.get("execution_contract") or {}), "required_tool_groups": groups}
        return {**context, "execution_contract": contract}

    def check_contract(self, result: dict) -> dict:
        """Fail a successful result whose output does not satisfy ``output_schema``."""
        if result.get("status") != "success" or self.output_schema is None:
            return result
        try:
            self.output_schema.model_validate(result.get("output"))
        except ValidationError as exc:
            error = f"The {self.role} result is not a valid {self.output_schema.__name__}: {exc}"
            return {**result, "status": "failure", "error": error, "result_summary": error}
        return result

    async def execute_task(self, task: dict) -> dict:
        context = self.step_context(dict(task.get("context") or {}))
        return self.check_contract(await super().execute_task({**task, "context": context}))


def _contract(produces: str, artifact_types=(), requires=(), effects=("read",)) -> dict:
    contract = {"effects": list(effects), "produces": produces}
    if artifact_types:
        contract["artifact_types"] = list(artifact_types)
    if requires:
        contract["requires_artifact_types"] = list(requires)
    return contract


class RepositoryCartographer(ReliabilityAgent):
    role = "repository_cartographer"
    description = "Maps executable architecture, test surfaces and trust boundaries."
    capabilities = ["repository_mapping", "build_discovery", "test_discovery"]
    capability_descriptions = {
        "repository_mapping": "Map languages, components, critical surfaces and trust boundaries.",
        "build_discovery": "Find and run the repository's authoritative build commands.",
        "test_discovery": "Find and run the repository's baseline test commands.",
    }
    capability_contracts = {
        capability: _contract("RepositoryMap with executed baseline runs", ["RepositoryMap"])
        for capability in capabilities
    }
    required_tools = {capability: [INSPECT, RUN] for capability in capabilities}
    output_schema = RepositoryMap
    system_prompt = prompts.CARTOGRAPHER


class DefectMiner(ReliabilityAgent):
    role = "defect_miner"
    description = "Discovers consequential latent defects from repository evidence."
    capabilities = ["defect_discovery", "security_analysis", "history_analysis"]
    capability_descriptions = {
        "defect_discovery": "Find correctness defects across control flow and state transitions.",
        "security_analysis": "Find exploitable authorization, injection and data-boundary defects.",
        "history_analysis": "Use supplied history to find regressions and defect provenance.",
    }
    capability_contracts = {
        capability: _contract(
            "FindingPortfolio of candidates and rejected hypotheses",
            ["FindingPortfolio", "CandidateFinding"],
        )
        for capability in capabilities
    }
    required_tools = {capability: [INSPECT] for capability in capabilities}
    output_schema = FindingPortfolio
    system_prompt = prompts.DEFECT_MINER


class ReproductionEngineer(ReliabilityAgent):
    role = "reproduction_engineer"
    description = "Turns candidate defects into deterministic failing executions."
    capabilities = ["defect_reproduction", "test_authoring", "runtime_diagnosis"]
    capability_descriptions = {
        "defect_reproduction": "Prove or reject one candidate with the smallest failing test.",
        "test_authoring": "Author a deterministic regression test for a candidate defect.",
        "runtime_diagnosis": "Capture commands, output and environment blockers for a candidate.",
    }
    capability_contracts = {
        capability: _contract(
            "ReproductionEvidence for one candidate",
            ["ReproductionEvidence"],
            ["CandidateFinding"],
            effects=("read", "propose"),
        )
        for capability in capabilities
    }
    output_schema = ReproductionEvidence
    system_prompt = prompts.REPRODUCER


class ImpactAnalyst(ReliabilityAgent):
    role = "impact_analyst"
    description = "Ranks reproduced defects by user impact and actionability."
    capabilities = ["impact_assessment", "finding_deduplication", "priority_ranking"]
    capability_descriptions = {
        "impact_assessment": "Assess user impact, exploitability, likelihood and blast radius.",
        "finding_deduplication": "Identify findings with the same root-cause mechanism.",
        "priority_ranking": "Promote only defects worth scarce engineering attention.",
    }
    capability_contracts = {
        capability: _contract(
            "PriorityAssessment for one finding",
            ["PriorityAssessment"],
            ["CandidateFinding", "ReproductionEvidence"],
            effects=("read", "propose"),
        )
        for capability in capabilities
    }
    output_schema = PriorityAssessment
    system_prompt = prompts.IMPACT_ANALYST


class RepairEngineer(ReliabilityAgent):
    role = "repair_engineer"
    description = "Implements minimal root-cause patches in the isolated workspace."
    capabilities = ["root_cause_repair", "patch_authoring"]
    capability_descriptions = {
        "root_cause_repair": "Repair a reproduced defect without changing unrelated behaviour.",
        "patch_authoring": "Produce a reviewable diff that keeps the reproduction test.",
    }
    capability_contracts = {
        capability: _contract(
            "PatchArtifact with workspace mutation receipts",
            ["PatchArtifact"],
            ["CandidateFinding", "ReproductionEvidence"],
            effects=("propose",),
        )
        for capability in capabilities
    }
    output_schema = PatchArtifact
    system_prompt = prompts.REPAIR_ENGINEER


class VerificationEngineer(ReliabilityAgent):
    role = "verification_engineer"
    description = "Independently proves fail-before/pass-after behaviour and regressions."
    capabilities = ["patch_verification", "regression_testing", "adversarial_testing"]
    capability_descriptions = {
        "patch_verification": "Prove the original reproduction fails before and passes after.",
        "regression_testing": "Run the regression suites around a repair.",
        "adversarial_testing": "Challenge a repair with boundaries and alternate paths.",
    }
    capability_contracts = {
        capability: _contract(
            "VerificationReport for one repair",
            ["VerificationReport"],
            ["ReproductionEvidence", "PatchArtifact"],
        )
        for capability in capabilities
    }
    required_tools = {capability: [RUN] for capability in capabilities}
    output_schema = VerificationReport
    system_prompt = prompts.VERIFICATION_ENGINEER


class RuleEngineer(ReliabilityAgent):
    role = "rule_engineer"
    description = "Generalizes verified defect mechanisms into tested repository guardrails."
    capabilities = ["rule_generation", "regression_guardrail"]
    capability_descriptions = {
        "rule_generation": "Generate a reusable rule from a verified defect mechanism.",
        "regression_guardrail": "Test a rule against positive and negative fixtures.",
    }
    capability_contracts = {
        capability: _contract(
            "RuleArtifact with tested fixtures", ["RuleArtifact"], effects=("read", "propose")
        )
        for capability in capabilities
    }
    required_tools = {capability: [INSPECT] for capability in capabilities}
    output_schema = RuleArtifact
    system_prompt = prompts.RULE_ENGINEER


class ReliabilityStrategist(ReliabilityAgent):
    role = "reliability_strategist"
    description = "Presents only verified current-revision findings and residual risks."
    capabilities = ["reliability_synthesis", "reliability_briefing"]
    capability_descriptions = {
        "reliability_synthesis": "Join findings, repairs and verification into one brief.",
        "reliability_briefing": "Give the person the current reliability answer.",
    }
    capability_contracts = {
        "reliability_synthesis": _contract(
            "ReliabilityBrief joining every finding's artifacts",
            ["ReliabilityBrief"],
            ["CandidateFinding", "ReproductionEvidence", "PatchArtifact", "VerificationReport"],
            effects=("propose",),
        ),
        "reliability_briefing": _contract(
            "ReliabilityBrief", ["ReliabilityBrief"], effects=("final_response",)
        ),
    }
    default_kernel_role = "communicator"
    output_schema = ReliabilityBrief
    system_prompt = prompts.STRATEGIST


ROLES = (
    RepositoryCartographer,
    DefectMiner,
    ReproductionEngineer,
    ImpactAnalyst,
    RepairEngineer,
    VerificationEngineer,
    RuleEngineer,
    ReliabilityStrategist,
)
