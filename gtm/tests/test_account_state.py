"""The Tuesday problem: run the same source twice, hear about it once."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gtm.state import AccountState, Novelty, Observation, ObservationError

MONDAY = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
TUESDAY = MONDAY + timedelta(days=1)


def posting(observed_at=MONDAY, title="VP of Operations", payload=None):
    return Observation(
        account_id="globex",
        source="serper",
        subject_key="https://globex.example/careers/4471",
        salient={"title": title, "location": "Leeds"},
        observed_at=observed_at,
        payload=payload or {},
    )


def desk():
    return AccountState(account_id="globex", name="Globex")


def test_second_run_of_an_unchanged_source_reports_nothing():
    state = desk()

    monday = state.diff([posting()])
    assert [e.novelty for e in monday.entries] == [Novelty.NEW]
    state.commit(monday)

    tuesday = state.diff([posting(observed_at=TUESDAY)])
    assert [e.novelty for e in tuesday.entries] == [Novelty.UNCHANGED]
    assert tuesday.reportable == ()
    assert not tuesday


def test_a_changed_field_is_news_and_the_desk_can_say_what_moved():
    state = desk()
    state.commit(state.diff([posting()]))

    delta = state.diff([posting(observed_at=TUESDAY, title="Director of Operations")])

    (entry,) = delta.changed
    assert entry.novelty is Novelty.CHANGED
    assert [str(c) for c in entry.changes] == [
        "title: 'VP of Operations' → 'Director of Operations'"
    ]


def test_payload_noise_cannot_manufacture_news():
    state = desk()
    state.commit(state.diff([posting(payload={"applicants": 12, "rank": 3})]))

    delta = state.diff([posting(observed_at=TUESDAY, payload={"applicants": 88, "rank": 1})])

    assert delta.unchanged and not delta.reportable


def test_identity_ignores_when_it_was_seen_and_how_the_dict_was_ordered():
    first = Observation(
        account_id="globex",
        source="serper",
        subject_key="k",
        salient={"a": 1, "b": 2},
        observed_at=MONDAY,
    )
    second = Observation(
        account_id="globex",
        source="serper",
        subject_key="k",
        salient={"b": 2, "a": 1},
        observed_at=TUESDAY,
    )
    assert first.observation_id == second.observation_id


def test_the_same_key_from_a_different_source_is_a_different_subject():
    args = {
        "account_id": "globex",
        "subject_key": "k",
        "salient": {"a": 1},
        "observed_at": MONDAY,
    }
    assert (
        Observation(source="serper", **args).subject_id
        != Observation(source="linkedin", **args).subject_id
    )


def test_a_crash_before_commit_costs_a_duplicate_not_a_missed_signal():
    state = desk()
    first = state.diff([posting()])
    assert first.new  # reported, then the process dies before commit

    second = state.diff([posting(observed_at=TUESDAY)])
    assert second.new  # said again rather than lost


def test_state_survives_a_round_trip_through_serialisation():
    state = desk()
    state.commit(state.diff([posting()]))

    restored = AccountState.from_dict(state.to_dict())

    assert restored.diff([posting(observed_at=TUESDAY)]).unchanged


def test_delta_summary_counts_every_class():
    state = desk()
    state.commit(state.diff([posting()]))
    delta = state.diff(
        [
            posting(observed_at=TUESDAY),
            Observation(
                account_id="globex",
                source="serper",
                subject_key="https://globex.example/careers/9999",
                salient={"title": "Head of Data"},
                observed_at=TUESDAY,
            ),
        ]
    )
    assert delta.summary == "1 new, 0 changed, 1 unchanged"


def test_a_source_without_a_stable_key_is_refused_rather_than_guessed():
    with pytest.raises(ObservationError):
        Observation(
            account_id="globex",
            source="serper",
            subject_key="   ",
            salient={"a": 1},
            observed_at=MONDAY,
        )


def test_an_observation_that_says_nothing_is_refused():
    with pytest.raises(ObservationError, match="non-empty mapping"):
        Observation(
            account_id="globex",
            source="serper",
            subject_key="k",
            salient={},
            observed_at=MONDAY,
        )


def test_values_without_a_stable_json_form_are_refused():
    with pytest.raises(ObservationError, match="cannot be hashed reliably"):
        Observation(
            account_id="globex",
            source="serper",
            subject_key="k",
            salient={"seen_at": MONDAY},
            observed_at=MONDAY,
        )


def test_observations_for_another_account_are_refused():
    with pytest.raises(ValueError, match="not 'globex'"):
        desk().diff(
            [
                Observation(
                    account_id="initech",
                    source="serper",
                    subject_key="k",
                    salient={"a": 1},
                    observed_at=MONDAY,
                )
            ]
        )
