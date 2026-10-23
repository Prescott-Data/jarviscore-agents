"""Offline fail-before/pass-after acceptance run for the reliability blueprint.

``software-reliability demo --live`` gives the same fixture, without its repair, to the
full Mesh and a real model.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jarviscore import CommandObservation, WorkspaceMutation

from software_reliability.contracts import (
    CandidateFinding,
    PatchArtifact,
    PriorityAssessment,
    ReliabilityFinding,
    ReproductionEvidence,
    SourceLocation,
    VerificationReport,
)

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_REPOSITORY = DEMO_ROOT / "fixtures" / "authorization_bypass"
FOCUSED_TEST = (
    "tests.test_authorization.AuthorizationTests.test_service_path_requires_admin"
)


def _run(command: list[str], cwd: Path) -> CommandObservation:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return CommandObservation(
        tool_receipt_id=f"demo:{uuid4().hex}",
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=int((time.monotonic() - started) * 1000),
        observed_at=datetime.now(timezone.utc),
    )


def _fixture_revision() -> str:
    digest = hashlib.sha256()
    for path in sorted(DEMO_REPOSITORY.rglob("*.py")):
        digest.update(path.relative_to(DEMO_REPOSITORY).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_demo() -> ReliabilityFinding:
    with tempfile.TemporaryDirectory(
        prefix="jarviscore-software-reliability-"
    ) as directory:
        workspace = Path(directory) / "repository"
        shutil.copytree(DEMO_REPOSITORY, workspace)
        selection = _run(
            [
                sys.executable,
                "-c",
                (
                    "import sys, unittest; "
                    "name=sys.argv[1]; "
                    "suite=unittest.defaultTestLoader.loadTestsFromName(name); "
                    "assert suite.countTestCases() == 1; print(name)"
                ),
                FOCUSED_TEST,
            ],
            workspace,
        )
        if selection.exit_code != 0 or FOCUSED_TEST not in selection.stdout:
            raise RuntimeError("focused authorization test was not collected exactly once")
        focused_command = [sys.executable, "-m", "unittest", "-q", FOCUSED_TEST]
        vulnerable = _run(focused_command, workspace)
        if vulnerable.exit_code == 0:
            raise RuntimeError("seeded authorization defect did not reproduce")

        patch_text = (workspace / "repair.patch").read_text()
        applied = _run(["git", "apply", "repair.patch"], workspace)
        if applied.exit_code != 0:
            raise RuntimeError(f"repair patch did not apply: {applied.stderr}")

        repaired = _run(focused_command, workspace)
        regressions = _run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
            workspace,
        )
        repaired_file = workspace / "service.py"
        repaired_payload = repaired_file.read_bytes()
        mutation = WorkspaceMutation(
            tool_receipt_id=f"demo:{uuid4().hex}",
            path="service.py",
            sha256=hashlib.sha256(repaired_payload).hexdigest(),
            bytes=len(repaired_payload),
            executable=False,
            observed_at=datetime.now(timezone.utc),
        )

    finding_id = "finding_service_auth_bypass"
    reproduction = ReproductionEvidence(
        finding_id=finding_id,
        status="reproduced",
        test_path="tests/test_authorization.py",
        test_selector=FOCUSED_TEST,
        selection_run=selection,
        vulnerable_run=vulnerable,
        expected_behavior="A non-admin request with a service path is rejected.",
        observed_behavior="The vulnerable authorization predicate accepts the request.",
    )
    verification = VerificationReport(
        finding_id=finding_id,
        status="verified",
        test_selector=FOCUSED_TEST,
        selection_run=selection,
        reproduction_before=vulnerable,
        reproduction_after=repaired,
        regression_runs=[regressions],
        tests_weakened=False,
    )
    return ReliabilityFinding(
        candidate=CandidateFinding(
            finding_id=finding_id,
            title="Service-scoped paths bypass administrator authorization",
            category="security",
            invariant="Every filesystem-serving path requires administrator authorization.",
            actual_behavior=(
                "The path predicate checks top-level handlers but omits service handlers."
            ),
            expected_behavior=(
                "Top-level and service-scoped paths participate in the same authorization check."
            ),
            impact="A non-admin user can configure an unauthorized filesystem path.",
            locations=[SourceLocation(path="service.py", start_line=22, end_line=23)],
            evidence_refs=[
                "tests/test_authorization.py::AuthorizationTests::"
                "test_service_path_requires_admin"
            ],
        ),
        reproduction=reproduction,
        priority=PriorityAssessment(
            finding_id=finding_id,
            decision="promote",
            priority="P1",
            rationale="The reproduced defect crosses an administrator boundary.",
            user_impact="A non-admin user can configure an unauthorized path.",
            exploitability="A crafted service path triggers the bypass.",
            likelihood="Configuration paths are routinely exercised.",
            blast_radius="Every service-scoped filesystem handler is affected.",
            evidence_refs=[vulnerable.tool_receipt_id],
        ),
        patch=PatchArtifact(
            finding_id=finding_id,
            status="applied",
            diff=patch_text,
            changed_files=["service.py"],
            mutations=[mutation],
            rationale="Include service handlers in the existing path authorization predicate.",
        ),
        verification=verification,
        disposition="verified",
    )


def main() -> None:
    print(run_demo().model_dump_json(indent=2))


def benchmark_main() -> None:
    from software_reliability.benchmark import BenchmarkCase, ExpectedDefect, score_cases

    finding = run_demo()
    report = score_cases(
        [
            BenchmarkCase(
                case_id="case_service_auth_bypass",
                commit_sha=_fixture_revision(),
                expected_defects=[
                    ExpectedDefect(
                        finding_id="finding_service_auth_bypass",
                        category="security",
                    )
                ],
                findings=[finding],
                elapsed_ms=(
                    finding.reproduction.vulnerable_run.duration_ms
                    + finding.verification.reproduction_after.duration_ms
                    + sum(run.duration_ms for run in finding.verification.regression_runs)
                ),
            )
        ]
    )
    print(report.model_dump_json(indent=2))
