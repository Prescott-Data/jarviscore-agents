# Changelog

All notable changes to JarvisCore for Software Reliability are documented here.

## 0.2.0 - 2026-10-22

Rebuilt on JarvisCore 2.3 using only its public API.

### Changed

- Requires `jarviscore-framework>=2.3.0,<2.4`; Agent Desk requires `>=2.3.0,<3`.
- Each role is a plain `AutoAgent` whose `output_schema` is its contract. Steps that must
  touch the repository declare `required_tool_groups`; a result that breaks its contract
  is a failure.
- `RepositoryMap` carries the executed `baseline_runs`; `BaselineExecutionReport` is gone.
- `ReliabilityBrief` no longer has `user_response`: the answer is the step's
  `result_summary`.
- Local scans use `LocalSource`, a JarvisCore source adapter, instead of Git worktrees.
  `software-reliability demo --live` runs the packaged fixture through the full Mesh.
- Reproduction, repair and verification scale out with `Pool`.
- Build-cache variables for the workspace sandbox come from the worker environment.
- `submit_task` and `reconcile_task` return the framework goal result with the Desk
  fields added (`desk_view`).

### Removed

- The custom Kernel and subagents, the semantic interpretation layer, JSON repair and
  fence stripping, completion gates, the result reconstruction in `team.py`, the custom
  Athena memory adapter, persona YAML profiles and the peer-selection prompt. JarvisCore
  2.2+ provides typed `done` results, receipt-grounded evidence, honest failures and
  memory itself.

## 0.1.0 - 2026-09-22

### Added

- An eight-peer Software Reliability Mesh covering repository mapping, defect
  discovery, deterministic reproduction, impact analysis, repair, independent
  verification, tested rule extraction, and final synthesis.
- Product-owned typed contracts for findings, rejected hypotheses, command and
  mutation receipts, repair state, verification applicability, residual risks,
  and current-revision reliability briefs.
- Durable Agent Desk execution through JarvisCore DAG claims, typed dependency
  artifacts, reconciliation revisions, execution epochs, and resumable work.
- A deterministic offline fail-before, pass-after, and regression fixture plus
  a machine-readable benchmark command.

### Reliability semantics

- A repair is accepted only when a focused failure is reproduced, the repair is
  applied with authoritative mutation evidence, the same check passes afterward,
  and relevant regressions pass without weakening tests.
- Candidate-free investigations produce typed negative evidence instead of
  synthetic findings or no-op repairs.
- Verification distinguishes not-applicable work from blocked work, while
  residual risk remains separate from unfinished obligations.
- Publication and merge authority remain explicit; investigation runs cannot
  mutate target repositories by default.

### Validation

- 82 Software Reliability tests passed against JarvisCore 1.13.0.
- Ruff and all coordinated repository CI jobs passed.
- Live immutable-revision acceptance satisfied every obligation for byteorder,
  gjson, once_cell, and xid.
- Walkdir completed native Cargo build/test coverage and multiple hypothesis
  investigations, but remained blocked because focused negative-reproduction
  receipts were not produced for every rejected hypothesis. The campaign result
  is therefore four of five fully accepted repositories.