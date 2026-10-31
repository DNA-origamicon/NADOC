# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 9 (last production gates: October 28).
The active goal supersedes recurring stop-loss confirmation. The October 28 deadline was missed.

**Tools done: 4/4. CAD: 26/34 complete, 1 core exit (FH-27) and 7 parked milestones remain.**
FH-18/25/26/28, ISSUE-99 and ISSUE-126 stay closed. No production gate or milestone changed.

## Active task and binding policy — October 31

The user expanded the task to **all remaining FULL-suite failures**, including junction balance.
Single next task: review remaining failures by actual app accessibility before further repairs.
User policy: no app-facing option means experimental; avoid broader fixes for such workflows.
Keep molecular candidates isolated. Do not reopen closed milestones.
Automatic placement preserves covalent root lengths ahead of collisions. Roots sharing one rigid
cluster without defined relative joint/flexible motion retain strain; exempt Relax is an exact no-op
with a notice and no new history/undo. Never infer flexibility, split clusters or close these roots.
Manual moves may stretch roots; repositioned-overhang collisions remain the user's responsibility.
The NP 2 nm contact exemption covers only the host strand. The five-atom Direct closure is withdrawn.

## Repairs and validation

Entry HEAD: `f2c6081c` (Direct/root checkpoint; parent `f966f12a`). Evidence uses
`.development-artifacts/feature-history-focus/remaining-failures/` (abbreviated **E**).
Latest completed authorized FULL: **20,416 passed / 15 failed / 26 skipped / 2 errors**,
20,459 software cases, 3,594.55 s, two workers. `E/full.{log,json}` and `full-timings.json`.
Memory peak 6,444,445,696 bytes; high events 287, max/OOM/OOM-kill all zero.
Its 3,967,379,279-byte scratch is absent. Both previously failing historical drains passed.
The user-opened FULL window expired **October 31, 03:54:25 MDT**; do not renew or bypass it.
Focused development checks remain authorized. CPD and physical convergence campaigns remain excluded.

**Five families repaired; 15 original failing/error cases pass focused:**
- Reach planning (10): plan from the stationary covalent host O3′/P pivot used by attachment.
  Preserve fixed particle centers, reach refusal, root lengths and collision diagnostics.
- Inserted-root identity (1): choose the unique actual covalent edge across the owning strand's
  boundary copies. Missing/nonterminal/ambiguous ownership still refuses. Four added traversal
  checks cover inserted 3′/5′ roots in Viewer/Export.
- Strained linker fixture (1): native complement→bridge covalent bond is already 3.887128 nm
  (CG 3.370113 nm), with both roots in one rigid cluster. The native integration test requires
  public structural refusal for flagged, already-strained linker edges; missing identities, bad
  pairs and unrelated errors still fail. No decoder guard or production placement changed.
- Junction balance (2): user explicitly approved **14.625°** template-frame offset and exact
  geometry-lock refresh. Both original balance failures pass; lattice phases and tolerances stay fixed.
- Voltron area (1): user explicitly approved the obsolete area reference correction only.
  After the approved offset, area is **19044.137046 nm²**. The 5% tolerance, pinned fixture,
  surface algorithm, volume/count references and other panel entries are unchanged.

Focused evidence: `reach-focused.log` **3 passed / 58.57 s**; `generator-focused.log`
**21 passed / 902.01 s**; `linker-verified.log` **2 passed / 60.93 s** (actual ds/ss native controls).
`approved-focused.log`: **12 junction + 10 geometry-lock + 1 Voltron tests passed**, 50.23 s total.
Its scratch is absent. A first launcher rejected unsupported multi-target arguments before testing;
accepted validation used separate `just test-focused` targets under the resource wrapper.
`failure-families.json` maps every original failure/error to its cause and evidence.

Required post-offset SMART: **FAST (fast suite only), 19,802 passed / 2 failed / 19 skipped**,
724.10 s; `E/smart-junction.{log,json}`. Both prior junction failures pass. Newly red: the Direct
absolute-distance pin and section-proof timeout listed below. Zero unmarked 5 s violators;
aggregate 765 s / 90 s backstop debt remains. Skill triage: 1,387.7 s summed test time over 19,823
cases, no individual offender or demonstrated shared slowdown. No reclassification/budget change.
Observed peak 2,835,836,928 bytes; high/max/OOM/OOM-kill zero; 2,752,891,140-byte scratch absent.
Exact deferral: “DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.”
App Open/Full previously passed on generated NP platform: 51 helices, 129 strands, 13,212 nt,
3 particles/attachments, 17 rows, max graft residual 3.90e-14 nm, no page errors. Both roots absent.
Post-offset 2HB app Open/Full passed and final image was inspected: 2 helices / 5 strands /
140 nt, no page errors. Both roots are absent. First screenshot had the file-open overlay; the
harness-only visibility wait fixed it. Evidence: `E/junction-app/`, `junction-browser-final.log`.

## Exact remaining failures and decisions

1. `tests/test_mrdna_pipeline.py::TestSyntheticRoundTrip::test_zero_step_position_accuracy`
   Legacy reconstruction mean error 0.6911751375 nm vs <0.10 nm; max limit remains 0.25 nm.
   The old ideal oracle also differs from native CG seeds (mean/max 0.253191/0.998488 nm).
   Production decoder, seed reconstruction and that oracle remain unchanged and unapproved.
