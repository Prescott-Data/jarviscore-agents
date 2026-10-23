from software_reliability.demo import run_demo


def test_demo_proves_fail_before_pass_after_without_weakening_tests():
    finding = run_demo()

    assert finding.disposition == "verified"
    assert finding.reproduction.vulnerable_run.exit_code != 0
    assert finding.verification is not None
    assert finding.verification.reproduction_after.exit_code == 0
    assert finding.verification.tests_weakened is False
    assert finding.patch is not None
    assert finding.patch.changed_files == ["service.py"]
