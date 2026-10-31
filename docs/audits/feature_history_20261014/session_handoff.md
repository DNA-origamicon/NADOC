# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 10 (last production gates: October 28).
The active goal supersedes recurring stop-loss confirmation. The October 28 deadline was missed.

**Tools done: 4/4. CAD: 26/34 complete; FH-27 and 7 parked milestones remain.**
FH-18/25/26/28, ISSUE-99 and ISSUE-126 stay closed. No gate or milestone changed.

## Scope and next task — October 31

User renewed FULL authorization, limiting repairs to fully implemented app features.
No app option, or an explicitly experimental app option, means excluded from repair.
Single next task: obtain the pending molecular review decisions, then promote only an authorized
candidate and validate its implemented feature. Neither remaining molecular failure is fixed yet.
Keep thresholds, goldens, scientific exclusions and test guards intact. Do not reopen milestones.

Automatic placement preserves covalent root lengths ahead of collisions. Roots in one rigid cluster
without defined relative joint/flexible motion retain strain; exempt Relax is an exact no-op with a
notice and no history/undo. Do not invent flexibility, split clusters or close these exempt roots.
Manual moves may stretch roots; repositioned-overhang collisions remain the user's responsibility.
The NP 2 nm exemption covers only its host strand. The five-atom Direct closure remains withdrawn.

## Completed FULL and resolved family

Entry HEAD: `38c05cab978eaa2c09d875ab245adf3dfbaabbb2`; parent `f2c6081c`, original `f966f12a`.
Evidence root **E**: `.development-artifacts/feature-history-focus/remaining-failures/`.
Current evidence **I**: `E/implemented-features/`. No production placement changed this session.

`E/full-implemented-baseline.{log,json}`: SMART **FULL (FULL suite) [test-dedicated session OPEN]**;
**20,435 passed / 5 failed / 26 skipped / 0 errors**, 20,466 cases, 3,447.62 s, two workers.
No DEFERRED groups. FULL collected before the Direct reference edit and new candidate unit tests.
Peak 6,444,376,064 B; high events 234, max/OOM/OOM-kill zero; guarded 8 GiB/6 GiB/512 MiB limits.
Its 4,029,987,513-byte scratch `/tmp/nf-7j06t7ay` is absent. Resource evidence is in I.
The old FULL window expired October 31 at 03:54:25 MDT. The renewed window is
**October 31, 10:52:09–14:52:09 MDT**; do not renew its marker or assume later broad authorization.
Focused development checks remain authorized after that window. No additional FULL has run.

Direct Connect/Relax: corrected only the absolute reference after the user-approved 14.625° offset,
7.558951938676602 → **7.558586405959171 nm**, retaining its tolerance. Unfitted Viewer/Export atom
identity, cold replay, exact exempt no-op/history, manual notice and nonexempt constraints remain.
`I/direct-focused.{log,json}`: **10 passed / 6.00 s**; its scratch is absent.
This resolves one of the five FULL failure families. Four failures remain: two eligible, two excluded.

## Exact remaining failures

1. **Eligible — mrDNA → Use as NAMD seed.**
   `tests/test_mrdna_pipeline.py::TestSyntheticRoundTrip::test_zero_step_position_accuracy`
   Mean error **0.6911751375159637 nm** vs <0.10; max limit 0.25 unchanged.
   The reader treats paired-midpoint DNA particles as an axis, ignores O-particle orientation and
   assigns identity geometrically from an intermediate restart. Its ideal oracle also differs from
   native seed coordinates. Production reader and oracle remain locked pending demonstrated approval.
2. **Eligible — Assembly → Polymerize Origami / NAMD preparation.**
   `tests/test_assembly_flatten.py::test_smallo_poly_namd_seed_has_no_ring_piercings`
   One canonical 0.16-nm O3′(ext2)–P(ext1) bond crosses its own ext2 sugar ring in a 5′ extension.
   Bond serials **48262/48233**; ring **48264/48263/48261/48259/48260**.
   Same graph: current 14.625° gives 1 piercing, prior 14.6° gives 0, current repeat gives 1 with
   byte-identical atoms. Max offset-induced displacement 0.465617 nm. No approved-offset reversion.
3. **Excluded — experimental Python-only corner optimizer.**
   `tests/test_headless_corner_build.py::test_fold_optimizer_reduces_clashes_and_beats_reference`
   13 bead clashes vs ≤11. No app command/HTTP route; opening saved corner designs does not expose
   the optimizer. No repair, reclassification, threshold change or renewed placement request.
4. **Excluded — experimental CPD numerical-history case.**
   `tests/test_part_transform_numerical_host.py::test_real_numerical_host_prepare_evaluate_apply_undo_reload_and_cold_proof[cpd-free]`
   Here `family=cpd`, `gesture=free`; it is not a CPD-free design. Apply reports failure after 47.2895 s;
   the nested reason is truncated in pytest output. Do not rerun/repair CPD. The existing selector
   strips parameter suffixes before checking CPD, so this case escaped exclusion. The shared dirty
   `tests/scientific_validation.py` is untouched; any next broad run must honor the CPD exclusion.