2. `tests/test_headless_corner_build.py::test_fold_optimizer_reduces_clashes_and_beats_reference`
   Current 13 bead clashes vs ≤11. Raw seam max <1 nm, total ≤3.43 nm, angle 90±5° remain intact.
   User clarified the model is experimental and asked about access. Saved workspace corner files
   can be opened; `build_corner()` is Python-only, with no app command or HTTP route.
   Its July 9 test is an experimental optimizer benchmark. Park its geometry repair. The placement
   approval request is set aside; test classification/thresholds remain unchanged during review.
3. `tests/test_direct_root_exemptions.py::test_native_connect_matches_unfitted_geometry_and_cold_replays`
   Newly red absolute pin: 7.558586405959171 vs 7.558951938676602 nm after the approved offset.
   Unfitted atom equality and cold replay PASS; this covers app Direct Connect/Relax. No runtime
   root-repair regression demonstrated. Test-reference correction remains to be reviewed.
4. `tests/test_native_section_proof.py::test_deleted_section_group_reports_missing_route_and_cascades_only_dependents`
   Newly red: extra synchronous proof hits its 0.5 s limit. Deletion/dependency checks PASS.
   Sections are used by Help → Generate design → Branched → Join branches and feature-log Delete.
   The failing synchronous proof endpoint has no frontend caller; investigate the harness without
   raising its guard. This is not evidence of failed app deletion.
`E/remaining-accessibility.json`: 4 failed cases, 1 entirely non-app workflow (corner), plus
1 test-only verification failure supporting app history. Other 2 cover user-facing Direct/MRDNA.

## Molecular evidence and limits

Approved junction review: `E/junction-review/review.html`; 72 Viewer/Export phase cases,
44 square/228 honeycomb covalent boundaries checked before placement. Offset 14.625° derives from
(8.23° + 171.02°)/2 − 150°/2. Balance residuals <0.000182 nm; atom/bond identities unchanged.
Viewer max displacement 0.000459 nm; Export 0.105564 nm. Some phases gain contacts; piercings do
not improve. Negative examples and per-junction evidence remain. Five exact stamps and 925 bridge
lengths were refreshed only after approval; all junction-key sets and tolerances are unchanged.
Voltron provenance: `E/surface-review.html`, `surface-conventions.json`, `approved-refresh.json`.
Legacy reconstruction area 18152.584097 nm² was within the old 5% band. September 20 retired that
placement but left Voltron's area reference behind. This was not a surface-algorithm repair.

MRDNA candidate remains isolated in `experiments/`. Existing `E/mrdna-calibrated-motion/` has
108 prescribed-motion cases (36 phases × zero/rigid/local twist), zero dynamics. Zero-motion atoms
are exact; rigid atom error ≤1.07e-13 nm; local-twist rigid-template error ≤4.08e-15 nm.
Nonrigid linker rebuilding differs by up to 0.312597 nm. Only direct paired fine sites qualify;
ssDNA/coarse/interpolated/loop-copy sites refuse. Ten motion/refusal tests pass guarded in 2.65 s.
An earlier 2.91 s invocation lacked the wrapper; the accepted repeat used it. Old aborted
`mrdna-phase-sweep` evidence is invalid because grid normalization erased its phase changes.
Current A/B comparator is production MD-seed reconstruction, not manifest display decoding.
New file-level prototype `experiments/mrdna_seed_candidate.py` regenerates the original native
fine reference: an intermediate-stage PDB must not reset earlier deformation. Its queued probe
was canceled before execution for the user's scope review; `E/mrdna-seed-probe-status.json`.
The prototype is unqualified, unapproved, and has no production caller; resume only within scope.

Corner candidate remains isolated: `E/corner-qualified-review/review.html` has 74 pre-offset cases,
24 active comparisons and 50 explicit no-ops for infeasible initial poses. Default rigid refinement
13→8 bead clashes, raw seam max 0.715856 nm, total 2.729436 nm, angle 91.173041°.
Atom contacts 20→11, piercings 8→4, bond flags 9→9; NEW piercings are shown explicitly.
It preserves topology/lengths but is not an authored Move/Rotate history or saved candidate design.
First two-2HB controls all refused; replacement controls use the native 56-bp length-only builder.
Do not promote this candidate while the experimental test scope is unresolved.

## Earlier work and shared-worktree closeout

`f2c6081c` resolved all 52 Direct/root FAST failures: 5 nonterminal fixtures, 3 reversed/ambiguous
fixtures, 4 unreachable inputs, 39 Viewer/Export conflicts, 1 driver-switch fixture. Constraints and
atomic refusal remain. Nonexempt frozen 2×2 relocation still needs separately approved geometry.
Preserve `workspace/Geometry Review/Platform - Root-preserving.nadoc`: 9 attachments, 3 particles,
45 helices, 124 strands, 13,176 nt, 58 rows. Later user save changed its hash; coordinate equality
was not requalified. Current/Candidate files remain historical four-attachment captures.

Commit explicit owned paths locally, `history: ...`; no push, stash, reset, restore or history rewrite.
All 203 pre-existing dirty entries still match entry hashes. Only approved constants/surface oracle
changed among the 14 locked inputs; see `E/ownership-post-approved.json`. Recheck before commit.
Pre-existing API/VR/simulation/activity/memory-hygiene work stays untouched and unstaged.
Final lint and memory hygiene checks pass (0 errors/warnings); owned experiment Ruff checks pass.
Local checkpoint includes the owned repairs and isolated diagnostics; the four review items remain.
No frontend behavior change; `main.js` LOC delta 0. No gate/milestone reopened or closed.
