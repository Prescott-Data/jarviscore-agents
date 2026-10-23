import pytest
from pydantic import BaseModel

from software_reliability import prompts
from software_reliability.agents import (
    INSPECT,
    ROLES,
    RUN,
    ImpactAnalyst,
    RepairEngineer,
    RepositoryCartographer,
    ReproductionEngineer,
    VerificationEngineer,
)
from software_reliability.demo import run_demo


@pytest.mark.parametrize("role", ROLES, ids=lambda role: role.role)
def test_every_role_declares_a_typed_capability_contract(role):
    assert issubclass(role.output_schema, BaseModel)
    assert set(role.capability_contracts) == set(role.capabilities)
    assert set(role.capability_descriptions) == set(role.capabilities)
    assert prompts.TEAM in role.system_prompt
    assert role.requires_auth is False
    assert role.default_kernel_role in {"coder", "communicator"}


def test_only_the_strategist_gives_the_final_response():
    final = [
        role.role
        for role in ROLES
        for contract in role.capability_contracts.values()
        if "final_response" in contract["effects"]
    ]
    assert final == ["reliability_strategist"]


def test_steps_that_must_use_tools_declare_them():
    cartographer = RepositoryCartographer()
    context = {"capability": "test_discovery", "execution_contract": {"kernel_role": "coder"}}

    contract = cartographer.step_context(context)["execution_contract"]

    assert contract == {"kernel_role": "coder", "required_tool_groups": [INSPECT, RUN]}
    assert ImpactAnalyst().step_context({"capability": "impact_assessment"}) == {
        "capability": "impact_assessment"
    }


def test_valid_work_products_pass_their_role_contract():
    finding = run_demo()
    checks = [
        (ReproductionEngineer(), finding.reproduction),
        (RepairEngineer(), finding.patch),
        (VerificationEngineer(), finding.verification),
    ]
    for agent, artifact in checks:
        result = {"status": "success", "output": artifact.model_dump(mode="json")}
        assert agent.check_contract(result) == result


def test_a_result_that_breaks_its_contract_is_a_failure():
    reproduction = run_demo().reproduction.model_dump(mode="json")
    reproduction["vulnerable_run"]["exit_code"] = 0

    result = ReproductionEngineer().check_contract(
        {"status": "success", "output": reproduction, "result_summary": "Reproduced."}
    )

    assert result["status"] == "failure"
    assert "failing vulnerable run" in result["error"]
    assert result["result_summary"] == result["error"]


def test_unsuccessful_results_pass_through_unchanged():
    failure = {"status": "failure", "output": None, "error": "No workspace."}
    assert VerificationEngineer().check_contract(failure) == failure
