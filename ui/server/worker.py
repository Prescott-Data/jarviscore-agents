"""Fixed-operation worker. Only acknowledged structured JSONL crosses stdout.

Raw stdout/stderr (including provider logs and model internals) go to /dev/null.
Public events use a duplicated private stdout descriptor created before imports.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .models import clean_event
from .security import Redactor
from .store import desk_home


def observation_text(observation, *, significance, because, novelty):
    """Only evidence fields and public judgements, never raw observation payloads."""
    candidate = observation.payload.get("url") or observation.subject_key
    try:
        parsed = urlsplit(candidate)
        url = candidate if parsed.scheme in {"http", "https"} and parsed.netloc else "not supplied"
    except (ValueError, TypeError):
        url = "not supplied"
    dated = (
        observation.occurred_at.isoformat() if observation.occurred_at
        else observation.payload.get("posted") or "not supplied by source"
    )
    title = observation.salient.get("title") or observation.subject_key
    return (
        f"title: {title}\nurl: {url}\ndated: {dated}\n"
        f"novelty: {novelty}\nsignificance: {significance}\nbecause: {because}"
    )


async def run_sample(emit):
    from gtm.demo import DEMO_ACCOUNT, DEMO_FIXTURES
    from gtm.sources.fixture import FixtureSource
    from gtm.state import AccountState

    await emit("status", {"message":
        "Fixture-data preview: synthetic Globex snapshots, not live research or agent reasoning. "
        "Real GTM Source + AccountState; no network and no LLM calls."
    })
    state = AccountState(DEMO_ACCOUNT.account_id, DEMO_ACCOUNT.name)
    start = datetime(2026, 9, 7, 9, tzinfo=UTC)
    for day, offset in (("monday", 0), ("tuesday", 1)):
        source = FixtureSource(DEMO_FIXTURES / f"{day}.json")
        await emit("status", {"message": f"Collecting {day} fixture with FixtureSource."})
        observations = await source.collect(DEMO_ACCOUNT, now=start + timedelta(days=offset))
        await emit("status", {"message": f"Collected {len(observations)} {day} fixture records."})
        delta = state.diff(observations)
        await emit("status", {"message": f"{day.title()} state diff: {delta.summary}."})
        text = [
            f"Fixture-data preview — {day.title()} (snapshot label, not elapsed live time).",
            delta.summary,
            "No significance assessment was performed. Novelty is computed, not a judgement.",
        ]
        for entry in delta.entries:
            text.append(observation_text(
                entry.observation, significance="not assessed (fixture-data preview)",
                because="Deterministic state comparison only; no model judgement was requested.",
                novelty=entry.novelty.value,
            ))
            text.extend(str(change) for change in entry.changes)
        await emit("result", {"text": "\n\n".join(text)})
        state.commit(delta)
        await emit("status", {"message": f"{day.title()} fixture state committed in memory."})
    await emit("result", {"text":
        "Preview complete. Tuesday has 1 new, 1 changed and 2 unchanged observations. "
        "The applicant count changed from 12 to 88 in payload only, so that vacancy "
        "remains unchanged. This demonstrates GTM identity/state, not buying intent. "
        "No live account state was modified."
    })


class ReportingSource:
    def __init__(self, source, emit):
        self.source, self.emit = source, emit
        self.name = source.name

    async def collect(self, account, *, now):
        await self.emit("status", {"message": f"Collecting {account.name}: {self.name}."})
        try:
            observations = await self.source.collect(account, now=now)
        except Exception:
            await self.emit("error", {"message":
                f"Collection failed for {account.name}: {self.name}. No account state committed."
            })
            raise
        await self.emit("status", {"message":
            f"Collected {len(observations)} observations for {account.name}: {self.name}."
        })
        return observations


async def run_watch(emit, home):
    from gtm import desk
    from gtm.demo import DEMO_WATCHLISTS
    from gtm.sources.ats import GreenhouseSource
    from gtm.store import AccountStore
    from gtm.watchlist import Watch, load_watchlist

    # Fixed installed blueprint resource, not user-provided filesystem/URL input.
    path = DEMO_WATCHLISTS / "watchlist-ats.yaml"
    watches = load_watchlist(path)
    if len(watches) != 1 or watches[0].account.account_id != "monzo" or not all(
        isinstance(source, GreenhouseSource) and source.token == "monzo"
        for source in watches[0].sources
    ):
        raise ValueError("The built-in watch requires the Monzo Greenhouse example.")
    watched = tuple(Watch(w.account, tuple(ReportingSource(s, emit) for s in w.sources)) for w in watches)

    store = AccountStore(home / "gtm" / "accounts")
    await emit("status", {"message": "Starting the GTM desk for Monzo Greenhouse."})
    runs = await desk.run_desk(watched, store, now=datetime.now(UTC))
    for run, _ in runs:
        if run.assessment is not None:
            await emit("status", {"message":
                f"The Account Expert judged {len(run.delta.reportable)} changes for {run.account.name}."
            })
    failed = False
    for run, _ in runs:
        if run.error:
            failed = True
            await emit("error", {"message":
                "Account assessment failed. No significance judgement or account-state commit "
                "is claimed. Check the explicitly configured LLM; raw provider logs are withheld."
            })
        judgements = {item.id: item for item in run.assessment.judgements} if run.assessment else {}
        if run.seeded:
            explanation = (
                "First collection is a baseline, not news. No significance assessment was requested."
            )
        elif run.error:
            explanation = "Assessment failed; these are observations only, not judgements."
        elif not run.delta.reportable:
            explanation = "Nothing changed against saved account memory; no assessment was requested."
        else:
            explanation = "Reportable changes were assessed by the real Account Expert."
        text = [f"Monzo — {run.delta.summary}", explanation,
                "dated is source-supplied (Greenhouse publication/update date), not proof of a new hire."]
        for entry in run.delta.entries:
            judgement = judgements.get(entry.observation.subject_id)
            because = judgement.because if judgement else (
                explanation if run.seeded or run.error else
                "Unchanged observation; no new significance assessment was requested."
            )
            text.append(observation_text(
                entry.observation,
                significance=judgement.significance if judgement else "not assessed",
                because=because, novelty="baseline" if run.seeded else entry.novelty.value,
            ))
        # emit's IPC acknowledgement guarantees the public report is durable first.
        await emit("result", {"text": "\n\n".join(text)})
    desk.commit(runs, store)
    await emit("status", {"message":
        "Unjudged account state was not committed." if failed else
        "Account state committed after the report was persisted by the desk."
    })


def prepare_gtm():
    # Shell/explicit launcher variables are already inherited in this child;
    # nothing may discover a repository .env on its own.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"


async def _run(operation, emit):
    from .framework import framework_info, require_framework_source

    request = json.loads(await asyncio.to_thread(sys.stdin.readline)) if operation == "configured" else None
    expected = os.environ.get("JARVISCORE_FRAMEWORK_SOURCE")
    info = await asyncio.to_thread(
        require_framework_source, Path(expected),
    ) if expected else await asyncio.to_thread(framework_info)
    revision = info["framework_revision"]
    details = (
        f"; {info['framework_branch']} at {revision[:12]}"
        f"{' with local changes' if info['framework_dirty'] else ''}"
    ) if revision else "; installed distribution"
    await emit("status", {"message": f"Worker runtime: JarvisCore {info['framework_version']}{details}."})
    if operation == "sample":
        await run_sample(emit)
    elif operation == "watch":
        prepare_gtm()
        await run_watch(emit, desk_home())
    elif operation == "configured":
        from .native import run_configured

        await run_configured(
            sys.argv[2], sys.argv[3], request["message"], emit,
            execution_context=request.get("context") or {},
        )
    else:
        raise ValueError("Unsupported worker operation")


def main():
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        sys.stdout = sys.stderr = sink
        logging.disable(logging.CRITICAL)
        redactor = Redactor()
        emit_lock = asyncio.Lock()

        async def emit(kind, data):
            async with emit_lock:
                clean = clean_event(kind, data, redactor.text)
                protocol.write(json.dumps({"type": kind, "data": clean}, ensure_ascii=False) + "\n")
                protocol.flush()
                if await asyncio.to_thread(sys.stdin.readline) != "ack\n":
                    raise RuntimeError("Desk disconnected before persistence acknowledgement")

        try:
            asyncio.run(_run(sys.argv[1], emit))
        except BaseException:  # noqa: BLE001
            # Never serialize an exception: providers may embed tokens or request bodies.
            return 1
        finally:
            protocol.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
