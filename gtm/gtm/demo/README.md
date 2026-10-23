# GTM demo data

Everything in this directory is synthetic or an explicit public-source example.
Nothing here is loaded by normal GTM or Desk execution unless the caller chooses
the demo entry point or passes one of these watchlists directly.

## Deterministic demo

Run without credentials, network access, or an LLM:

```bash
gtm-demo
# or
python -m gtm.demo
```

The fictional Globex snapshots show two consecutive observations. They exercise
source collection and state-diff behavior only; they do not represent live
research or an agent judgement.

## Watchlist examples

From a source checkout rooted at `gtm/`:

```bash
gtm run --watchlist gtm/demo/watchlists/watchlist-globex-monday.yaml
gtm run --watchlist gtm/demo/watchlists/watchlist-globex-tuesday.yaml
gtm run --watchlist gtm/demo/watchlists/watchlist-ats.yaml
gtm run --watchlist gtm/demo/watchlists/watchlist-live.yaml
```

The first Globex run records a baseline without a model call; the second asks
the Account Expert to judge what moved, so it needs a model key.

- `watchlist-ats.yaml` uses Monzo's public Greenhouse board.
- `watchlist-live.yaml` uses JarvisCore's configured web-search providers.
- `watchlist-globex-*.yaml` explicitly select fictional fixture snapshots.
