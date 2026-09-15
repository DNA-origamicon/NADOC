# Two-electrode setup

NAMD → Hard surface → **Two-electrode system** → **Settings**.
This mode has independent geometry and charge controls; it does not reuse hidden
single-wall settings. Enabling it clears Hard surface on, Add surface charge,
Graphene nanopore. Enabling any of those switches back. PEG coating can coexist
with two electrodes and attaches to the working wall. Values are retained and setup presets capture the new mode.

| Setting | Default | Meaning |
| --- | --- | --- |
| Model | Abstract fixed charge | Restrained repulsive walls; no metallic response |
| Normal | Y | Working-to-counter direction; intended lateral periodicity |
| Gap | 10 nm | Inner-face separation, excluding wall thickness |
| Width / depth | 10 / 10 nm | Equal projected lateral spans of both walls |
| Working charge | −0.0413 C/m² | Signed density on the working interface |
| Counter charge | +0.0413 C/m² | Derived opposite density; not independently editable |

For normal X, lateral width/depth are Y/Z; for Y they are X/Z; for Z they are X/Y.
Zero charge is allowed as a neutral control. Dimensions are bounded at 2–200 nm
and charge at ±0.5 C/m² for setup validation, not as qualified production limits.
Salt and temperature are set in Box and solvent. Potential is not an alternative input:
fixed density does not specify voltage without a model of the interface response.
The 10 nm gap is a starting control for bare electrodes at 300 mM NaCl, not a
universal recommendation or a preset override of salt. Compare against 15 nm and
verify a bulk plateau; add space for PEG and DNA before introducing them.

## Electrode protocol and qualification

The wizard now defaults to **Electrode relaxation (fixed cell)** when this mode is
enabled. It prepares DNA-free, DNA, PEG and combined compartments through the shared
NAMD relaxation machinery, with separate bulk NPT calibration and confined NVT
stages. Existing jobs retain their saved configuration; attempting to run an older
protocol with this setup enabled presents a warning with Cancel/Continue.
See [the protocol and its current limits](namd_electrode_protocol.md).

Native force/energy checks and managed GPU execution have been exercised for the
abstract solvent-only model, including retained 40 ns runs. The
[screening assessment](namd_debye_assessment.md) separates this evidence from
timestep, dielectric, finite-size and equilibration uncertainties. Package tests
and browser checks alone do not establish physical validity. Explicit neutral gold
has a separate [qualification path](namd_gold_model_selection.md); it is not selected
by these abstract-wall controls. Constant-potential gold remains a
[proposed electrostatics implementation](namd_constant_potential_design.md).

The two-plane schematic and signed markers remain setup-only. Their appearance is
not evidence that a selected older job contains electrodes.

## Gold versus an abstract control

Start with abstract fixed-charge walls to qualify geometry, ion counts, screening
and finite-size effects. Gold additionally needs validated Au–water/ion interactions
and an electrode electronic-response model. Fixed charges on Au atoms do not model
a voltage-controlled metal. Constant-potential electrode charges respond to nearby
ions and molecular configurations; gold-specific adsorption can substantially alter
its compact layer. Do not convert a requested voltage into a fixed density using
an assumed universal capacitance.

