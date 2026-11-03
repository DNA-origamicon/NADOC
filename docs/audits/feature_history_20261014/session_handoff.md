# Feature-history campaign handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 2 (part navigation and broad regression repair; no gate flip).
Latest user follow-up (November 2): track the polymerization-to-extension conversion change as follow-on work; correct Full's S37 attachment to `Extension - 0[-5›1]`; defer general long-extension geometry until after the feature-log/dependency overhaul.
Latest priority decision (November 2): part scrub/Revert is complete; qualify early Extrude edits through downstream Autoscaffold and Autostaple. The three remaining broad-suite failures are explicitly deferred and non-blocking for rollout. Assembly parity and transaction repairs remain subsequent work.

**Tools done: 4/4. CAD: 33/34 complete; FH-31/32/36 close; FH-27 remains open.**
No molecular candidate was approved. No new host, queue, storage format or scientific algorithm was added.
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

## November 2 — broad regression repair

User authorized the broad run: **20,618 passed /37 failed /26 skipped**, 4,257.87 s.
FULL previously omitted numerical thread pinning: all scopes now default to one BLAS/OpenMP thread; native fingerprints and resource gates are unchanged.
The benchmark fixture inherited a 6 nm solvent reservoir (1.09M atoms). Explicit test-only 1.5 nm padding retains real solvation and every simulation stage; **47 benchmark tests pass**, native run 91.59 s.
The generator history check now uses native commands and the ordinary evaluation job/commit, preserved loadout and unrelated DNA, scrub/edit/refusal/Revert/undo/redo and poisoned-recovery proof.
Recovery-poisoning supports input-only transform rows. The joined-path file passes unchanged after an intermittent 25 ms capture refusal; no capture budget was raised.
Final SMART **FULL: 20,655 passed /3 failed /26 skipped**, 1,961.16 s (32m41s versus 70m57s before repair): **34 original failures resolved, zero new failures**. No deferred selection; failed FULL does not clear regression debt.
Zero unmarked tests exceed five seconds; summed test time 7,381.5 s versus 16,774.5 s. Guard tests:19 passes; lint passes; memory lint has zero errors and one existing unrelated warning. Desktop completion notification submitted successfully.
Evidence: `C/broad-regression-20261102/`. Remaining unchanged failures: mrDNA zero-step mean0.691175 nm versus <0.10; assembly ring piercing (ISSUE-163/164 follow-on); excluded corner optimizer13 versus ≤11 clashes. No molecular candidate/oracle change, reclassification or production geometry change.
Cleanup verified: no active scratch readers; removed 4,029,968,236 bytes from the three owned final pytest roots. Original broad and cancelled oversized-benchmark roots were already absent. Compact logs/timings and cleanup manifest remain under C; `main.js` LOC delta:0.

## November 2 — recipe-backed part scrub/Revert

Part navigation now reconstructs unavailable/corrupt recovery from recorded prefix inputs; native Revert always rebuilds its retained prefix.
F0, Fine Routing child boundaries, retained identities, source revision checks and one undo/redo are covered; unsupported commands refuse atomically.
The UI offers native Revert despite eviction. Retired named-group admission remains unchanged; no assembly-specific implementation was changed.
Final SMART **FAST: 19,982 passed /19 skipped** (401.41 s pytest); full regression remains deferred by the selector message below.
Timing triage: zero individual violators, maximum3.91 s, summed1,483.6 s; no budget/classification change or new shared delay.
Full frontend: **803 files,9,562 passed /one skipped** (367.22 s). Lint passes; memory lint has zero errors and one unrelated existing length warning.
Final isolated app: rail to empty F0 and back, evicted-row Revert, undo/redo, save/reopen, independent native proof and rendered pixels pass (5.8 s test).
Isolated smoke: **23 passed** (2.5 min); all four browser/smoke scratch roots independently verified absent. Evidence: `.development-artifacts/feature-history-focus/recipe-navigation-20261102/`.
Initial FAST failures were obsolete snapshot-refusal expectations/retired-group admission plus one verification timeout; all resolved in focused and final FAST runs.
Next priority remains completion of part-related FH-27 acceptance before assembly parity/transaction work. `main.js` LOC delta:0.

## November 2 scope correction

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

Use the base Properties-card designations when discussing geometry. In retained
01 Terminal linker, S37's internal piercing is `Extension - 0[-5›3]` O3′ to
`Extension - 0[-5›2]` P, through the former's sugar. The separately reported Full
attachment must join S37 position 1 to `Extension - 0[-5›1]`, not ›16 (ISSUE-162).
The renderer ordering repair is qualified: 58 focused frontend checks, an isolated
app check of all 12 extension roots and S37's Properties labels, plus the full
frontend suite (800 files, 9,527 passed / 1 skipped; 384.68 s). No atom coordinates changed.
Evidence: `.development-artifacts/extension-connectivity-20261102/`.

