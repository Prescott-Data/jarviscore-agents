from software_reliability.benchmark import BenchmarkCase, ExpectedDefect, score_cases
from software_reliability.demo import run_demo


def test_seed_benchmark_scores_stable_ids_and_verified_evidence():
    finding = run_demo()
    report = score_cases(
        [
            BenchmarkCase(
                case_id="case_service_auth_bypass",
                commit_sha="fixture-v1",
                expected_defects=[
                    ExpectedDefect(
                        finding_id="finding_service_auth_bypass",
                        category="security",
                    )
                ],
                findings=[finding],
                elapsed_ms=100,
            )
        ]
    )

    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.reproduction_coverage == 1.0
    assert report.verified_repair_rate == 1.0
    assert report.weakened_test_repairs == 0


def test_false_positive_reduces_precision_without_changing_recall():
    finding = run_demo()
    false_positive = finding.model_copy(deep=True)
    false_positive.candidate.finding_id = "finding_not_in_ground_truth"
    false_positive.reproduction.finding_id = "finding_not_in_ground_truth"
    false_positive.priority.finding_id = "finding_not_in_ground_truth"
    false_positive.patch.finding_id = "finding_not_in_ground_truth"
    false_positive.verification.finding_id = "finding_not_in_ground_truth"

    report = score_cases(
        [
            BenchmarkCase(
                case_id="case_service_auth_bypass",
                commit_sha="fixture-v1",
                expected_defects=[
                    ExpectedDefect(
                        finding_id="finding_service_auth_bypass",
                        category="security",
                    )
                ],
                findings=[finding, false_positive],
                elapsed_ms=100,
            )
        ]
    )

    assert report.precision == 0.5
    assert report.recall == 1.0
