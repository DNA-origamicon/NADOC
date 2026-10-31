# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 4 (last production gates: October 28).
The active goal and expanded-repair authorization supersede recurring one-task/stop-loss confirmation.
The original **October 28, 2026 before 6 p.m. America/Denver deadline was missed**.

**Tools done: 4/4. CAD: 26/34 complete, 1 core exit (FH-27) and 7 parked milestones remain.**
FH-18/25/26/28 stay closed. Move/Rotate, Fine Routing and the four tool gates stay qualified.
ISSUE-99 is resolved at the selected cluster scope; MV-48 retains FH-27 integration/resource debt.
ISSUE-126 duplicate-slot refusal/publication/repair/undo remains closed. Do not reopen closed work without a reproduced regression.

## Current user rule and next task — October 30

Automatic NADOC processes must preserve overhang-root bond lengths ahead of collision avoidance.
Manual edits may stretch roots. Collisions of repositioned overhangs are the user's responsibility,
including NP positioning before simulation. The 2 nm contact exemption covers only the host strand.
This explicitly authorizes the root-preservation repair; the earlier shortest-root candidate is superseded.
It does not authorize unrelated molecular changes, phase/threshold/golden changes or simulations.

**Single next task: finish this rule for ordinary Direct Connect and its Relax solver.**
A read-only reproduction of the existing end-to-root fixture (`_seed(cluster_b_translation=(6,3,2))`
then `_cv_create_bound_binding`) measures actual O3′–P roots, in both viewer/export builders:
OH A **0.136575 → 1.773216 nm**; OH B **0.136575 → 1.564670 nm**. Source is unchanged.
This is a confirmed violation, not merely an unaudited solver. `duplex_midpoint_placement` currently
shares the stretch between the roots; old tests deliberately assert that behavior. Supersede it under
this explicit user rule: preserve both roots or refuse atomically when placement is unreachable;
retain manual Move/Rotate freedom. Audit Relax against the actual covalent endpoints as well.
Evidence: `.development-artifacts/feature-history-focus/direct-root-scope.json` (scratch absent).
Do not claim universal root preservation from the completed NP repair below.

## Completed NP root repair

Automatic NP attachment, generation and collective relaxation pivot around the stationary covalent
root atom, compose translation plus rotation, and solve axial roll to preserve both viewer/export
linker lengths. Keep graft closure and unreachable-fit refusal. Clearance ranks feasible poses and
remaining collisions are advisory. Generator finalization retains the saved covalent pivot; manual
NP movement commits its preview pivot. Manual overhang/duplex translation remains unrestricted.
No atom templates, phase constants, detector thresholds or geometry goldens changed.

Complete requested native design: `workspace/Geometry Review/Platform - Root-preserving.nadoc`.
It has 9 attachments, 3 fixed-center gold particles, 45 helices, 124 strands, 13,176 nt and 58 native
feature rows. Maximum root-length change **1.70e-14 nm**; maximum graft residual **1.54e-14 nm**.
Ordinary app Open/Full preserves all geometry/attachment records, shows all three gold meshes and
has no page errors; screenshot inspected. No full-history editing/replay or simulation claim.
SHA256: `c0bafdc8d855d050733306c257b921ab8069ff28b6caf034b6ded869585c5182`.
Evidence: `.development-artifacts/feature-history-focus/root-bond-repair/` (manifest and cleanup).

Focused passes: 9 root contracts, 10 attachment, 6 kinematics, 18 NP lifecycle and 9 review/platform.
The 14-case generator matrix had 13 passes and one final gold-overlap refusal; advisory finalization
repairs that exact six-connection/rebind case (33.55 s). Final platform/root/pivot check passes (40.24 s).
Lint/whitespace passed; `main.js` unchanged. All owned browser/FAST/focused scratch and launchers absent.

Required `just test-smart`: **FAST (fast suite only), 19,711 cases, 4 workers; 19,689 passed,
19 skipped, 3 failed**, 315.52 s (339 s guard wall). Two unchanged square/honeycomb junction-balance
1 pm oracles remain. The third was an incomplete NP `SimpleNamespace` test fixture, corrected to the
real model; all 5 native NP placement tests then pass (2.72 s). No production change followed FAST.
Raw broad result remains three failures. Native incident `20261030T213106-c3ff173d61e2` has retained
root-cause review and explicit Codex acknowledgement; review gate clear.
Exact deferral: “DEFERRED: this change would have needed the FULL suite, but no test-dedicated session
is open, so only the fast suite ran. Parked in .nadoc-slow-pending.” No marker/budget changes.
Timing triage: zero 5 s violators, maximum 4.17 s, aggregate 1,148.0 vs prior 1,224.6 worker-seconds;
no reclassification or demonstrated shared-fixture slowdown. FAST scratch removed: 2,753,217,249 bytes.

## MRDNA diagnosis retained; production unchanged

After Direct root repair, resume the isolated zero-step decoder investigation. Fresh production
parameterized fine PSF/PDB for `Examples/2hb_xover_val.nadoc`, **zero ARBD/dynamics steps**:
- Local mrDNA list reader seeds DNA at the two CG input sites' midpoint; O is 1.5 Å along frame x.
  The old FORWARD-backbone claim is false for this bridge. CG input and native Full O5′ are distinct
  conventions; their 0.349 nm mean separation alone is not a defect.
- Legacy sigma=0 decoder reproduces the unchanged failing 0.691 nm oracle; it ignores O orientation.
  Current manifest decoder mixes native O5′ pair centers with CG centers and applies an unmatched
  90° frame conversion. Its zero-step displacement from native Full averages 1.204 nm.
