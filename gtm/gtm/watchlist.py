"""The desk's watchlist: which accounts, watched why, through which surfaces.

One file, edited by the person who owns the accounts. The ``why`` on each entry
is what every judgement is measured against, so a watchlist of names with no
reasons produces an agent that can only tell you things happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gtm.accounts import Account
from gtm.sources import Source
from gtm.sources.ats import GreenhouseSource, LeverSource
from gtm.sources.fixture import FixtureSource
from gtm.sources.web import WebSearchSource


class WatchlistError(ValueError):
    """The watchlist is not usable as written."""


@dataclass(frozen=True)
class Watch:
    """One account and the surfaces the desk watches it through."""

    account: Account
    sources: tuple[Source, ...]


def _build_source(spec: Any, base_dir: Path, account_id: str) -> Source:
    if not isinstance(spec, dict) or "type" not in spec:
        raise WatchlistError(f"{account_id}: each source needs a 'type'")
    kind = spec["type"]
    if kind == "fixture":
        if "path" not in spec:
            raise WatchlistError(f"{account_id}: a fixture source needs a 'path'")
        return FixtureSource(base_dir / spec["path"])
    if kind == "web":
        if "query" not in spec:
            raise WatchlistError(f"{account_id}: a web source needs a 'query'")
        return WebSearchSource(
            query=str(spec["query"]),
            name=str(spec.get("name", "web")),
            max_results=int(spec.get("max_results", 10)),
        )
    if kind in {"greenhouse", "lever"}:
        if "token" not in spec:
            raise WatchlistError(
                f"{account_id}: a {kind} source needs a 'token' — the board name in "
                "the company's careers URL"
            )
        builder = GreenhouseSource if kind == "greenhouse" else LeverSource
        return builder(token=str(spec["token"]), name=str(spec.get("name", kind)))
    raise WatchlistError(
        f"{account_id}: unknown source type {kind!r} — no source is better than a "
        "guessed one, so this is an error rather than a skip"
    )


def load_watchlist(path: str | Path) -> tuple[Watch, ...]:
    """Read the watchlist. Paths inside it resolve relative to the file itself."""
    import yaml

    path = Path(path).resolve()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WatchlistError(f"no watchlist at {path}") from exc
    except yaml.YAMLError as exc:
        raise WatchlistError(f"{path} is not valid YAML: {exc}") from exc

    entries = (document or {}).get("accounts")
    if not isinstance(entries, list) or not entries:
        raise WatchlistError(f"{path} must carry a non-empty 'accounts' list")

    base_dir = path.parent
    watches = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise WatchlistError(f"{path}: each account must be a mapping")
        try:
            account = Account(
                account_id=str(entry.get("id", "")),
                name=str(entry.get("name", "")),
                domain=str(entry.get("domain", "")),
                why=str(entry.get("why", "")),
            )
        except ValueError as exc:
            raise WatchlistError(f"{path}: {exc}") from exc
        if account.account_id in seen:
            raise WatchlistError(f"{path}: {account.account_id!r} appears twice")
        seen.add(account.account_id)

        specs = entry.get("sources")
        if not isinstance(specs, list) or not specs:
            raise WatchlistError(f"{account.account_id}: needs at least one source")
        sources = tuple(_build_source(s, base_dir, account.account_id) for s in specs)
        watches.append(Watch(account, sources))

    return tuple(watches)
