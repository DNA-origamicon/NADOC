# Feature-history campaign handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 0 (ordinary protein import gate ON November 1).
The user requested the next three independent milestones after the original 14:00 campaign; no new deadline was supplied.

**Tools done: 4/4. CAD: 30/34 complete; FH-27/31/32/36 remain open.**
FH-30/34/35 closed in the preceding campaign; FH-18/25/26/28, ISSUE-99 and ISSUE-126 remain closed.

Evidence root **C**: `.development-artifacts/feature-history-focus/`.

## November 3 — actual workspace autosave interruption

User verification superseded the prior refresh-only diagnosis: the earlier app
fixtures did not activate ordinary workspace autosave. Opening an isolated copy of
`workspace/test.nadoc` through the normal workspace route reproduced the popup
closing after a successful autosave advanced revision10→11 with no changed inputs.
The source guard correctly rejected that revision; tolerating equivalent GET data
alone did not solve the user's failure.

Extrude now uses the existing workspace-save coordination lease. It drains saves
already in flight before taking its edit source, holds later workspace writes
through temporary scrubs/draft editing, and releases them after Apply/Cancel
restores the opening cursor. Document reset/failure also releases the lease.
The real unmodified workspace flow now survives a12-second dwell. The durable
regression covers both Cancel and Apply, retained lattice selection/parameters,
resumed autosave, reopen and recipe proof. Both real-file cases pass (34.9 s and
35.9 s);21 controller tests plus2 save-coordination tests pass. Original file SHA256
`232f14b590dc0ccc7181afa4388eaddf44af1bbd9e918c707f045e2dcc047bb1`
is unchanged. Full frontend: **805 files /9,599 passed /1 skipped**,379.10 s.
Lint and whitespace checks pass; isolated `just smoke`: **23 passed**. All7 owned
browser roots are verified absent; original source checksum remains unchanged.
Evidence: `C/extrude-autosave-20261103/`. The user's file is read only; diagnostic
copies use ordinary import/Save As in isolated launcher storage. Copies preserve
the original open-name: otherwise the workspace loader stamps the temporary
filename into authoring metadata and correctly fails recipe comparison. The first
copy also had an incompatible existing revision-store head; legitimate Save As
provides its own project identity. Neither diagnostic artifact problem is evidence
of a native-edit defect in the user's source. The separate full agent audit reports
physical loadout state outside native authoring replay; native recipe proof after
the corrected workspace flow passes. No main.js change.

## November 3 — Extrude session stability and return position

Follow-up: equivalent passive design refreshes (including recovery-body hydration)
no longer retire the Extrude picker or discard its draft. The editor rebinds only
within the same document generation and authoritative revision, with unchanged
cursor and authored data. Actual input/revision/document changes still invalidate
it. Apply now restores the opening feature and child cursor after rebuilding the
full suffix; Cancel continues to restore that cursor and camera. A failed return
seek after successful publication reports that navigation failure without offering
the already-committed draft as a retry.

Regression coverage delays a real GET design response while changing the length
in the ordinary popup, then checks Apply from end, Extrude, and downstream positions,
save/reopen cursor persistence and full-recipe proof. Unit coverage includes late
recovery bodies, equivalent full refresh, actual input/revision changes, child
cursors and failed post-publication navigation. Evidence:
`C/extrude-edit-stability-20261103/`. Delayed-refresh app matrix: **3 passed**,
including saved/reopened cursor and complete-recipe proof. Both automatic-routing
orders also passed. The three owned history roots are absent; the interrupted
frontend command had not started its suite and was restarted. Full frontend:
**805 files /9,596 passed /1 skipped**,395.87 s. Lint and whitespace checks pass;
isolated `just smoke`: **23 passed**. All four owned browser roots are absent.
`main.js` delta for this follow-up:0. No backend or assembly behavior change.

## November 3 — Extrude edits in the ordinary lattice tool

For bundle-create, extrude-segment, canonical extrude-continuation and
extrude-deformed-continuation, Edit now seeks to the feature, binds occupancy to
its recorded prefix, restores the selected cells and signed parameters in the
ordinary Extrude popup, and aligns the camera face-on to the selection. Apply
edits the original feature through the existing native editor and rebuilds the
retained suffix. Cancel restores the opening cursor and camera without editing
feature inputs. Navigation uses ordinary seeks (and therefore ordinary navigation
undo entries); the final native edit remains one undoable operation.
The popup moves over an adjacent sidebar when the canvas is too narrow to select
cells beside it. Hidden plane handles no longer intercept lattice clicks.

