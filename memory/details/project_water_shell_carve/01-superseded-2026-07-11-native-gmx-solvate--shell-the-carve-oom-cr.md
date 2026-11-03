# ⚡ SUPERSEDED 2026-07-11: native `gmx solvate -shell` (the carve OOM-crashed WSL) — supporting detail

[Topic head](../../project_water_shell_carve.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚡ SUPERSEDED 2026-07-11: native `gmx solvate -shell` (the carve OOM-crashed WSL)
The fill-then-carve above still **fills the whole box first** — for a 121 nm plate
(GT_corner_v2) that's ~6M waters generated just to keep the shell. Two multi-GB peaks
result: gmx tiling the box, then **Python `_parse_gro` loading the entire full-box
`.gro` → the backend hit 22 GB RSS and OOM-**crashed WSL** twice** (`_carve_water_shell`
runs only after the whole box is already in memory, so it can't prevent the peak).
**Fix:** `_gmx_solvate` now passes `gmx solvate -shell {water_shell_nm}` when a shell is
requested, so GROMACS places ONLY the hydration layer around the DNA — the empty box is
never materialised. The Python carve is skipped on that path (`_carve_water_shell` kept
only for its unit tests + the no-shell fallback). Box/PME/cellOrigin unchanged; the DNA
frame is still the recentred `[0,L]` from `_recenter_pdb_in_padded_box`. Verified: 1hbx300
60,447→15,856 waters (3.8×, `.gro` 8.7→2.7 MB); 2x3x100_Sq 72,797→28,814 (2.2×). The
`.gro` (→ the Python parse) shrinks by the shell/box emptiness ratio — that's the spike
that was killing WSL. NOTE: gmx's OWN peak is dominated by tiling the box and is roughly
UNCHANGED by `-shell` (moderate-box test: 42 MB either way); on a 121 nm box gmx alone
peaked ~15 GB, which SURVIVED before — the crash was the *compounding* Python parse on
top. So `-shell` removes the compound peak; the residual gmx tiling peak on a huge box is
inherent to GROMACS and would need chunked solvation to cut further (not done). Min-image
constraint unchanged (2·shell ≥ 12 Å cutoff → shell ≥ 6 Å). See [[namd-solvate]].

Key knobs:
- `water_shell_nm` (nm) threads: routes_md `CreateJobRequest` → `prepare_mgh_slow_release`
  → `build_namd_solvated_package` / `get_solvation_stats`. Default 0 = off. Use 1.5
  (15 Å); need 2·shell ≥ 12 Å cutoff for valid minimum image.
- ✅ **2026-07-29 — FIXED (the four items below are now code).** `build_production_conf`
  and `build_reseed_conf` take `npt=`; both call sites pass `package_npt_allowed(pkg)`,
  which reads a new `solvation` block in the manifest (`padding_nm`, `water_shell_nm`,
  `carved`, `npt_allowed`, `box_check`). Legacy packages without that block default to
  NPT, so no existing job's ensemble changes silently. NPT stages now carry
  `margin 3` (`NPT_MARGIN_ANG`; a LARGE margin on a CARVED box was the old GPU
  tile-list crash — carved is NVT now, so they cannot combine; margin 3 + GPUresident +
  NPT verified clean, 5000 steps @ 261 ns/day). `xstFreq` is capped at 10 ps
  (`XST_MAX_INTERVAL_PS`) so the 300 ps criterion is resolvable — it used to inherit
  `outputEnergies`, i.e. one cell sample per 500 ps on a long run. New module
  `backend/core/md_cell_health.py` (pure, 21 tests): `settle_report` (the Aksimentiev
  box-trace gate, on cell LENGTH — 3 % linear, because the legitimate full-box trim is
  7.4 % by volume), `is_collapsing` (floor 0.85 volume, between the measured 0.926 trim
  and the 0.67 crash), `solute_envelope`/`box_from_envelope`/`box_adequacy`,
  `min_image_distance`. The runner records `cell_shrink_events` and
  `cell_settle_reports` on the job and **refuses to auto-resume a COLLAPSING cell**
  (it still resumes a trimming one). `namd_solvate` gained `box_mode="rotation"`
  (cubic, `2·r_max + 2·pad`, orientation-proof) alongside the default `"bbox"`, and every
  build now records + warns on `box_check` (verified: the real 2hb package reports
  `fits_as_built=True, fits_rotated=False`, rotated image gap −49 Å).
- ✅ **2026-07-30 — `box_check` is now ENFORCED, not just recorded.** Recording it was not
  enough: `build_replica_package` dropped the whole `solvation` block from the child
  manifest, so the guard read `{}` on every production child and its `fits_rotated=True`
  default let a 1 µs run start in the ladder cell. The block is now inherited, resolved
  through `parent_job_id` for pre-existing jobs (`routes_md._inherited_box_check`), and
  checked on **both** production routes. `CreateJobRequest.production_ns_intent` lets a
  package be rotation-sized at prep — the only point where the choice exists, since nothing
  after prep re-solvates. (A later 2hb build at `padding_nm=2.0` reports gap −33 Å; the −49 Å
  above is the 1.2 nm-padding package — same verdict, different cell.)
  Full context in [[md-job-system]].
- ⚠ **2026-07-29 — THE NVT GUARD DID NOT COVER PRODUCTION, and it failed hard.**
  `nvt_only=carve_shell` is set only in `mgh_slow_release_segments` (md_protocols.py:2105);
  `build_production_conf` and the reseed conf **hardcode `langevinPiston on`**
  (md_protocols.py:552, :648). Measured on 2hb_1xT (`exp47_protocol_delta`, carved
  `water_shell_nm=1.2`, 6093 waters = 211 nm³ of content in a 334 nm³ cell → **37 % vacuum**):
  the ladder held the box at 44.147×66.635×113.568 ✓, then production shrank it isotropically
  and **crashed at ~0.95 ns with `FATAL ERROR: Periodic cell has become too small for
  original patch grid!`** — at ~67 % of the starting volume, while the water's own equilibrium
  volume is **61.8 %**. So the cell CANNOT reach equilibrium without crossing the patch-grid
  limit: the crash is guaranteed, not unlucky. The original 2 ns production hit it too
  (`auto_resumes: 1`, 32 copies of the string in its log) and NADOC's runner silently
  auto-resumed past it — which is how the 200 ns run inherited a collapsed 37.6 Å box.
  **12-arm one-knob-at-a-time series (exp47 `RESULTS.md`): NO conf knob prevents it** —
  9/9 died in a 0.93–1.17 ns window at 66–72 % volume (barostat period 1000/500 buys
  7500 steps; `useGroupPressure no` buys the most, 1.17 ns). Only two arms completed:
  **`langevinPiston off`** (cell held at 100 %) and **`margin 30`**, which survives the
  shrink and lands at **61.7 %** vs the **61.8 %** predicted from the water count — closing
  the mechanism (the barostat is correctly expelling vacuum; the crash is just NAMD's patch
  grid being sized for the original cell). The tutorial's own Note-4 remedy (NPT with the
  DNA `fixedAtoms`) reached 1.83 ns — nearly 2× the baseline — but still crashed.
  ⚠ **Surviving ≠ succeeding: ALL twelve arms end with the DNA within 3.8–9.5 Å of its own
  periodic image** (clean is >24 Å), including both that completed — `margin 30` succeeds
  *into* the collapsed cell, and NVT holds a cell that was already too small. 100 % of
  designed bp stay intact in every arm, so that is real geometry, not melting. **The box
  SIZE is the defect; the ensemble is not.** Bonus: the tutorial's electrostatics
  (cutoff 8/10/12 + fullElect 2 + PME 1.5) are **+37 % throughput** (484 vs 354 ns/day), but
  a smaller cutoff = finer patch grid = crashes at a *larger* volume, so adopting it without
  fixing the box makes this failure more frequent.
  See [[reference-aksimentiev-protocol]] and `experiments/exp47_protocol_delta/`.
- Carved cell has **vacuum corners → must run NVT**. `mgh_slow_release_segments(nvt_only=True)`
  is auto-set when `water_shell_nm>0` (an NPT piston would collapse the cell onto
  the DNA image). Stage names keep their `NPT` label for manifest/resume continuity.
- Ion count uses carved **solvent** volume (water_count ÷ 33.4 /nm³), not box
  volume, so molarity stays correct (else ~2× over-salted).

## Follow-up: first-dynamics-stage stability (RATTLE crash)

After the carve let it past minimization, segment 01 crashed at timestep 140:
`Margin is too small for 1 atoms` → `Constraint failure in RATTLE algorithm for
atom N` (a DNA C5'). Cause: a residual local strain in the ideal-B-DNA build that
ENM-restrained minimisation can't fully relieve; 2 fs + `rigidBonds all` explodes
it. NOT carve-related (failing atom is interior, fully solvated).

Fix (implemented): **soft start** — `mgh_slow_release_segments` now marks the FIRST
segment `soft=True` (rigidBonds none + 1 fs) even on the non-declash path; later
segments stay 2 fs rigid. No RATTLE ⇒ no crash; structure relaxes then speed
resumes. Confirmed: VoltronCore reached step 9600 at 298.6 K, stable.

GOTCHA — do NOT add an explicit `margin`. `margin 3.0` crashes NAMD's GPU tile-list
kernel at startup (`buildTileLists`). This is STILL LIVE and is pinned by
`test_no_explicit_margin_in_configs`. The K2 patch fixes the underlying crash, but the
**3080 Ti box does not have the patched `NAMD_3.0.2p1` built yet**, so an explicit margin
would break there. It is also not a measured win: the 18.8 ns/day carved-offload result
was obtained with NO margin. Tried and reverted 2026-07-12 — don't re-add it without first
building the patched NAMD on both machines.

Defaults raised in `_common_header` 2026-07-12 (margin deliberately NOT among them):
`stepspercycle` 12 → **20**, `pairlistdist` 12 → **13.5**. Carved/offload 16.7 → 18.8 ns/day.
⚠️ `stepspercycle` is duplicated as a constant in TWO places that MUST be kept in sync or
NAMD FATALs at startup on a non-multiple `minimize`/`run` count:
`md_protocols.AKSIMENTIEV_STEPS_PER_CYCLE` and `benchmark_runner.NAMD_STEPS_PER_CYCLE`
(+ `NAMD_BENCH_STEPS`, now 2000 = 100 × 20).
