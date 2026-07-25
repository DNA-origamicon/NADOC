# exp44 — VoltronCore local NAMD production (no RunPod, 12 GB VRAM)

**Started:** 2026-07-21 · **Owner:** autonomous session · **Status:** ACTIVE

## Mission

Get `workspace/VoltronCore.nadoc` (14,774 nt, 59 helices, square lattice) into a **local
NAMD production run** on this machine, or prove it impossible after exhausting every option.

- **Hardware wall:** RTX 3080 Ti, **12 GB VRAM** (~11.4 GB free), 32 cores, 30 GB RAM
  (~12 GB free), system disk 88% full. **All heavy data + runs live on `/media/jojo/Archive`**
  (5.8 TB free). Never write sim data to the system disk.
- **Constraints:** no RunPod. GPU-resident / GPU-accelerated wherever possible. Coarse-grain
  engines are seed-only, **never** a production answer. Implicit water (or any water+ion-aware
  scheme) is acceptable if defensible. Don't develop BLADE further unless exceedingly promising.
- **Reference point:** full explicit box = **11.3M atoms** (needs 80 GB; ran only on rented
  H100/H200 — see `memory/project_voltroncore_fullbox_bench.md`). That path is closed locally.

## Known assets (already on disk)

- `Archive/.../md_jobs/4108540fbead/package/VoltronCore_namd_solvated/` — a **1.31M-atom
  explicit periodic box** (494×149×779 Å, PME, `top_all36_na.rtf`) with a ready ENM restraint
  ladder (Aksimentiev protocol, k=0.5→0.1→0.01, 2.43M base restraints/file) + min/NPT confs.
  This is a much smaller box than the 11.3M full box — candidate for local explicit runs.
- Solute ≈ **~470k atoms** (14,774 nt DNA); base-ENM anchor atoms = 110,718.
- `namd3` (NAMD 3.0.2 multicore-CUDA) at `~/Applications/NAMD_3.0.2/namd3` — confirmed to
  contain **GBIS CUDA kernels** (GPU-accelerated implicit solvent). Also a Dec-2025 git build.
- oxDNA CG seed for VoltronCore exists (`5ce768ef2acf/1_production/last_conf.dat`).

## Two-axis metric for every run

Report BOTH: **ns/day** (throughput) and **fidelity** (structure held: RMSD/RMSF vs seed,
radius of gyration, helix integrity, no melting). A fast run that melts the origami is a failure.
Never trust a single lucky seed — replicate before concluding.

---

## Thrust A — Explicit tight-box, GPU-resident fit test

**Hypothesis:** the existing 1.31M-atom box fits in 12 GB under NAMD GPU-resident
(`CUDASOAintegrate on`), giving a fully-rigorous *explicit-water* local production path — the
cleanest possible outcome (no implicit-solvent argument needed).

- **Research:** NAMD 3 GPU-resident VRAM ≈ several GB/M atoms + PME grid (~330×100×520 here).
  1.31M is plausibly in reach; only empiricism decides.
