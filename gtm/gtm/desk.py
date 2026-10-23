"""One morning's work: collect, diff, judge, deliver, remember — in that order.

Nothing is committed until the run has reached the human, so a failure anywhere
upstream costs a repeated report rather than a signal that is never mentioned
again.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from jarviscore import Mesh, Pool
from pydantic import ValidationError

from gtm.accounts import Account
from gtm.agents import AccountExpert
from gtm.contracts import Assessment
from gtm.prompts import render_assessment_request
from gtm.sources import collect_all
from gtm.state import AccountState, Delta
from gtm.store import AccountStore
from gtm.watchlist import Watch

# Accounts judged at once. Each is one AccountExpert instance from the pool.
MAX_PARALLEL_ACCOUNTS = 4


@dataclass(frozen=True)
class AccountRun:
    """What one account produced this morning."""

    account: Account
    delta: Delta
    assessment: Assessment | None = None
    error: str | None = None
    seeded: bool = False

    @property
    def committable(self) -> bool:
        """Whether this run may be remembered once it has been delivered."""
        return self.error is None


def commit(runs: list[tuple[AccountRun, AccountState]], store: AccountStore) -> None:
    """Remember what was delivered.

    Called by whoever delivered the report, after it has landed. Committing
    earlier means a crash between judging and telling someone buries the news.
    """
    for run, state in runs:
        if run.committable:
            state.commit(run.delta)
            store.save(state)


async def _observe(watch: Watch, store: AccountStore, now: datetime):
    state = store.load(watch.account)
    observations = await collect_all(list(watch.sources), watch.account, now=now)
    return watch.account, state, state.diff(observations)


def judged(account: Account, delta: Delta, result: dict) -> AccountRun:
    """Turn the Account Expert's result into a run; anything unusable is an error, not calm."""
    if result.get("status") != "success":
        return AccountRun(account, delta, error=str(result.get("error") or result.get("status")))
    try:
        assessment = Assessment.model_validate(result.get("output")).require_exactly(
            entry.observation.subject_id for entry in delta.reportable
        )
    except (ValidationError, ValueError) as exc:
        return AccountRun(account, delta, error=f"invalid assessment: {exc}")
    return AccountRun(account, delta, assessment)


async def run_desk(
    watches: tuple[Watch, ...],
    store: AccountStore,
    *,
    now: datetime,
) -> list[tuple[AccountRun, AccountState]]:
    """Observe every account, judge what moved, and return without committing.

    The caller delivers first, then calls :func:`commit`.
    """
    observed = await asyncio.gather(*(_observe(watch, store, now) for watch in watches))

    runs: dict[str, AccountRun] = {}
    to_judge: dict[str, tuple[Account, Delta]] = {}
    for account, state, delta in observed:
        if not state.has_memory:
            # First sight of an account is a baseline, not news.
            runs[account.account_id] = AccountRun(account, delta, seeded=True)
        elif not delta.reportable:
            runs[account.account_id] = AccountRun(account, delta)
        else:
            to_judge[account.account_id] = (account, delta)

    if to_judge:
        mesh = Mesh(config={"p2p_enabled": False})
        mesh.add(AccountExpert, pool=Pool(max=MAX_PARALLEL_ACCOUNTS))
        await mesh.start()
        try:
            result = await mesh.fanout(
                f"desk-{now:%Y%m%dT%H%M%S}",
                agent=AccountExpert.role,
                items=list(to_judge),
                task=lambda account_id: render_assessment_request(*to_judge[account_id]),
                concurrency=MAX_PARALLEL_ACCOUNTS,
            )
        finally:
            await mesh.stop()
        for item in result.results:
            account, delta = to_judge[item["item"]]
            runs[item["item"]] = judged(account, delta, item)

    return [(runs[account.account_id], state) for account, state, _ in observed]
