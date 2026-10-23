# Software Reliability Benchmark

The benchmark must measure the complete path from repository state to accepted
repair. Finding count is not a success metric.

## Corpus

A publishable evaluation requires:

- at least 10 unrelated repositories;
- at least four implementation languages;
- at least 200 independently labeled defects and non-defects;
- correctness, security, concurrency, data integrity, availability, performance,
  documentation drift, and dead-code cases;
- both seeded defects and naturally occurring historical defects;
- frozen commits, build instructions, and ground-truth provenance;
- hidden evaluation cases not used to tune prompts or rules.

Every case uses stable defect IDs. Matching is adjudicated against root cause,
not title similarity or string patterns.

## Required metrics

| Metric | Definition |
|---|---|
| Precision | Ground-truth findings divided by all surfaced findings |
| Recall | Ground-truth defects surfaced divided by expected defects |
| Reproduction coverage | Expected defects with a deterministic failing execution |
| Verified repair rate | Repairable defects with fail-before/pass-after and clean regressions |
| Test-integrity violations | Repairs that skip, delete, weaken, or rewrite tests to pass |
| Deduplication precision/recall | Correctly grouped root-cause families and preserved distinct defects |
| Importance percentile | Blinded pairwise ranking against competing findings |
| Maintainer acceptance | Accepted or merged proposals divided by submitted proposals |
| Efficiency | Wall time, tokens, cost, environment failures, and retries per accepted finding |

Report all denominators, per-language results, confidence intervals, failures,
and abstentions. Do not omit repositories where environment setup failed.

## Superiority gates

No “better than Detail” claim is permitted until a frozen public evaluation:

1. exceeds Detail's public 82.9% correctness acceptance point estimate;
2. exceeds the public 87.85 mean importance percentile under a blinded,
   position-balanced tournament;
3. exceeds the public 81.8% merge rate from 33 showcased PRs on a comparable,
   non-curated submission cohort;
4. reproduces at least 90% of surfaced P1/P2 findings;
5. verifies repairs with the same failing test before and passing test after;
6. records zero test-integrity violations;
7. includes multiple independent model judges and blinded human adjudication;
8. publishes prompts, traces, inputs, outputs, scoring code, costs, and failures.

Because Detail's public examples are selected, matching them is not enough. The
JarvisCore benchmark must be broader and independently reproducible.

## Current milestone

The packaged `case_service_auth_bypass` fixture is one deterministic contract
test. It currently scores:

```text
precision:             1.0
recall:                1.0
reproduction coverage:1.0
verified repair rate:  1.0
test-integrity errors: 0
```

That result proves the scorer and verification boundary. It does not satisfy the
corpus or superiority gates above.

## Framework development-speed gate

Product quality still requires real evaluation, but JarvisCore must remove the
days of custom harness construction that preceded GTM. Measure onboarding from a
clean clone with dependencies already downloadable:

| Task | Target |
|---|---|
| Install and run deterministic demo | 15 minutes or less |
| Add one typed peer with prompt, profile and contract tests | 60 minutes or less |
| Launch that peer and its Mesh in Agent Desk | 90 minutes or less |
| Run the first isolated repository scan with configured Redis and LLM | 2 hours or less |

Publish the exact commands and elapsed times. These targets measure framework
leverage, not defect-finding quality. A harness can start in hours; proving that
it finds and repairs important defects better than an established product takes
the full corpus and acceptance gates above.
