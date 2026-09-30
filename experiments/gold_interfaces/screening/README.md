# Gold versus the existing Debye screening benchmark

This isolated experiment transfers the existing **fixed-charge diffuse-screening
check** to an explicit Au(111) contact surface. It does not implement constant
potential, image charges, charge transfer, Au–S chemistry or production validation.
The registered neutral gold builder and application APIs are unchanged.

## Declared comparison

| Setting | Existing abstract-wall reference | New Au controls |
| --- | --- | --- |
| Physical gap | 6 nm | 6 nm between inner Au planes |
| Area | 64 nm² | 64.52762582 nm², commensurate Au(111) lattice |
| Electrode charge | ±16e, ±0.25e/nm² | Neutral or ±16.13190646e, ±0.25e/nm² |
| Charge placement | Abstract wall sites | Uniform prescribed charges on each inner Au layer |
| Ions | 64 Na, 64 Cl | 64 Na, 64 Cl |
| Water | 11,772 | 12,810; transferred surface-excess inventory, then measured |
| Temperature | 300 K | 300 K |
| Integration | 4 fs rigid water | 1 fs rigid water, same mass convention |
| Electrostatics | PME + EW3DC; 18 nm normal cell | PME + EW3DC; 23.65 nm normal cell includes finite Au thickness |
| Interface | Repulsive barriers | Five-layer Au slabs, neutral-IFF LJ, native harmonic restraints |
| Sampling | 40 ns; same start across hardware | 300 ps per arm, two independently prepared seeds |

These differences prevent a claim of a strictly matched reproduction. Gold needs
its own solvent inventory and contact interactions; the normal padded cell includes
the metal thickness. No physical parameter is fitted to the old screening length.
The copied ±0.25e/nm² is a prescribed surface charge, not a voltage conversion.

Each neutral/charged pair shares coordinates and seed before separate minimization.
Seeds 317 and 719 use independent prior bulk NPT snapshots and independent ion
placement. The water count transfers the measured water surface excess from the
3 nm slit and adds bulk water for the larger gap. That source was at 298.15 K and
nominal 150 mM; density under the new 300 K/64-pair conditions is an observable,
not assumed correct. Nominal setup salt is not a substitute for measured central salt.

## Analysis fixed before seeing the runs

- Primary window: 100–300 ps; additionally report each successive 100 ps window.
- Reuse `experiments.electrode_relax.debye_analysis` for the finite-gap ion-ratio
  fit, canonical PB, classical Debye comparator and exact planar charge integration.
- Retain the historical 0.5/0.6/0.8 nm exclusion sensitivity.
  Also tabulate actual near-surface ionic charge at 0.3/0.5/0.6/0.8/1.0 nm. The Au near-surface
  region may require a different diffuse-layer boundary, so these are comparisons,
  not certified Stern-plane positions.
- Report central 0.8 nm water density, measured Na/Cl concentrations, water
  translation/rotation temperatures, half-cell ion excess and spatial profiles.
- Separate gold, ions and explicit water in the microscopic potential. Their
  sum is checked against the all-charge potential. Zero potential is the midplane
  gauge; zero potential there does not imply zero electric field.
- A neutral run may produce a numerical optimizer result; it does not have an
  imposed electrode screening response from which to qualify a Debye length.
  `optimizer_converged` is explicitly distinct from `screening_validated`.
- The 200 ps primary window contains **zero** complete historical 300 ps bootstrap
  blocks. Do not report a screening confidence interval. Density block intervals
  are conditional on stationary, independent block means and do not prove either.
- Compare both the old 100–300 ps window and its late 20–40 ns window. Do not
  choose whichever historical or gold interval agrees best.

The deterministic `estimator_reference.json` applies the unchanged estimator to
canonical PB profiles at the corresponding geometry and count. It diagnoses the
estimator's approximation to nonlinear PB, not molecular force-field accuracy.

## Literature basis

- [Limaye, Suvlu and Willard, Faraday Discussions (2024)](https://doi.org/10.1039/D3FD00114H):
  explicit-water layering and polarization can dominate double-layer potential;
  diffuse ionic screening does not validate the full microscopic potential.
- [Asthagiri et al., Chemical Science (2025)](https://doi.org/10.1039/D4SC08437C):
  rigid-water timestep errors affect equipartition, density and dielectric response.
  This motivates the 1 fs control; it does not itself qualify that timestep.
- [Grossfield et al., uncertainty assessment](https://pmc.ncbi.nlm.nih.gov/articles/PMC6286151/):
  correlation, sampling and model uncertainty must be distinguished.
- [Existing Debye assessment](../../../docs/namd_debye_assessment.md) documents
  the historical runtime, fits and their limits.

Assumed dielectric constants 78.3 and 100 are retained as sensitivity comparisons.
Neither is a measurement of this particular TIP3P/CUFIX electrolyte. Agreement
with either is not a universal acceptance threshold.

## Running and preserving evidence

```bash
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/campaign.py prepare
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/campaign.py run
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/analyze.py
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/audit.py
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/references.py
PYTHONPATH=. uv run python experiments/gold_interfaces/screening/report.py
```

Preparation refuses existing package paths. Every native config, checkpoint,
trajectory and run record is retained under `.development-artifacts/gold_screening_20260915`.
The pinned binary path is workstation-specific. Prior calibration assets are
required for preparation; these are research scripts, not portable production APIs.
The campaign retains the previous four-local-GPU-hour total ceiling, reserves time
for earlier work, and launches no remote jobs. No individual pilot exceeds 1 ns.
Charged manifests explicitly declare the override and are rejected by the normal
registered-neutral-model verifier; they cannot silently qualify as neutral IFF.
