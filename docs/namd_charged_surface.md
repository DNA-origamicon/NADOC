# Charged surface / electrolyte control

Status: UI, package preparation and initial native profiles verified, 2026-09-13; relaxation running. No Debye-length recovery has
been demonstrated by this change.

## Literature and scope

Lowe et al., *Calculation of surface potentials at the silica–water interface
using molecular dynamics: Challenges and opportunities*, JJAP 57, 04FM02 (2018),
used NAMD, TIP3P, 300 mM NaCl plus neutralizing Na+, 298.15 K NVT, 2 fs steps,
PME with 1 Å spacing and 10^-6 tolerance, and a 12 Å local interaction distance.
Their surface was INTERFACE-force-field crystalline silica, not an inert wall.
Reported negative charge magnitudes include 0.0413, 0.0825, 0.1238, 0.1650 and
0.3851 C/m². The lateral dimensions were 3.34076 × 3.48705 nm, initial water height
7.3 nm and final cell height 26.5 nm including vacuum. They used an EW3DC slab
correction. They ran 320 ns, analyzed the last 180 ns in three 60 ns windows,
and compared independently initialized counterions. Roughly 100 ns was needed
for millivolt-scale potential convergence.
[Primary author manuscript](https://eprints.soton.ac.uk/419931/1/SS17040_accepted.pdf).

These provide reference charge/salt values, **not a universal Debye benchmark**.
The current card is explicitly a surrogate: one periodically tiled, closed,
harmonically restrained carbon-like wall with two solvent-exposed faces, 3D PME
and fixed volume. It has neither silica chemistry, vacuum slab correction nor
constant-potential electrode polarization. It uses NADOC's existing water/ion
parameter stack and standard relaxation/production integrators. It must not be
reported as reproducing the paper's interfacial potential.

## User workflow

1. File → New Part; choose a name and save the blank `.nadoc` document.
2. Simulations → NAMD → Hard surface → Add surface charge → Settings.
   The support is enabled automatically. Its geometry is under Hard surface on → Settings.
3. Edit total sheet charge density (default -0.0413 C/m²) in the surface settings. Set reservoir padding
   (water margin) on each side to 3.65 nm in **Box and solvent**. Choose salt and
   temperature in that same card; the wizard uses these values. To match the reference
   conditions, choose Custom, NaCl 300 mM, magnesium 0, and 298.15 K. The existing
   charged-wall path requires NaCl-only conditions and rejects incompatible choices.
   Surface face, margin and clearance remain available. This mode sets nanopore
   diameter to zero, one layer and external E-field off.
4. Use New job to save a normal relaxation draft. Click its job row to render the surface;
   configuring a surface or automatically highlighting a new job does not render it. Run prepares its molecular
   package and executes the managed relaxation. Blank DNA is permitted.
5. Select the completed relaxation to create a production child with the normal
   production controls. Production inherits topology, wall charge and cell.
   Choose duration from convergence evidence; a completed short run is not a
   screening validation.

Charge density here is **total sheet charge / projected periodic area**. Both
faces share the screening cloud; it is not a per-face charge density. In a
symmetric cell, each side compensates approximately half the sheet charge.
Preparation rounds the requested total to the nearest integer elementary charge
and distributes it over wall sites to six-decimal PSF precision. The package
records requested and realized density, area, site count and exact charge map.
Na+ or Cl- explicitly balances negative or positive wall charge. Salt pair counts
use the placed-solvent volume; added salt is distinct from measured bulk salt.
Resume audits both ordinary and HMR PSFs against the saved charge map.

## Remaining barriers to literature reproduction

- The inert wall cannot reproduce silica-specific adsorption or water structure.
  Exact reproduction requires the referenced silica model and parameter assets.
- The periodic two-sided geometry is a membrane stack, not the paper's isolated
  one-sided slab. Adding vacuum alone is not the EW3DC correction. An isolated
  slab implementation needs its own energy/force and vacuum-size validation.
- Temperature defaults to the paper's 298.15 K and is inherited by production.
  The inherited standard protocol is not the paper's exact 2 fs / 320 ns schedule. Those differences are not hidden behind a “literature preset”.
- Native relaxation and production must be qualified in a user-opened test session
  before this new charge path is considered validated. Package preparation passed.
- Ion concentration, ionic charge and finite-slit screening diagnostics are now
  available in Graphs and Metrics. Microscopic potential reconstruction, bulk-region
  and bin/window sensitivity, independent seeds and uncertainty qualification are
  still required. Near-wall layering is not an exponential Debye fit.
- Compare diffuse screening against measured bulk ion concentration and the water
  model's dielectric response. A periodic stack at 300 mM is not automatically in
  the linear, isolated-surface Debye–Hückel regime.

No DNA geometry or linker parameters are changed by this feature.

## Prepared review artifact and verification

Open `workspace/NAMD_charged_wall_control.nadoc` and select job `6ed2945c805e`.
It was initially queued without launching; it is now running with periodic surface
profiles (see the native validation report below). The 69,834-atom package contains 3,772 wall sites,
21,932 TIP3P waters, 146 Na+ and 120 Cl-. Its 100.9798 nm² sheet carries -26e,
realizing -0.04125240145 C/m²; the final PSF charge audit passes (net ~8e-11e).
The managed NVT relaxation and standalone fast template use 298.15 K.
Production inheritance is unit-tested; no production trajectory is claimed.

Automated coverage includes either sign of wall charge and counterions, PSF/HMR
charge validation, blank-draft persistence, the final API-to-builder handoff,
production temperature inheritance, and a real File → New → charged-wall draft
browser gesture. The browser test caught and pinned an initial-autosave reset
that previously erased the user's surface setup.

Preparation-phase verification found unrelated blockers: missing BigO/smallO test fixtures
in the backend suite and an mrDNA job-list concurrent temporary-file rename race
(HTTP 500) in the app smoke gate. Full/native tests were deferred at that point because the
user-opened test session was expired; the subsequent validation report supersedes that deferral. The test guard also exposed native Chudoba
HMC tests incorrectly included in the fast suite; they now carry slow/oxdna scope.

Final fast checks: 5 charged-surface backend tests and 3 Playwright checks passed;
`just test-smart` selected FAST: 8,297 passed, 11 fixture-dependent failures,
109 skipped. `just smoke`: 22 passed, 1 failed on the mrDNA HTTP 500 described above.
`just test-frontend`: 6,277 tests passed across 404 files.
Touched Python files pass Ruff. Browser document/job artifacts were removed.

Test selector deferral (verbatim):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

## Surface profiles (2026-09-13)

Graphs and Metrics → Surface ions and screening opens an interactive popup with
editable parameters, Calculate, three graphs and Export JSON. Profiles persist per job and work during relaxation or
production. See [analysis method and monitor](../experiments/charged_surface/README.md).
The native monitoring record is separate from the earlier preparation-only checks
above. A neutralized midpoint and a good diagnostic fit do not certify equilibrium.

[Initial native profile validation and running monitor](../experiments/charged_surface/VALIDATION.md).

UI refinement verification: 6,282 frontend tests, 23 smoke checks and the dedicated
blank-document popup browser check passed. The browser check edits parameters,
calculates twice, verifies three replacement graphs and closes via Escape.
Ion transport now separates Generate from Display and PNG/CSV Export; generation
results and pending requests are scoped to the selected job. Main.js LOC delta: 0.


## Boundary assessment (2026-09-13)

For a supported PEG brush compressed by origami, the recommended target is one
solvent compartment above a substrate, periodic parallel to the substrate, with
controlled confinement along its normal. A second solvent compartment beneath a
macroscopic support is not required by that experiment. This is a recommendation,
not an implemented change to the current two-faced periodic sheet.

The current solvent on either side of the sheet connects across the normal
periodic boundary: these are not independently controlled ion reservoirs. Moving
the sheet to the cell edge merely translates the periodic system. A finite NVT
water compartment also does not impose a constant salt chemical potential.

Simply disabling normal periodicity leaves an exposed liquid interface unless a
far-side confining boundary is supplied. Specify a distant neutral repulsive cap
(or a deliberately modeled second electrode), avoid overlap of its perturbed
region with the brush/double layer, and establish bulk water density and measured
bulk ion concentration between them. The neutral cap has its own layering and
pressure effects; it is not an ideal bulk boundary.

NAMD documents MSM for semi-periodic electrostatics and recommends confinement
for non-periodic directions. Its documented MSM virial limitation rules out using
the ordinary pressure barostat for this path. Standard 3D PME cannot become an
isolated slab simply by disabling coordinate wrapping. A PME alternative needs
vacuum separation plus a validated slab correction, with convergence against cell
height. The existing pipeline implements neither alternative. GPU-resident
compatibility and performance of the chosen electrostatics/confinement combination
must be qualified on the installed binary; existing PME performance is not proof
of MSM support.

Sources: [NAMD electrostatics](https://www.ks.uiuc.edu/Research/namd/3.0/ug/node25.html),
[NAMD GPU-resident support](https://www.ks.uiuc.edu/Research/namd/3.0/ug/node102.html),
and the Lowe manuscript cited above for an EW3DC slab precedent.

Before a one-sided mode is exposed, implement and validate:

- Solvation and ion placement only in the accessible compartment, including a
  far boundary and explicit counterion neutrality.
- Surface charge normalization: the current symmetric two-face model screens
  approximately half its total sheet charge on each side. The same numerical
  sheet charge in a one-sided model is not the same per-interface condition.
- Electrostatics forces, residual bulk field, lateral/normal size convergence,
  wall stability and GPU-resident execution compatibility.
- One-sided profile integration and accessible-volume bins; retain finite-size
  and measured-bulk checks instead of assuming an exponential near the wall.
- For later applied-field experiments, specify blocking versus conducting
  boundaries: a closed cell under a normal field polarizes and can deplete ions;
  it does not supply a sustained DC current from an external reservoir.

Keep the existing periodic sheet as a symmetric screening control while qualifying
this supported-brush geometry. No boundary, molecular placement or saved job was
changed by this assessment.