- **Testing:** load structure, `CUDASOAintegrate on`, PME, minimize + short dynamics with ENM
  restraints; watch `nvidia-smi` VRAM; capture ms/step via `outputTiming` in EQUILIBRIUM
  dynamics (not minimize — minimize ms/step is ~2.7× off, per fullbox bench trap #2).
- **Observations (2026-07-21):** 1.31M box **fits easily** — offload minimize peaked **4.1 GB**,
  GPU-resident peaked **4.65 GB total** (~3.8 GB NAMD) → **~2.9 GB/M atoms**, so ~3M atoms fit
  12 GB (big headroom). Timings: **offload dynamics ~68 ms/step** (stable), **GPU-resident
  ~26 ms/step** (~2.7× faster). Minimize (offload) ran clean; gentle offload dynamics (50 K,
  0.5 fs) ran clean.
- **THE RESIDENT BUG + FIX:** NAMD **3.0.2 release** binary GPU-resident **crashes at the first
  force eval** — `CUDA error ... buildTileLists ... illegal memory access` (`CudaTileListKernel.cu:1141`),
  independent of margin/temp/timestep/ENM/PE-count. The **Dec-2025 git build**
  (`~/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3`) runs GPU-resident
  **clean** on the identical conf. → **Use the git build for all resident runs.** (3.0.2 is fine
  for CPU-offload.)
- **Results:** projected throughput on this 3080 Ti — **resident ~6.6 ns/day @2fs, ~13 ns/day
  @4fs**; offload ~2.5 / ~5. VRAM never a constraint.
- **Conclusions:** **Route A is the production path.** Explicit water (rigorous, no
  implicit-solvent argument needed), GPU-resident, fits 12 GB with room to spare. Implicit
  solvent (Thrust B) is now a *fallback/curiosity*, not needed. Ambitious "bigger box" is
  feasible (headroom to ~3M atoms) if better solvation is wanted later.

## Thrust B — Implicit solvent (GBIS), GPU-accelerated

**Hypothesis:** with no explicit water, ~470k solute atoms run comfortably in 12 GB; GBIS +
`ionConcentration` (Debye screening) + retained explicit Mg²⁺ accounts for water and ions
defensibly; GPU GBIS kernels give usable ns/day.

- **Research (DONE 2026-07-21):** definitive from NAMD source (`SimParameters.C:5143`):
  **GBIS is HARD-INCOMPATIBLE with GPU-resident** (`GPUresident`/`CUDASOAintegrate`) — NAMD
  `NAMD_die`s at startup. GBIS is also **incompatible with PME** (`SimParameters.C:3676`) —
  must drop PME, lengthen cutoff to 16–18 Å. BUT GBIS nonbonded + Born-radius phases **do run
  GPU-accelerated** via `CudaComputeGBISKernel.cu` (all 3 phases on device) — only the Langevin
  **integrator stays on CPU** (classic CUDA-offload). Net: Route B is GPU-accelerated but not
  GPU-resident → slower per-step than an explicit resident run of equal atom count; the win is
  ~470k atoms vs 1.31M and no water/PME. Recommended GBIS params: `GBIS on`,
  `solventDielectric 78.5`, `ionConcentration 0.3`, `alphaCutoff 14`, `switchdist 15`,
  `cutoff 16`, `pairlistdist 18`, `sasa on`, `surfaceTension 0.006`, `timestep 1`,
  `nonbondedFreq 2`, `fullElectFrequency 4`. GB-OBC-II defaults (Delta/Beta/Gamma 1.0/0.8/4.85).
  Fidelity caveat: GB under-screens a dense charged origami bundle → swelling; retaining
  explicit Mg²⁺ near DNA mitigates. **Consequence: Route A (explicit, GPU-resident) is preferred
  if 1.31M atoms fit 12 GB — it beats B on BOTH throughput and fidelity.**
- **Testing:** build solute-only PSF/PDB (strip water/box from the 1.31M package, keep DNA +
  Mg²⁺), GBIS conf, minimize + dynamics; VRAM, ms/step, fidelity vs Thrust A / seed.
- **Observations / Results / Conclusions:** _(fill)_

## Thrust C — Seed screen (fastest route to a production-ready start)

**Hypothesis:** a cheap CG/relaxed seed (oxDNA already exists; mrDNA; or the ENM-relaxed
explicit frame) removes the fresh-box clash that forces slow 1-fs soft-starts, letting
production begin sooner. Seeds only — production stays all-atom NAMD.

- **Screen:** oxDNA seed (have it) vs mrDNA vs geometric build vs ENM-relaxed explicit frame,
  judged by how quickly each yields a stable ≥2-fs all-atom NAMD start.
- **Observations / Results / Conclusions:** _(fill)_

## UX POLISH PLAN — "Relax" flow + decision gates (2026-07-23)

Visual spec (flowchart + exact popup copy): artifact
`https://claude.ai/code/artifact/84a4bfc4-f946-4b97-9b27-cd55de65a037`.

**Principle:** minimum configuration — the common case (fits + healthy GPU, now that the resident
build is pinned) asks NOTHING: press Relax → size → build → full-speed run → fidelity report.
Decisions appear ONLY at a real memory limit or speed trade-off. Full-speed GPU (resident) is the
DEFAULT/required mode; degradation is never silent — it asks, showing what was checked.

**Decision gates (trigger → where it fires → user action):**
| Gate | Trigger | Fires in | User sees |
|---|---|---|---|
| A1 (auto) | full box slightly too big, safe thinner shell fits | `md_vram.auto_water_shell` | non-blocking notice ("using 15 Å jacket") |
| A2 (decision) | only a *tight* shell fits (accuracy trade-off) | `md_vram.recommend_downsize` | modal: Use tight padding / Cancel |
| A3 (hard stop) | tightest box still > VRAM | `md_vram` | modal: Reduce design / Cancel (no local path) |
| B (decision) | GPU-resident probe fails after NADOC's fixes | after `gpu_resident_probe` in `run_job` — replaces silent `downgrade_gpu_resident_confs` | modal w/ check-trail: Run slower GPU mode (~3×) / Cancel; escalates to CPU offer |
| C (hard stop) | free disk < 5 GB, any stage | `disk_guard` (`ABORT_MIN_FREE_BYTES`) | modal: free space + Resume |

**Messaging rules (copy layer):** never expose internal names (`buildTileLists`, `pinned-host`,
`GPUresident`); every slowdown states the time cost; every stop states the fix + one action; size
limits caught in pre-flight, never after an hour of building.

**Settings (once, remembered):** "Prefer fastest GPU mode" (default on) · remember choices per
design (don't re-ask on resume) · unattended-run behavior (auto-accept slower | stop & notify;
default stop & notify — the headless answer to the require-resident default).

**Build order + status:**
- ✅ **(1) DONE** — failure classifier: `md_vram.FailureUX` + `describe_failure()` maps each
  `FAILURE_*` to {severity, jargon-free message, retry_other_binary, degrade_target}. `gpu_error`
  is the only retry_other_binary kind. Tests in `test_md_vram.py` (37 pass).
- ✅ **(2) DONE (backend)** — Gate B pause-and-ask: `namd_runner.handle_resident_probe_failure`
  replaces the silent `downgrade_gpu_resident_confs` — default policy "ask" (`NADOC_GPU_FALLBACK=
  auto_offload` restores silent). On probe fail it stashes `MdJob.decision` (the modal payload from
  `build_gpu_fallback_decision`), sets status=paused (not auto-resumed), and exits. `resolve_gpu_
  decision` + `POST /md/jobs/{id}/gpu-decision` apply "offload" (downgrade→resume, skips probe) or
  "cancel" (clean stop). Tests in `test_md_gpu_decision.py` (10 pass). **Dormant in practice — the
  pinned git build makes the probe pass.** Frontend to resolve it = Phase 3.
- 🔨 **(3) Phase 3 BUILT (awaiting in-app user validation) — modal + deadend fixes.**
  - **Modal:** `frontend/src/ui/md_gate_b.js` (pure `gateBMessage`/`hasPendingGpuDecision` + DOM
    `openGpuDecisionModal`, mirrors `md_vram_fix.js`); `resolveMdGpuDecision` in client.js;
    `_maybeOpenGpuDecision` auto-opens/closes from `_applyJobState` (dismiss-tracked vs 3 s re-pop).
  - **Deadend fixes (reuse existing affordances, per user):** the ⚠ stale marker now also flags a
    decision-paused job (per-job `staleTitle` — made function-capable in `jobs_panel_model.js`;
    `decision` added to `mdJobRowSig` so ⚠ re-renders); `mdSelectedJobControl` offers **↻ Resume**
    for a decision-paused job; `_resumeSelected` reassesses-if-stale via the shared `ensureJobCurrent`
    guard and clears the dismiss so the gate re-appears. So the modal is no longer the sole surface —
    ⚠ (list) + Resume (detail) make it discoverable and re-findable. **No backend change** (reuses the
    stale-signal machinery). Reassess semantics: nothing changed → same gate; design changed → the
    stale-guard prompts rollback/rebuild.
  - Dev hook `__NADOC_DBG__.mdForceGpuDecision()` forces the whole surface (⚠ + Resume + modal).
  - Vitest: `md_gate_b.test.js` (14) + 5 new panel/model tests; `just test-frontend` **3125 pass**.
- ✅ **(4) Phase 4 — Gate A size gate.** **4a backend:** `md_vram.classify_vram_fit` (A1/A2/A3
  tier — the one new bit) + `preflight_vram_advice` (dry design → advice+tier, `{skipped}` on
  unknown) + `POST /md/jobs/preflight-vram` (clone of estimate-disk). Tests: 5 in `test_md_vram.py`;
  `just test-smart` 5349 pass. **4b frontend (awaiting in-app validation):** `md_gate_a.js`
  (pure `gateAMessage` + promise `openGateAModal`); `preflightMdVram` client call; `_launchRelax`
  calls it before POST — A1 auto-fits the shell + info toast, A2 opens a "use tight padding" modal,
  A3 a hard-stop modal (both gate the launch). Dev hook `__NADOC_DBG__.mdForceGateA('a1'|'a2'|'a3')`.
  Vitest `md_gate_a.test.js` (9); `just test-frontend` **3134 pass**. **Limitation:** pre-flight
  skips seeded jobs (design resolved at prep) — they keep the silent auto-carve; direct designs gate.
- ✅ **(5) Phase 5 — settings + remember-choice.** The GPU-fallback policy is now a real per-run
  setting: `CreateJobRequest.gpu_fallback_policy` → `prep_params` (via model_dump) →
  `handle_resident_probe_failure` reads it (per-job overrides the `NADOC_GPU_FALLBACK` env). UI:
  a **"Prefer fastest GPU mode (ask before running slower)"** checkbox in the Advanced drawer
  (`index.html`), remembered in localStorage (`_GPU_ASK_KEY`), sent in the launch payload via the
  pure `gpuFallbackFromToggle`. One toggle spans the axis: ON = ask (require resident; unattended
  → pause & notify), OFF = auto-accept the slower GPU mode. "Remember per design" = the localStorage
  default + the per-package probe cache (Gate B) + the persisted `job.decision`. Tests: 2 backend
  (per-job policy beats env, both directions) + 1 frontend; `test-smart` 5351, `test-frontend` 3135.

**SEEDED-PATH ACCELERATION FIX (2026-07-24).** A user oxDNA-seeded job ran ~19× slow (0.127 s/step,
1.47 days/ns): NADOC solvated the full box (830×168×826, ~11.3M), `auto_water_shell` silently carved
to an 18 Å shell (3.14M), and `md_protocols` blanket-disabled GPU-resident on ANY carve → offload 1fs.
Root cause: box sized from raw min–max including oxDNA-splayed ssDNA tails (~150 Å out). Hard limit:
VoltronCore can't be resident on 12 GB regardless (>3.16M atoms even tightest). **Fix (c), ssDNA
untouched per user:** the resident gate is now FILL-BASED, not blanket — `md_protocols._segment_conf`
`gpu_resident = fast and (not carved or fill_fraction >= 0.90)`; `md_vram.carve_fill_fraction`
computes cell fill; `prepare_mgh_slow_release` threads it (carved + can't-compute → old offload
default; probe is the runtime backstop). So a WELL-FILLED carve (tight box) now attempts resident
(recovering it for that class + bigger cards); a sparse big-box carve (VoltronCore's) correctly stays
offload. Tests: 3 (carve_fill tight-vs-big, gate wellfilled→resident / sparse→offload); test-smart
5354, same 4 pre-existing. The deeper box-tightening fix (a) is OFF (would manipulate ssDNA).

**UX POLISH: ALL 5 PHASES BUILT** (awaiting in-app validation of Phases 3–5 + a pre-commit `just
smoke`). Net for gap C: with the git build pinned the whole cascade is dormant, but if it ever
fires the user now gets an honest classified message, a Gate B decision (ask by default) that's
discoverable (⚠) and re-findable (Resume), pre-flight Gate A size decisions, and a remembered policy
toggle — no silent degradation, no dead-ends.

## GAP C RESOLVED — NAMD build decision + implementation (2026-07-23)

**Gap C** (from the pipeline-gap review): NADOC detects the GPU-resident tile-list crash but
*degrades* (→ offload, or → CPU) instead of using a build that fixes it. User direction: find the
single fastest build that works for all configs on THIS machine and standardize on it.

**Build comparison** (VoltronCore 1.31M, this RTX 3080 Ti; `runs/buildcmp/`):

| config | NAMD 3.0.2 release | **NAMD git Dec-2025** |
|---|---|---|
| minimize | ✅ | ✅ |
| GPU-offload 2fs | ⚠️ crashes on the equilibrated structure (`buildTileLists`+`cudaHostAlloc`) | ✅ **66.6 ms/step** |
| GPU-resident 2fs | ❌ always crashes (`buildTileLists`) | ✅ **25.7 ms/step** (2.6× faster) |

**Decision: standardize on the Dec-2025 git build.** It STRICTLY dominates 3.0.2 here — equal-or-
faster on every config, and it *runs configs where 3.0.2 crashes* (resident always; offload on
relaxed geometry). The crash is a tile-list/host-alloc buffer-sizing bug; the git source has a
reallocation-retry (`CudaTileListKernel.cu:1126-1154`) that 3.0.2 lacks. Observing 3.0.2 crash
where git survives (same bug, same line 1141) is the real-world Gate-1 evidence.

**No capability lost.** The only two things a single CUDA build can't do — true CPU-only runs and
GBIS implicit solvent — need a *non-CUDA* build that **is not installed** on this machine (only the
two CUDA builds exist), and both are irrelevant to the goal (GBIS = abandoned dead-end; CPU-only =
pointless with a capable GPU). So switching removes zero working capability and adds the whole
GPU-resident fast path.

**Implemented** (machine-local, reversible): `~/.bashrc` now exports
`NADOC_NAMD_BIN=$HOME/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3` (find_namd's
highest-precedence hook) and points the NAMD PATH entry at the git build instead of 3.0.2. Verified
`find_namd()`/`resolve_namd_launch(GPU)` → git build. **Effect: the entire gap-C fallback cascade
(resident→offload downgrade, tile-list→CPU reroute) never fires — the one binary that fixes the bug
is the one used.** Takes effect on the next `just dev` restart. The deferred UX work (clearer
messaging, require-resident-by-default + diagnostic popup, ship the right build in setup docs) is
now optional polish, not needed for a working minimum-config run.

## FINDING — VoltronCore 21↔24 seam splay is a design under-crossovering (2026-07-23)

User observed one side stretched near helices 21/22. Measured interhelical center-to-center
spacing per neighbor pair vs the 22.5 Å square-lattice design (`metrics/measure_helix_spacing.py`,
`residue_helix.json`, `helix_geom.json`). Bulk lattice HEALTHY (median 22–23 Å = design). Sharp
LOCAL splay: **21–24 median 65 Å, 22–23 43 Å** (design 22.5). Traced through the pipeline:
- **Not the seed/build:** raw oxDNA seed pdb = uniform 22.5 Å everywhere (incl. 21–24).
- **Introduced during NAMD relaxation:** born at s1_heat (21–24: 22.5→47 Å), grows as ENM ladder
  relaxes k0.5→0.01 (→63 Å). 21–22 and 23–24 stay tight; the two *columns* splay.
- **Root cause = under-crossovered seam.** From strand routing (crossover = consecutive-resid
  helix transition): 21–24 has **6 crossovers with a 63 bp crossover-free span**; every other
  seam in the bundle has 11–12 crossovers / ≤31 bp gaps. The gap is **pinned to ~20 Å AT the
  crossovers and bows to 60–100 Å between them.** 22–23 splay is secondary (rigid 23–24 pair
  dragged out by the 21–24 bow). CG/idealized models pin the lattice and hide it; the first
  atomistic explicit-solvent run reveals it.
- **Fix is topological** (Three-Layer Law): add a crossover in the 64→127 offset gap on 21–24
  (~offset 95) + optionally at the unsupported ends (offsets 8–63, 160–231).
- Present in BOTH replicates (same relaxed start). This is the headline scientific result:
  atomistic MD as a design-validation tool catching what CanDo/oxDNA/mrdna cannot.

## Thrust D — Production + metrics

**FIRST PASS COMPLETE (2026-07-21) — VoltronCore HELD.** Full ladder ran clean on the git-build
resident path: minimize→heat(1fs)→ENM k0.5/0.1/0.01→**2 ns free NVT production** @2fs, all in
12 GB. Measured throughput: relaxation ~7.7 ns/day, **free production 9.2 ns/day @2fs** (~22 ms/step).
Fidelity oracle on the 400-frame trajectory (DNA-only, 469,391 atoms):
- **RMSD** plateaus 45–52 Å after 600 ps (slope 1.6 Å/ns) → equilibrated to a global bend, NOT drifting.
- **Rg** 257→254 Å, range 3.8 Å (**1.5%**) → compactness preserved, no swell/collapse.
- **RMSF** median 2.9 Å, mean(excl top 1%) 4.5 Å; only 3.2% of backbone >15 Å (free ss ends).
Verdict: **stable, physical production trajectory. The local NAMD explicit-water GPU-resident
pipeline works.** Artifacts: `runs/A_prod/out/s5_prod.dcd`, `metrics/A_prod_firstpass.*`.

**REP-1 COMPLETE — 10 ns, VoltronCore HELD (corrected analysis).** Survived a host crash at
step 150k (power-level reset, ~5 min lost; auto-resumed by `resilient_run.sh`). Reached 4M steps
(10 ns total incl. the 2 ns first pass) cleanly.
- **PBC-wrapping artifact caught + corrected:** raw metrics (`wrapAll on` + whole-origami boundary
  diffusion) inflated RMSD to 60 Å and extent to [712,173,626] (>box, impossible). Re-analyzed by
  min-image unwrap to the whole reference (`metrics/rep1_unwrapped.npz`): **true RMSD 17.5→24.9 Å,
  slope +0.50 Å/ns over last 5 ns (plateaued)**, unwrapped extent [486,71,599] **fits box** with
  margin (x snug ~8 Å). Modest ~4% z-compaction, leveling off = physical relaxation, not melting.
- **metrics.py had a wrapping bug** (used wrapped coords). FIXED: now unwraps min-image to the
  original whole structure before RMSD/Rg/extent. rep-1's official numbers = the unwrapped ones.
- Verdict: **stable, equilibrating, structure-preserving 10 ns production. Proof-of-pipeline
  replicate 1 = satisfied.**

**REP-1 official unwrapped metrics** (`metrics/A_prod_rep1_10ns_uw.summary.json`): RMSD last 25.0 Å
(mean 22.2, plateaued), Rg −2.3%, **RMSF median 3.2 Å / mean 3.5 Å** (helices fully intact, minimal
fluctuation). `verdict_hint=CHECK` is only the strict all-atom extent threshold catching a few
flailing ssDNA-end atoms (x-extent 1.11×box); the P-backbone fits the box (0.98×) and every robust
signal = HELD. metrics.py now unwraps min-image to the whole reference (bug fixed).

**REP-2 = independent-velocity replicate on the PROVEN oxDNA 1.31M box (RUNNING ~28 h).**
Seeded from A_prod's relaxed structure (`s4_k0p01`) with FRESH Maxwell-Boltzmann velocities +
new RNG seed (20260722) → independent trajectory testing velocity-seed robustness of HELD.
`runs/B_prod_oxdna_rep2/`, resilient (auto-resume), 8.6 ns/day, step 0 sane (300 K, −5.31 M).

**Why NOT the mrdna box for rep-2 (pivot): mrdna→atomistic seed has UNRECOVERABLE clashes for
plain minimize.** The 0.01 Å base-ring overlaps → NaN forces (VDW pegged −1e11, no minimize
progress after 1000 steps). Declash-first minimize does NOT fix exact-zero-distance overlaps.
→ Rather than block the proof-of-pipeline deliverable, rep-2 uses the proven oxDNA box. The mrdna
faster-pipeline (Thrust H) stays open: **next step = jitter seed coords ±0.3 Å to break exact
overlaps, then minimize** (or improve the mrdna→atomistic reconstruction). Box + ENM ladder for it
are built (`seeds/rep2_box/`, k0.5/0.1/0.01), 2.15M atoms — ready once declashed. This is R&D, not
the deliverable.

**Infra added post-crash:** `resilient_run.sh` (auto-resume from newest checkpoint after any crash
OR reboot), 30 s GPU power/thermal telemetry (`logs/gpu_telemetry.csv`), failure/stall/complete
monitor. Crash cause = abrupt power reset (no OOM/thermal/panic in logs; GPU pinned ~343 W for 10 h;
first unclean shutdown in ~2 months). Recommend `sudo nvidia-smi -pl 280` before long runs (needs user).


Once A or B yields a stable, in-VRAM, GPU-accelerated step: run the relaxation ladder to a
free-dynamics production segment, collect metrics on replicates, and report ns/day + fidelity.
Define "done" per the success criterion (see OPEN QUESTIONS).

- **Observations / Results / Conclusions:** _(fill)_

---

## Ambitious thrusts (user-authorized 2026-07-21: "massively ambitious sidequests tolerated")

These target FASTER (beyond resident 2fs) and/or BIGGER (toward the true 11.3M full box, or
better-solvated boxes) than the now-proven 1.31M resident baseline.

Scout verdicts (2026-07-21) reshaped these — most were closed, one elevated:

### Thrust E — Domain decomposition — **DEMOTED to seed-only (not production).**
NADOC has cluster boundaries (`cluster_autodetect.py`, `dropped_boundary_crossovers`) but no MD
substrate. Cutting bridge crossovers destroys global bend/twist modes = exactly the flexibility
target. Valid only to cheaply relax a seed; never reported as production dynamics.

### Thrust F(a) — GBIS-on-resident — **DEAD-END, closed.**
`SequencerCUDA.C` (the resident integrator) has *zero* GBIS wiring; GBIS lives only in the
legacy offload path with per-phase host round-trips architecturally opposed to resident mode.
Patching the guard → vacuum electrostatics, not implicit solvent. Corollary: GBIS **is**
available via CUDA-*offload* (no water at all → fits the full object) but at offload ms/step —
a fallback, not a resident unlock.

### Thrust G — CUDA unified-memory oversubscription — **CLOSED (impossible on one card).**
No out-of-core NAMD fork exists; managed-memory spill would PCIe-thrash away all resident speed.
The full 11.3M explicit box on one 12 GB GPU is genuinely not achievable. Fuller-box wins come
only from dropping water (implicit) — not from fitting more water.

### Thrust H — mrdna-seeded fast pipeline — **ELEVATED (primary ambitious thrust). PREPPED.**
mrdna (Aksimentiev multi-resolution CG→atomistic) relaxes the design → seeds NAMD near
equilibrium, skipping the slow clash-ridden early production. Serves the "shortest pipeline" goal.
- **Ready (2026-07-21):** mrdna v1.0a.dev219 (`~/mrdna-tool/mrdna`) + ARBD (`/usr/local/bin/arbd`)
  installed. NADOC uses mrdna as a **CG relaxer**, then reconstructs coords into its **own
  CHARMM36 builder** (`build_namd_seed_from_mrdna`) → drop-in `VoltronCore_seed.pdb/.psf`,
  compatible with the A_prod box by construction. CG model builds clean on CPU (50 dsDNA +
  90 ssDNA, ~2000 beads). Prep script (not yet run): `seeds/mrdna_seed_PLAN.sh`.
- **GPU/ARBD stage:** coarse 1e5 (~1 min) + fine 2e5 (~20–25 min) ≈ **25–30 min, <1 GB VRAM**.
  **QUEUED for the gap after first-pass production** (don't contend with the validating run).
- **SEED BUILT (2026-07-21):** ran concurrently with rep-1 (GPU time-share, 1.9 GB, ~30 min, no
  disruption to rep-1). `seeds/VoltronCore_seed.{pdb,psf}` — CHARMM36, 469,403 solute atoms,
  56/59 helices with crossover-inclusive overrides, 90 ss runs seeded. Valid.
- **Use:** seed a shorter-ladder production (rep-2) → measure time-to-production + fidelity vs
  the oxDNA-seeded A_prod path = the faster-pipeline demonstration.
- **rep-2 box build DEFERRED to post-rep-1** (RAM: only 7 GB free + swap full now; solvating
  469k→~1.3M would risk OOM against rep-1's 4.8 GB. rep-2 needs the GPU anyway, freed when rep-1
  ends ~25 h). Build box → short ladder → rep-2 10 ns after rep-1 completes.
- **Watch:** mrdna-seed leaves ~14–19 Å stretches at far-end ss scaffold-crossovers (NAMD min
  ladder resolves it); VoltronCore has 334 extension-tail beads (live-ARBD sterics unproven but
  not required for the seed).

### Thrust I — Fuller-box explicit (optional fidelity upgrade).
VRAM headroom fits ~3M atoms → a more generously solvated box than the tight 1.31M. Only if the
1.31M fidelity proves marginal. Build is CPU/psfgen (RAM-permitting), benchmarks later.

**Priority:** proven 1.31M resident path (Thrust A) = the deliverable, running now. Under
BALANCED: H (mrdna) is the active ambitious thrust; I is on-demand; E is seed-only; F(a)/G closed.

---

## Scope decisions (user answered 2026-07-21)

1. **Success bar = PROOF-OF-PIPELINE:** one stable ≥10 ns free-dynamics run that holds the
   origami + metrics, **replicated ×2**. (First pass runs 2 ns to validate fidelity, then extend
   to ≥10 ns + a 2nd replicate with a different seed.)
2. **Aim = BALANCED:** keep explicit production running AND develop ambitious thrusts with GPU
   time-sharing (non-GPU prep in parallel; short GPU experiments slotted into gaps).
3. **Sci target = GLOBAL STABILITY + FLEXIBILITY:** RMSD/RMSF, radius of gyration, helix
   integrity, whole-object twist/bend. **Consequence:** domain decomposition (Thrust E) is
   *excluded* as a production method — cutting the platform↔arm bridge crossovers destroys the
   exact global modes being measured; it survives only as a cheap seed accelerator, not the
   flexibility measurement.

(Ion rigor is moot — Route A is fully explicit water WITH explicit Mg-hexahydrate ions.)

## Log

- 2026-07-21: scaffold created; hardware/assets mapped; GBIS CUDA kernels confirmed in namd3;
  subagent researching GPU-resident GBIS support. Next: Thrust A VRAM fit test.
