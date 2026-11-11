# 3 nm graded-boundary pilot

User-requested follow-up to the shell-damping study. All outputs are derived
simulation artifacts; no NADOC structure or managed job is authored or modified.
The exact prior source snapshot, source PSF/PDB, selection receipt, checkpoint
hash and source-to-native atom map are retained.

## Protocol fixed before production

- Same central 6.4 × 6.4 × 4.76 nm box and identical core atom/pair identities.
- Shell width 3 nm; outermost 0.3 nm fixed, plus every retained residue involved
  in a bonded term crossing the extraction boundary. Fixed support does not
  overlap the core.
- Static per-nucleotide distance from its original source-space P (terminal
  fallback C1′) to the oriented box, consistent with the retained selection. Core coefficients are zero. Mobile shell heavy atoms use
  `k = 0.5 × (3t² − 2t³)`, `t = clamp(d / 2.7 nm, 0, 1)`.
  Coefficients are rounded to 0.01 kcal/mol/Å² to match the actual PDB B column.
  Hydrogen coefficients are zero. The coefficients do not change as atoms move.
- Controls: wholly fixed shell and uniform k=0.1 on the same mobile buffer with
  the same fixed outer boundary. No damping sweep: 1 ps⁻¹ on mobile heavy atoms.
- All cropped DNA starts from the prior full-model `common_relax.coor` checkpoint,
  mapped by segment/residue/atom identity. Selection remains the original
  source-space box; geometry is not reauthored. Crop solvent is newly generated
  and minimized, then relaxed for 20 ps at 2 fs with **all DNA fixed**. Thus crop
  conditions share both DNA and solvent starts, and the full/crop core DNA starts
  agree within PDB precision. Full/crop solvent is not identical.
- Explicit TIP3P, 150 mM NaCl, no Mg, 300 K NVT, 2 nm solvent padding, PME,
  GPU offload. Production: HMR, rigid bonds, 4 fs, two seeds (77/177), 50 ps each.
  Full references are the existing two 50 ps runs from that same full checkpoint,
  reused read-only. No new full-model minimization is needed.
- The rectangular cell is for this short fixed-boundary pilot. Its dimensions
  do not establish safety for arbitrary rotation or longer unrestrained runs.

The initial endpoints are exploratory choices, not optimized physical boundary
parameters. The fixed boundary still imposes missing long-range mechanics.
This study asks whether a graded shell gives a stable, responsive local preview.

## Metrics prepared before dynamics

`analyze.py` reuses the prior core metric implementation, accepting the explicit
condition registry, and adds spatial shell diagnostics. Outputs include:

- Core-aligned RMSD to the ideal source and to each checkpoint; RMSF over the
  last 25 ps; radius of gyration; per-atom RMSF profiles and per-frame traces.
  Per-nucleotide profiles retain segment/residue identities for local diagnosis.
- Topology-defined WC contact fraction (all expected heavy-atom contacts ≤3.6 Å),
  separate central hydrogen-bond distance/angle fraction, paired C1′ distances.
- Core and shell-involving heavy-bond strain relative to the checkpoint. Shell
  bond comparisons use identical retained bond identities in full and crop.
- Shell profiles in 0.5 nm bands: core-aligned RMSF/displacement, absolute cell-
  frame displacement, atom and nucleotide counts. Fixed atoms can appear to move
  relative to an aligned core; cell-frame and fixed-drift checks distinguish that.
- Harmonic restraint energy/force proxies, using the actual serialized k values.
- Local hydration count (water O within 5 Å of core heavy atoms), temperature,
  and pressure diagnostic. NVT pressure with `fixedAtomsForces off` is not a
  directly comparable ambient-pressure validation.
- Finite coordinates in every saved frame; >20 Å conservative DNA periodic-image
  clearance; fixed native-checkpoint drift <1e-8 Å and DCD drift <5e-5 Å (float32).
- Native wall time, sampled peak process RSS and process GPU allocation (1 s
  sampling, not guaranteed instantaneous peaks), trajectory size. The reused
  full references have timings but no newly measured memory samples.

Report per-seed means/ranges; do not treat correlated frames as independent
replicates. Continuing RMSD drift or pairing differences preclude an equivalence
claim. Shell width, preparation and restraint treatment must remain identifiable
when comparing against the earlier 2 nm campaign.

## Execution

```sh
just validate-safe .venv/bin/python -m experiments.namd_submodel_gradient.run PRIOR NEW_OUTPUT --binary NAMD --prepare-only
just validate-safe .venv/bin/python -m experiments.namd_submodel_gradient.run PRIOR OUTPUT --binary NAMD --prepared
just validate-safe .venv/bin/python -m experiments.namd_submodel_gradient.analyze OUTPUT
```

A fresh directory is required for preparation. Recorded successful production
trials are skipped on resume; existing unrecorded inputs refuse overwrite.

