from datetime import datetime, timezone

import pytest
from jarviscore import CommandObservation, WorkspaceMutation
from pydantic import ValidationError

from software_reliability.contracts import (
    CandidateFinding,
    FindingPortfolio,
    PatchArtifact,
    PriorityAssessment,
    RejectedHypothesis,
    ReliabilityBrief,
    ReliabilityFinding,
    RepositoryMap,
    ReproductionEvidence,
    SourceLocation,
    VerificationReport,
)

TEST_SELECTOR = "tests/test_authorization.py::test_service_path_requires_admin"


def observation(exit_code: int) -> CommandObservation:
    return CommandObservation(
        tool_receipt_id=f"tool:test:{exit_code}",
        command=["python", "-m", "pytest", "-q", TEST_SELECTOR],
        exit_code=exit_code,
        stderr="assert False" if exit_code else "",
        duration_ms=24,
        observed_at=datetime.now(timezone.utc),
    )


def selection_observation(stdout: str = TEST_SELECTOR) -> CommandObservation:
    return CommandObservation(
        tool_receipt_id="tool:test:selection",
        command=["python", "-m", "pytest", "--collect-only", "-q", TEST_SELECTOR],
        exit_code=0,
        stdout=stdout,
        duration_ms=12,
        observed_at=datetime.now(timezone.utc),
    )


def candidate() -> CandidateFinding:
    return CandidateFinding(
        finding_id="finding_service_auth_bypass",
        title="Service path bypasses administrator authorization",
        category="security",
        invariant="Every filesystem-serving path requires administrator authorization.",
        actual_behavior="Service handlers bypass the path-handler authorization check.",
        expected_behavior="Service handlers participate in the same authorization check.",
        impact="A non-admin user can configure an unauthorized filesystem path.",
        locations=[SourceLocation(path="src/serve.py", start_line=8, end_line=14)],
        evidence_refs=["tests/test_authorization.py::test_service_path_requires_admin"],
    )


def rejected_hypothesis() -> RejectedHypothesis:
    return RejectedHypothesis(
        hypothesis_id="hypothesis_service_auth_is_enforced",
        title="Service authorization bypass was not reachable",
        invariant="Every filesystem-serving path requires administrator authorization.",
        trigger="A non-admin request selects a service-scoped filesystem path.",
        expected_failure="The request bypasses the administrator check.",
        observed_evidence="The focused authorization test rejected the request.",
        locations=[SourceLocation(path="src/serve.py", start_line=8, end_line=14)],
        evidence_refs=["tool:test:authorization"],
    )


def mutation(path: str) -> WorkspaceMutation:
    return WorkspaceMutation(
        tool_receipt_id=f"tool:test:{path}",
        path=path,
        sha256="0123456789abcdef",
        bytes=1,
        executable=False,
        observed_at=datetime.now(timezone.utc),
    )


def reproduced() -> ReproductionEvidence:
    return ReproductionEvidence(
        finding_id="finding_service_auth_bypass",
        status="reproduced",
        test_path="tests/test_authorization.py",
        test_selector=TEST_SELECTOR,
        selection_run=selection_observation(),
        vulnerable_run=observation(1),
        expected_behavior="A non-admin request is rejected.",
        observed_behavior="The request is accepted.",
    )


def priority() -> PriorityAssessment:
    return PriorityAssessment(
        finding_id="finding_service_auth_bypass",
        decision="promote",
        priority="P1",
        rationale="The defect crosses an authorization boundary.",
        user_impact="A non-admin user can configure an unauthorized path.",
        exploitability="A crafted service path triggers the bypass.",
        likelihood="Configuration paths are routinely exercised.",
        blast_radius="Every service-scoped filesystem handler is affected.",
        evidence_refs=["tests/test_authorization.py::test_service_path_requires_admin"],
    )


def test_reproduced_finding_requires_a_failing_command():
    with pytest.raises(ValidationError, match="failing vulnerable run"):
        ReproductionEvidence(
            finding_id="finding_service_auth_bypass",
            status="reproduced",
            test_path="tests/test_authorization.py",
            test_selector=TEST_SELECTOR,
            selection_run=selection_observation(),
            vulnerable_run=observation(0),
            expected_behavior="A non-admin request is rejected.",
            observed_behavior="The request is accepted.",
        )


def test_reproduction_rejects_a_selector_absent_from_collection_output():
    with pytest.raises(ValidationError, match="collection output must contain"):
        ReproductionEvidence(
            finding_id="finding_service_auth_bypass",
            status="reproduced",
            test_path="tests/test_authorization.py",
            test_selector=TEST_SELECTOR,
            selection_run=selection_observation("0 tests collected"),
            vulnerable_run=observation(1),
            expected_behavior="A non-admin request is rejected.",
            observed_behavior="The request is accepted.",
        )


def test_blocked_patch_requires_a_typed_blocker():
    with pytest.raises(ValidationError, match="typed blocking kind"):
        PatchArtifact(
            finding_id="finding_service_auth_bypass",
            status="blocked",
            rationale="The repair cannot proceed.",
        )


def test_not_applicable_patch_cannot_claim_mutations():
    with pytest.raises(ValidationError, match="cannot carry workspace mutations"):
        PatchArtifact(
            finding_id="finding_service_auth_bypass",
            status="not_applicable",
            diff="+ speculative change",
            changed_files=["src/serve.py"],
            mutations=[mutation("src/serve.py")],
            rationale="No reproduced finding exists.",
        )