Agent publication additionally rejects private diagnostic and assembly commands
in part logs even when they independently replay. Focused guard coverage: 18 passed.
All six old process-review files contain private diagnostic stages; retain them
as evidence rather than newly accepted part deliverables. This restriction does
not edit their saved bytes or alter production molecular placement.

Polymerization strands must not be converted to ordinary extensions (ISSUE-163).
The existing materializer's terminal-tail policy is rejected; simulation handling
requires its own explicit development. The user chose **“Track the conversion
change as follow-on work”**, rather than adding an immediate unsupported-case
refusal. Production simulation preparation is unchanged; ISSUE-163 is deferred.
Do not substitute another topology.

**General long-extension molecular geometry is separate follow-on ISSUE-164,
deferred until after the feature-log/dependency overhaul.** Prior FH-27 ring-piercing
evidence is retained as that issue's evidence, not a requirement to promote the
isolated linker candidate during the overhaul. This does not mark a failing test
passed, relax an oracle, approve any candidate or automatically close FH-27.
See [the binding scope decision](../../../memory/feedback_polymerization_extension_scope.md).

## Enabled asset work — November 1, 2026

**FH-31:** ordinary Attach, bound Move/Rotate and Relax now use the existing private worker and one guarded publication.
Native history forms preserve exact references, output identities and numerical pins. Application v2 supports exact
removal/replacement after fitting, relaxation and multiple anchors. [Contract](nanoparticle_connection_contract.md#fh-31-ordinary-integration--november-1-2026).
**FH-32:** ordinary coating and biotin create/remove plus historical edits use pinned original inputs. Invalid upstream
site-count edits name the failing biotin row, refuse publication and leave history unchanged; valid edits rebuild it.
Save coordination preserves the original path across in-flight/queued autosave, private edits and reopen (ISSUE-159).
The unchanged 100 ms coating capture profile admits only the saved empty default animation and one editable main loadout;
combined retained data stays within 8 MB. [Contract](coating_input_plan.md#fh-32-ordinary-integration--november-1-2026).
**FH-36:** recipe-rooted Generate Design records additive native grafts and explicit fitting intent through final connections.
Source and complete candidate independently reproduce. Regeneration tears down exact prior anchors and retains unrelated DNA.
Admitted maximum: four source-free uncoated particles, twelve grafts/active anchors, 128 handles/retained versions,
50,000 bases subject to existing capture/recovery limits. Explicit numerical repair preserves generated v2.
Imported molecular geometry, unrelated duplex ownership, flexible/CPD/protein/individual-pose scopes and scientific
mechanics remain excluded. [Contract](remaining_native_contracts.md#fh-36-generated-asset-integration--november-1-2026).

## Qualification and measured limits

`remaining-assets-lifecycle-correctness-20261101`: 110 focused passes; `generated-repair-v2-green-20261101`: eight.
`generated-assets-boundaries-corrected-20261101` plus `generated-assets-regeneration-20261101`: seven generated cases,
including platform/curved construction, four particles/twelve anchors, upstream edits, cold proof and repeated generation.
`generated-capture-final-correctness-v2-20261101`: 145 passes; final complete-model copying adds two checks (18 in that file).
ISSUE-160 fixes capture allocation, recursive memo retention and repeated header-default introspection; exact aliases,
unknown fields, history/display undo data and original accounting remain. No deadline/node/byte limit or GC policy changed.
`remaining-assets-boundaries-release-20261101`: 239/240 captures, 240/240 publications, eight real worker commits and
cold proofs; actual cancellation/stale cases reap and preserve source. Fitted capture/publication lock p95 ≤1.89/0.81 ms;
biotin ≤36.19/21.97 ms. Its one safe timeout makes the script's zero-refusal criterion exit1; not an all-green benchmark.
`generated-largest-final-20261101`: 29/30 captures, 30/30 publications; capture lock p95/max 24.522/25.135 ms,
publication lock 18.177/20.241 ms. Actual maximum generation completed in 152.639 s; a real edit took 49.834 s,
with one undo and correct source guards. Cancellation/stale commit returns409 and releases the worker admission.
These are cooperative bounded-work observations, not hard real-time guarantees. Both safe refusals and earlier failures remain.
`remaining-assets-browser-release-20261101`: fitting and generated app flows pass; biotin hit a 5 s test wait after commit.
`remaining-assets-browser-biotin-release-20261101`: corrected worker wait passes (58.3 s flow, 4.166 s creation-to-adoption).
Together they cover actual Move/Rotate preview cancellation/Apply, ordinary dialogs, historical/downstream edits with visible
failure feedback, undo/redo, save/reopen and independent cold proof; zero tool console errors. Fit/biotin screenshots inspected.
Owned workspace/profile/cache/report/process roots were verified absent; retained review PNGs live only in C.
Required frontend rerun: **799 files, 9,518 passed /1 skipped**, 367.49 s. Initial failure was an obsolete missing-revision
fixture; the guarded attachment rejection test now supplies a real revision. `just lint` and `git diff --check` pass.
`remaining-assets-routes-release-20261101`: seven passes /64.25 s; isolated `just smoke`: 23 passes /2.6 min.
Smoke workspace, project stores, profiles, caches, credentials and owned processes were removed and absence verified.
First required SMART FAST: 19,928 passed /2 failed /19 skipped, 438.76 s pytest /468 s wrapper. Failures were stale
application-version and repair-capability assertions. Updated contract files pass 39 tests, including actual v1/v2 rename.
Slow-test skill review: zero per-test violators (max 3.66 s); 1,625.2 s summed test time, versus prior 1,702.3 s.
Existing replay/worker/runner families dominate; no new shared accidental delay identified. No budget or classification change.
`remaining-assets-smart-final-20261101`: required **FAST 19,931 passed /19 skipped**, 438.73 s pytest /470 s wrapper.
No per-test violations (max4.27 s; summed1,617.6 s); aggregate warning reviewed under the slow-test skill. No broad sweep ran.
Selector output (verbatim):
```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Remaining release exit

FH-27 remains the final aggregate acceptance milestone. The November 2 repaired FULL run resolves all 34 newly found failures; the three pre-existing failures above remain. Never renew its session marker automatically.
The full suite is not green. No remaining part-history regression was reported in this run. The user explicitly deferred all three remaining failures on November 2 as non-blocking for feature-log rollout; do not reopen them as release blockers. Current priority is early Extrude edits rebuilding downstream Autoscaffold and Autostaple. Assembly parity follows part completion. Terminal-extension geometry and polymerization conversion remain separate follow-on work under ISSUE-163/164, not candidate-promotion requirements for this task.
Legacy-file migration, PartGroup motion, sealed rollout, strict-agent/provenance milestones, experimental CPD and
Python-only corner optimization stay outside this release queue. No simulation or molecular promotion is authorized.

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

November 1 FH-27 process correction: the original six snapshot-only walkthrough parts were
**noncompliant**. Atom/camera checks did not establish construction history. The binding rule is now
in root `AGENTS.md`, `CLAUDE.md` and `memory/feedback_structure_requires_process.md`: structure
without process is disallowed for every agent, including diagnostic candidates and flattened assemblies.
The old capture writer refuses publication. `scripts.agent_structure_guard.publish` verifies the
serialized/reopened state by executing all inputs from an empty root; recovery snapshots are not proof.
It checks authoring plus atom references and refuses unlogged changes or changed diagnostic implementations.
This is a mandatory agent publication boundary, not an operating-system write restriction.

The six reconstructed files are in **`workspace/Geometry Review/Process Complete/`**:
`FH-27 - 01 Terminal linker - Current/Candidate` (11/12 steps, 49,086 atoms),
`FH-27 - 02 Adverse contact - Current/Candidate` (15/16 steps, 4,136 atoms), and
`FH-27 - 03 mrDNA zero-step - Current/Candidate` (11/11 steps, 2,800 atoms).
Terminal process: six original native source commands → Add Part → Polymerize Origami (three repeats)
→ Prepare NAMD materialization → current molecular placement → optional isolated candidate → Rename.
**Subsequent user correction: the terminal pair is not an accepted part deliverable.**
Its replay is complete, but F7/F8 perform assembly operations inside a diagnostic part
history and F9 replaces the part with a flattened three-repeat assembly. `Prepare NAMD`
is the diagnostic display label for `assembly-flatten`, not a legitimate part-level
polymerization feature. The flattener retains unmatched terminal staples' missing halves
as extensions; source-part periodic seam strands should remain source-part instructions.
The proper ownership is source construction/seam routing in `.nadoc`, repeated instances
and joins in `.nass`, and materialization in derived assembly simulation/export evidence.
Existing terminal files remain diagnostic evidence; neither their replay/app checks nor
the original replay-only publication guard establish this ownership contract. The
November 2 guard now refuses private diagnostic/assembly publication. No file
migration or molecular change was made by this clarification.
The 2HB is explicitly reconstructed from two helix and five strand inputs, then derived connectivity;
this does not invent its missing original actions. Four extension commands and the +210° diagnostic
phase step precede the adverse atoms. The zero-step control records resolved zero-degree frames and
actual Fine PSF/PDB production reconstruction or candidate transport; no dynamics run.
Every resulting atom coordinate and bond is checked against retained original review evidence.

Existing top-level Candidate filenames had divergent payloads at inspection: Terminal Candidate held
Current atoms; Adverse Candidate held the terminal assembly. They are preserved. The top-level Terminal
Current was repaired in place with identical coordinates before this mismatch was discovered; use the
separate Process Complete set for the matching atom comparisons, subject to the terminal ownership
defect above. No cause of the filename/payload divergence
is asserted. New parts have distinct identities.

Feature logs retain input parameters and recovery states. Ordinary production editing does not execute
the isolated diagnostic stages; their process can be independently replayed with the agent guard.
History recovery restores each diagnostic atom reference and its source placement owners. Atom-reference
changes require a complete render refresh, preventing the final candidate from leaking into earlier steps.
Use **Feature Log**, or **Animations → Construction process - recorded feature steps**.
Use Stick/Ball & Stick for atom inspection. Camera poses01–04 retain the original views;
new matched poses05/06 inspect the 5′/3′ roots on both terminal and adverse pairs.

**New root diagnosis:** all16 root bonds join the expected strand endpoint, host nucleotide and
chemical atom pair. All8 5′ roots have C3′–C5′ gaps **0.689715–0.708733 nm**, exceeding the
four canonical bridge lengths' total **0.606 nm**. O3′–P is **0.20326–0.20792 nm** instead of
0.160 nm, with strain spread through the other bonds. All8 5′ roots and2 of8 3′ roots reverse the
native C3′ oriented-volume sign (C2′,C4′,O3′ about C3′). The native tail and host templates have
negative signs. Terminal chainAR and adverse chainA are the affected3′ examples. Thus correct endpoint
identity and even canonical bridge lengths do not prove a valid attachment pose. All16 roots are exactly
unchanged by the existing candidate, which targets internal self-piercing tail links only.
The radial Bézier/template placement in `atomistic._build_extension_atoms` and the unconstrained
C3′ exit in `_minimize_backbone_bridge` are the inspection targets. Root placement needs a separate
isolated proposal preserving stereochemistry and reachable anchors; no production molecular change,
phase/oracle change or approval has occurred. FH-27 remains open.

Process/replay, root measurements and app evidence: `.development-artifacts/fh27-process-repair-20261101/`.
All six exact atom/bond feeds,88 history positions,26 saved-camera checks and6 camera-tour playback checks
pass in isolated app copies, with zero browser errors. Adverse F14→F16 changes OP2(3243) in the live
atom renderer to the correct candidate coordinate. Source-owner and physical-reference recovery regressions
are ISSUE-161. Three owned browser scratch roots and32 disposable PNGs are removed; existing user servers
remain running. Required SMART: **FAST19,946 passed /19 skipped**,441.45 s pytest/477 s wrapper.
Aggregate runtime warning reviewed via `.claude/skills/triage-slow-tests/SKILL.md`: zero per-test
violators, maximum4.17 s, summed1,636.0 s vs prior1,617.6 s. No new shared accidental delay found;
no test classification or budget changed. Focused15pass; code lint and memory lint pass.
The same FULL deferral quoted above remains; no broad session was opened.
Earlier walkthrough evidence remains in `.development-artifacts/fh27-native-review-20261101/` and
is historical, not current process acceptance. Required frontend: **799 files,9,519 passed /1 skipped**,
376.83 s. All six delivered file hashes still match publication; final `git diff --check` passes.
`frontend/src/main.js` delta0. No commit, simulation, broad-suite gate bypass or molecular promotion.

Entry HEAD `a79ee35655b15a738e047aa807ad41b91724c1db`; baseline hashes/status are in
`C/remaining-rollout-baseline-20261101.json`. Preserve unrelated shared changes, including API/VR/simulation/activity
and memory hygiene. Task hunks in the mixed client/issues/memory files must not absorb other sessions' edits.
`frontend/src/main.js` delta is zero. No staging, commit, push, stash, reset, restore, rebase or hook bypass was performed.
Final ownership/cleanup inventory: `C/remaining-rollout-final-20261101.json`; unrelated baseline files remain unchanged.
