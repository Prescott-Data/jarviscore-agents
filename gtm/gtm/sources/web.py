"""Research through JarvisCore's own multi-provider search.

The framework already runs Google Grounded, SearXNG, Wikipedia, arXiv, Crossref
and optionally Serper in parallel, deduplicates by URL, ranks by trust weight
and query overlap, and trips a circuit breaker on a provider that keeps
failing. Writing our own HTTP client against one search API would be strictly
worse and would need a key we do not otherwise need.

What this module contributes is the part search engines cannot do: deciding
what counts as the *identity* of a result and what counts as *news* about it.

    subject_key   the normalised URL — a page is a page
    salient       the title, because a retitled page is a changed page
    payload       snippet, rank, provider

That split matters more here than anywhere else in the desk. Snippets are
rewritten constantly by the engines themselves, and rank moves every time
anyone else publishes. Either one in ``salient`` would make every run look like
a flood of news, which is precisely the failure this system exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from gtm.accounts import Account
from gtm.state.observation import Observation

DEFAULT_MAX_RESULTS = 10


def _normalise_url(url: str) -> str:
    """Strip the parts that vary without the page changing."""
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


@dataclass
class WebSearchSource:
    """One standing question about an account, asked of the open web.

    Args:
        query: What to ask. ``{name}`` and ``{domain}`` are filled from the
            account, so one watchlist entry serves every account.
        name: Source name recorded on every observation. Distinct queries need
            distinct names, or two questions about the same page collapse into
            one subject and each will look like the other changing it.
        max_results: How many ranked results to keep.
        exclude_providers: Providers to skip entirely, avoiding the network
            call rather than filtering afterwards. Academic sources are off by
            default: arXiv and Crossref rarely say anything about a company's
            commercial priorities.
    """

    query: str
    name: str = "web"
    max_results: int = DEFAULT_MAX_RESULTS
    exclude_providers: frozenset[str] = field(
        default_factory=lambda: frozenset({"arxiv", "crossref"})
    )

    def render_query(self, account: Account) -> str:
        return self.query.format(name=account.name, domain=account.domain)

    async def collect(self, account: Account, *, now: datetime) -> list[Observation]:
        from jarviscore.search import InternetSearch

        async with InternetSearch() as search:
            results = await search.search(
                self.render_query(account),
                max_results=self.max_results,
                exclude_providers=set(self.exclude_providers),
            )

        observations: list[Observation] = []
        seen: set[str] = set()
        for rank, result in enumerate(results, start=1):
            url = (result.get("url") or result.get("link") or "").strip()
            title = (result.get("title") or "").strip()
            if not url or not title:
                # No stable key or nothing to notice a change in. Dropping it
                # is honest; inventing either would fabricate a subject.
                continue
            subject_key = _normalise_url(url)
            if subject_key in seen:
                continue
            seen.add(subject_key)
            observations.append(
                Observation(
                    account_id=account.account_id,
                    source=self.name,
                    subject_key=subject_key,
                    salient={"title": title},
                    observed_at=now,
                    payload={
                        "url": url,
                        "snippet": (result.get("snippet") or "")[:500],
                        "rank": rank,
                        "provider": result.get("source") or result.get("provider") or "",
                    },
                )
            )
        return observations
