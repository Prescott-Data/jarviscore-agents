"""What the desk remembers about an account between runs.

This is the difference between an agent that has a memory and one that
re-reads the internet every morning. It holds, per subject, the last state
the desk saw — so the next run can be a diff rather than a fresh scrape.

Reading and recording are deliberately separate calls:

:meth:`AccountState.diff`
    Pure. Classifies observations against what is known. Changes nothing.
:meth:`AccountState.commit`
    Records a delta as seen.

Keeping them apart matters more than it looks. If a run marked observations
as seen at the moment it read them, a crash between reading and reporting
would bury that news permanently — the second run would find nothing new and
the signal would be lost for good. So the desk commits *after* the human has
been told, and a crash costs a duplicate report rather than a missed one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from gtm.state.observation import Observation


class Novelty(str, Enum):
    """How an observation relates to what the desk already knew."""

    NEW = "new"              # this subject has never been seen
    CHANGED = "changed"      # seen before, in a different state
    UNCHANGED = "unchanged"  # seen before, identical


@dataclass(frozen=True)
class FieldChange:
    """One salient field that moved, and what it moved from."""

    field: str
    before: Any
    after: Any

    def __str__(self) -> str:
        return f"{self.field}: {self.before!r} → {self.after!r}"


@dataclass(frozen=True)
class ObservationDelta:
    """An observation, classified."""

    observation: Observation
    novelty: Novelty
    changes: tuple[FieldChange, ...] = ()

    @property
    def is_reportable(self) -> bool:
        return self.novelty is not Novelty.UNCHANGED


@dataclass(frozen=True)
class Delta:
    """The result of one run's observations against remembered state."""

    account_id: str
    entries: tuple[ObservationDelta, ...] = ()

    @property
    def new(self) -> tuple[ObservationDelta, ...]:
        return tuple(e for e in self.entries if e.novelty is Novelty.NEW)

    @property
    def changed(self) -> tuple[ObservationDelta, ...]:
        return tuple(e for e in self.entries if e.novelty is Novelty.CHANGED)

    @property
    def unchanged(self) -> tuple[ObservationDelta, ...]:
        return tuple(e for e in self.entries if e.novelty is Novelty.UNCHANGED)

    @property
    def reportable(self) -> tuple[ObservationDelta, ...]:
        """Everything an agent should be asked to consider. May still be noise."""
        return tuple(e for e in self.entries if e.is_reportable)

    def __bool__(self) -> bool:
        return bool(self.reportable)

    @property
    def summary(self) -> str:
        return (
            f"{len(self.new)} new, {len(self.changed)} changed, "
            f"{len(self.unchanged)} unchanged"
        )


def _diff_salient(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[FieldChange, ...]:
    missing = object()
    fields = sorted(set(before) | set(after))
    return tuple(
        FieldChange(
            field=name,
            before=None if before.get(name, missing) is missing else before[name],
            after=None if after.get(name, missing) is missing else after[name],
        )
        for name in fields
        if before.get(name, missing) != after.get(name, missing)
    )


@dataclass
class _KnownSubject:
    """The last state the desk saw of one subject."""

    observation_id: str
    source: str
    subject_key: str
    salient: dict[str, Any]
    first_seen: datetime
    last_seen: datetime


@dataclass
class AccountState:
    """One account's dossier, carried between runs."""

    account_id: str
    name: str
    subjects: dict[str, _KnownSubject] = field(default_factory=dict)

    @property
    def has_memory(self) -> bool:
        """Whether the desk has ever seen this account.

        The first sight of an account is a baseline, not news: every job, page
        and post in existence would be 'new'. Callers use this to record the
        starting position rather than reporting the entire internet as change.
        """
        return bool(self.subjects)

    def diff(self, observations: Iterable[Observation]) -> Delta:
        """Classify observations against what is known. Records nothing."""
        entries: list[ObservationDelta] = []
        for observation in observations:
            if observation.account_id != self.account_id:
                raise ValueError(
                    f"observation belongs to account {observation.account_id!r}, "
                    f"not {self.account_id!r}"
                )
            known = self.subjects.get(observation.subject_id)
            if known is None:
                entries.append(ObservationDelta(observation, Novelty.NEW))
            elif known.observation_id == observation.observation_id:
                entries.append(ObservationDelta(observation, Novelty.UNCHANGED))
            else:
                entries.append(
                    ObservationDelta(
                        observation,
                        Novelty.CHANGED,
                        _diff_salient(known.salient, dict(observation.salient)),
                    )
                )
        return Delta(self.account_id, tuple(entries))

    def commit(self, delta: Delta) -> None:
        """Record a delta as seen. Call this after the human has been told."""
        if delta.account_id != self.account_id:
            raise ValueError(
                f"delta belongs to account {delta.account_id!r}, not {self.account_id!r}"
            )
        for entry in delta.entries:
            observation = entry.observation
            known = self.subjects.get(observation.subject_id)
            if known is None:
                self.subjects[observation.subject_id] = _KnownSubject(
                    observation_id=observation.observation_id,
                    source=observation.source,
                    subject_key=observation.subject_key,
                    salient=dict(observation.salient),
                    first_seen=observation.observed_at,
                    last_seen=observation.observed_at,
                )
                continue
            known.observation_id = observation.observation_id
            known.salient = dict(observation.salient)
            known.last_seen = max(known.last_seen, observation.observed_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form, for the account blob in UnifiedMemory."""
        return {
            "account_id": self.account_id,
            "name": self.name,
            "subjects": {
                subject_id: {
                    "observation_id": s.observation_id,
                    "source": s.source,
                    "subject_key": s.subject_key,
                    "salient": s.salient,
                    "first_seen": s.first_seen.isoformat(),
                    "last_seen": s.last_seen.isoformat(),
                }
                for subject_id, s in self.subjects.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AccountState:
        return cls(
            account_id=raw["account_id"],
            name=raw["name"],
            subjects={
                subject_id: _KnownSubject(
                    observation_id=s["observation_id"],
                    source=s["source"],
                    subject_key=s["subject_key"],
                    salient=dict(s["salient"]),
                    first_seen=datetime.fromisoformat(s["first_seen"]),
                    last_seen=datetime.fromisoformat(s["last_seen"]),
                )
                for subject_id, s in raw.get("subjects", {}).items()
            },
        )
