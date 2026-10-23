# Deterministic Reliability Acceptance Fixture

`authorization_bypass/` is a synthetic repository with one seeded defect:
service-scoped filesystem handlers are omitted from the authorization predicate.

The demo copies the repository into a temporary workspace, runs its real unittest
suite, applies `repair.patch`, and runs the same suite again. A verified finding is
emitted only when the vulnerable run fails and the repaired run passes.

The fixture uses no network, credentials, LLM, or mocked test result.

`software-reliability demo --live` gives the same repository, without `repair.patch`,
to the full Mesh and a real model, which must find, reproduce, repair and verify the
defect on its own.
