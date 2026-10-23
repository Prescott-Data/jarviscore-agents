"""The product contracts: what an agent may claim."""

import pytest
from pydantic import ValidationError

from gtm.contracts import Action, Assessment, GTMBrief, Judgement


def _assessment(*judgements):
    return Assessment(judgements=[
        Judgement(id=i, significance=s, because="Bears on the renewal.") for i, s in judgements
    ])


def test_an_assessment_covering_every_change_once_is_accepted():
    assessment = _assessment(("a", "act"), ("b", "ignore")).require_exactly(["a", "b"])
    assert [j.id for j in assessment.actionable] == ["a"]


@pytest.mark.parametrize(
    ("judged", "expected", "problem"),
    [
        ([("a", "act"), ("x", "note")], ["a"], "unknown"),
        ([("a", "act")], ["a", "b"], "unjudged"),
        ([("a", "act"), ("a", "note")], ["a"], "more than once"),
    ],
)
def test_an_assessment_may_not_invent_drop_or_repeat_a_change(judged, expected, problem):
    with pytest.raises(ValueError, match=problem):
        _assessment(*judged).require_exactly(expected)


def test_a_judgement_needs_a_known_verdict_and_a_reason():
    with pytest.raises(ValidationError):
        Judgement(id="a", significance="urgent", because="Big news.")
    with pytest.raises(ValidationError):
        Judgement(id="a", significance="act", because="")


def test_a_draft_or_completed_action_needs_the_providers_record():
    assert Action(action="Draft intro to Dana", state="proposed").record_id is None
    assert Action(action="Draft intro", state="drafted", system="gmail", record_id="r-1")
    with pytest.raises(ValidationError, match="record id"):
        Action(action="Sent intro to Dana", state="done", system="gmail")


def test_a_brief_carries_its_sources():
    brief = GTMBrief.model_validate({
        "decision": "hold",
        "summary": "Globex is hiring a VP of Operations; no contact verified yet.",
        "findings": [{"claim": "VP Ops req open", "source": "https://globex.example/careers/4471"}],
        "open_questions": ["Who owns the renewal?"],
    })
    assert brief.findings[0].source.startswith("https://")
    assert brief.actions == []
