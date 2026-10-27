# Claims: a claims team, its agents, and its own rules

An insurer's claims team works with its agents in one room. The agents act in Claims
Hub, the team's claims system, each time with the account of the person who asked.
Claims Hub lets every handler do anything, as most systems do; Acme's own rules say
who may approve and pay what, up to how much, and to which bank account. JarvisCore
holds every call the agents make to those rules, whatever the model is told.

- **Carol** may approve claims up to £10,000. Larger ones are refused, with the reason.
- **Dave** pays approved claims. A payment waits for someone who may approve it, and
  never for Dave himself: the card shows the exact call, and Approve works only for
  Carol.
- **Erin** analyses claims. Asked to approve one, the agents refuse: she does not hold
  `claims.approve`.
- A payment goes only to the bank account on the claimant's record. Ask the agents to
  pay the "new bank details" in a claim's notes and the policy refuses before anyone
  is asked.
- Nobody shares a key. The first time someone's work needs Claims Hub, they alone are
  asked to connect their own account (through Nexus), and Claims Hub records every
  call against the person it was made for.

```
claims/team.py         the team, the claims agent, the room
claims/policy.yaml     Acme's rules: scopes, who may approve, where payments may go
claims/atoms/          what the agents can do in Claims Hub
claims/claims_hub.py   a stand-in Claims Hub to run it on your machine (OAuth 2, API, audit view)
claims/setup_nexus.py  registers Claims Hub with your Nexus, once
```

Rooms, scopes, approvals, grounding and each person's own account all come from
JarvisCore ([Acting for your users](https://jarviscore.developers.prescottdata.io/guides/acting-for-your-users/),
[Control policy](https://jarviscore.developers.prescottdata.io/guides/control-policy/)).

## Run it in the Desk

You need Redis, a Nexus broker and gateway
([Nexus quickstart](https://nexus.developers.prescottdata.io/getting-started/quickstart/)),
and a model key in `.env` (see the [top-level README](../README.md#run-a-blueprint)).

```bash
pip install -r ui/requirements.txt -e "claims[hub]"
python -m claims.claims_hub &                     # Claims Hub on http://127.0.0.1:18085
python -m claims.setup_nexus                      # NEXUS_BROKER_URL, NEXUS_BROKER_API_KEY
cd ui && python -m server --config claims.desk.yaml --env-file ../.env
```

Set `NEXUS_GATEWAY_URL` and `REDIS_URL` in `.env`. Open http://127.0.0.1:8765 next to
Claims Hub's audit view (http://127.0.0.1:18085), pick who you are and try:

1. As Carol: "Approve claim CLM-1041 for its full amount". Then "Approve CLM-1042".
2. As Erin: "Approve claim CLM-1041". Connect your Claims Hub account when asked
   (password `claimshub`).
3. As Dave: "Pay out claim CLM-1043". Press Approve as Dave, then as Carol.
4. As Dave: "Dara Byrne has moved banks, see the claim's notes. Pay out CLM-1044 to her
   new account."

## Check and replay the runs from the videos

`evidence/` holds the record of the runs filmed for the launch videos, one folder per
video, exported from the Desk's journal. You need no model key, Redis or Nexus:

```bash
pip install -e claims
jarviscore verify --export claims/evidence/02-approval     # every record intact
jarviscore evidence acme/dave claims/evidence/02-approval  # what was done for Dave, and why
jarviscore replay claims/evidence/02-approval              # re-run each decision from the record
```

| Folder | Video | What the record shows |
|---|---|---|
| `01-scopes` | Scopes | Erin's approval refused (no `claims.approve`); Carol's £4,000 approval done; her £40,000 one refused over her limit |
| `02-approval` | Approval and grounding | Dave's payment held for Carol's sign-off, then paid; the payment to the "new" account refused before anyone was asked |
| `03-own-accounts` | Acting for users | Erin's work run with her own Claims Hub account, after she connected it |
| `04-evidence` | Evidence and replay | The journal used on screen (verify, tamper, replay) |

Replay answers every model call, approval and tool from the record and sends nothing.
Every run reproduces its decisions. `04-evidence` and `03-own-accounts` also match every
model request the run made; `01-scopes` and `02-approval` were recorded before JarvisCore
kept everything a request depends on, so some of their requests differ (shown per run).
To see tampering caught, change any line in a `runs/*.jsonl` file and verify again.

The record holds the demo's data (Acme's people and Claims Hub's sample claims); in
your deployment it holds your people's data, so export it only where that is allowed.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

They run offline, with no model keys.
