"""Applicant tracking systems — the job board itself, not a page about it.

The strongest routinely available GTM signal is a requisition for the role that
owns the problem you solve. Reaching that through a search engine returns
Glassdoor, Indeed and LinkedIn aggregator pages: real results that say only
that the company employs people. The board itself is public JSON, needs no
credentials, and gives the requisition id, the title, the location and the
dates.

Greenhouse and Lever between them cover most of the market. Both endpoints are
the same ones their own careers pages call.

Identity is the requisition id, which the ATS guarantees stable. Title and
location are salient, because a retitled or relocated role is a changed role.
``updated_at`` is not salient: boards touch it for reasons that are not news,
and putting it in identity would make every run a flood.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from gtm.accounts import Account
from gtm.state.observation import Observation

GREENHOUSE_BOARD = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_BOARD = "https://api.lever.co/v0/postings/{token}?mode=json"
TIMEOUT_SECONDS = 20


class ATSError(RuntimeError):
    """The board did not answer in a usable way."""


async def _fetch(url: str) -> Any:
    import ssl

    import aiohttp
    import truststore

    # The OS trust store: Python's bundled CAs fail on macOS and behind proxies.
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    connector = aiohttp.TCPConnector(ssl=tls)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(url) as response:
            if response.status == 404:
                raise ATSError(f"no public board at {url} — check the board token")
            if response.status != 200:
                raise ATSError(f"{url} returned HTTP {response.status}")
            body = await response.text()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ATSError(f"{url} did not return JSON: {exc}") from exc


def _parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class GreenhouseSource:
    """A company's Greenhouse board.

    Args:
        token: The board token — the path segment in
            ``job-boards.greenhouse.io/<token>``, usually the company name.
        name: Source name recorded on every observation.
    """

    token: str
    name: str = "greenhouse"

    async def collect(self, account: Account, *, now: datetime) -> list[Observation]:
        document = await _fetch(GREENHOUSE_BOARD.format(token=quote(self.token)))
        jobs = document.get("jobs") if isinstance(document, dict) else None
        if not isinstance(jobs, list):
            raise ATSError(f"greenhouse board {self.token!r} returned no jobs list")

        observations = []
        for job in jobs:
            job_id = job.get("id")
            title = (job.get("title") or "").strip()
            if job_id is None or not title:
                continue
            location = ((job.get("location") or {}).get("name") or "").strip()
            observations.append(
                Observation(
                    account_id=account.account_id,
                    source=self.name,
                    subject_key=f"greenhouse:{self.token}:{job_id}",
                    salient={"title": title, "location": location},
                    observed_at=now,
                    occurred_at=_parse_date(job.get("first_published"))
                    or _parse_date(job.get("updated_at")),
                    payload={
                        "url": job.get("absolute_url", ""),
                        "updated_at": job.get("updated_at", ""),
                        "requisition_id": job.get("requisition_id", ""),
                    },
                )
            )
        return observations


@dataclass
class LeverSource:
    """A company's Lever board."""

    token: str
    name: str = "lever"

    async def collect(self, account: Account, *, now: datetime) -> list[Observation]:
        postings = await _fetch(LEVER_BOARD.format(token=quote(self.token)))
        if not isinstance(postings, list):
            raise ATSError(f"lever board {self.token!r} returned no postings list")

        observations = []
        for posting in postings:
            posting_id = posting.get("id")
            title = (posting.get("text") or "").strip()
            if not posting_id or not title:
                continue
            categories = posting.get("categories") or {}
            created = posting.get("createdAt")
            observations.append(
                Observation(
                    account_id=account.account_id,
                    source=self.name,
                    subject_key=f"lever:{self.token}:{posting_id}",
                    salient={
                        "title": title,
                        "location": (categories.get("location") or "").strip(),
                        "team": (categories.get("team") or "").strip(),
                    },
                    observed_at=now,
                    occurred_at=(
                        datetime.fromtimestamp(created / 1000, tz=now.tzinfo)
                        if isinstance(created, (int, float))
                        else None
                    ),
                    payload={"url": posting.get("hostedUrl", "")},
                )
            )
        return observations
