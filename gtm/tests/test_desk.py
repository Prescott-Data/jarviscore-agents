"""The account-watch desk: observe, diff, judge, report, then remember."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gtm.agents import AccountExpert, GTMAgent
from gtm.cli import main
from gtm.contracts import Assessment
from gtm.demo import DEMO_ACCOUNT as GLOBEX
from gtm.demo import DEMO_FIXTURES as FIXTURES
from gtm.demo import DEMO_WATCHLISTS
from gtm.desk import AccountRun, commit, judged, run_desk
from gtm.prompts import render_assessment_request
from gtm.sources.fixture import FixtureError, FixtureSource
from gtm.state import AccountState
from gtm.store import AccountStore
from gtm.watchlist import load_watchlist

MONDAY = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
TUESDAY = MONDAY + timedelta(days=1)


async def _tuesday_delta():
    state = AccountState("globex", "Globex")
    monday = await FixtureSource(FIXTURES / "monday.json").collect(GLOBEX, now=MONDAY)
    state.commit(state.diff(monday))
    tuesday = await FixtureSource(FIXTURES / "tuesday.json").collect(GLOBEX, now=TUESDAY)
    return state.diff(tuesday)


async def test_a_second_day_of_the_same_surface_reports_only_what_moved():
    delta = await _tuesday_delta()
    assert delta.summary == "1 new, 1 changed, 2 unchanged"
    assert {e.observation.subject_key for e in delta.reportable} == {
        "https://globex.example/careers/4488",
        "https://globex.example/pricing",
    }


def test_a_malformed_fixture_is_refused(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"source": "serper"}', encoding="utf-8")
    with pytest.raises(FixtureError, match="records"):
        FixtureSource(bad)


async def test_the_task_carries_the_mandate_and_every_change_id():
    delta = await _tuesday_delta()
    task = render_assessment_request(GLOBEX, delta)
    assert GLOBEX.why in task
    for entry in delta.reportable:
        assert entry.observation.subject_id in task


async def test_a_complete_judgement_becomes_the_accounts_assessment():
    delta = await _tuesday_delta()
    first, second = (e.observation.subject_id for e in delta.reportable)
    output = {"judgements": [
        {"id": first, "significance": "act", "because": "A data-platform head owns our workflow."},
        {"id": second, "significance": "ignore", "because": "Pricing is not what we sell against."},
    ]}
    run = judged(GLOBEX, delta, {"status": "success", "output": output})
    assert run.error is None
    assert [j.id for j in run.assessment.actionable] == [first]


@pytest.mark.parametrize(
    "result",
    [
        {"status": "failure", "error": "provider is down"},
        {"status": "success", "output": {"judgements": []}},
        {"status": "success", "output": "Everything looks calm."},
    ],
)
async def test_an_unusable_judgement_is_an_error_not_a_quiet_morning(result):
    run = judged(GLOBEX, await _tuesday_delta(), result)
    assert run.error and run.assessment is None
    assert not run.committable


async def test_first_sight_is_a_baseline_and_needs_no_model(tmp_path: Path):
    watches = load_watchlist(DEMO_WATCHLISTS / "watchlist-globex-monday.yaml")
    store = AccountStore(tmp_path)

    first = await run_desk(watches, store, now=MONDAY)
    assert [run.seeded for run, _ in first] == [True]
    commit(first, store)

    again = await run_desk(watches, store, now=MONDAY)
    run, _ = again[0]
    assert not run.seeded and run.assessment is None and not run.delta.reportable


async def test_nothing_is_remembered_for_an_account_that_was_not_judged(tmp_path: Path):
    store = AccountStore(tmp_path)
    delta = await _tuesday_delta()
    failed = AccountRun(GLOBEX, delta, error="provider is down")
    commit([(failed, AccountState("globex", "Globex"))], store)
    assert not (tmp_path / "globex.json").exists()


def test_the_cli_seeds_the_demo_account(tmp_path: Path, capsys):
    watchlist = DEMO_WATCHLISTS / "watchlist-globex-monday.yaml"
    assert main(["run", "--watchlist", str(watchlist), "--state-dir", str(tmp_path)]) == 0
    assert "baseline recorded" in capsys.readouterr().out
    assert (tmp_path / "globex.json").is_file()


def test_only_the_agent_that_calls_providers_gets_credentials():
    assert GTMAgent.requires_auth is True
    assert AccountExpert.requires_auth is False
    assert AccountExpert.output_schema is Assessment
