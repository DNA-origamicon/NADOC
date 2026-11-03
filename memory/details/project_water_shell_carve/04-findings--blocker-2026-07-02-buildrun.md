# Findings + BLOCKER (2026-07-02 build/run) — supporting detail

[Topic head](../../project_water_shell_carve.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Findings + BLOCKER (2026-07-02 build/run)

Built `backend/core/md_shell_reprep.py`: `read_namd_coor`, `com_restraint_colvars`
(3× distanceZ pinning DNA COM by leading serial range), `stamp_relaxed_dna_model`,
`prepare_shell_nvt_production` (orchestrator). Added optional `colvars_file` to
`md_protocols._segment_conf`. Tests: tests/test_md_shell_reprep.py (8, green).

**Reversals learned the hard way:**
1. **Do NOT seed re-solvation from the checkpoint's relaxed coords.** (a) The MD PSF
   is psfgen → hydrogens interleaved, so `build_atomistic_model` HEAVY order (149,750)
   ≠ checkpoint row order (232,109 DNA atoms w/ H): `checkpoint[:n_heavy]` maps garbage.
   (b) The relaxed coords have DRIFTED/spread in the periodic cell → bigger bbox →
   bigger re-solvation box → carve WORSE (745k) than the compact design build (668k).
   → Orchestrator now seeds the **design build** (no stamp); design-strain is relieved
   by the restrained equil, not by coord reuse.
2. **Neutrality needs `require_full_topology=True` + `protocol=EQUILIBRIUM_AWARE`.** The
   default (heavy-atom Python PSF) path left net −11438 e (DA/DC naming, no psfgen
   neutralising Na). With full topology → psfgen (ADE/CYT), netQ **+0.00**. ✓
3. **This structure is COMPACT, not sparse-curved.** 47% bbox occupancy, ~straight
   flat 3×6 bundle (PCA spread 200/38/19 Å). 15 Å shell → 668k atoms = only **1.55×**
   vs 1.03M (NOT the 2.5-5× of a hollow/curved design). Projected ~19.5 ns/day
   (clears 16, modest). n_dna for the colvars range = ATOM-record count in the built
   PDB (232,109 w/ H), NOT the heavy model count.

**BLOCKER — carved min crashes the GPU:** `FATAL ... CudaTileListKernel.cu
buildTileLists ... illegal memory access` at minimize step 1 (both +p8 and +p1).
NOT the margin gotcha (no margin set) and NOT atoms-outside-box (the ORIG full-box
build has MORE atoms outside — 71,874 vs 60,744 — and minimised fine). Specific to
the carved cell's vacuum regions × GPU tile list. VoltronCore reportedly ran carved
(step 9600) so it's structure/config-specific — unresolved; needs dedicated GPU
debugging (try: no-ENM-extrabonds min to isolate; CPU-only min then GPU dynamics;
patch/twoAway settings; or a thin bulk-water margin instead of hard vacuum).

Net: shell is NOT a quick win for a compact bundle. The shipped **full-box 4 fs HMR**
production (12.6 ns/day, paper-faithful) is the reliable path; >16 needs the shell
(blocked) or a 2nd GPU. Scratch build/run scripts under the session scratchpad.
