# Software Reliability Architecture

## The loop

```text
repository at an immutable revision
  -> executed build and test baseline           (Repository Cartographer)
  -> candidate defects and rejected hypotheses  (Defect Miner)
  -> a failing test per surviving candidate     (Reproduction Engineer)
  -> deduplication and priority                 (Impact Analyst)
  -> minimal root-cause repair                  (Repair Engineer)
  -> fail-before / pass-after and regressions   (Verification Engineer)
  -> tested guardrail                           (Rule Engineer)
  -> current reliability brief                  (Reliability Strategist)
```

`Mesh.execute_goal()` turns the request into source obligations and a
capability-addressed DAG; peers claim ready steps independently. The planning brief in
`team.py` tells the planner how this team normally works; the user's request and its
explicit limits (review only, do not modify) always win.

Artifact types on each capability (`CandidateFinding`, `ReproductionEvidence`,
`PatchArtifact`, `VerificationReport`, …) let JarvisCore connect every consumer directly
to the producers whose evidence it needs. A ranking does not relay the reproduction it
read; the verifier depends on the reproduction and the patch themselves.

## Evidence

Each role returns a Pydantic contract from `contracts.py`. The `done` result is typed
from it, and `ReliabilityAgent.check_contract` turns a result that breaks a domain rule
into a failure. Command observations (`CommandObservation`) and file changes
(`WorkspaceMutation`) are cited by tool receipt; JarvisCore substitutes the recorded
command, exit code, output and file hash, so a model cannot invent a failing run or a
patch. An applied patch must also survive in the step's final workspace delta.

## Workspaces and authority

| Effect | Policy |
|---|---|
| Read the repository, build, run tests | Autonomous, in a per-step copy-on-write workspace |
| Add a reproduction test, apply a repair | `propose`: local to the workspace |
| Publish a finding, open a pull request, merge, deploy | Not available to this team |

Sources are immutable snapshots: GitHub through Nexus (built into JarvisCore) or a local
directory through `sources.LocalSource`. No agent holds provider credentials, so none
sets `requires_auth`.

## Identity

Stable `finding_id`s join candidate, reproduction, priority, patch, verification and
rule. A reconciliation revision supersedes evidence for the obligations it covers
without erasing earlier attempts or repeating satisfied work.
