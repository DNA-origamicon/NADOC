# Frame rigidity — why the 3D Cartesian map is demoted — supporting detail

[Topic head](../../project_cpd_umbrella_sampling.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Frame rigidity — why the 3D Cartesian map is demoted

Measured (see the archive for the full tables): a body-fixed frame built from **multiple**
junction arms is not rigid — 8.65 Å RMSD on the AutoNAMD junction; trimming 7 bp → 3 bp does
not help (junction-core articulation, not end fraying); motion is continuous, not discrete
conformers, so per-conformer maps are not available as a rescue.

| local group, 12 Å radius | RMSD |
|---|---|
| isolated Holliday junction | 4.63 Å |
| **2hb origami crossover** | **2.83 Å** (85 frames only — a lower bound) |

The lattice helps ~1.6× but even the origami is marginal. **Rule: never build the frame from
multiple arms; use a single ~12 Å local neighbourhood and carry ~3 Å blur as explicit map
uncertainty.** A 3D Cartesian PMF is therefore a *qualitative* candidate-finder, not the
quantitative reactive surface. It earns its cost on `24hb_1xT` (338 extra T) /
`6hbx100_1xT`, not on 2hb_1xT which has exactly one pair.

## Phased plan

- **Phase 0 — unbiased baseline.** ✅ DONE (above).
- **Phase 1 — colvars emitter.** Populate `photoproduct_junctions` from `reciprocal_pairs()`;
  emit `d_mid` + `eta` per declared junction. Oracle: structural match to
  `colvars_cpd_metrics.in`. Shaped for `/automate-feature`.
- **Phase 2 — 2D F(d, η).** eABF, all-atom, d ≈ 3.4 → 12 Å, η periodic. Validate one d-slice
  against a 1D umbrella ladder. ~1.7 days at 4 fs / ~360 ns/day for 4 walkers × 150 ns.
- **Phase 3 — 3D map (oxDNA/LAMMPS).** Blocker first: confirm `fix colvars` sees oxDNA
  ellipsoids at all (untested; `fix colvars` reads positions/forces, not quaternions/torques,
  so orientation CVs are likely unavailable — bias on COM, reweight to base site).
- **Phase 4 — ⟨k⟩ reweighting + authoring UI.**

## Corrections and dead ends — do not repeat

- **⟨k⟩ does NOT need enhanced sampling on the reference system.** An early claim that
  unbiased averaging under-samples the reactive tail was wrong: on the AutoNAMD junction ⟨k⟩
  drifts +2.9% over the last half and 50% of Σk comes from the top 18% of frames — broad, not
  a rare-event tail. US is for the *landscape*, not the rate number. (On 2hb_1xT US **is**
  needed, but because the pair starts 11.4 Å apart, not because of tail statistics.)
- **KIMMDY's `|η − η0|` is not periodic-aware.** At η = −175° it returns 191.7° where the true
  separation is 168.3°, underestimating k ~2×. Only matters in the antiparallel region.
- **AutoNAMD designs are REFERENCE ONLY, never production.** Its KIMMDY off-target hits
  (AN1:T34–BN1:T6 etc.) are not of interest — they are artifacts of that construct.
- **PBC unwrapping is mandatory** before any geometry measurement on these trajectories, and
  per-fragment unwrap is not enough — the strands must also be brought into a common image.
- **Do not hand-roll Kabsch.** A transposed covariance is silent and returns plausible-looking
  large RMSDs. Use `MDAnalysis.analysis.rms.rmsd(..., superposition=True)`.

## Tooling

- `scripts/measure_cpd_coordinates.py` — measures (d_mid, η, k) for a design's declared
  extra-base pairs over any package trajectory. Identifies the extra bases two independent
  ways (WC geometry + the design's insert walk) and refuses to measure if they disagree.
- Gates: `scripts/check_catenation.py` (design), `scripts/check_ring_piercing_frame.py` (built
  structure / trajectory).
- Reference only: `~/Work/AutoNAMD` (window ladder, MBAR via `autonamd/free_energy.py`,
  overlap-index QC), `~/Work/kimmdy-namd-cpd` (the rate model).

## Related

[[project_crossover_catenation]] · [[project_extra_base_4fs_geometric_fixb]] ·
[[project_oxdna_extra_bases]] · [[project_md_job_system]] · [[project_lammps_oxdna]]