def test_ready_repository_map_requires_an_executed_baseline():
    ready = RepositoryMap(
        status="ready",
        commit_sha="abc123",
        languages=["python"],
        test_commands=[["python", "-m", "pytest"]],
        baseline_runs=[observation(0)],
    )
    assert ready.baseline_runs[0].exit_code == 0

    with pytest.raises(ValidationError, match="executed baseline command"):
        RepositoryMap(status="ready", commit_sha="abc123", languages=["python"])
    with pytest.raises(ValidationError, match="needs unresolved facts"):
        RepositoryMap(status="incomplete", commit_sha="abc123", languages=["python"])


def test_not_applicable_verification_requires_passing_regressions_only():
    report = VerificationReport(
        finding_id="finding_missing_upstream_candidates",
        status="not_applicable",
        regression_runs=[observation(0)],
        unresolved_risks=["No repair transition existed."],
    )
    assert report.reproduction_before is None

    with pytest.raises(ValidationError, match="passing independent regressions"):
        VerificationReport(
            finding_id="finding_missing_upstream_candidates",
            status="not_applicable",
            regression_runs=[observation(1)],
        )


def test_no_candidates_cannot_claim_an_executed_reproduction():
    with pytest.raises(ValidationError, match="cannot claim an executed reproduction"):
        ReproductionEvidence(
            finding_id="finding_missing_upstream_candidates",
            status="no_candidates",
            test_path="tests/test_unrelated.py",
            vulnerable_run=observation(1),
            expected_behavior="A concrete candidate exists before reproduction.",
            observed_behavior="No upstream portfolio contained a candidate.",
        )

    product = ReproductionEvidence(
        finding_id="finding_missing_upstream_candidates",
        status="no_candidates",
        expected_behavior="A concrete candidate exists before reproduction.",
        observed_behavior="No upstream portfolio contained a candidate.",
    )

    assert product.vulnerable_run is None


def test_completed_negative_portfolio_requires_typed_rejected_hypotheses():
    with pytest.raises(ValidationError, match="explicit rejected hypotheses"):
        FindingPortfolio(
            status="no_actionable_findings",
            commit_sha="abc123",
            searched_surfaces=["src/serve.py authorization path"],
        )

    portfolio = FindingPortfolio(
        status="no_actionable_findings",
        commit_sha="abc123",
        rejected_hypotheses=[rejected_hypothesis()],
        searched_surfaces=["src/serve.py authorization path"],
        unresolved=["Windows ACL behavior was not exercised."],
    )

    assert portfolio.rejected_hypotheses[0].hypothesis_id == (
        "hypothesis_service_auth_is_enforced"
    )


def test_negative_brief_separates_residual_risk_from_unfinished_work():
    brief = ReliabilityBrief(
        status="no_verified_findings",
        commit_sha="abc123",
        residual_risks=["Windows was not exercised."],
    )
    assert brief.unresolved == []

    with pytest.raises(ValidationError, match="only incomplete briefs"):
        ReliabilityBrief(
            status="no_verified_findings",
            commit_sha="abc123",
            unresolved=["Required stress execution did not run."],
        )

    incomplete = ReliabilityBrief(
        status="incomplete",
        commit_sha="abc123",
        residual_risks=["Windows was not exercised."],
        unresolved=["Required stress execution did not run."],
    )
    assert incomplete.status == "incomplete"


def test_verified_finding_requires_fail_then_pass_without_weakened_tests():
    finding = ReliabilityFinding(
        candidate=candidate(),
        reproduction=reproduced(),
        priority=priority(),
        patch=PatchArtifact(
            finding_id="finding_service_auth_bypass",
            status="applied",
            diff="- return False\n+ return service_has_path\n",
            changed_files=["src/serve.py", "tests/test_authorization.py"],
            mutations=[
                mutation("src/serve.py"),
                mutation("tests/test_authorization.py"),
            ],
            rationale="Include service handlers in the existing authorization predicate.",
        ),
        verification=VerificationReport(
            finding_id="finding_service_auth_bypass",
            status="verified",
            test_selector=TEST_SELECTOR,
            selection_run=selection_observation(),
            reproduction_before=observation(1),
            reproduction_after=observation(0),
            regression_runs=[observation(0)],
        ),
        disposition="verified",
    )

    assert finding.disposition == "verified"


@pytest.mark.parametrize(
    ("after_exit_code", "tests_weakened", "message"),
    [
        (1, False, "passing post-patch reproduction"),
        (0, True, "weakens tests"),
    ],
)
def test_verification_rejects_unproven_or_test_weakening_repairs(
    after_exit_code: int, tests_weakened: bool, message: str
):
    with pytest.raises(ValidationError, match=message):
        VerificationReport(
            finding_id="finding_service_auth_bypass",
            status="verified",
            test_selector=TEST_SELECTOR,
            selection_run=selection_observation(),
            reproduction_before=observation(1),
            reproduction_after=observation(after_exit_code),
            tests_weakened=tests_weakened,
        )


def test_verification_rejects_a_selector_absent_from_collection_output():
    with pytest.raises(ValidationError, match="collection output must contain"):
        VerificationReport(
            finding_id="finding_service_auth_bypass",
            status="verified",
            test_selector=TEST_SELECTOR,
            selection_run=selection_observation("0 tests collected"),
            reproduction_before=observation(1),
            reproduction_after=observation(0),
        )


def test_verified_disposition_cannot_skip_patch_or_verification():
    with pytest.raises(ValidationError, match="applied patch"):
        ReliabilityFinding(
            candidate=candidate(),
            reproduction=reproduced(),
            priority=priority(),
            disposition="verified",
        )


def test_reliability_finding_rejects_mixed_finding_identity():
    mismatched = reproduced().model_copy(
        update={"finding_id": "finding_other_defect"}
    )

    with pytest.raises(ValidationError, match="share one finding_id"):
        ReliabilityFinding(
            candidate=candidate(),
            reproduction=mismatched,
            disposition="reproduced",
        )