Specialized circle, overhang, frame and source-frame continuation features retain
their dedicated parameter editor; the ordinary lattice tool cannot represent all
of their inputs. Other feature editors retain the restore-end behavior below.
Assembly work remains deferred. User workspace files are untouched.

App workflows: **6 passed** — two real six-helix selection/Cancel/Apply flows with
both automatic-routing orders, bundle→Bend→Sweep, and the three lattice extrusion
variants. Feature IDs, suffix inputs, undo/redo, saved/reopened geometry and
independent recipe replay pass. Evidence: `C/extrude-tool-edit-20261103/`.
The successful browser root `/tmp/__e2e__history-4astvl7f` is removed.
Full frontend: **805 files /9,587 passed /1 skipped**,391.83 s. Lint and diff
whitespace checks pass; isolated `just smoke`: **23 passed**. All seven owned browser
roots are verified absent, including smoke. No deployment or backend behavior change. `main.js` delta: **+3 lines**,
solely import, factory initialization and callback wiring; behavior lives in
`frontend/src/app/extrude_history_editor.js`.

## November 3 — editing from a scrubbed feature

User correction: a supported feature is editable when the cursor is at it or later,
including Fine Routing child positions. F0 and future steps remain unavailable.
The part rail now uses that rule. Except for the ordinary Extrude flow above, clicking Edit restores the complete retained history
through ordinary seek before opening the existing guarded editor; this moves the cursor
to the end without deleting a suffix or authoring an operation. Failed restoration or a
document switch prevents opening. Assembly behavior is unchanged.
Frontend suite: **803 files /9,562 passed /1 skipped**; final focused cursor/editor checks:
**46 passed**. Evidence: `C/edit-at-cursor-20261103/`. `main.js` LOC delta:0.
Browser: **2 passes** (34.6 s and 28.2 s), scrub to Extrude then Edit, both
Extrude→Autoscaffold→Autostaple and the saved `test.nadoc` operation order
Extrude→Autostaple→Autoscaffold. Downstream inputs/IDs, regenerated geometry,
one Save undo step, redo and saved/reopened independent recipe proof pass.
The initial browser assertion counted navigation undo steps as edit steps; it now
measures Save against the restored editor source. Both disposable roots are absent.
Isolated app smoke: **23 passed**; `just lint` and diff whitespace checks pass.
Smoke workspace cleanup verified absent as well. User `workspace/test.nadoc` was read
for diagnosis and never modified. No backend behavior change or new broad backend run.

## November 2 — upstream Extrude through automatic routing

The existing native extrusion editor rebuilds both downstream automatic routing commands;
no new replay implementation is needed for the tested six-helix length-edit case.
`tests/test_extrusion_auto_routing_history.py`: **2 passes**, real spawned evaluator,
seamless and seamed scaffold routing followed by full Autostaple, 84→126→63 bp.
Results equal fresh native construction at each length; downstream feature identities and
inputs persist. Cold proof after JSON reopen, undo/redo, and atomic invalid-length refusal pass.
Browser: `Early Extrude edit reapplies Autoscaffold and Autostaple` **1 pass /41.0 s**:
actual feature-log Edit/Save, changed geometry, one undo, redo, saved/reopened native proof.
Launcher cleanup verified `/tmp/__e2e__history-xq5zb3l_` absent. Test-only additions;
no fresh broad suite needed. Ruff and diff whitespace checks pass.
No molecular algorithm change; `main.js` LOC delta:0.

## November 2 — piercing visualizer and performance

**Piercing performance follow-up (ISSUE-166):** precomputed ring triangles and
bounded vectorized intersection batches preserve the existing criteria and exact
reports. Terminal-linker warm benchmark: scan **31.76 → 0.43 s**, combined check
**32.25 → 0.86 s**; 208,000-atom platform **4.40 s**. Checks exceeding one second
show a spinner and measured bond-check percentage beside the piercing count.
Preparation remains 0%; cancellation and completion clear the indicator and
document-scoped progress record. Actual app: Full terminal/corner findings unchanged;
large platform in Cylinders showed the spinner at 1.03 s, advanced through
15/32/44/59/76/94/99%, completed at 7.57 s, and passed toggle-off cancellation.
All three screenshots inspected then removed; all three disposable app roots
removed, source-file hashes unchanged. Evidence:
`.development-artifacts/piercing-performance-20261102/`. No molecular repair or
polymerization conversion change is included; ISSUE-163/164 remain deferred.
Qualification: **55 focused backend / 27 focused frontend**;
**SMART FAST 19,964 passed / 19 skipped** (428.60 s; FULL deferred by the same
selector message below); **frontend 802 files, 9,545 passed / one skipped**
(383.99 s). Aggregate timing triage found zero per-test violations, maximum
3.93 s, summed 1,582.3 s versus prior 1,596.1 s; no budget/classification changed.
Isolated **`just smoke`: 23 passed** (2.6 min), cleanup verified absent.
Lint and memory hygiene pass. `main.js` LOC delta: 0.

