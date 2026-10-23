"""Where observations come from.

A source turns one external surface into :class:`~gtm.state.observation.Observation`
records. It decides the ``subject_key`` — the stable identity of a record in
that surface — and which fields are salient. Nothing downstream can recover
from a source that gets those two wrong, which is why they belong here and not
in a general-purpose helper.

Sources are deliberately dumb: fetch, shape, return. They do not judge, dedupe
or summarise. Deduplication is :class:`~gtm.state.account.AccountState`'s job
and judgement is the agent's.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol, runtime_checkable

from gtm.accounts import Account
from gtm.state.observation import Observation


@runtime_checkable
class Source(Protocol):
    """One external surface the desk watches."""

    name: str

    async def collect(self, account: Account, *, now: datetime) -> list[Observation]:
        """Everything this surface currently says about the account."""
        ...


async def collect_all(
    sources: list[Source], account: Account, *, now: datetime
) -> list[Observation]:
    """Gather from every source at once.

    A failing source raises rather than returning nothing. A source that
    quietly returned an empty list on error would be indistinguishable from a
    surface where genuinely nothing is happening, and the desk would report a
    calm morning it has no evidence for.
    """
    batches = await asyncio.gather(
        *(source.collect(account, now=now) for source in sources)
    )
    return [observation for batch in batches for observation in batch]
