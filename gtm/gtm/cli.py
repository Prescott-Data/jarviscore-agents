"""``gtm run`` — run the account-watch desk."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from gtm.desk import AccountRun, commit, run_desk
from gtm.store import AccountStore
from gtm.watchlist import WatchlistError, load_watchlist

_MARK = {"act": "ACT ", "note": "note", "ignore": "  · "}


def report(runs: list[AccountRun]) -> int:
    """Print the morning's report. Returns 1 when any account went unjudged."""
    failures = 0
    for run in runs:
        print(f"\n{run.account.name}  ({run.delta.summary})")
        if run.error:
            failures += 1
            print(f"  ! unjudged — {run.error}")
            print("    these changes will be reported again next run")
        elif run.seeded:
            print(f"  baseline recorded — watching {len(run.delta.entries)} things from now")
        elif run.assessment is None:
            print("  nothing new")
        else:
            by_id = {e.observation.subject_id: e for e in run.delta.reportable}
            for judgement in run.assessment.judgements:
                entry = by_id[judgement.id]
                print(f"  {_MARK[judgement.significance]}  {entry.observation.subject_key}")
                for change in entry.changes:
                    print(f"          {change}")
                print(f"          {judgement.because}")

    acted = sum(len(r.assessment.actionable) for r in runs if r.assessment)
    print(f"\n{len(runs)} account(s), {acted} worth acting on today.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gtm", description="Run the GTM account-watch desk.")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--watchlist", default="watchlist.yaml")
    parser.add_argument("--state-dir", default=None)
    args = parser.parse_args(argv)

    try:
        watches = load_watchlist(args.watchlist)
    except WatchlistError as exc:
        print(f"watchlist: {exc}", file=sys.stderr)
        return 2

    store = AccountStore(Path(args.state_dir)) if args.state_dir else AccountStore.from_env()
    results = asyncio.run(run_desk(watches, store, now=datetime.now(timezone.utc)))

    status = report([run for run, _ in results])
    # Delivered above; only now is it safe to forget these changes were new.
    commit(results, store)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