**Clash visualizer follow-up (ISSUE-165):** the clash toggle now includes the
existing ring-piercing detector over atomistic **display** coordinates. Red halos
identify backbone clashes; cyan wireframe diamonds identify bases participating
in a pierced bond/ring. The legend separates counts and definitions, shows pending
or unavailable checks, and labels capped results. Source geometry is unchanged.
The actual retained terminal-linker app check reports zero clashes / one piercing,
marking `Extension - 0[-5›3]` and `Extension - 0[-5›2]` on S37. The corner fixture
reports six clashes / one piercing. Full and atomistic pixels, representation
switching, off cleanup, and shared-view serialization are qualified. Focused tests:
55 frontend / five backend passed. Evidence: `.development-artifacts/clash-piercing-20261102/`.
Complete qualification: **FAST 19,954 passed / 19 skipped** (432.80 s);
**frontend 801 files, 9,538 passed / one skipped** (369.40 s); isolated
**`just smoke`: 23 passed** (2.5 min). Lint and memory hygiene pass. The aggregate
FAST timing warning was reviewed with `triage-slow-tests`: zero per-test violations,
maximum 3.88 s, summed 1,596.1 s versus prior 1,617.6 s. No new shared accidental
delay identified; no budget or classification changed. `main.js` LOC delta: 0.
Selector output (verbatim):
```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```
Both isolated app roots and their processes were removed; source hashes unchanged.
Five reviewed screenshots (1,773,667 bytes) were pruned after visual inspection;
compact results and reusable exercise scripts remain in the evidence directory.
Production conversion (ISSUE-163) and long-extension repair (ISSUE-164) stay deferred.

## Current three-milestone scope — November 1

Selected FH-33 original protein inputs/library placement, FH-31 fitting/bound motion/multi-anchor relaxation,
and FH-32 coupled biotin create/remove. New explicit goal was not created: the prior deadline campaign was complete.
FH-33 closes: ordinary free/library placement gate is ON after retained-state, desktop and required SMART passes.
FH-31/32 have tested native numerical commands in the existing worker; both append rollout gates stay OFF.
No molecular review was approved. Old-file compatibility, experimental CPD and Python-only corner optimization stay excluded.
No new host, queue, storage layer or scientific algorithm was added. Organization/PartGroup gates remain OFF.
Evidence root **C**: `.development-artifacts/feature-history-focus/`.

## Protein source and placement qualification

