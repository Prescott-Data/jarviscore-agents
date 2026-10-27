# JarvisCore for GTM

A go-to-market desk built on [`jarviscore-framework`](https://pypi.org/project/jarviscore-framework/) 3.0.
Two plain `AutoAgent`s, no framework workarounds.

| Agent | Job | Credentials |
|---|---|---|
| `GTMAgent` (`gtm_agent`) | Does whatever revenue work a request needs: research, qualification, meeting prep, drafts, CRM truth. Runs as a durable `Mesh.execute_goal()` from the JarvisCore Desk. | `requires_auth = True` (Nexus) |
| `AccountExpert` (`account_expert`) | Judges which of an account's changes since the last run matter. Code computes the changes; the agent only judges significance. | none |

Both return typed results through `output_schema` (`gtm/contracts.py`), and every
result carries JarvisCore's `output`, `result_summary` and `evidence`.
Consequential provider actions (sending email, booking, CRM writes) wait for a
person's approval through JarvisCore HITL; resolve them with `Mesh.resolve_hitl()`.

## Install

```bash
pip install -e ".[dev]"
```

Put a model key in `.env` in the directory you run from (the Mesh reads it), then
check the setup with `jarviscore check`. Connect providers for the GTM agent with
`jarviscore nexus register <provider>`.

## Account-watch desk

```bash
gtm run --watchlist gtm/demo/watchlists/watchlist-globex-monday.yaml   # baseline, no model call
gtm run --watchlist gtm/demo/watchlists/watchlist-globex-tuesday.yaml  # judges what moved
```

Each account's state lives in `.jarviscore/gtm/accounts/` (override with
`--state-dir` or `GTM_STATE_DIR`) and is written only after the report is printed.
Accounts with changes are judged in parallel by an `AccountExpert` pool
(`mesh.add(AccountExpert, pool=Pool(max=4))` and `mesh.fanout`).

`gtm-demo` shows the Monday/Tuesday diff with no network or model calls.
See `gtm/demo/README.md` for the bundled watchlists.

## JarvisCore Desk

`../ui/gtm.desk.yaml` runs the GTM mesh: `gtm.team:build_mesh` builds it,
`gtm.team:submit_task(mesh, message, context)` runs a request as a goal (Redis
required, `REDIS_URL`), and `gtm.team:reconcile_task(mesh, workflow_id, context)`
continues one. Both return the goal's `status` (`success`, `yield` with
`yield_metadata`, or `failure`), `result_summary`, `output`, `evidence` and
`obligation_status`.

## Test

```bash
pytest
```
