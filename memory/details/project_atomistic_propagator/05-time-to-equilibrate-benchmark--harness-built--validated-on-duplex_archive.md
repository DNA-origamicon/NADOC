# TIME-TO-EQUILIBRATE BENCHMARK — harness BUILT + validated on duplex (2026-07-20) — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## TIME-TO-EQUILIBRATE BENCHMARK — harness BUILT + validated on duplex (2026-07-20)
The definitive seeding test: does a BLADE-relaxed solute, solvated + handed to NAMD, reach
equilibrium in fewer NAMD ps than a cold idealized build? Two arms, IDENTICAL solvation+NAMD,
differ ONLY in solute start coords: (cold) ideal B-DNA vs (seed) BLADE-implicit-relaxed.
- **New reusable infra (committed to core — BLADE-seeds-NAMD is a stated goal):**
  `build_namd_solvated_package(..., solute_coords=(N,3))` overwrites the built solute PDB's x/y/z
  in psfgen atom order before water is placed (fresh water around the seeded conformation), leaving
  topology columns untouched — `namd_solvate._overwrite_solute_coords`. Threaded through
  `prepare_mgh_slow_release` → `prepare_propagator_reference` (**kwargs) → `local_run.prepare_local_
  reference(solute_coords=)`. Pins: exact all-atom order == the `export_windows` npz order, so a
  BLADE-relaxed seed indexes 1:1 against the same PSF. Tested: `tests/test_namd_solute_coords.py` (5).
- **Harness** (`scratchpad/blade_equil_benchmark.py`, dry|full): builds design →
  `build_charmm_psfgen_topology` (ideal all-atom) → BLADE relax in the gpu env (`blade_relax.py`,
  subprocess: OpenMM CHARMM+OBC2 minimize + short constrained Langevin) → solvate both arms → run
  both NAMD ladders local → slice solute DCD → `equil_metric.benchmark`. Metric (`equil_metric.py`,
  self-tested): solute Kabsch-RMSD to a COMMON equilibrium (pooled last-third of both arms); τ = last
  time still outside the plateau band. Runs in uv env, shells to gpu env for OpenMM (two-env split).
- **Duplex result (20 bp, smoke — expected ~0 savings, CONFIRMED): τ_cold = τ_seed = 0 ps.** Both
  arms at plateau from frame 0 (rmsd0 1.00/0.91, plateau 0.929/0.928 — same equilibrium). A duplex
  equilibrates instantly and its ideal build is already ~1 Å from eq → nothing to save. BLADE relax
  moved the solute 1.25 Å; injection verified (seed arm solvates with a different solute Rg 20.72 vs
  cold 20.22). **The harness is proven end-to-end; the duplex simply has no settling time to detect.**
- **CURVED 6hb WIRED + BLADE-relax STABLE (2026-07-20).** Harness now takes a `.nadoc` path (arg1)
  → `Design.model_validate_json` → same build→relax→(solvate→NAMD) path; new `relax` mode does
  build + BLADE relax + trajectory capture ONLY (no heavy solvate/NAMD — the local stability gate
  before the RunPod arms). `workspace/6hbx100_90deg.nadoc` = 6 helices, 40,087 solute atoms; the
  90° curve is a DEFORMATION (+1 cluster_transform) and `build_atomistic_model` APPLIES it, so the
  idealized all-atom build is already curved (correct cold-seed geometry). **BLADE relax verdict:
  STABLE** — finite, rmsd_moved 1.78 Å, Rg 100.37→100.49, bbox-diag 385→389 Å (curve HELD, no
  straighten/collapse), 72 s on CUDA. **Perf fix (important):** OBC2 GBSA must use
  `CutoffNonPeriodic` (18 Å) not `NoCutoff` at origami scale — NoCutoff is O(N²) and silently fell
  to the CPU platform → glacial; `blade_relax.py` now sets the cutoff + logs the platform (raises
  the CUDA error instead of silent CPU). Artifacts in `workspace/propagator_pilot/blade_view/`
  (`6hbx100_90deg_solute.psf` + `_relax.dcd` (~60 frames) + `_relaxed.pdb`) — viewable in Windows
  VMD via `\\wsl.localhost\Ubuntu\...` UNC paths (harness `emit_vmd`).