The earlier section-proof timeout **passed this FULL**. Its specialized fixture supports the
explicitly experimental Branched generator; no timeout/guard change or experimental repair.
`I/scope.json` records app entry points and the complete five-failure classification.

## Isolated molecular reviews and blockers

**mrDNA:** `I/mrdna-transport-review/review.html`; pending async user approval, no answer yet.
180 real-file controls: 36 phases × zero PDB/DCD, rigid motion, local twist and prior-stage restart.
Zero atom displacement is exact; rigid error ≤8.903806e-6 nm, twist ≤2.072995e-6 nm; restart equals
its direct control exactly. Scratch absent. `I/transport-focused.log`: **3 passed / 2.90 s**.
Candidate transports native atoms without rebuilding linkers, using DNA centers for global drift
and O particles for local rotation. Only fully paired, direct, unposed Fine sites qualify.
Unpaired/inserted/coarse/interpolated/posed designs remain unsupported; this is not a general decoder.
Native strain stays visible: original-phase zero has 12 bond flags, prescribed twist 16; some swept
native phases retain piercings. These are reconstruction-fidelity controls, not simulation readiness.
The approval question includes the demonstrated placement and native zero-step reference correction,
retaining 0.10/0.25 nm limits. Existing physical gates remain. Do not infer approval from elapsed time.
The older file-level prototype rebuilt linkers after float32 noise, moving atoms by 0.073959 nm
under rigid motion; `E/mrdna-seed-probe.json` records why that prototype must not be promoted.

**Terminal extension:** current isolated candidate in `experiments/terminal_extension_bridge_*`.
It acts only on an existing internal O3′–P own-sugar piercing. Hold native C3′–O3′ direction, constrain
all four bridge lengths to existing canonical values and fit the remaining three angles; preserve
all roots, sugars, bases, unrelated links and topology. Failed solves retain the current linker.
The actual smallO candidate removes the piercing, contacts 37→36, bond flags 241→241; only five
internal-link atoms move, max 0.291085 nm. All 12 roots and nonextension atoms are exact.
Its C3 oriented volume remains negative; angles O3′–P–O5′ 103.6→97.002° and P–O5′–C5′
120.9→113.887°. These explicit tradeoffs require review; no production authorization yet.
`I/terminal-fixed-exit-review/review.html`: **37 comparisons**, 156 root checks exact, no new
piercings or bond flags. Thirteen phases introduce 1–2 contacts; a shown OP2–C4′ pair is **0.07524 nm**.
Maximum swept displacement 0.398053 nm; angle deviations reach 11.41°. These negative examples
are material limits, not simulation-readiness evidence. The bounded Export/NAMD approval question
is pending; no answer received. `I/terminal-focused.log`: **3 passed / 3.27 s**, including chirality,
canonical lengths, rigid-pose consistency and infeasible-span refusal.

Rejected tail prototypes remain in I: changing every internal initialization introduces piercings
at phases 30/40/310; retrying only self-piercings still inverts C3 in smallO. That second sweep was
terminated at 12 completed comparisons (exit 143), not passed. The current candidate adds the native
C3 direction and exact-length constraints; do not promote either rejected initialization prototype.

## Earlier decisions and shared-worktree closeout

`f2c6081c` resolved all 52 Direct/root FAST failures. `38c05cab` repaired reach planning, inserted-root
identity, the documented already-strained native linker fixture, approved junction balance and
Voltron's approved area reference. The current FULL confirms those earlier failures stay resolved.
Approved 14.625° template offset, five exact locks and 925 bridge lengths remain; lattice phases and
detectors are unchanged. Approved Voltron area is 19044.137046 nm² at unchanged 5% tolerance.
Earlier app checks and evidence stay in E; no new frontend or production geometry change this session.
Preserve `workspace/Geometry Review/Platform - Root-preserving.nadoc` (9 attachments); its later user
save was not requalified. Historical four-attachment Current/Candidate captures remain historical.

Ownership: 203 pre-existing dirty entries, including 202 recorded file hashes and one untracked
`memory/details/` directory without an entry hash. All recorded file hashes match; that directory
was not edited. API/VR/simulation/activity/memory-hygiene work remains untouched and unstaged.
Local checkpoint uses eight explicit owned paths: the Direct test, this handoff, two MRDNA
candidate/review modules, two terminal candidate/review modules and their two focused test files.
No push, stash, reset, restore or history rewrite. Final lint, owned Ruff, diff and memory hygiene
checks pass (0 memory errors/warnings). No new frontend/app check: production geometry is unchanged.
