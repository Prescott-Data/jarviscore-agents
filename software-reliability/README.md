# JarvisCore for Software Reliability

An open-source reliability team built on [JarvisCore](https://github.com/Prescott-Data/jarviscore-framework).
Point it at a repository and eight agents map how it builds and tests, hunt for
consequential defects, reproduce them with failing tests, repair the root cause and
verify the repair independently.

A plausible finding is not a finding. A repair counts as verified only when:

1. the original code fails a focused, collected test;
2. a patch is applied in an isolated workspace;
3. the same test passes afterwards;
4. the surrounding regression tests pass; and
5. no test was weakened, skipped or deleted to get there.

## The team

| Agent | Owns | Returns |
|---|---|---|
| Repository Cartographer | Build and test entry points, executed baseline, trust boundaries | `RepositoryMap` |
| Defect Miner | Falsifiable candidates and rejected hypotheses | `FindingPortfolio` |
| Reproduction Engineer | The smallest failing test for one candidate | `ReproductionEvidence` |
| Impact Analyst | Deduplication and priority | `PriorityAssessment` |
| Repair Engineer | The minimal root-cause patch | `PatchArtifact` |
| Verification Engineer | Fail-before, pass-after and regressions | `VerificationReport` |
| Rule Engineer | A tested guardrail for a verified mechanism | `RuleArtifact` |
| Reliability Strategist | The answer for the person who asked | `ReliabilityBrief` |

Everything is ordinary JarvisCore:

- each agent is an `AutoAgent` ([agents.py](software_reliability/agents.py)) whose
  `output_schema` is its Pydantic contract ([contracts.py](software_reliability/contracts.py)).
  The contracts hold the domain rules, for example "reproduced needs a failing run whose
  command uses the collected selector";
- `capability_contracts` declare each capability's effects and the artifact types it
  produces and needs, so the planner wires reproduction to discovery and verification to
  both reproduction and repair;
- steps that must touch the repository declare `required_tool_groups`;
- command and file-change claims cite tool receipts, which JarvisCore replaces with the
  real observation before a step completes;
- `Mesh.execute_goal()` plans the work, peers claim it, and the reproduction, repair and
  verification agents scale out with `Pool`;
- the repository is an immutable source snapshot: every step gets its own copy-on-write
  workspace and never touches your checkout.

The Mesh is defined in [team.py](software_reliability/team.py); there is no manager agent.

## Try it

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

The offline demo needs no model. It runs a packaged repository with a real
authorization bypass through fail-before, patch, pass-after and regressions:

```bash
.venv/bin/python -m software_reliability.demo
```

The live demo gives the same repository, without its patch, to the full team. It needs
Redis, model keys for any provider JarvisCore supports, and permission to run the
repository's tests:

```bash
export REDIS_URL=redis://localhost:6379/0
export AZURE_API_KEY=... AZURE_ENDPOINT=... AZURE_DEPLOYMENT=...
export ALLOW_UNSAFE_LOCAL_EXECUTION=true
.venv/bin/software-reliability demo --live
```

JarvisCore runs workspace commands as unconfined host processes only with
`ALLOW_UNSAFE_LOCAL_EXECUTION=true`. The agents build and test the code they inspect, so
set it only for code you trust or inside a disposable container or VM, or configure a
remote sandbox (`SANDBOX_MODE=remote`).

It prints the goal status, the brief's `result_summary` and the `ReliabilityBrief` with
the reproduction, patch and verification evidence. Reasoning deployments spend output
tokens on hidden reasoning, so declare their ceiling, e.g.
`LLM_MODEL_OUTPUT_LIMITS='{"gpt-5.6-luna": 128000}'`, or planning stops at JarvisCore's
default allowance.

## Scan your own code

```bash
# A local Git repository at HEAD (or --commit REV); uncommitted changes are not included
.venv/bin/software-reliability scan path/to/repository

# A GitHub repository, through a Nexus GitHub connection
.venv/bin/software-reliability scan-github owner/repository --ref main
```

`--goal` narrows the request, for example `--goal "Review authorization only; do not
modify code."`

Commands the workspace may run beyond JarvisCore's defaults (`python`, `git`, `npm`, …)
are listed in `build_mesh()`: `cargo`, `cmake`, `dotnet`, `go`, `gradle`, `java`,
`javac`, `make`, `mvn` and `rustc`. The sandbox does not inherit your environment; set
`CARGO_HOME`, `CARGO_TARGET_DIR`, `RUSTUP_HOME`, `GOCACHE`, `GOMODCACHE`,
`GRADLE_USER_HOME`, `NPM_CONFIG_CACHE` or `PIP_CACHE_DIR` on the worker to give it build
caches and toolchains.

## Agent Desk

[`ui/software-reliability.desk.yaml`](../ui/software-reliability.desk.yaml) runs the team in
Agent Desk:

```bash
ui/.venv/bin/python -m pip install -e software-reliability
PYTHONPATH="$PWD/ui:$PWD/software-reliability" ui/.venv/bin/python -m server \
    --config ui/software-reliability.desk.yaml --port 8765
```

Ask the Mesh row something like "Run a deep reliability scan of github.com/owner/repo".
`submit_task` runs the goal and `reconcile_task` continues one whose obligations are
still open; both return the goal result with Desk fields added (`desk_view`).

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check software_reliability tests
```

The tests run without a model. `software-reliability benchmark` scores the offline demo
with the [benchmark](BENCHMARK.md) metrics; one fixture proves the harness, not a
competitive result.
