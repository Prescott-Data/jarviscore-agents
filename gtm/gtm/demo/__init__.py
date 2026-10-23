"""Synthetic, credential-free GTM demonstration resources.

The fixtures and watchlists in this package are never selected by the GTM
runtime implicitly. They are used only by ``gtm-demo``, ``python -m gtm.demo``,
tests, or an explicitly supplied demo watchlist path.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gtm.accounts import Account
from gtm.prompts import render_assessment_request
from gtm.sources.fixture import FixtureSource
from gtm.state import AccountState

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_FIXTURES = DEMO_ROOT / "fixtures" / "globex"
DEMO_WATCHLISTS = DEMO_ROOT / "watchlists"

DEMO_ACCOUNT = Account(
    account_id="globex",
    name="Globex",
    domain="globex.example",
    why="Renewal is due in Q1 and their ops team owns the workflow we replace.",
)

__all__ = ["DEMO_ACCOUNT", "DEMO_FIXTURES", "DEMO_ROOT", "DEMO_WATCHLISTS", "main"]


async def _run() -> None:
    state = AccountState(DEMO_ACCOUNT.account_id, DEMO_ACCOUNT.name)
    monday = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
    delta = None

    for day, offset in (("monday", 0), ("tuesday", 1)):
        now = monday + timedelta(days=offset)
        source = FixtureSource(DEMO_FIXTURES / f"{day}.json")
        delta = state.diff(await source.collect(DEMO_ACCOUNT, now=now))

        print(f"\n{day.title()} — {delta.summary}")
        for entry in delta.reportable:
            print(f"  {entry.novelty.value:>7}  {entry.observation.subject_key}")
            for change in entry.changes:
                print(f"           {change}")
        for entry in delta.unchanged:
            print(f"  {'silent':>7}  {entry.observation.subject_key}")

        state.commit(delta)

    print("\n" + "─" * 72)
    print("What the Account Expert would be asked about Tuesday:\n")
    print(render_assessment_request(DEMO_ACCOUNT, delta))


def main() -> None:
    """Run the deterministic two-snapshot demo."""
    asyncio.run(_run())