Sources:
- [Constant-potential electrode algorithm](https://doi.org/10.1063/5.0171502)
- [Electronic response and charge inversion at polarized gold](https://pubmed.ncbi.nlm.nih.gov/39313472/)
- [Validated periodic alternatives to slab electrostatics](https://arxiv.org/abs/2201.12963)

These sources motivate the staged model choice; no gold model or constant-potential
solver is implemented by this UI change.


## Initial toggle verification (before the schematic preview)

6,394 frontend tests passed. Three focused browser checks passed, exercising
matching collapsible sections, mutual exclusion in both directions, signed derived
countercharge, blocked New job, no draft rendering, and workspace preset restore.
The expanded section screenshot was inspected after correcting a clipped model
label. All 23 smoke checks passed. Test documents and exact owned preset IDs were
removed by failure-safe teardown and absence verified. No native simulations ran.
No backend behavior changed. Repository lint retains two pre-existing unused-symbol
errors (`seq` in routes_oxdna.py, `Path` in test_oxdna_peg.py); diff whitespace checks
pass. The known mrDNA job-file rename race still appears in backend logs.
Main.js line delta for this feature: 0.


## Slab implementation and qualification preparation (2026-09-13)

`backend/core/namd_slab.py` implements the neutral-cell Yeh–Berkowitz correction:
U = 2π k M_n² / V and F_i,n = −4π k q_i M_n / V, in Å/e/kcal mol⁻¹ units,
with NAMD's k = 332.0636 and dielectric 1 for explicit solvent. The Tcl callback
includes all PSF charges (water, ions and both walls), plus one-sided harmonic
confinement outside the liquid compartment. Net-charged cells are rejected.
Coordinates are not wrapped along the normal; the cell is fixed-volume and no
barostat is enabled. This is vacuum-padded EW3DC, not exact 2D Ewald.

The installed NAMD Git-2025-12-04 source explicitly rejects MSM in GPU-resident
mode (`SimParameters.C`, MSMOn feature guard). Tcl forces have a supported path
with recent Tcl, but the coordinate/force transfers and vacuum cell must be
qualified on the installed executable. No native performance is assumed.

`backend/core/namd_two_electrode_package.py` now builds an isolated DNA-free
control using existing TIP3P/CUFIX assets, two equal-area NGRC wall grids with
opposite quantized charges, harmonic site restraints, a single solvent compartment
and 3× normal cell height. These are carbon-like surrogate sites with the existing
wall LJ model, not gold. The continuous confinement is a separate soft barrier.
No existing DNA, PEG or production placement has changed.

A real GROMACS solvation/preparation run produced:
`workspace/two_electrode_qualification_20260913/`:

- 10 × 10 nm walls, Y normal, 10 nm liquid gap; 10 × 30 × 10 nm padded cell.
- 2,500 sites per wall; −26e/+26e, realized ±0.041656592484 C/m².
- 29,960 TIP3P waters, 164 Na⁺ and 164 Cl⁻; 95,208 atoms total, net charge zero.
- Ordinary topology, two-wall restraint PDB, `slab.tcl`, manifest and offload/resident
  configurations. This preparation is not a successful native NAMD run.

Native qualification is implemented in `experiments/two_electrodes/qualify.py`.
It checks native correction energy/forces against the analytic result, offload vs
resident forces, vacuum factors 3/4/5 on identical coordinates, and short 2 fs
minimization/dynamics in both modes. It saves every config/log plus a JSON verdict.
Failure cannot set the qualified flag. It does not establish Debye convergence,
4 fs stability, metallic polarization, or PEG/DNA readiness.

After the user opens `just test-session`, run from the repository root:

```bash
scripts/test_guard.sh two-electrode-qualification 0 1 -- uv run python -m experiments.two_electrodes.qualify --output workspace/two_electrode_qualification_20260913 --existing
```

Native execution remains pending: the test-session marker was expired during
implementation. Managed job creation, resume/production integration and per-face
trajectory metrics remain blocked until native qualification; this is not yet a
fully executable two-electrode workflow from the UI.

References:
[Yeh–Berkowitz correction](https://doi.org/10.1063/1.479595),
[NAMD GPU-resident Tcl support and transfer overhead](https://www.ks.uiuc.edu/Research/namd/3.0/ug/node102.html).


Latest verification: all 6,395 frontend tests and three focused browser checks pass.
The framed scene screenshot was inspected: two planes, external signed markers,
box outline, live dimension changes, and toggle-off cleanup. All 23 smoke checks
pass; the existing mrDNA job-file rename race still appears in server logs.
Browser-created documents/presets were removed and absence verified. Main.js gains
only one import and one scene initializer (+2 lines).

FAST backend: 8,319 passed, 110 skipped, nine existing missing BigO/smallO fixture
failures; no timing violations. The seven new backend checks cover neutral charge
maps, finite-difference energy/force agreement and translation invariance, generated
Tcl execution against the analytic force, confinement, package charge/coordinate
integrity, and native-force file parsing. New Python files pass Ruff; repository
lint retains its two existing unused-symbol errors. Diff whitespace checks pass.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
