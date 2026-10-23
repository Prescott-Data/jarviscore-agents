"""Evidence contracts for software-reliability findings and repairs."""

from __future__ import annotations

from typing import Literal

from jarviscore import CommandObservation, WorkspaceMutation
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReliabilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocation(ReliabilityContract):
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str | None = None

    @model_validator(mode="after")
    def lines_are_ordered(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class ReproductionEvidence(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    status: Literal["reproduced", "not_reproduced", "no_candidates", "blocked"]
    test_path: str | None = None
    test_selector: str | None = None
    selection_run: CommandObservation | None = None
    vulnerable_run: CommandObservation | None = None
    expected_behavior: str = Field(min_length=1)
    observed_behavior: str = Field(min_length=1)
    blocking_reason: str | None = None

    @model_validator(mode="after")
    def reproduced_findings_have_a_real_failure(self):
        if self.status in {"reproduced", "not_reproduced"}:
            if not self.test_path:
                raise ValueError(f"{self.status} findings require a test path")
            if not self.test_selector or self.selection_run is None:
                raise ValueError(
                    f"{self.status} findings require a collected exact test selector"
                )
            if self.selection_run.exit_code != 0:
                raise ValueError("test selection requires a successful collection run")
            selection_output = self.selection_run.stdout + self.selection_run.stderr
            if self.test_selector not in selection_output:
                raise ValueError("collection output must contain the exact test selector")
            if self.vulnerable_run is None:
                raise ValueError(f"{self.status} findings require an executed test")
            if self.test_selector not in " ".join(self.vulnerable_run.command):
                raise ValueError("executed test command must use the collected selector")
            if self.selection_run.tool_receipt_id == self.vulnerable_run.tool_receipt_id:
                raise ValueError("test collection and execution require distinct receipts")
        if self.status == "reproduced":
            if self.vulnerable_run.exit_code == 0:
                raise ValueError("reproduced findings require a failing vulnerable run")
        elif self.status == "not_reproduced" and self.vulnerable_run.exit_code != 0:
            raise ValueError("not_reproduced findings require a passing executed test")
        elif self.status == "blocked" and not self.blocking_reason:
            raise ValueError("blocked reproductions require a blocking reason")
        elif self.status == "no_candidates" and (
            self.test_path is not None
            or self.test_selector is not None
            or self.selection_run is not None
            or self.vulnerable_run is not None
        ):
            raise ValueError("no_candidates cannot claim an executed reproduction")
        return self


class CandidateFinding(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    title: str = Field(min_length=1)
    category: Literal[
        "correctness",
        "security",
        "concurrency",
        "data_integrity",
        "availability",
        "performance",
        "documentation",
        "dead_code",
    ]
    invariant: str = Field(min_length=1)
    actual_behavior: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    locations: list[SourceLocation] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class RejectedHypothesis(ReliabilityContract):
    hypothesis_id: str = Field(pattern=r"^hypothesis_[a-z0-9][a-z0-9_-]+$")
    title: str = Field(min_length=1)
    invariant: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    expected_failure: str = Field(min_length=1)
    observed_evidence: str = Field(min_length=1)
    locations: list[SourceLocation] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class FindingPortfolio(ReliabilityContract):
    status: Literal["candidates_found", "no_actionable_findings", "incomplete"]
    commit_sha: str = Field(min_length=1)
    candidates: list[CandidateFinding] = Field(default_factory=list)
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    searched_surfaces: list[str] = Field(min_length=1)
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_candidates(self):
        if self.status == "candidates_found" and not self.candidates:
            raise ValueError("candidates_found requires at least one candidate")
        if self.status == "no_actionable_findings" and self.candidates:
            raise ValueError("no_actionable_findings cannot carry candidates")
        if self.status == "no_actionable_findings" and not self.rejected_hypotheses:
            raise ValueError(
                "no_actionable_findings requires explicit rejected hypotheses"
            )
        if self.status == "incomplete" and not self.unresolved:
            raise ValueError("incomplete discovery must name unresolved surfaces")
        return self


class RepositoryMap(ReliabilityContract):
    status: Literal["ready", "incomplete", "unbuildable"]
    commit_sha: str = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    build_commands: list[list[str]] = Field(default_factory=list)
    test_commands: list[list[str]] = Field(default_factory=list)
    baseline_runs: list[CommandObservation] = Field(default_factory=list)
    critical_surfaces: list[str] = Field(default_factory=list)
    trust_boundaries: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def map_status_matches_execution(self):
        if self.status == "ready" and not self.baseline_runs:
            raise ValueError("a ready repository map requires an executed baseline command")
        if self.status != "ready" and not self.unresolved:
            raise ValueError("an incomplete or unbuildable repository map needs unresolved facts")
        return self


class PriorityAssessment(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    decision: Literal["promote", "hold", "reject"]
    priority: Literal["P1", "P2", "P3"] | None = None
    rationale: str = Field(min_length=1)
    user_impact: str = Field(min_length=1)
    exploitability: str = Field(min_length=1)
    likelihood: str = Field(min_length=1)
    blast_radius: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def promoted_findings_have_priority(self):
        if self.decision == "promote" and self.priority is None:
            raise ValueError("promoted findings require a priority")
        if self.decision != "promote" and self.priority is not None:
            raise ValueError("held or rejected findings cannot claim a priority")
        return self


class PatchArtifact(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    status: Literal["proposed", "applied", "not_applicable", "blocked"]
    blocking_kind: Literal[
        "product_intent", "infrastructure", "contradictory_evidence"
    ] | None = None
    diff: str = ""
    changed_files: list[str] = Field(default_factory=list)
    mutations: list[WorkspaceMutation] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def applied_patch_has_content(self):
        if self.status == "blocked" and self.blocking_kind is None:
            raise ValueError("a blocked patch requires a typed blocking kind")
        if self.status != "blocked" and self.blocking_kind is not None:
            raise ValueError("only blocked patches can carry a blocking kind")
        if self.status == "applied" and (
            not self.diff or not self.changed_files or not self.mutations
        ):
            raise ValueError(
                "an applied patch requires a diff, changed files, and workspace mutations"
            )
        if self.status == "applied" and set(self.changed_files) != {
            mutation.path for mutation in self.mutations
        }:
            raise ValueError(
                "applied patch changed files must match workspace mutation receipts"
            )
        if self.status == "not_applicable" and (
            self.diff or self.changed_files or self.mutations
        ):
            raise ValueError("not-applicable repairs cannot carry workspace mutations")
        return self


class VerificationReport(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    status: Literal["verified", "not_applicable", "failed", "blocked"]
    test_selector: str | None = None
    selection_run: CommandObservation | None = None
    reproduction_before: CommandObservation | None = None
    reproduction_after: CommandObservation | None = None
    regression_runs: list[CommandObservation] = Field(default_factory=list)
    tests_weakened: bool = False
    unresolved_risks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_repairs_prove_the_transition(self):
        if self.status == "not_applicable":
            if self.test_selector or self.selection_run:
                raise ValueError(
                    "not-applicable verification cannot claim a repair selector"
                )
            if self.reproduction_before or self.reproduction_after:
                raise ValueError(
                    "not-applicable verification cannot claim a repair transition"
                )
            if not self.regression_runs or any(
                run.exit_code != 0 for run in self.regression_runs
            ):
                raise ValueError(
                    "not-applicable verification requires passing independent regressions"
                )
            return self
        if self.status != "verified":
            return self
        if not self.test_selector or self.selection_run is None:
            raise ValueError("verified repairs require a collected exact test selector")
        if self.selection_run.exit_code != 0:
            raise ValueError("test selection requires a successful collection run")
        selection_output = self.selection_run.stdout + self.selection_run.stderr
        if self.test_selector not in selection_output:
            raise ValueError("collection output must contain the exact test selector")
        if self.reproduction_before is None or self.reproduction_before.exit_code == 0:
            raise ValueError("verified repairs require a failing pre-patch reproduction")
        if self.reproduction_after is None or self.reproduction_after.exit_code != 0:
            raise ValueError("verified repairs require a passing post-patch reproduction")
        for run in (self.reproduction_before, self.reproduction_after):
            if self.test_selector not in " ".join(run.command):
                raise ValueError(
                    "verified reproduction commands must use the collected selector"
                )
            if self.selection_run.tool_receipt_id == run.tool_receipt_id:
                raise ValueError("test collection and execution require distinct receipts")
        if any(run.exit_code != 0 for run in self.regression_runs):
            raise ValueError("verified repairs require passing regression runs")
        if self.tests_weakened:
            raise ValueError("a repair that weakens tests cannot be verified")
        return self


class RuleArtifact(ReliabilityContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    status: Literal["ready", "incomplete", "not_generalizable"]
    rule_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rule_files: dict[str, str] = Field(default_factory=dict)
    positive_fixtures: list[str] = Field(default_factory=list)
    negative_fixtures: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ready_rules_are_tested(self):
        if self.status == "ready" and (
            not self.rule_files or not self.positive_fixtures or not self.negative_fixtures
        ):
            raise ValueError("ready rules require files plus positive and negative fixtures")
        return self


class ReliabilityFinding(ReliabilityContract):
    candidate: CandidateFinding
    reproduction: ReproductionEvidence
    priority: PriorityAssessment | None = None
    patch: PatchArtifact | None = None
    verification: VerificationReport | None = None
    disposition: Literal[
        "candidate",
        "reproduced",
        "repair_proposed",
        "verified",
        "dismissed",
        "blocked",
    ]

    @model_validator(mode="after")
    def disposition_requires_supporting_evidence(self):
        artifact_ids = {
            self.candidate.finding_id,
            self.reproduction.finding_id,
            *(
                [self.priority.finding_id]
                if self.priority is not None
                else []
            ),
            *([self.patch.finding_id] if self.patch is not None else []),
            *(
                [self.verification.finding_id]
                if self.verification is not None
                else []
            ),
        }
        if len(artifact_ids) != 1:
            raise ValueError("joined reliability artifacts must share one finding_id")
        if self.disposition in {"reproduced", "repair_proposed", "verified"}:
            if self.reproduction.status != "reproduced":
                raise ValueError(f"{self.disposition} requires reproduced evidence")
        if self.disposition == "repair_proposed" and self.patch is None:
            raise ValueError("repair_proposed requires a patch")
        if self.disposition == "verified":
            if self.patch is None or self.patch.status != "applied":
                raise ValueError("verified findings require an applied patch")
            if self.verification is None or self.verification.status != "verified":
                raise ValueError("verified findings require successful verification")
        return self


class ReliabilityBrief(ReliabilityContract):
    status: Literal["verified_findings", "no_verified_findings", "incomplete"]
    commit_sha: str = Field(min_length=1)
    findings: list[ReliabilityFinding] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def brief_status_matches_evidence(self):
        verified = [finding for finding in self.findings if finding.disposition == "verified"]
        if self.status == "verified_findings" and not verified:
            raise ValueError("verified_findings requires at least one verified finding")
        if self.status == "no_verified_findings" and self.findings:
            raise ValueError("no_verified_findings cannot carry findings")
        if self.status != "incomplete" and self.unresolved:
            raise ValueError("only incomplete briefs can carry unresolved work")
        if self.status == "incomplete" and not self.unresolved:
            raise ValueError("incomplete briefs must name unresolved work")
        return self
