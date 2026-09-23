# R1–R9 routing resolution

Implemented with user authorization on 2026-09-22. Conversion findings C1–C7 and
mrDNA finding M1 remain under review; their implementations were not changed.
The original audit results and fingerprints remain historical evidence.

| ID | Implemented behavior | Verification |
|---|---|---|
| R1 | Preflight scaffold extensions; check active occupancy before/after routing. Reject the whole candidate on conflict, returning the original design with an explicit failed result. API rejection leaves history unchanged. | Four public routers, both lattices, both faces; duplicate and self-overlap validator cases; API snapshot regression. All 32 original extension probes now return collision-free original designs. |
| R2 | Reset leaves fresh designs alone and declines to rebuild a routed scaffold containing an unstapled helix domain. Explicitly manual scaffold crossovers also prevent reset. | Mixed supported/unsupported path retained; historical probe now preserves all 532 domain nucleotides. |
| R3 | Reseeding merges only touching coverage, preserving disconnected intervals within a staple span. | Fresh gap probe and previously routed gap regression. |
| R4 | Reference strands no longer contribute active routing coverage or crossover strand type. | Identical active paths with/without the reference obstacle across all four routers. |
| R5 | Crossover placement restores its original input when validation rejects the candidate; temporary nicks are discarded. | Exact design snapshot regression. |
| R6 | Validation and public routing report direction-inconsistent bounds. | Reversed-bound regression and original probe. |
| R7 | Validate active endpoint coverage, duplicate junctions, and consistency between junction records and backbone transitions; reject uncovered crossover placement. | Missing endpoint, orphan ligation, duplicate record, missing transition record, and valid periodic forced-ligation controls. Pending terminal connections remain representable. |
| R8 | Validation uses the shared insertion/deletion-aware sequence length calculation. | One-insertion case accepts 85 bases and rejects 84. |
| R9 | Remap assigned scaffold bases by helix, coordinate, direction, and insertion ordinal through reset/routing. New positions receive N. | Nonuniform sequence with insertion and deletion survives routing/reset/rerouting; original reset probe retains all 336 assigned bases. |

## Deliberate forced ligations

Reset retains its existing forced-ligation bypass. Each public routing transaction
also verifies that every original directed forced-ligation edge remains in the
actual backbone. The original record, ID, extra bases, and periodic-seam metadata
are retained. A candidate that cannot preserve a connection is rejected as a whole;
no feature-history entry is added. This preserves intentional multi-scaffold joins
without silently asking a new route to reinterpret them.

The regression constructs a deliberate two-scaffold join and checks reset and
repeated routing with all four routers. This protection does not promise every
constrained design can be autorouted: rejection is an intended safe outcome.

## Evidence and limitations

- Focused guarded tests: **124 passed, 2 skipped**. Coverage includes idempotence,
  scaffold invariants, section routes, and available hinge fixtures.
- Lint for the new modules/regressions passed; `git diff --check` passed.
- [Post-fix probes](results_after.json): the same 126 observations as the original
  harness, including unchanged conversion failures. These observations are not a
  substitute for the regression suite.
- Browser check uses temporary isolated backend/frontend servers and workspace,
  loads a representative four-helix `.nadoc`, and invokes the real routing API.
  [Screenshot](routing-fixed.png) and [browser result](browser_validation.json) are
  retained review evidence. Temporary workspace, server processes, and test-port
  credential file are removed in a `finally` block, including on failure.
- No native scientific simulations were run. No molecular placement or locked
  phase constants were changed.

Final `just test-smart` decision: **FAST (fast suite only)**.
**8,852 passed, 7 skipped, 7 failed**, 105.12 seconds in pytest / 110 seconds
under the guard. All seven failures originate in `tests/test_photoproduct_review.py`
while copying the missing external fixture:
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`.
They occur before the routing code is exercised. The overall suite is not green.

The guard also flagged the aggregate 90-second backstop. Following the
`triage-slow-tests` skill, the timing report was inspected: **zero per-test
violators**, slowest individual test 4.60 seconds (streptavidin packing). No routing
regression warranted reclassification; budgets and classifications were left intact.
The aggregate overrun remains unresolved. [Timing report](timing_final.json).

Deferred output, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