See [FH-33 contract/evidence](protein_free_import_contract.md#fh-33-source-and-placement-qualification--november-1-2026).
Library imports retain exact source/filter choices; placement copies the existing source envelope into the document,
with import plus attachment/conjugation in one revision/undo. Replay has no library fallback or atom-to-PDB reconstruction.
Both entry routes preserve original bytes; equal atoms with different source/filter inputs do not deduplicate.
The source table survives native bundle reconstruction: a red regression and the real desktop edit both exposed its loss.
`next3-protein-destinations-20261101`: **330/330** expected outcomes, eleven boundary/retained cases, eight cold proofs.
Worst p95 route/capture-lock/publication-lock/light request: **294.452/15.280/4.056/24.047 ms**; max capture **23.984 ms**.
Empty atom-copy destinations allocate before the lock and receive scalar source values under existing isolation/accounting.
No GC policy, 25 ms capture, 30,000 nodes/2 MB, 8 MB recovery, scientific formulas or old numerical pins changed.
`next3-protein-desktop-qualified-20261101`: **2 pass**, actual File and Tools menus, upstream edit, undo/redo,
save/reopen, original-byte equality and cold proof; zero console errors. Observed display adoption **223/695 ms**.
Library fixture uses the existing harness's unrelated-request stubs and paused software GPU raster.
Earlier failed benchmarks, browser fixture/menu attempts and actual missing-source failure remain in C.

## Two numerical candidates — rollout remains open

[FH-31 contract](nanoparticle_connection_contract.md#fh-31-numerical-candidate--november-1-2026): exact bounded
particle/graft/target/active-anchor selection, deterministic identities and numerical code/runtime provenance;
unchanged fit, constrained movement and one-to-four-anchor solve. Solved poses remain outputs.
[FH-32 contract](coating_input_plan.md#fh-32-biotin-candidate--november-1-2026): pinned original coating/tether PDB,
sequence/pocket/linker/site intent and exact owned removal. Existing pocket/clearance math is unchanged.
Explicit pin upgrades and exact source restoration use existing repair; ordinary edits cannot refresh pins.
`next3-assets-final-focused-20261101`: **169 pass**, including native full-output parity, two/four anchors,
cold-worker lifecycle/edits, exact ownership/bounds, actual capture/commit/undo/cancel/stale publication.
`next3-numerical-repair-20261101`: **99 pass**; `next3-bundle-source-green-20261101`: **18 pass**, including new repair/source controls.
Actual biotin deadline failures remain evidence. Bounded preallocated destinations in the existing coating capture
preserve its 100 ms/100,000-node/4 MB profile; three later real job checks pass at **49.45–91.59 ms** capture.
Worker correctness separately uses a test-only 1 s capture clock; this is never production qualification.
Remaining FH-31/32: ordinary entry-point/editor integration, complete admitted connection removal/replacement,
downstream diagnostics and repeated boundary/retained-history/display qualification. Neither milestone is closed.

## Validation and next task

`next3-smart-20261101`: first required FAST **19,994 pass /8 fail /19 skip**, 467.23 s; six protein route-contract failures and two wrapper Unix-socket path failures. No broad test session is open.
Protein HTTP status/revision/metrics contracts are restored; typed native prevalidation retains exact reference diagnostics and legacy checks remain parametrized.
The 5.03 s slow-guard offender was the socket startup timeout: owned reproduction at 112 bytes gives `AF_UNIX path too long`. Wrapper roots are shortened to `/tmp/n3-*`; no budgets/markers change.
`next3-protein-http-regression-20261101`: 139 pass /one new assertion used the wrong missing-reference code; corrected. `next3-protein-pins-explicit-20261101`: **142 pass**, including current duplex/coating pins and retired-pin refusals.
The prior pin invocation split its exclusion argument and was refused before collection; explicit duplex/coating nodes replace it. No CPD test ran.
`next3-smart-final-20261101`: required **FAST 20,005 pass /19 skip**, 459.60 s pytest /467.74 s wrapper. Zero per-test violators; maximum 4.43 s. Full sweep stays deferred below.
Slow-test skill review: aggregate runtime warning only; summed test time fell 1,728.0→1,702.3 s. Existing solver/replay families dominate; no new shared accidental delay identified. No reclassification or budget change.
Next: FH-31 ordinary job/editor integration and complete connection removal/replacement after relaxed/multiple-anchor state; keep its gate OFF until app and repeated-boundary qualification pass.
No frontend production code changed; final app exercise passes. Scoped Ruff (36 Python files), memory lint (zero errors/warnings) and `git diff --check` pass.
All 26 completed wrapper roots and browser-owned workspace/cache/report/profile roots are verified absent; final FAST removed 2,754,042,855 scratch bytes.
The prior campaign's required FAST/frontend/smoke outcomes remain in C and the linked milestone plans.
The broad window expired **October 31, 10:52:09–14:52:09 MDT**. Do not renew its marker. Selector output (verbatim):
```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Scientific constraints and prior FULL evidence

Automatic placement preserves covalent root lengths ahead of collisions. Roots in one rigid cluster without defined
relative joint/flexible motion retain strain; exempt Relax is an exact no-op with notice and no history/undo.
Do not invent flexibility, split clusters or close exempt roots. Manual moves may stretch roots; repositioned-overhang
collisions remain the user's responsibility. The NP 2 nm exemption covers only its host strand.
The five-atom Direct closure remains withdrawn. Approved 14.625° template offset, five exact locks and 925 bridge
lengths remain; lattice phases/detectors are unchanged. Approved Voltron area is 19044.137046 nm² at unchanged 5% tolerance.

Evidence **E**: `C/remaining-failures/`; **I**: `E/implemented-features/`.
`E/full-implemented-baseline.{log,json}`: SMART FULL in the prior user-opened session;
**20435 passed /5 failed /26 skipped /0 errors**, 3447.62 s, two workers. No deferred groups in that run.
Peak 6444376064 B, high events 234, max/OOM/OOM-kill zero. Its 4029987513-byte scratch is absent.
Direct absolute reference corrected after approved offset: 7.558951938676602 → **7.558586405959171 nm**, tolerance unchanged;
`I/direct-focused`: 10 passed /6.00 s. This resolves one prior FULL family. Four prior failures remain:

1. Eligible mrDNA → Use as NAMD seed: `test_mrdna_pipeline.py::TestSyntheticRoundTrip::test_zero_step_position_accuracy`.
   Mean **0.6911751375159637 nm** versus <0.10; max limit 0.25 unchanged. Reader/oracle locked pending review.
2. Eligible Assembly → Polymerize Origami / NAMD: `test_assembly_flatten.py::test_smallo_poly_namd_seed_has_no_ring_piercings`.
   Canonical 0.16-nm O3′(ext2)–P(ext1) bond **48262/48233** pierces ext2 sugar ring **48264/48263/48261/48259/48260**.
   Current 14.625° gives 1, prior 14.6° gives 0; current repeat byte-identical. No approved-offset reversion.
3. Excluded experimental Python-only corner optimizer: `test_fold_optimizer_reduces_clashes_and_beats_reference`, 13 versus ≤11 bead clashes.
   No app command/HTTP route. Do not rerun, repair, reclassify or change its threshold.
4. Excluded CPD numerical host `[cpd-free]`: means CPD family/free gesture, not CPD-free design. Now explicitly scientific-marked.
   Do not rerun or repair it. The earlier section-proof timeout passed FULL; experimental Branched controls remain excluded.

## Isolated molecular reviews — no approval received

**mrDNA:** `I/mrdna-transport-review/review.html`. 180 real-file controls: 36 phases × zero PDB/DCD,
rigid motion, local twist and prior restart. Zero displacement exact; rigid ≤8.903806e-6 nm, twist ≤2.072995e-6 nm;
restart matches direct control. Candidate transports native atoms with DNA centers/O-particle rotation, without rebuilding linkers.
Only fully paired, direct, unposed Fine sites qualify; unpaired/inserted/coarse/interpolated/posed designs remain unsupported.
Native strain remains: original zero 12 bond flags, prescribed twist 16; some phases pierce. This is fidelity, not readiness.
Approval includes demonstrated placement and native zero-step reference correction at unchanged 0.10/0.25 nm limits.
`I/transport-focused`: 3 pass /2.90 s. Older linker-rebuilding prototype moved atoms 0.073959 nm under rigid motion; do not promote.

**Terminal extension:** `experiments/terminal_extension_bridge_*`, `I/terminal-fixed-exit-review/review.html`.
Candidate only addresses existing internal own-sugar piercing: native C3′–O3′ direction, four canonical bridge lengths,
fit three remaining angles, preserve roots/sugars/bases/unrelated links/topology; infeasible solves keep current linker.
smallO: piercing removed, contacts 37→36, bond flags 241→241, five atoms move ≤0.291085 nm; all 12 roots exact.
C3 volume stays negative; O3′–P–O5′ 103.6→97.002°, P–O5′–C5′ 120.9→113.887°. These require review.
37 comparisons/156 exact root checks: no new piercings/bond flags, but 13 phases add 1–2 contacts; OP2–C4′ reaches **0.07524 nm**.
Max swept move 0.398053 nm; angle deviations reach 11.41°. This adverse contact still blocks general use.
`I/terminal-focused`: 3 pass /3.27 s. Rejected initialization prototypes stay rejected; one partial sweep ended exit143, not pass.
Neither candidate is authorized for production. Elapsed time and independent-milestone priority are not molecular approval.

## Preserved native review files and shared worktree

Four user-requested files in `workspace/Geometry Review/`: `Polymerized assembly - Current/Candidate.nadoc`
and `Tail phase 210 - Current/Candidate.nadoc`. First pair: 18 helices, 2394 nt, 49086 atoms; second: adverse 2HB control.
Use **Ball & Stick / Stick → Animations → Camera Poses**, views03/04. Both pairs have identical cameras/four-step tours.
They are captured topology roots with exact atom references, not authored candidate histories or MD results.
Phase-control helix namespaces preserve 210° on reopen. Generator: `experiments/terminal_extension_review_nadoc.py`;
evidence `I/nadoc-review/`. Atom/bond feeds verified, max component rounding 0.000006704 nm; 12 views/four tour checks passed.
Preserve `Platform - Root-preserving.nadoc` (9 attachments); its later user save is not requalified.

Entry HEAD `06ec94bd`; baseline **203 dirty entries**, recorded in `C/next-three-20261101-baseline.json`.
The task's new/previously-clean owned paths are inventoried in `C/next3-owned-paths.json`; all baseline hashes
were unchanged before documentation updates. Stage only this task's added milestone note in the mixed memory file.
Other API/VR/simulation/activity/memory-hygiene changes remain untouched and unstaged. `main.js` delta is zero.
Commit explicit owned paths locally; no push, stash, reset, restore, amend, rebase or hook bypass.