## Results — 2026-11-10

Six new production runs completed successfully (two seeds per cropped condition),
compared with two reused full-model references. All used 4 fs production. Core
comparison covers the same 3,457 heavy atoms and 84 designed base pairs.
Independent coordinate matching found 0.000497 Å aligned RMSD between the full
and cropped starting cores; maximum atom discrepancy 0.000847 Å. This removes
the substantial DNA-preparation mismatch in the earlier damping comparison.

Values below are means across the two seeds of the last-25-ps averages. Brackets
are seed-level ranges, not confidence intervals. Pairing is the fraction of
core pairs meeting all expected WC heavy-atom contacts ≤3.6 Å.

| Treatment | Core RMSD to ideal (Å) | Core RMSF (Å) | WC contacts |
| --- | --- | --- | --- |
| full | 3.072 [2.889, 3.254] | 0.712 [0.712, 0.712] | 0.961 [0.957, 0.966] |
| fixed | 2.924 [2.885, 2.963] | 0.652 [0.629, 0.674] | 0.944 [0.943, 0.945] |
| uniform | 3.034 [2.972, 3.096] | 0.728 [0.710, 0.746] | 0.949 [0.949, 0.950] |
| gradient | 3.301 [3.216, 3.385] | 0.697 [0.685, 0.710] | 0.948 [0.938, 0.958] |

The gradient leaves more motion immediately outside the core and progressively
reduces motion toward the fixed boundary. In the 0–0.5 nm band, cell-frame shell
displacement averaged 1.07 Å (uniform: 0.63 Å); in the 2–2.5 nm band it fell to
0.33 Å (uniform: 0.49 Å). Both gradient seeds show essentially the same spatial
trend. The fixed shell has zero cell-frame displacement. Its nonzero
*core-aligned* shell RMSF reflects motion of the core relative to that fixed
frame, not motion of the fixed atoms.

Gradient core RMSF is about 2.1% below full, versus 8.5% below with the wholly
fixed shell; uniform restraints give about 2.2% above full. Gradient paired C1′
separation averages 10.726 Å, versus 10.713 Å for full. However, gradient RMSD is
higher than uniform/full and pairing remains about 1.4 percentage points below
full. The gradient is therefore a working candidate, not a uniformly superior
choice. RMSD continues drifting over 50 ps; this is not a convergence result.

Core heavy-bond strain p99 is 0.116–0.117 Å across conditions. Shell-involving
bond strain p99 is 0.112–0.113 Å for mobile buffers versus 0.116 Å for full;
fixed-shell values are zero by construction. These comparisons use identical
retained heavy-bond identities. Gradient maximum harmonic-force proxy is
1.63–1.67 kcal/mol/Å versus 0.63–0.67 for uniform restraints. This reflects its
stronger outer coefficients; no dynamics failure or excess core bond strain was
observed. Temperature means are 297.1–297.7 K and local hydration counts are
3,302–3,338 waters. Global temperature is solvent-dominated; local kinetic
thermalization is not established by this metric.

All 400 analyzed frames are finite. Conservative DNA image clearance remains
above the predefined 20 Å limit. Fixed checkpoint and DCD displacements pass
their precision-specific tolerances. Per-nucleotide profiles, per-frame traces,
seed ranges and native logs remain available for inspection.

The 3 nm crop contains 182,739 atoms including solvent. New production runs took
102–107 s per 50 ps versus 266–269 s for the reused full references (427,610
atoms). Gradient runs peaked at about 526 MiB sampled process RAM and 628 MiB
process GPU allocation. These are observed allocations, not safe job-admission
budgets. Monitoring samples every second and may miss instantaneous peaks.

**Interpretation:** the gradient performs its intended boundary function and
preserves a useful level of core motion. Keep it experimental. The next width
comparison should retain this shared DNA checkpoint and the same gradient rule;
the older 2 nm campaign changed both preparation and boundary conditions, so it
cannot identify width-dependent diminishing returns on its own. The uniform
control remains competitive and should remain in that comparison.

Evidence: `.development-artifacts/namd-submodel-gradient-20261110/` contains
`experiment.json`, `preflight.json`, `shared-start-verification.json`,
`analysis.json`, `summary.json`, `shell-metrics.json`, `residue-profiles.json`,
`performance.json`, native inputs/masks/checkpoints/trajectories, and the
`comparison` and `shell-profiles` figures (PNG/PDF). Initial preparation failures
were metadata/receipt integration errors before any native dynamics; their logs
and explanation are retained, and disposable failed packages were removed.

Validation: five focused software checks and scoped Ruff checks passed. Native
run/analysis assertions passed; both result figures were visually inspected.
No production backend/UI behavior changed, and no source document or managed
job was modified. The 3 nm gradient is an isolated experiment, not a new default.
