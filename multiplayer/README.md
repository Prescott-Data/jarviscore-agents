# Multiplayer: a marketing team and its agents

A team of three plans a holiday card campaign with its agents, in one room: Ava owns
the room, Bob and Dana edit it. Anyone asks in their own words. A strategist agent
researches the audience and channels, a writer drafts, and their work arrives as a
proposal the team can read as a diff or a formatted preview.

People disagree, change their minds and add "oh, and also…" while work is running.
Nothing anyone adds is lost: it is kept and applied to the running work's result. Only
one version of each piece of work lands, and only when the person deciding confirms it.

```
multiplayer/team.py   who the team is, the strategist and writer agents, the room and its brief
```

That is the whole blueprint. Rooms, proposals, permissions, the agent that understands
people and the conversation all come from JarvisCore
([Build a Multiplayer Agent](https://jarviscore.developers.prescottdata.io/guides/multiplayer-agents/)).

## Run it in the Desk

From the repository root, with Redis running and a model key in `.env` (see the
[top-level README](../README.md#run-a-blueprint)):

```bash
pip install -r ui/requirements.txt -e "multiplayer[dev]"
cd ui && python -m server --config multiplayer.desk.yaml --env-file ../.env
```

Open http://127.0.0.1:8765, pick who you are (the Desk's stand-in for your product's
login) and try:

1. As Ava: "We need campaigns for the Platinum holiday offer while people plan their
   trips. Give us 6 ideas to brainstorm."
2. As Bob: "Let's go with a hybrid of 1 and 2". As Dana, straight after: "Disagree, go
   with 3 and 5, built on the travel perks".
3. As Ava: "Ship the latest version", then Confirm. Only Ava gets the button.

## Run it in Slack

Replace the Desk with `SlackApp` from `jarviscore.room.slack`; see the guide's Slack
step. The team and the agents do not change.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

They run offline, with no model keys.