- Isolated matched-frame transport recovers CG sites to max 7.24e-6 nm and native Full reference
  points to max 6.68e-6 nm. Seven focused tests pass (3.31 s): zero-motion preservation, independent
  rigid motion/local twist, and explicit refusal of unsupported bindings. Ruff/whitespace pass.
- Actual production MD-seed decoder (default sigma=1.5) gives atom displacement mean/max
  **0.313880/0.562561 nm**; isolated candidate **0.000184/0.043411 nm**, 2,800 identical atom/bond
  identities. Remaining largest differences are crossover linker atoms. Even exact CG input sent
  through the existing override builder shifts linkers up to 0.008798 nm: minimizer sensitivity.
- Current/candidate clashes 2→0, piercings 0→0, flagged bonds 6→12; candidate's 12 match the native
  reference. These are unchanged detector verdicts, not a simulation-readiness claim.

Code: `experiments/mrdna_frame_candidate.py`, `experiments/mrdna_zero_step_review.py` and focused tests.
Evidence: `.development-artifacts/feature-history-focus/mrdna-decoder-review/` includes exact points,
source/code hashes, all current/candidate/native atoms, four junction deltas and exact defects.
`comparison.preliminary.json.gz` is **not approval-ready or registered in Help**. No production decoder,
MD seed, oracle, phase or golden changed. Qualify nonzero atomistic transport and the full phase sweep,
then prepare the in-app review with real full geometry and explicit construction steps before asking
for molecular approval. ssDNA, coarse/interpolated sites and loop copies remain unsupported by the
candidate; its point-transport tests do not qualify those or an atomistic trajectory decoder.

## Remaining FH-27 regression / integration debt

Last completed FULL: **20,297 passed / 26 skipped / 9 failed / no errors**, 2,621.09 s,
20,332 software cases, 2 workers. Zero unmarked 5 s violators; no OOM/hard-limit events.
Evidence: `expanded-full-repaired.{log,json}`, `expanded-full-repaired-timings.json` under the focus folder.
Its 4,027,076,897-byte scratch is absent. The user-opened broad window expired October 28 at
11:52 p.m. MDT; do not renew/bypass it. Focused development checks remain authorized.
Retained failures: two sealed historical drains (`dimensions-bend`, `readiness-twist`), MRDNA zero-step,
corner 13 vs 11 clashes, Voltron area 5.354% vs 5%, square/honeycomb junction balance; the remaining
FULL platform collision refusal and branch 7,230 vs 7,249 nt shortfall have since been repaired focused.
No failure is waived and focused passes do not clear FULL.

Prior expanded repairs retained: NAMD cancellation cleanup off event loop/reaping; bad-frame audit
fixture conversion; generator retained-handle ordering; branch resequencing before candidate selection;
lazy proof/display dispatch imports. Focused branch test passes (100.05 s), 243 cold-import/proof checks
pass (120.15 s); worker readiness median 1.138→0.656 s. These do not prove broad-load drains resolved.
Branch app inspection shows 7,249 nt, 12 connections, 134 feature rows, fixed four particle centers,
residual ≤9.30e-14 nm, no errors. All owned scratch/launchers absent; `expanded-cleanup-final.json`.
Previous full frontend: 9,490 passed / 1 skipped; Geometry Review app 1/1, smoke 23/23 and build/lint pass.
No frontend behavior changed in the root or MRDNA diagnostic work.

## Review/history and scope boundaries

Help → geometry Review retains the historical rejected attachment/shortest-root candidate and two
unchanged controls. User requested full native workspace copies because that crop omitted gold/context.
`Platform - Current.nadoc` / `Platform - Candidate.nadoc` are four-attachment captured import states,
not completed nine-attachment designs or replayable candidate histories. Both rendered with all gold
and full geometry. They were later user/app saved; do not restore earlier artifact hashes. The separate
Root-preserving file above is the completed native generation. Historical evidence remains in
`platform-bond-clearance-review/`, `full-geometry-workspace/` and `geometry-review-*`.

Clusters own geometry among grouping constructs; Staple Groups organize strands. Organization gates
stay OFF. Seven asset/import milestones, PartGroup migration, arbitrary named-group motion/compiler
rollout, old-file compatibility and simulation/agent provenance remain excluded. Preserve cold replay,
exact Cancel, one Apply/undo, stable identity, earliest-error feedback and failure atomicity.

## Shared work and closeout

Base HEAD before this closeout: `498fbc16` (in-app review). Prior overhaul/recovery repairs are committed;
see Git history. Commit only explicit owned paths under operating-contract §7; no push or history rewrite.
Pre-existing API/VR/simulation/strict-host/activity/test/memory-hygiene edits stay untouched. In particular,
strict-HTTP assertions depend on pending sealed adapters; do not commit them without that implementation.
Mixed memory files (project_mrdna_panel, project_nanoparticles, project_feature_log_overhaul) remain
uncommitted; so do prior implementation/conftest/manual-debt reconciliation hunks. Do not stash/reset.
This closeout also verifies the new diagnostic's scratch and empty focused-test workspace are absent;
its duplicate temporary probe is removed, with the reproducible experiment and full evidence retained.
`mrdna-decoder-review/cleanup-final.json` records absence. Memory lint: zero errors/warnings.
The local session commit contains the NP repair, isolated MRDNA experiment/tests, these corrections
and the handoff; inspect the latest `history:` commit for its hash. No push. FH-27 remains open.
