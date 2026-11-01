# Feature-history campaign handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 0 (ordinary protein import gate ON November 1).
The user requested the next three independent milestones after the original 14:00 campaign; no new deadline was supplied.

**Tools done: 4/4. CAD: 30/34 complete; FH-27/31/32/36 remain open.**
FH-30/34/35 closed in the preceding campaign; FH-18/25/26/28, ISSUE-99 and ISSUE-126 remain closed.

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
