# Assembly Simulations: tab-opening freeze

Prior sharing/visualization/annotation work committed and pushed as `27c50980`
on `feature/standalone-viewer-presentations` before this change.

## Findings and changes

- The shared API adapter flattened an assembly before **every** request under an
  engine prefix, including availability, job lists and recommendation refreshes.
  Replaying committed `simulation_context.js` confirms one unwanted preparation
  for each cold `/simulate/recommendation`, `/oxdna/available`, `/md/jobs` and
  `/cando/jobs` request. Preparation loads a full Design and synchronizes geometry
  into frontend state, so opening a sidebar could do whole-assembly work.
- Preparation now distinguishes HTTP methods and skips passive browsing,
  hardware/capability reads, status polling, cancellation/stop, and archives.
  Explicit design consumers retain preparation: creation, previews, estimates,
  continuation checks and result alignment. The previously missed design-prefixed
  oxDNA/CanDo autorefine paths use the same seam.
- A failed preparation cannot fall through and launch against a previous Design.
  Preparation requests serialize; returning through part mode invalidates the
  prior assembly projection.
- Recommendation GET incorrectly supplied a JSON `null` body. Real Chromium
  rejected it with “Request with GET/HEAD method cannot have body.” Removed it.
- Recommendations can inspect the assembly without flattening or replacing the
  active Design. Per-source nucleotide counts are multiplied over visible copies
  using the existing nucleotide traversal, with assembly strands included. This
  is a source-count estimate for policy, not a substitute for prepared topology
  validation (periodic stitching can change the final count). Assembly and source
  protein presence are included. Work runs off the API event loop.
- Unified jobs use `flat_<assembly id>` directly, including remote artifact lookup,
  before any projection exists. Part filtering retains its previous behavior.
- NAMD's workspace-path provider now follows the assembly host, as the other
  engine panels already did. `main.js` LOC delta: **0** (one wiring replacement).

## Parity inventory and verification scope

| Surface | Status |
| --- | --- |
| Five visible engine tabs, availability and options | Shared panels retained; browser checks below |
| Recommendation and unified job identity | Adapted for lightweight assembly browsing; part/assembly tests |
| All six engine preparation paths (including LAMMPS fallback) | Existing focused parity test rerun; identical complete two-copy namespaced topology and prepared input files |
| Saved jobs, progress and lifecycle dispatch | Shared engine implementations retained; focused parity test |
| Stop/cancel and archive access | No longer require flattening; request-policy regression tests |
| Preparation failure | Explicit regression: no job request follows a failed projection |
| Scientific solver execution, remote execution and convergence | Not run: this request is software validation; no production sampling authorized |
| Every engine's completed-result visualization | Existing shared behavior retained, not newly exhaustively verified in this tab-opening fix |

## Validation

- `just test-frontend`: **7,106 passed, 1 skipped**, 550 files, 105.37 s.
- Focused frontend request/context checks: **9 passed** (also included above).
- Focused assembly browsing backend: **4 passed**; six-engine prepared-job parity:
  **1 passed**, testing all six engines in one workflow (no solvers launched).
- Playwright: **2 passed**, 3.1 min total. BigO (30 copies) visits all five engine
  tabs with zero flatten calls and no Design replacement; source-count policy is
  423,360 nucleotides and its disposable identity has no jobs. Standard part visits
  the same five tabs and reports its 200 nucleotides correctly. No console errors.
  BigO source-count recommendation measured separately at **0.353 s**.
- BigO headless tab gestures still take **11–19 s** under SwiftShader software
  rendering (baseline 16–20 s). This fixes unsolicited whole-assembly preparation;
  it is not a claim that large-scene software rendering meets the one-second goal.
- The narrow-window test initially could not open another sidebar because the
  existing layout correctly refused an extra column with “No room.” Final test
  closes other panels before opening Simulations; sidebar semantics are unchanged.
- `just lint` and `git diff --check`: passed.
- `just smoke`: **23 passed**, 2.2 min. Production build: passed, 9.76 s
  (existing large-chunk warning).
- `just test-smart` decision: **FAST**. **9,293 passed, 15 skipped, 8 failed**,
  98.37 s pytest / 105 s guard. Seven failures require the missing external
  `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json` archive;
  `test_cpd_preview::test_snapshot_refresh_preserves_evidence_and_release_registry`
  retains its existing coordinate-golden mismatch. These are the same eight
  failures recorded in the annotation audit; no scientific evidence or goldens
  were changed.
- Applied [triage-slow-tests](../../.claude/skills/triage-slow-tests/SKILL.md) to
  the aggregate 105 s / 90 s notice. **Zero per-test violators**, slowest 4.94 s.
  Reviewed the report, shared workspace fixture, existing host-probe stubs and
  the two largest cumulative files (45 mock lifecycle cases / 24 s;
  246 oxDNA cases / 23 s). No newly exposed host probe or single heavy test was
  identified. Similar aggregate overruns with fewer tests are already recorded
  in `project_test_parallelization.md` (99–116 s); the 9,316-case suite retains
  aggregate runtime debt. No markers, guards or time budgets were altered.

The selector's deferred notice, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

## Artifact inventory

Browser tests use isolated ports 8002/5175, session cache disabled, and only
`__e2e__` assembly/part identities. BigO and its source remain read-only. No jobs,
external downloads or screenshots outside Playwright output are created. Global
teardown removes prefixed workspace files and associated project stores even on
failure; the cleanup reporter removes test output. The baseline run caught the
GET-body defect. One development rerun was interrupted after a source change
invalidated its browser session; the final run uses unchanged frontend sources.


Final cleanup verified: no new workspace-root entries, no remaining `__e2e__` or
`e2e__` paths, no Playwright report/output directories. SHA-256 hashes of BigO's
assembly, its source part, and the smoke Example are unchanged. Temporary logs
were summarized here and removed. Simulation fixes are left in the working tree;
the earlier requested sharing/visualization/annotation commit is already pushed.
