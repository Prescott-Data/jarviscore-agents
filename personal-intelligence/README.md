# JarvisCore for Personal Intelligence

One general agent that works for a person. Give it a goal in your own words (research a
decision, plan a trip, handle an errand, keep track of what matters) and it does the work
until it is done or something real stops it.

```
personal_intelligence/agent.py   the agent: its prompt, capabilities and the apps it may use
personal_intelligence/team.py    the Mesh, and the Desk's submit/continue entry points
```

There is no catalogue of use cases and no agent per domain. `PersonalIntelligenceAgent` is
a plain JarvisCore [`AutoAgent`](https://jarviscore.developers.prescottdata.io/guides/autoagent/),
and everything else comes from the framework:

- the **Kernel** sends each step to the researcher, browser, coder or communicator it needs;
- the person's **connected apps** (Gmail, Calendar, Drive, Notion, Slack and more, listed in
  [agent.py](personal_intelligence/agent.py)) are reached through
  [Nexus](https://jarviscore.developers.prescottdata.io/guides/nexus/), which holds the
  credential; the agent never sees it;
- **approval** (HITL): sending, booking, buying, paying and deleting wait for the person;
- **memory** is per person (`memory_scope_field: owner_id`): preferences, corrections and
  decisions carry over between sessions;
- the **Mesh** holds the goal, splits independent parts across up to three agents, and
  resumes after an approval or a restart.

An effect counts as done only when there is proof (a provider record, an observed page, a
hashed file). A plan or a draft is never reported as something that happened.

## Run it

```bash
pip install -e ".[dev]"
playwright install chromium        # the browser, for sites without an API
pytest                             # offline, no model keys
```

In the [Desk](../ui/), launch with `ui/personal-intelligence.desk.yaml`. To reach the same
agent from Telegram:

```bash
export TELEGRAM_BOT_TOKEN=...
personal-intelligence-telegram
```
