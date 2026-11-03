# Why this is cheap (established 2026-07-11) — supporting detail

[Topic head](../../project_snupi_mimic.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Why this is cheap (established 2026-07-11)
- SNUPI (Lee/Kim, ACS Nano 2021) ran **almost no new MD**: regular+nicked BP steps = published
  3DNA values (SI Tables S1–S2); CO motifs = **reused** Bathe-2012 trajectories (the 32-hb
  honeycomb bundles, Fig S2) + a few additions (SI Note S14). All **74-motif** params are
  printed in **SI Tables S1–S5**; Figure S1 plots them.
- SNUPI's model = the **same corotational per-bp beam FE as CanDo**, plus three deltas. NADOC's
  `fem_solver.py` is already a CanDo-replica **validated** vs CanDo (RMSF 0.8–0.97, twist
  ~10–30%, bend ~0.9 — see [[project_cando_fem]]). So this is a small delta on validated code,
  not a rebuild.

## The three deltas (CanDo → SNUPI)
1. **Anisotropic per-motif 6×6 stiffness**, sequence-dependent (6 rigidities EA/GAy/GAz/GJ/EIy/EIz),
   74 motif types — vs the current isotropic scalar EA=1100 / EI=230 / GJ=460. Transcribe S1–S5.
2. **15 coupling coefficients** per motif (trans–rot, incl. twist–stretch ≈ −277 pN·nm) — currently none.
3. **Debye–Hückel inter-helix electrostatic elements** (SI Notes S6/S7) — the one genuinely new
   solver piece; today inter-helix coupling is via crossover links only. **Deferrable to P3.**

## Validation data — ON DISK, no new MD
- **6hbx100_noT** — standard 6-helix honeycomb, no extra bases; complete set at
  `/media/jojo/Archive/nadoc_jobs/892ad3d12d4f/package/6hbx100_noT_namd_solvated/` → psf + pdb +
  **20 ns k=0 production DCD (1.96 GB)**. **Primary base-SNUPI target.**
- **3x4SQ** — square lattice, k=0 DCD (`/media/jojo/Archive/nadoc_jobs/93cdbbd3a3f1/...`) → validates SQ params.
- 6hbx100_1xT / 2xT, 6hb_2xT — extra-base variants → the EXTENSION targets (base SNUPI can't
  predict these; use after the Δbase extra-base motifs are added).
- ⚠ **18hb trajectory is NOT on this machine** (job `e29d1e5d5ace` absent; only exp30 summary
  docs in `experiments/exp30_18hb_production/`). The 39 GB DCD lives on the work computer —
  sync it if you want 18hb as an extra target; **not needed to start**.
- ⚠ **`Literature/SNUPI_SI.pdf` is gitignored (local only)** — run this plan ON THIS MACHINE,
  or re-copy the SI + main paper on the other computer first.
