"""What the desk saw, and how it knows it has seen it before.

An account watcher is only worth running if it can tell you what is *new*.
The failure mode of every "AI monitors your accounts" tool is the Tuesday
problem: it reports the same job posting on Tuesday that it reported on
Monday, you stop reading it by Thursday, and it is uninstalled by Friday.

Novelty here is computed, not judged. Two identities do the work:

``subject_id``
    Identity of the *thing* — this job posting, this pricing page, this
    executive's account. Derived from the account, the source, and the
    source's own stable key for the record.
``observation_id``
    Identity of the thing's *state* — the subject plus the fields whose
    change constitutes news.

Same posting seen twice hashes the same and is silently dropped. The same
posting with a changed title hashes differently, and because the prior state
is retained the desk can say what moved rather than only that something did.

The split between ``salient`` and ``payload`` is the whole design. ``salient``
is the handful of fields that mean something changed; ``payload`` is
everything else the source returned. View counts, scrape timestamps and
pagination cursors belong in ``payload``, where they cannot manufacture news.

Deciding *whether a change matters* is not done here. That is judgement, it
needs context, and it belongs to an agent. This module only answers the
mechanical question of whether something is the same as before.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_SEPARATOR = b"\x1f"


class ObservationError(ValueError):
    """A source produced something that cannot be given a stable identity."""


def _validate_json_value(value: Any, path: str) -> None:
    """Reject anything whose JSON form is not stable across processes."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ObservationError(f"{path}: non-finite float has no stable identity")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ObservationError(f"{path}: keys must be strings, got {type(key).__name__}")
            _validate_json_value(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    raise ObservationError(
        f"{path}: {type(value).__name__} cannot be hashed reliably — "
        "convert it to a string, number or mapping in the source adapter"
    )


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=None,
    )


def _digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(_SEPARATOR)  # so ("ab","c") cannot collide with ("a","bc")
    return digest.hexdigest()


@dataclass(frozen=True)
class Observation:
    """One record from one source about one account, at one moment.

    Args:
        account_id: The account this concerns.
        source: Which source produced it — ``serper``, ``linkedin``, ``hubspot``.
        subject_key: The source's own stable key for this record. A posting id,
            a canonical URL, a CRM record id. If a source has no stable key its
            adapter must construct one; guessing here would make every run
            report everything as new.
        salient: The fields whose change is news.
        observed_at: When the desk saw it. Deliberately excluded from identity —
            the same posting seen at a different time is the same posting.
        occurred_at: When the source says the thing itself happened or last
            moved. Also excluded from identity, but shown to the agent, because
            a change from last week and one from 2019 are not the same news and
            nothing else in the record distinguishes them.
        payload: Everything else the source returned. Never affects identity.
    """

    account_id: str
    source: str
    subject_key: str
    salient: Mapping[str, Any]
    observed_at: datetime
    occurred_at: datetime | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    subject_id: str = field(init=False, repr=False)
    observation_id: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for name in ("account_id", "source", "subject_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ObservationError(f"{name} must be a non-empty string")

        if not isinstance(self.salient, Mapping) or not self.salient:
            raise ObservationError(
                "salient must be a non-empty mapping — a source that observes "
                "something must say what it observed, or nothing can ever change"
            )
        _validate_json_value(dict(self.salient), "salient")

        if not isinstance(self.observed_at, datetime):
            raise ObservationError("observed_at must be a datetime")
        if self.occurred_at is not None and not isinstance(self.occurred_at, datetime):
            raise ObservationError("occurred_at must be a datetime or None")

        subject_id = _digest(self.account_id, self.source, self.subject_key)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(
            self, "observation_id", _digest(subject_id, _canonical(dict(self.salient)))
        )

    def describe(self) -> str:
        return f"{self.source}:{self.subject_key}"
