"""A source backed by a file, so the desk can be watched working without keys.

This exists for two reasons and both matter. It is how someone evaluates the
system in under a minute without connecting an account to anything, and it is
how the novelty model is tested without a network.

Fixtures are the same shape a real source produces, so nothing downstream can
tell the difference. That is the point — a fixture that needed special handling
downstream would be proving the wrong thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gtm.accounts import Account
from gtm.state.observation import Observation


class FixtureError(ValueError):
    """A fixture file is not shaped like a source's output."""


@dataclass
class FixtureSource:
    """Replays one day of one surface from disk.

    Args:
        path: A JSON file with ``source`` and ``records``; each record carries
            ``subject_key``, ``salient`` and optionally ``payload``.
    """

    path: Path
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.name = self._document()["source"]

    def _document(self) -> dict:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FixtureError(f"no fixture at {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise FixtureError(f"{self.path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict) or not document.get("source"):
            raise FixtureError(f"{self.path} must be an object with a 'source'")
        if not isinstance(document.get("records"), list):
            raise FixtureError(f"{self.path} must carry a 'records' list")
        return document

    async def collect(self, account: Account, *, now: datetime) -> list[Observation]:
        document = self._document()
        observations = []
        for index, record in enumerate(document["records"]):
            if not isinstance(record, dict) or "subject_key" not in record:
                raise FixtureError(f"{self.path} record {index} has no subject_key")
            observations.append(
                Observation(
                    account_id=account.account_id,
                    source=document["source"],
                    subject_key=record["subject_key"],
                    salient=record.get("salient", {}),
                    observed_at=now,
                    payload=record.get("payload", {}),
                )
            )
        return observations
