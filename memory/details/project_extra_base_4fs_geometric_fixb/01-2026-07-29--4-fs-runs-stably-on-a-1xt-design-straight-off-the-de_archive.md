# ✅ 2026-07-29 — 4 fs runs STABLY on a 1xT design straight off the DECLASH relax (historical) — historical evidence

[Topic head](../../project_extra_base_4fs_geometric_fixb.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ✅ 2026-07-29 — 4 fs runs STABLY on a 1xT design straight off the DECLASH relax (historical)

> **Current policy (2026-08-09):** 1xT junctions no longer enter declash automatically.
> The run below predates that threshold change and remains evidence that 1xT is stable,
> not a description of the package the current builder emits. Automatic declash now begins
> at 2+xT on any one junction; the count is not summed across separate crossovers.

`2hb_1xT` (32,566 atoms solvated, ONE extra T per crossover), produced directly from the ordinary
**declash** relaxation — no geometric+Fix-B re-prep:

| | ms/step | ns/day |
|---|---|---|
| 1 fs, `rigidBonds none`, offload | 1.086 | 79.6 |
| 2 fs, `rigidBonds all`, GPUresident | 1.365 | 126.6 |
| **4 fs, `rigidBonds all` + HMR, resident OFF** | **0.960** | **~360** |

**COMPLETED 2026-07-29 — all 50M steps = 200 ns, ZERO RATTLE / constraint / fast-atom
failures**, 360.7 ns/day sustained (0.958 ms/step, sd 9e-6), T flat 297.4 → 297.3 K, 13.3 h
wall. Job `29c5b267380f`, 20 000-frame DCD (10 ps) on Archive.
The HMR PSF was **built on demand at production time** from the declash package's own PSF (1086
hydrogens repartitioned) — the relax never made one.
It has since been mined for the equilibrium extra-base pose — see [[crossover-catenation]]
§2026-07-29 and `experiments/exp46_xb_placement/REPORT.md`; note the caveat there that NPT
shrank the carved-shell box **below the solute width** (DNA within 2–3 Å of its own periodic
image for part of the run).

**What this does and does not say.** It does NOT overturn the Fix-B finding above: that was
established on **24hb_1xT (338 extra T)** and **6hb_2xT (48 extra-base residues)**, where HMR
lightening C5' on unpaired inserts broke 4 fs. It BOUNDS it — at *one* extra T per crossover the
unpaired population is too sparse to destabilise the constraint solver, so a small 1xT design needs
no Fix B. Treat Fix B as required above some extra-base density, not for extra bases per se; the
threshold between 1xT/2hb and 2xT/6hb is unmeasured.

**Also note the 4 fs win here is larger than the naive 2×** over 2 fs (2.8×), because the 4 fs conf
also dropped GPU-resident — which is a LOSS below ~100k atoms (see [[project_water_shell_carve]]).
Per-step cost actually fell (1.365 → 0.960 ms) while the step doubled.

> **2026-07-28 — a THIRD, independent defect was found in the same seed geometry.**
> Reciprocal crossover pairs carrying extra bases were built **topologically catenated**
> (Gauss `Lk = ±1`), invisible to every health check here, and unfixable by relaxation.
> The 4 fs work above is unaffected (it is about masses and ring clashes, not topology) but
> **any stiffness number extracted from a pre-2026-07-28 extra-base ensemble is suspect** —
> a pinned junction mimics a soft hinge. See [[crossover-catenation]].
> Also recorded there: the standard prep path calls `write_hmr_psf` WITHOUT `heavy_residues`,
> so **Fix B is applied only by `prep_24hb_seeded.py`** — a job prepped through the UI does
> not get it.
