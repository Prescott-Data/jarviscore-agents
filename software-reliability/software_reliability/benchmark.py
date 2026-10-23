"""Transparent scoring for software-reliability benchmark cases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from software_reliability.contracts import ReliabilityFinding


class BenchmarkContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedDefect(BenchmarkContract):
    finding_id: str = Field(pattern=r"^finding_[a-z0-9][a-z0-9_-]+$")
    category: str = Field(min_length=1)
    must_reproduce: bool = True
    repairable: bool = True


class BenchmarkCase(BenchmarkContract):
    case_id: str = Field(pattern=r"^case_[a-z0-9][a-z0-9_-]+$")
    commit_sha: str = Field(min_length=1)
    expected_defects: list[ExpectedDefect] = Field(min_length=1)
    findings: list[ReliabilityFinding] = Field(default_factory=list)
    elapsed_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    cost_usd: float = Field(ge=0, default=0.0)

    @model_validator(mode="after")
    def finding_ids_are_unique(self):
        ids = [finding.candidate.finding_id for finding in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("a benchmark case cannot surface the same finding twice")
        return self


class BenchmarkReport(BenchmarkContract):
    cases: int
    expected_defects: int
    surfaced_findings: int
    true_positive_findings: int
    verified_repairs: int
    reproduced_expected_defects: int
    weakened_test_repairs: int
    precision: float
    recall: float
    reproduction_coverage: float
    verified_repair_rate: float
    elapsed_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score_cases(cases: list[BenchmarkCase]) -> BenchmarkReport:
    expected_count = 0
    surfaced_count = 0
    true_positives = 0
    reproduced = 0
    repairable_count = 0
    verified = 0
    weakened = 0

    for case in cases:
        expected = {item.finding_id: item for item in case.expected_defects}
        findings = {item.candidate.finding_id: item for item in case.findings}
        expected_count += len(expected)
        surfaced_count += len(findings)
        true_positives += len(set(expected).intersection(findings))
        repairable_count += sum(item.repairable for item in expected.values())
        for finding_id, defect in expected.items():
            finding = findings.get(finding_id)
            if finding is None:
                continue
            if defect.must_reproduce and finding.reproduction.status == "reproduced":
                reproduced += 1
            elif not defect.must_reproduce:
                reproduced += 1
            if (
                defect.repairable
                and finding.verification is not None
                and finding.verification.status == "verified"
            ):
                verified += 1
            if finding.verification is not None and finding.verification.tests_weakened:
                weakened += 1

    return BenchmarkReport(
        cases=len(cases),
        expected_defects=expected_count,
        surfaced_findings=surfaced_count,
        true_positive_findings=true_positives,
        verified_repairs=verified,
        reproduced_expected_defects=reproduced,
        weakened_test_repairs=weakened,
        precision=_ratio(true_positives, surfaced_count),
        recall=_ratio(true_positives, expected_count),
        reproduction_coverage=_ratio(reproduced, expected_count),
        verified_repair_rate=_ratio(verified, repairable_count),
        elapsed_ms=sum(case.elapsed_ms for case in cases),
        input_tokens=sum(case.input_tokens for case in cases),
        output_tokens=sum(case.output_tokens for case in cases),
        cost_usd=sum(case.cost_usd for case in cases),
    )