- **CURVED 6hb REFERENCE DATA PULLED (2026-07-20).** The other computer's MD capture is now local
  (rented a brief EU-RO-1 pod on network volume `77pnhye88p`, SFTP'd off, reaped — ~$0.62; script
  `scratchpad/fetch_curved6hb.py`, EU-RO-1 has NO 4090s → use `RTX 4000 Ada / L4 / RTX PRO 4500` on
  SECURE). In `workspace/propagator_pilot/blade_capture/` (gitignored):
  - `6hbx100_90deg_06_capture.dna.npz` (3.27 GB) — **2500 frames × 39,661 DNA atoms**, full
    pos+vel+force + z/mass/charge/resid/bonds/segment_starts/box_ang (the `export_windows` schema).
    This is the curved-6hb ground truth for baseline + correction training and the seed-NAMD benchmark.
  - `..._dna_chelated_mg.npz` (1.4 KB) — Mg²⁺ chelation analysis: 59 ions, `mg_atom_index`/`mg_resid`/
    `persistence`/`chelated`/`cutoff_A`=4.0 (which Mg are site-bound — curved stability is Mg-dependent).
  - ✅ **Atom-count delta RESOLVED (2026-07-20):** the 39,661 (capture) vs 40,087 (my earlier local
    build) gap is purely SCAFFOLD SEQUENCING, not topology. The other computer's source design is now
    on git at **`Examples/6hbx100_90deg.nadoc`** (105 KB) — topologically identical to `workspace/
    6hbx100_90deg.nadoc` (174 KB; 6 helices, 19 strands, same routing) but with the **scaffold left
    UNSEQUENCED** (588 staple nt only, vs the workspace copy's 588+676 = 1264 with the M13 scaffold).
    Unsequenced scaffold → default bases → different purine/pyrimidine count → −426 atoms. **VERIFIED:
    `build_charmm_psfgen_topology(Examples) = 39,661` (== capture), `(workspace) = 40,087`.** ⇒ For the
    curved benchmark USE `Examples/6hbx100_90deg.nadoc` — it is the exact capture source; the workspace
    copy's sequenced scaffold would mismatch the ground-truth atom ordering AND base identities.
- **NEXT = the FULL curved showcase (RunPod).** Solvating the curved 6hb at 1.2 nm padding around a
  ~385 Å bbox → ~1.5-3 M atoms — RunPod-bound. Run `blade_equil_benchmark.py <nadoc> full` with a
  showcase trim: production ~100-500k steps (200 ps-1 ns @ 2 fs), `production_dcd_freq` ~1000-2000
  (matches real dcdfreq), so the metric can watch the solute settle. That is where τ_cold >> τ_seed
  should appear (idealized curve vs MD-equilibrium curve). Metric discrimination already proven on
  synthetic data (cold 70 ps vs seed 39 ps); the duplex proved the pipeline; the curved-6hb relax
  proves BLADE can produce the seed. Only the RunPod NAMD arms remain.

## UNIFIED duplex+ssDNA correction + SEEDING verdict (2026-07-20)
- **ONE ForceNet handles BOTH duplex + ssDNA — no negative transfer.** Trained a single ForceNet on
  the POOLED residuals of both systems (each residual = its own captured F_true − its own CHARMM+GBSA
  baseline; system-homogeneous batches, epoch mixes both). Unified R²: **duplex 0.711 (vs 0.72 separate),
  ssDNA 0.668 (vs 0.66 separate)** — matches the specialists, slight positive transfer on ssDNA. ⇒ BLADE
  does NOT need a per-motif model zoo; one correction spans paired + single-stranded environments. Model
  `energy/forcenet_unified.pt`; driver `scratchpad/unify_train.py`. This is the general recipe: pool any
  new motif's residual into the same net.
- **SEEDING verdict: the BASELINE seeds NAMD; the NN correction does NOT help (and doesn't need to).**
  Test (`scratchpad/seed_test.py`): perturb the duplex explicit-mean by ~1 Å, OpenMM-minimize (both start
  identical), then Langevin-relax under (a) baseline-only vs (b) baseline+unified-correction; measure
  tail RMSD to the explicit-MD mean. Result over 2 seeds: baseline 1.075/0.977 Å, corrected 1.107/0.942 Å
  — **Δ = −0.03/+0.03, a wash** (both within ~2× the explicit ensemble's own 0.53 Å thermal spread; Rg
  matched to <1%). WHY: the delta-force net reproduces 71% of a correction that is only ~6% of the total
  force, and it is NON-conservative (not a gradient) → it cannot cleanly relocate an equilibrium; its 29%
  residual error injects ≈ the tiny systematic shift it could offer. ⇒ **BLADE's seeding value is the
  training-free CHARMM+GBSA baseline alone** — it lands the solute ~1 Å from the explicit basin with NO
  training data, a STRONGER result for arbitrary standard structures (no per-design training to seed NAMD).
  The learned correction's payoff is elsewhere: dynamics / invariant-measure fidelity (the 6% solvent-PMF
  that shifts *fluctuation* statistics), not the mean structure. NEXT (heavy, needs a run): the full
  BLADE-baseline→solvate→NAMD leg to time the equilibration actually saved vs a cold water ladder.

**NOTE (stability):** the custom BAOAB `langevin_rollout` has NO H-bond constraints → dt=2 fs blows up
(X–H stretch ~10 fs); use **dt ≤ 0.5 fs** for unconstrained all-atom rollouts (or add RATTLE). The NAMD
reference used HMR+RATTLE at 2 fs; our implicit rollout does not.

## ssDNA basic training + the BLADE-relaxer both VALIDATED (2026-07-20)
- **BLADE-baseline as a RELAXER (training-free) — WORKS + robust.** Perturbed 6hb (σ=0.3-0.6 Å,
  even E=5.6e13 clashes) → OpenMM minimize + short implicit Langevin → stable, folded (Rg within
  0.7%), ~1 Å RMSD to the explicit reference (the GBSA-vs-explicit gap the NN correction would
  tighten). Confirms the SEED path: BLADE relaxes rough/clashing structures fast → can seed NAMD
  (skip the water-equilibration ladder) AND accept oxDNA/SNUPI backmaps as starts. Driver
  `scratchpad/relaxer_test.py`. NEXT: full BLADE→solvate→NAMD leg to measure equilibration saved.
- **Basic ssDNA reference RAN + correction TRAINED (local, ~15 min end-to-end).** Built a lone
  ssDNA strand via `create_bundle([[0,0]], N, strand_filter="scaffold")` + `assign_scaffold_
  sequence(custom_sequence=…)` (no staples) — a sanctioned single-strand build (green regression
  test `test_namd_topology.py:63`). 24 nt → solvated 20,220 atoms (job 67fa301eade0) → propagator-
  reference capture (2 fs, capture_vel_force, 3 unrestrained MGHH chunks) → 6000 frames / 761 DNA
  atoms (`ssdna24_dna_forces.npz`). RESULTS: **baseline explains 0.949 (== duplex 0.94 — bonded-
  dominated, pairing-independent), ForceNet residual R² 0.66 (vs duplex 0.72 — modestly harder:
  the solvent residual is less predictable when the conformation is floppier), total ~98% force
  accuracy.** Model `energy/forcenet_ssdna.pt`. ⇒ REVISES the earlier caveat: ssDNA is NOT harder
  at the per-frame FORCE level (baseline fine); the real ssDNA challenge is CONFORMATIONAL SAMPLING
  (floppy ensemble — this short-production reference samples ideal-B→partially-coiled only) + the
  modestly-lower correction learnability. The build→capture→export→baseline→train loop is now the
  general recipe for ANY new motif. [DONE: unified duplex+ssDNA correction — see section above.]

## BLADE — the method has a name + the curved-origami test case (2026-07-19)
**BLADE = Box-Less Atomistic Dynamics Engine.** The A2 + delta-learning + Langevin + CUDA
propagator: `E = CHARMM+GBSA(DNA-only) baseline + learned solvent correction (ForceNet)`,
implicit solvent, NO periodic box / NO PME. Chosen because box-free is the differentiator.
**Strategic thesis (user, correct):** BLADE's biggest win is CURVED / EXTENDED origami — where
explicit MD needs a huge, mostly-empty, water-dominated periodic box (+PME, +periodic-image
padding around the curve), while BLADE's cost is DNA-atom-count only, box- and curvature-
INDEPENDENT. Speedup ≈ water:DNA ratio, which grows from ~10× (compact) to 20-100× (extended).
Plain implicit solvent (GBIS) failed before (artificial damping) — BLADE differs by LEARNING the
correction to GBSA from explicit-solvent forces = implicit COST, explicit-corrected ACCURACY.
- **Test case: `workspace/6hbx100_90deg.nadoc`** — a 6hb bent 90° via Dietz insertion/deletion
  `loop_skips` (+32 inserts / −22 deletions). **CORRECTED counts (other computer, authoritative
  from PSF):** 1244 nt / **39,661 DNA atoms**; the relaxed box's 42,125 "DNA" = 39,661 DNA +
  2,464 explicit ions (1225 Na + 118 Cl + 1121 Mg-hexahydrate). My earlier 1264/42,125 folded
  ions into DNA + over-counted nt by 20 (subagent/stale report.json). Design has NO overhangs/
  extensions (arrays empty) → no newer revision; BLADE trains against this design as-is. NOTE:
  `workspace/` is GITIGNORED → the `.nadoc` does NOT sync across machines; each uses its local copy.
  **CORRECTION (from other computer's disk, commit 0073923):** the CURRENT relaxed FULL box =
  job `6d3b1a440ace` = **770,219 atoms** (DNA 42,125 + 728,094 bulk water), at
  `/media/jojo/Archive/NADOC_archive/6d3b1a440ace/package/6hbx100_90deg_namd_solvated/`. This
  does NOT fit the local 8 GB → **RunPod IS needed** (my earlier "197,107 fits local" was WRONG:
  197,107 is a water-CARVED subset (DNA + ~1.5 nm hydration shell ≈ 51.6k waters) that is NOT on
  disk — it must be carved from the 770 k box via `water_shell_carve` for a shell reference; the
  full box goes to RunPod). The old local build `workspace/md_jobs/8553cf4fa9a0/` is a stale
  earlier revision — do not use.
- **Skip/loop handling (investigated):** INSERTIONS built INLINE axially-stacked in the duplex
  column (`geometry.nucleotide_positions` delta≥1 → n=delta+1 copies offset ±½·rise, same
  twist/radius — NOT looped-out bulges) → near-duplex local env → M3 correction likely transfers.
  DELETIONS omit the pair, bridge O3′→P (~5-8 Å) via `_minimize_backbone_bridge` (atomistic.py
  ~1617) → strained, NOVEL env → the part the correction must learn. TOPOLOGY is VALID (197k PSF
  runs in NAMD; OpenMM CharmmPsfFile should accept it). CAVEATS: residual skip-site strain +
  UNRESOLVED o3prime template angle (C3′-O3′-P 94° vs 119°) bias backbone geometry → **SEED BLADE
  + force-capture from a NAMD-RELAXED restart frame (`output/*.restart.coor`), NOT the raw PDB**
  (CHARMM EM fixes the geometry). Refs: `project_atomistic_skip_backbone`, `skip_site_gromacs_fix`
  (GROMACS LINCS blow-ups FIXED via constraints=h-bonds+annealing), `o3prime_investigation`.
  ⇒ GNN-on-skips answer: representationally fine; inline-inserts near-duplex; deletion/strain
  sites novel → TRAIN the correction on the curved reference's own forces (learns skip solvation
  locally, transfers to future curves).
- **Two-computer + RunPod plan (2026-07-19):** relaxed curved 6hb is on the other computer.
  Transfer = **RunPod persistent volume as the hub** (production runs there anyway). Send the
  MINIMAL restart bundle (psf+hmr-psf + latest restart.coor/vel/xsc + forcefield/ + prod .conf +
  ENM files ≈ 50-100 MB) via `runpodctl send`→`receive` (machine→pod P2P; NOT git — workspace
  isn't versioned, GitHub 100 MB limit). sha256 both ends; verify atom count 197107/1264 nt vs
  current design (build was 1 day older than .nadoc). **REQUIREMENT: the RunPod production must
  CAPTURE FORCES** — run the propagator-reference protocol (2 fs, capture_vel_force) for ≥1
  segment seeded from the relaxed restart, else no BLADE training data. Return only the compact
  DNA-force npz (`windows.export_windows dna_only`) → Archive drive (`/media/jojo/Archive`), not
  raw DCDs. This box does BLADE dev/rollout locally (needs only psf + a relaxed .coor for the GBSA
  baseline). Follow RUNPOD_RUNBOOK (preflight, babysitter kills on failure, judge $/ns AND ns/day).
