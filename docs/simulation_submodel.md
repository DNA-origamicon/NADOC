# Submodel selection and oxDNA boundary-treatment review

2026-11-10. Normal local oxDNA Run now extracts and simulates the boxed region
plus the fixed shell. The source design and full job topology remain intact;
a full-order display projection restores omitted context for existing visualizers.
NAMD now prepares cropped explicit-solvent DNA packages with a uniformly restrained shell
for relaxation and production. The dated experiments below are historical evidence,
not descriptions of the current managed execution path.

2026-11-12: the isolated [24hb_2xT shell-calibration framework](../experiments/namd_shell_calibration/README.md)
maps the saved RunPod control selection to archived whole-model production,
profiles box-frame covariance and extra-base observables, and provides tentative
scalar stiffness updates from matched profile pairs. It does not launch engines,
modify managed inputs, or install calibrated restraints. Initial sparse sampling
revealed substantial preparation/reference shape mismatch and different recorded
ion recipes; calibration remains unqualified. The user's local NAMD job stays
undisturbed; only bounded offline analysis and small synthetic tests were run.

The NAMD and oxDNA cards also provide **Define submodel from selection**, directly
below Define/Edit submodel, using the shared `btn btn--sm` styling. Select DNA
bases (including crossover inserts), ends, bonds, domains, strands, crossovers,
overhangs, extensions, or clusters, then derive an editable axis-aligned box with
1 nm padding around the selected positions. Assembly instances, nested groups,
and selected instance clusters use their live world transforms. The surrounding
shell remains separate and retains its existing value. Empty/unavailable
selections cannot silently replace a region with a default box. Immutable NAMD
jobs retain their saved inputs; redefining their region starts a fresh setup.
This action captures bounds once; it does not yet persist base identities as an
independent simulation membership definition. Other bases inside the resulting
box are included by the existing preparation rules.

## Launch estimates and confirmations (2026-11-10)

Duration alone never opens a launch confirmation: relaxation stages can be skip
accelerated. The shared NAMD/oxDNA confirmation now triggers only for predicted
output above 10 GiB, titled “Large output”. RAM/VRAM admission and low-disk checks
remain independent. ETA is still descriptive wherever displayed.

NAMD relaxation captures and saves the selected submodel before either estimator
runs. Sizing uses the preparation crop, including whole residues and bonded
support; solvent, ions and fixed-shell buffers count toward resource budgets.
Cache identity includes box pose and shell width. Submodels quote offload, and
preparation RAM also budgets the full source topology transient. Production
forecasts use the prepared PSF/cell and expose saved-package memory ceilings;
actual production admission is checked again at launch.

Read-only R1 comparison: full 505,099 vs cropped 172,522 solvated atom upper bound,
with cropped RAM 1,705 MiB, VRAM 1,171 MiB and output 1.592 GiB. These are planning
budgets, not measured usage; no dynamics were run for this estimator check.

## NAMD submodels (2026-11-10)

New packages use a **3 nm shell by default** and **uniform k=0.1 kcal/mol/Å²**
on mobile shell DNA heavy atoms (native NAMD convention U=k·r²). The outer
0.3 nm, measured at the nucleotide P/C1′ representative, and whole retained
residues participating in cut bonded terms remain fixed. The core is free in
production; all water and ions remain mobile. This is the uniform treatment
selected after the matched-start gradient comparison, not a convergence claim.

The version-2 `submodel.json` records fixed and restrained indices and the
boundary recipe. Existing version-1 jobs retain their entirely fixed shell,
including continuations. Relaxation keeps its scheduled core restraints, while
shell heavy-atom coefficients stay at 0.1 independently of stage scaling.
Production shell references are reset to the parent's native checkpoint;
checkpoint coordinates and velocity continuation are preserved. NVT and GPU
offload remain required, with 4 fs HMR and 1 ps⁻¹ production damping.


Managed uniform-shell verification: a new central-box `Submodel_tests.nadoc`
relaxation completed minimization plus all 21 shortened stages (1,000 steps
at 2 fs each), then a separate 5,000-step production child completed at **4 fs
HMR**, 1 ps⁻¹. The emitted markers contain 3,948 restrained heavy shell atoms,
1,458 fixed boundary atoms, and 5,363 unrestrained production core atoms;
all solvent markers are zero. Native fixed-atom displacement was exactly zero.
The isolated evidence is `.development-artifacts/namd-uniform-default-20261110/`.
An initial production request inherited 2 fs from relaxation; the qualified
production request explicitly pins 4 fs/HMR. This is workflow verification,
not an equilibrated trajectory or another full-reference comparison.

Browser verification exercised job creation, saved box/shell restoration, native
playback, RMSF, occupancy/density, T–T propensity, water/ions and periodic-box
views. Water is deliberately available in Display MD snapshots, not full
trajectory playback. Nanopore-specific views are disabled for this DNA-only job.
Visual inspection found and fixed atomistic scalar-map cloning dropping the
zero-value fallback for unscored bases. The follow-up checked all 8,349 rendered
heavy-atom colors against the map and visually confirmed the corrected view.
Browser copies/captures were removed; source design bytes were unchanged.
Final software checks: FAST 20,691 passed / 90 skipped, with the pre-existing
CPD packet-contract failure; frontend 10,192 passed / one skipped; smoke 25
passed; lint passed. FULL remains deferred by the test-session gate. The FAST
suite exceeded its aggregate backstop with zero individual timing violations.

New NAMD production requests default to **1 ps⁻¹**, including submodels and
continuations of a job that explicitly used another coefficient. Explicit new
production overrides remain supported; historical jobs retain their original
protocol. Relaxation-stage damping is unchanged.

Changing a completed/preparing job's box or shell now starts a fresh setup and
clears its job selection, preserving the historical job's immutable region.
Creating a NAMD job saves its box atomically with the creation request; the UI
adopts that saved region without an unnecessary second PUT. Visibility changes
can still be saved on completed jobs. Shell inputs retain in-progress edits
through unrelated sidebar refreshes; committing the value saves the intended
radius rather than a value repainted from the old job.

The submodel controls sit at the bottom of the Box / Box and solvent card.
**Use as zoom volume** is enabled when a box is loaded and copies its inner bounds
and rotation into the existing Zoom Volume inset (excluding the shell). The
zoom is an independent snapshot; click again to update it after editing the box.

The submodel controls now open only after clicking Define/Edit submodel; guidance
is on the button's hover tooltip. When a NAMD region exists, the viewport hides
the larger solvent-cell/margin overlay and labels the oriented mobile box instead.
The surrounding-shell preview remains available. This changes visualization, not the
actual solvent cell used by the engine.

The user-requested completed trial copies are now in the normal workspace job list:

| Source | Relaxation job | Production child |
| --- | --- | --- |
| `duplex.nadoc` | `0200c9e048cc` | `de6b538207cb` |
| `Submodel_tests.nadoc` | `063b14bd09aa` | `bb93e0db63bd` |

The published copies preserve the source snapshots, native inputs, trajectories
and parent links. Their import receipts identify the original isolated evidence;
known preparation settings are restored in job metadata so the cards show the
actual custom 150 mM NaCl, zero Mg and 2 nm solvent padding.

Both trials used explicit TIP3P water, CHARMM DNA parameters, periodic PME and
300 K NVT. The duplex contains 45,144 waters, 165 sodium and 123 chloride ions;
the specimen contains 41,933 waters, 307 sodium and 115 chloride ions. The ion
imbalance neutralizes the retained DNA. Inspection of the fixed-atom marker
confirms **no water or ions were fixed**, even inside the geometric shell. Only
DNA outside the mobile region was fixed. Mobile non-hydrogen atoms use Langevin
damping of 5 ps⁻¹ during relaxation and 1 ps⁻¹ during production.

A restrained, thermostatted DNA buffer is a sensible next comparison against
the fixed shell. Harmonic restraints allow limited mechanical response; Langevin
friction plus noise exchanges heat with a bath. Friction alone neither anchors
the boundary nor repairs steric clashes. A graded buffer with an outer fixed
layer must preserve complete bonded support for every newly mobile atom. Compare
shell widths, base pairing, local RMSF, boundary strain, temperature and solvent
density against full-model runs before selecting defaults. The classic
[Brooks–Brünger–Karplus stochastic-boundary study](https://doi.org/10.1002/bip.360240509)
supports harmonically constrained Langevin buffer atoms in a protein example;
it does not establish DNA-specific parameters. NAMD supports
[per-atom Langevin coefficients](https://www.ks.uiuc.edu/Research/namd/cvs/ug/node38.html).
The published trials retain their original fixed-shell protocol; no buffered-shell
simulation has yet been qualified.

The subsequent [central-shell damping pilot](../experiments/namd_submodel_damping/README.md)
completed ten native 50 ps production runs: two seeds each for full, fixed-shell,
and restrained buffers at 0.1/1/5 ps⁻¹. All used 4 fs HMR production. A 1 ps⁻¹
buffer brought core RMSF closer to full (0.684 vs 0.712 Å; fixed shell 0.605 Å),
but did not restore full-reference pairing. RMSD still drifted, and the full and
crop preparations differed before production. This is a feasibility pilot, not
a qualified replacement for the fixed-shell default. See the protocol, seed
ranges, hydration/bond/temperature checks, pressure caveat and retained evidence
in that report.

The [3 nm graded-boundary follow-up](../experiments/namd_submodel_gradient/README.md)
starts cropped DNA from the same full-relax checkpoint and compares fixed,
uniform, and smoothstep restraints at 1 ps⁻¹ damping. Six new native runs passed.
The gradient produces decreasing shell motion toward its fixed outer layer,
with core RMSF close to full; pairing and RMSD remain imperfect. These isolated
results motivated the user-selected uniform-shell default; they do not establish
a minimum shell width. The report includes spatial profiles, matched-start verification,
resource measurements, seed ranges, and the retained native evidence.

UI/publication follow-up: 10,187 frontend tests passed (883 files, one skipped),
16 focused UI/overlay tests passed, all 25 smoke checks passed, and lint passed.
The real browser check verified source-filtered job rows, initially collapsed
controls, the tooltip, box/shell editing and trajectory playback; final screenshots
were inspected. Published snapshots and topology files match the original trials.
Temporary publication/browser workspaces and isolated bridge credentials were
removed. `main.js` LOC delta remains zero. Evidence:
`.development-artifacts/namd-submodel-20261110/controls-publication-verification.json`.

Define the region in **Box and solvent → Define submodel**. The existing box/shell
visibility toggle also controls the NAMD region. `CreateJobRequest.submodel` accepts
the same oriented-box object as the UI; `PUT /api/md/jobs/{id}/submodel` supports
headless edits. A geometry change on an unstarted prepared job returns it to draft
and discards only its generated inputs, preserving the original Design snapshot.
Run prepares it again with the saved region. Once started, the region is frozen;
visibility remains editable. Production inherits the exact topology and shell.
Older jobs with display-only boxes cannot silently run their full prepared
topology: Start rejects a selection/package mismatch and requests a newly
prepared relaxation. Changing the region of an already-run full-model NAMD job
is not supported by this initial implementation.

Selection operates on the full psfgen CHARMM topology, before solvation:

- A nucleotide moves when its phosphate is inside the box; a phosphate-less
  terminal nucleotide uses C1′. All atoms of that nucleotide move together.
- A nucleotide joins the surrounding shell when any atom is within the shell distance.
  Every residue supporting a bond, angle, dihedral or improper touching a mobile
  atom is also retained, including with a zero shell.
- Cuts occur only among fixed atoms. No artificial caps, charge edits or molecular
  geometry changes are introduced. The full source Design and source PSF/PDB
  remain available, alongside source-index and residue maps in `submodel.json`.
- Water and ions are added around the retained topology and remain mobile.
  NAMD uses native `fixedAtoms`, a fixed-volume cell and CPU/GPU offload.
  GPU-resident execution is incompatible with native fixed atoms.
- Initial support is explicit-solvent DNA without additional anchors or surfaces.
  Unsupported material/protocol combinations fail explicitly. Prepared RAM/VRAM
  admission counts all retained atoms and solvent, plus fixed-mask buffers; fixed
  atoms are not deducted from neighbor/topology memory. Preparation reservation
  remains conservative because constructing the full source topology still costs RAM.

The fixed-atom and constant-pressure restrictions follow the
[NAMD user guide](https://www.ks.uiuc.edu/Research/namd/3.0/ug.pdf).
These are design-exploration boundary conditions, not an equilibrium model of the
whole origami. Shell-size convergence and agreement with a full simulation remain
separate scientific validation tasks.

Native trials used the installed December-2025 NAMD build, four CPU threads and
CUDA offload. Each ran minimization, 10,000 relaxation steps at 2 fs, and a separate
5,000-step production at 4 fs with HMR and rigid hydrogen bonds:

| Source | Full DNA atoms | Retained DNA atoms | Mobile DNA atoms | Retained / mobile nucleotides | Shell |
| --- | ---: | ---: | ---: | ---: | ---: |
| `duplex.nadoc` | 2,665 | 1,334 | 920 | 42 / 29 | 1 nm |
| `Submodel_tests.nadoc` | 35,971 | 6,157 | 3,339 | 194 / 105 | 2 nm |

Both trials completed. Fixed-shell maximum displacement was below 2×10⁻¹⁴ Å;
mobile-atom RMS displacement during production was 1.36 Å and 1.74 Å respectively.
These short runs establish execution, not equilibration. The second source uses
the saved box previously exercised with oxDNA. Selection uses phosphate sites rather than oxDNA particle centers, so retained
and mobile counts need not match oxDNA.

Normal API preparation, box-edit rebuilding, production creation and managed
production execution were also exercised. Both parents and production children
passed trajectory, atomistic-frame and flexibility-map API checks. Canonical PSF
term packing is tested with MDAnalysis as well as the native engine: an arbitrary
whitespace layout accepted by NAMD is insufficient for the visualization reader.
The browser check restores each job's box and shell, exercises the existing
visibility toggle, and plays its atomistic trajectory. Side-view inspection
exposed and corrected the solvent-overlay center: cropped packages now record
their cell center in source-design coordinates and show the fixed-volume label.
The read-only test fixture redirects only file loading to the diagnostic load
endpoint; job, region, display and trajectory requests use their real endpoints.
Original source files are unchanged. Native trials and browser copies are
isolated from user jobs; browser workspaces are removed on success or failure.
Evidence is in `.development-artifacts/namd-submodel-20261110/`, including native
logs, motion measurements, API results, source hashes and lossless PSF reflow checks.

Initial integration validation: 9 NAMD-submodel tests, 13 selection tests and 6 sequence-guard tests
passed. The frontend suite passed 883 files / 10,185 tests (one skipped); smoke
passed all 25 checks; lint passed. `main.js` LOC delta is zero. `test-smart`
selected `FAST  (fast suite only)`: 20,681 passed, 90 skipped, one unrelated
failure in `test_part_transform_frontend_contract.py`'s CPD case. The aggregate
190-second runtime exceeded the 90-second backstop, with no per-test violators;
timing triage found distributed suite growth, not a new submodel bottleneck.
No test limits or classifications were changed. The initial sequence-start
regression was corrected and its six-test file rerun successfully. Final
focused checks also cover preservation of older boxes during deferred sequence
preparation. Broad-suite deferral, verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Managed CPU execution and compute budgets

Install the isolated adapter beside the existing engine with
`uv run python -m scripts.build_oxdna_submodel`. Define a box before creating a
relaxation job, or edit the Box card on a queued job, then Run. Run waits for box
persistence. A production child inherits the parent's selection and frozen mobile
particle identities; an explicit changed selection is planned against its starting
pose. A completed full relaxation can also seed a cropped production job.
Only local DNA2 MC/MD is currently supported. Pending stages use CPU and the
per-particle Brownian thermostat. Unsupported hybrid/remote jobs and non-pair
external forces fail explicitly. The installed full-system engine is unchanged.

The native stage lives in `stage/submodel/`, with extraction indices, source
hashes, effective input and execution receipts. Only retained particles enter the
native topology; only boxed particles move. Direct backbone neighbours are
retained even at shell radius zero. Fixed poses and momenta are checked before
frames are published. Pair-retention gates count designed pairs touching the
mobile region. Failed relaxation remains failed; the existing bounded retry
policy applies. Stop/resume keeps the original region, and changing a partial
job's region requires a copy. Visibility remains adjustable while running.

Native output is scattered into the original source order for display,
trajectories, flexibility, strain, deviation, occupancy and atomistic rendering.
Omitted positions are static context, not simulated particles. Their zero
fluctuations are imposed; whole-context maps must not be interpreted as full
system sampling. Fixed context anchors alignment to avoid artificial motion.
Native potential energy belongs to the cropped system only.

**Fixed-shell FENE correction (2026-11-10):** user production job `52d968f5e2cc`
failed at initialization on native bond 129–130, source particles 720–721
(`h_XY_0_3`, bp 76 FORWARD → `h_XY_1_3`, bp 76 REVERSE). Both are fixed.
Its backbone-site distance, 1.037145 oxDNA units, exceeds the uncapped FENE
upper limit of 1.0064. Capped relaxation could not shorten a fixed–fixed bond;
removing the force cap at production exposed this otherwise constant term.
The extraction is exact: native particle rows equal their parent source rows.

Installer version 2 adds the `SubmodelDNA2` interaction plugin to MD, MC and
DNAnalysis. It removes **only fixed–fixed backbone-spring energy**, a constant
with respect to every mobile degree of freedom. It preserves topology, terminal
charges, stacking and all mobile–mobile/mobile–fixed interactions. Upstream
bounds remain enforced for bonds touching mobile particles; a negative control
making particle 129 mobile still fails explicitly. Reported energy has a different
constant offset from earlier runs and must not be compared as an absolute energy
across full/submodel systems or changed masks.

The exact failed input completed 10,000 steps in native and managed checks;
100 saved frames preserved all 78 fixed poses/momenta, the managed pairing gate
passed at 50%, and display returned 1,134 source positions. All-mobile and cropped
MD plus masked MC controls had exactly identical particle rows before/after;
the cropped energy shift was constant. These are startup/regression checks, not
validation of the requested five-million-step sampling run. Original jobs remain
unchanged. Execution receipts now record the binary/plugin and hashes **before**
launch, including failed launches; the error-log API resolves that adapter instead
of incorrectly reporting the standard executable. Evidence:
`.development-artifacts/oxdna-submodel-fixed-bond-20261110/`.

Correction validation: 13 focused runtime tests passed; `just lint` passed.
`just test-smart` chose FAST: 20,673 passed, 90 skipped, one pre-existing CPD
native-packet frontend-contract failure. Its 199 s aggregate guard report had
zero per-test violators; slow-test triage did not identify a test to reclassify.
The FULL deferral quoted below still applies. The running app's error-log endpoint
was checked directly and now identifies the installed CPU submodel adapter.


Three matched 20,000-step CPU trials per case on Ryzen 9 9950X:

| Case | Native/mobile particles | Median wall time | Steps/s | Maximum native RSS |
| --- | ---: | ---: | ---: | ---: |
| Full, all mobile | 1134 / 1134 | 42.26 s | 473 | 10.30 MiB |
| Full, same mobile mask | 1134 / 102 | 60.91 s | 328 | 9.98 MiB |
| Cropped, same mobile mask | 182 / 102 | 6.09 s | 3284 | 8.13 MiB |

Cropping is **6.94× faster than the full mobile run**, and **10× faster than
holding the same region mobile while retaining every particle**. Native RSS
falls about 21% versus the full mobile case; fixed engine overhead dominates at
these sizes. Initialization and final output are included. The fixed/full case
is not a universal scaling baseline: evolving contacts and geometry matter.
Evidence: `.development-artifacts/oxdna-submodel-benchmark-20261110/`.
The benchmark uses the historical 102-base mask. The managed planner uses the
actual aligned backbone display and selects 104 mobile bases for that saved
specimen box, with the same 182 retained particles.

The Box card reports mobile/fixed/source counts, MD runtime, host RAM budget and
zero **simulation** VRAM. CPU throughput uses the measured constrained anchors
(182–1134 particles); live measured throughput supersedes the reference estimate.
Outside that range it is extrapolation, not a guarantee. MC ETA waits for MC
samples. The host budget includes a conservative 512 MiB worker allowance,
twice the native RSS estimate, and source-sized context storage; it is not a
measurement of the full application. Viewer memory is additional. Output budgets
include both cropped native frames and full-context frames; cropping does not
promise proportional trajectory disk savings. Frequent full-context output can
also dominate end-to-end time for very small submodels. No remote/GPU cost quotation is
claimed for this CPU-only path.

An independent 60-particle duplex managed relaxation measured 12,163 MD steps/s
against the initial estimate of 13,274 (about 9% runtime underprediction), then
completed equilibration with 100% mobile-pair retention. Cropped production after
that relaxation and after the pre-existing full relaxation both completed and
returned all 84 source display positions through the normal visualization APIs.
A real stop/resume check banked 2,000 steps and completed the remaining 198,000,
with the same extraction receipt and archived partial native/display trajectories.
The adapter exempts fixed particles from the upstream nonzero-angular-momentum
restart check, while retaining mobile-particle validation. Its fresh all-mobile
and cropped 1,000-step controls are byte-identical to the benchmark adapter's
configuration and energy outputs.

The real-app check activated all seven visualization modes and inspected the
rendered box/shell, counts/budget and flexibility map. Its disposable workspace
was removed; evidence is under
`.development-artifacts/oxdna-submodel-managed-centered-20261110/` (including
`duplex-box.png`, `duplex-mode-flex.png`, `continuation-checks.json`, and
`resume-check.json`). Original duplex/specimen files and the original specimen
job hashes remain unchanged.

These short checks establish workflow operation, not equilibrium or boundary
convergence. The difficult origami specimen's earlier pairing failures remain
scientific limitations; speed does not establish physical validity.


## Validation of managed integration (2026-11-10)

- Native: three benchmark repetitions per case; managed duplex relaxation;
  cropped production from both a submodel and an existing full relaxation;
  stop/resume (2,000 + 198,000 steps); rebuilt-adapter equivalence controls.
- App: real persisted job, rendered box/shell and budget, all seven visualization
  modes activated; atomistic and surface endpoints also returned ready outputs.
  Browser scratch cleanup and original source/job hash checks passed.
- `just test-frontend`: **10,185 passed, 1 skipped** (883 files).
- Focused backend: runtime **11 passed**, selection **13 passed**, existing
  relaxation/runner suite **258 passed, 11 slow tests deselected**. Lint passed.
- `just test-smart`: decision **FAST**; **20,664 passed, 90 skipped, 3 failed**.
  The submodel fixture failure was corrected and its focused file passed.
  The remaining failures are the CPD native-packet frontend contract and the
  ds-linker part-capture budget test, outside this subsystem. This is not a clean
  broad-suite pass. The aggregate guard reported 207 s with no per-test budget
  violators; triage found distributed suite cost, so no arbitrary tests were moved.

Selector deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

Logs: `.development-artifacts/oxdna-submodel-benchmark-20261110/`.

## UI contract

oxDNA has a Box card; NAMD uses Box and solvent. Define submodel creates one
oriented box using the actual View Volumes editor: edge picking, Move/Resize/
Rotate, world-space translation, local-space scaling/rotation, Tab cycling and
Escape deselection. Delete removes the selection. Bounds are in the scene's nm
frame; rotation is an XYZW unit quaternion about the box center. This is not the
periodic simulation cell.

Before job creation, the selection is a document- and engine-specific session
draft. Normal relaxation and production creation copy the current selection to
the new job. Later gestures save immediately to that job. Selecting another job
loads its own box; selecting a job without a box clears the displayed selection.
Saved selections survive reload. Drafts without a job do not survive browser reload.
The box payload accepts `shell_nm` (default 3, range 0–1000 nm) and `visible`
(default true); these can also be set headlessly through the same PUT endpoint.
NAMD display visibility follows its existing box/solvent master switch.
Part and assembly hosts use the same editor and their respective scene bounds.

`GET/PUT /api/{oxdna|md}/jobs/{id}/submodel` reads/writes the job-owned
`submodel_selection.json` file atomically. Keeping this UI record separate from
`job.json` avoids background runner writes overwriting it. No design view-volume
or molecular history is modified. The record deliberately does not claim to be
an executed simulation configuration. The card explicitly states that Run is not
restricted by this box yet.

## What the sources support

1. **General relaxation guidance exists, but is not a frozen-patch protocol.**
   The upstream guide describes 10²–10⁴ CPU Monte Carlo steps, commonly 1,000,
   with translation/rotation proposals of 0.1 and backbone force limits 5 and 10
   in reduced units. Its MD example uses `dt=0.002`, Bussi thermostat,
   `bussi_tau=1000`, `newtonian_steps=53`, and roughly 10⁶ steps. The guide says
   the required duration is structure-dependent. These are startup examples,
   not validated defaults for short overhang or crossover submodels.
   [Upstream relaxation guide](https://lorenzo-rovigatti.github.io/oxDNA/relaxation.html).

2. **Stationary harmonic traps can restrain boundary nucleotide positions.**
   The documented `trap` force uses `pos0`, `stiff`, and `rate=0`; its example
   stiffness is 1 in oxDNA units. The force acts on the nucleotide center of
   mass. Thus a positional trap is neither exact freezing nor an orientation
   constraint. The documentation warns that external forces require care with
   timestep and thermostat settings. Mutual traps are pair-distance restraints;
   both directed forces must be supplied to make them reciprocal. They are useful
   during relaxation but cannot substitute for a frozen surrounding origami.
   [Upstream external forces](https://lorenzo-rovigatti.github.io/oxDNA/forces.html).

3. **Published practical protocols support restrained relaxation.**
   Haggenmueller et al., *How We Simulate DNA Origami* (2025), describe the
   import–relaxation–equilibration–analysis workflow and recommend mutual traps
   to retain intended pairing during initial relaxation. Their discussion of
   overlaps and overstretched bonds is directly relevant to a local design check.
   It does not establish a universal shell width, frozen-boundary prescription,
   or sufficient run length for an arbitrary spatial crop.
   [Tutorial](https://pmc.ncbi.nlm.nih.gov/articles/PMC12182891/).

4. **Mechanical-boundary precedents exist, with application-specific parameters.**
   Madhvacharyula et al., *Realizing mechanical frustration at the nanoscale
   using DNA origami* (2025), remove actuating edges while retaining short
   paired residues and impose loading with harmonic traps. The reported trap
   stiffness is 0.1 reduced units (about 5.7 pN/nm). This is evidence for
   controlled boundary loading, not proof that the same stiffness immobilizes
   an arbitrary origami patch.
   [Paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12134127/).

The targeted search covered upstream input/force/relaxation documentation,
origami simulation tutorials, and frozen/subset/subsystem and restrained-boundary
queries. I did not identify a general validated oxDNA protocol for the precise
workflow requested. This is a scoped search result, not a claim that none exists.

## Proposed next implementation, not yet executed

First separate two approximations: retain the whole structure but integrate only
the selected nucleotides, or extract a smaller system with an explicitly defined
boundary shell. The former preserves connectivity and external steric context but
may save less force-computation time; the latter needs a defensible policy for
cut bonds and omitted interactions. Neither should silently sever scaffold or
staple bonds at the selection-box faces.

For an exact frozen environment, both translation and orientation must remain
fixed, including thermostat and minimizer updates. Verify that capability in the
installed CPU/CUDA implementation before choosing it. A trap-based alternative
should be called restrained, with its finite positional and rotational freedom
made explicit. Determine membership once from a recorded reference configuration;
keep the selection box separate from periodic cell sizing and coordinate mapping.

Before scientific interpretation, compare an overhang and a crossover case across
larger mobile regions/boundary shells, restraint strengths (if used), and fully
mobile references. Assess boundary displacement, pairing, backbone stress, local
geometry and sensitivity to initial configuration. A short minimization can flag
clashes or local strain; it cannot establish equilibrium flexibility or kinetics.
No such tests have been started in this UI phase.

## Software verification

- Full frontend run: 882 files passed; 10,174 tests passed, one skipped.
- Final focused frontend run after lifecycle, retry and assembly-routing fixes:
  seven files / 453 tests passed. Includes both job-panel selection hooks and
  proof that submodel metadata never materializes assembly geometry.
- Focused backend: eight tests passed, including saved/reopened records for both
  routes and preservation through NAMD settings rebuilds.
- Browser feature exercise: passed against a read-only existing two-helix example.
  Real edge picking, Tab mode changes, TransformControls events, edit-after-create,
  switching jobs, reload, and the NAMD card were exercised. Job-region transport
  was mocked; actual disk persistence was covered separately by backend tests.
- Isolated `just smoke`: 25 passed; lint passed.
- `main.js` LOC delta: +3, imports/initialization/wiring only.

`just test-smart` selected **FAST**: 20,645 passed, 90 skipped, three failed in
198.07 seconds. Two new tests initially used an unavailable async pytest plugin;
they were corrected to `asyncio.run` and passed in the focused rerun. The remaining
failure is outside this change:
`tests/test_part_transform_frontend_contract.py::test_actual_complete_native_packet_is_accepted_by_frontend[cpd]`
(`Comparison unavailable: incomplete or unsupported display fields`). No CPD work
or scientific validation was undertaken to address it.

The guard also reported a 200-second aggregate overrun (90-second backstop).
The required slow-test triage found no per-test violators; the slowest test was
3.32 seconds. No timing limits or test classifications were changed.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Browser-fixture corrections: an initial no-design tab lock was resolved by
loading an existing example and enabling the harness sidebar. The first standard
fixture also exposed background trajectory-cache analysis against its default
workspace; that server was stopped and subsequent feature/smoke runs used an
empty temporary workspace. No submodel minimization or dynamics was launched.
A smaller two-helix example replaced the expensive close-up 26-helix render, and
selectors were scoped to the canonical controls to handle duplicate sidebars.
Temporary captures, traces, Vite caches and test workspace are disposable;
smoke teardown removed eight test artifacts and one project revision store.

Final retry-race check: all seven submodel-controller tests passed after ensuring
that a successful queued edit clears an earlier save error. Cleanup verified no
remaining `__e2e__` workspace artifacts or test bridge credentials; the owned
temporary browser workspace/caches/captures were removed (12,287,591 bytes).

## First native duplex experiment — 2026-11-09

The user authorized native exploration after the UI-only milestone. The existing
`workspace/duplex.nadoc` has 42 bp; the pilot selects helix indices 14–27 inclusive
(28 nucleotides) and freezes all 56 outside nucleotides. Full topology and all
interactions are retained, including backbone bonds crossing the selection boundary.
No cropped part, caps, new molecular placement algorithm or topology edits are used.
The box is an initial membership selection, not a confining wall.

`experiments/oxdna_submodel/prepare.py` uses the real headless job-create route and
PUT/GET submodel routes, checks the reopened box and maps native particle IDs through
the exporter's nucleotide order. The job snapshot preserves all three construction
commands and its document history. Source SHA-256 stayed unchanged. Independent
replay exposed a receipt compatibility bug: adding `ClusterTransform.folding_order`
changed hashes of old serialized snapshots. Verification now accepts historical
bytes only when their original hash matches AND their current-schema structural
value equals independently executed commands. No history was removed or fabricated.

The installed oxDNA CPU `MC2` backend supports move plugins. The pilot builds isolated
copies of upstream translation/rotation moves with selection restricted to `mobile.txt`.
It does not modify the installed engine, nucleotide types, potential, thermostat or
geometry. `fix_diffusion=false` prevents global recentring. Positions AND orientations
outside the box are immutable. This is an experimental native plugin path, **not yet
connected to the ordinary Run button**. The UI correctly retains its selection-only
notice. Full-system energy evaluation is retained; this pilot demonstrates constrained
motion, not speedup for a large origami.

Both trials use oxDNA2, average sequence, 20 °C, 0.5 M monovalent salt, CPU double
precision, seed 271828, full FENE, no external traps and no pair-preserving restraints.
One MC sweep is 84 proposals, restricted to the 28 mobile particles. These are
exploratory choices, not literature-validated submodel parameters.

| Trial | Proposals / sweep settings | Result |
|---|---|---|
| Metropolis MC | 10,000 sweeps; translation half-width 0.01 oxDNA units/component, rotation max 0.025 rad | Mobile RMS displacement 0.4386 nm; only 4/14 mobile pairs retained in the final frame |
| Downhill-only stochastic relaxation | 20,000 sweeps; translation half-width 0.002 units/component, rotation max 0.005 rad; reject every uphill proposal at the same 20 °C potential | Mobile RMS displacement 0.1429 nm, maximum 0.2139 nm; all 14/14 mobile and 42/42 total pairs retained in every saved frame |

The downhill energy decreased from −0.458705 to −0.513502 oxDNA units per nucleotide.
It is stochastic local relaxation, not a finite-temperature ensemble, MD trajectory,
or proof of a converged minimum. Native `DNAnalysis` HB lists provide pair counts
(the engine's default hydrogen-bond energy cutoff). Both runs showed exactly zero
fixed-position and fixed-axis drift in all saved frames relative to a zero-step native
initialization. Normalization of six-decimal input axes causes up to 5.65e−7 component
change on load; this is distinguished from subsequent motion.

The thermal pairing loss remains an open scientific finding. The next investigations
should separate seed strain, imposed boundary torque/separation and sampling protocol,
then compare boundary widths and independent seeds. This first experiment supports
starting with downhill local relaxation, not claiming that the thermal model is ready.

Evidence: `.development-artifacts/oxdna-submodel-duplex-20261109/` contains exact inputs,
source manifest/mapping, upstream move-source hashes, native logs/configurations,
HB lists, measurements and plots. `duplex-box.png` shows the actual app restoring the
headlessly saved box around the middle third; its outline was also ray-picked in the
browser. `quench-relaxation.png` shows the local displacement and energy decrease.
All browser workspace copies, caches and sessions were isolated and removed in a
`TemporaryDirectory` cleanup. Two never-started staging attempts and failed compiler
outputs were removed before the retained successful run.

### Reproduce in a new evidence directory

Use the same source revision as the installed engine when building plugins; the builder
fails if the expected upstream selection/acceptance statements have changed. Set `CXX`
to the compiler compatible with that installation. Output must be a fresh directory.
These commands run simulations and should only be used for an explicitly requested
scientific experiment. Paths below are arguments, not machine-specific defaults:

```sh
uv run python -m experiments.oxdna_submodel.prepare workspace/duplex.nadoc OUTPUT
just validate-safe uv run python -m experiments.oxdna_submodel.build_plugins ENGINE_SOURCE ENGINE_LIB OUTPUT/quench_plugins --downhill
uv run python -m experiments.oxdna_submodel.run OUTPUT OXDNA_BINARY --mode downhill
uv run python -m experiments.oxdna_submodel.analyze OUTPUT DNANALYSIS_BINARY --run quench
just validate-safe uv run python -m experiments.oxdna_submodel.check_visual OUTPUT
```

For the thermal comparison build `OUTPUT/plugins` without `--downhill`, run with
`--mode thermal`, and analyze with `--run experiment`. The pilot deliberately requires
a single 42-bp duplex; arbitrary rotated boxes, crossover selections, GPU masks,
production stages and efficient environment truncation still need implementation and
validation. General box saving through the API already supports quaternion rotation.
MD would additionally require masking integration and thermostat degrees of freedom;
post-step coordinate resetting is not the chosen strategy.

A follow-up 10,000-sweep thermal run started from the downhill final frame with the
same original fixed flanks. It retained 8/14 mobile pairs (36/42 total), versus 4/14
without pre-relaxation; mobile RMS displacement from its relaxed start was 0.3676 nm.
Positions and orientations of all fixed particles again stayed unchanged. This
single-seed comparison does not isolate the cause of melting or establish sampling
convergence. `run --mode postquench` and `analyze --run postquench` reproduce this
continuation; `postquench/execution.json` binds its input to the downhill output hash.

Validation for this native phase: the two new schema-receipt regression tests passed;
real-app headless-box restore/raycast/screenshot passed (1 browser test); lint passed.
`main.js` LOC Δ is **0 in this phase**. No frontend runtime behavior changed in this
phase; the preceding full frontend suite and smoke results remain recorded above.
`just test-smart` selected `FAST` and reported **20,650 passed, 90 skipped, 1 failed**
in 191.04 s. The failure remains the pre-existing
`test_part_transform_frontend_contract.py::test_actual_complete_native_packet_is_accepted_by_frontend[cpd]`
(unsupported display fields), outside this work. Aggregate guard time was 193 s against
90 s. Slow-test triage found **zero individual violators**, maximum 2.31 s; no timing
thresholds or test classifications were changed.

Selector deferral, verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## MD production continuations — 2026-11-09

The next requested experiment uses actual CPU molecular dynamics, following both
(a) the local downhill relaxation and (b) existing completed job `c49058f52282`,
whose source is `duplex.nadoc`. Its `3_equil/last_conf.dat` is the second starting
frame. Only `submodel_selection.json` is added to the existing job; none of its
relaxation inputs, outputs, job metadata or molecular history is replaced.

The existing relaxed duplex needs a slightly rotated box to select exactly both
strands at bp 14–27. `production.duplex_box` finds parallel separating planes and
independently tests oriented-box membership against all 84 aligned display positions.
The real PUT/GET routes persist and reopen that box on the original job. The mask
is frozen at preparation time; the box is not a reflecting wall and moving particles
are not reclassified. The local-relaxation continuation uses the same explicit IDs
as its original local relaxation, with its own relaxed poses as the fixed boundary.

`build_md.py` compiles an **isolated experimental executable** from the upstream CPU
backend, linked against the unchanged installed interaction library. It skips fixed
particles in both Verlet half-steps, initializes their linear/angular momenta to zero,
and passes only mobile particles to the upstream per-particle Brownian thermostat.
All original particle interactions and topology remain present. It refuses CPU/MD
alternatives, global recentring, COM momentum resets, barostat, shear, and incompatible
thermostats. It does not reset positions after a dynamics step. The ordinary installed
engine and the normal Run button are unchanged.

Both runs use 1,000,000 MD steps, dt 0.003, seed 314159, 28 mobile/56 fixed nucleotides,
Brownian thermostat with `newtonian_steps=53`, diffusion coefficient 2.5, and refreshed
initial mobile velocities. Frames are saved every 10,000 steps. Local-start conditions
retain 20 °C, 0.5 M, average-sequence oxDNA2 and full FENE. Existing-job conditions
retain 296 K, 0.5 M, its exact average-sequence parameter file and backbone-force caps
50/100 from its equilibration input. The existing parent used Bussi/CUDA; this constrained
CPU pilot deliberately uses the per-particle Brownian thermostat so fixed degrees of
freedom cannot contaminate a global thermostat rescaling.

The native all-mobile control is compared to the installed CPU engine for 1,000 steps,
with identical input and seed. An initial O2 build differed by 6.63e−12, exceeding the
chosen 1e−12 tolerance. Matching the installed compiler's O3/fast-math/native flags
produced **exactly identical** positions, axes, velocities and angular momenta. Both
attempts are retained; thresholds were not relaxed. The matching binary is used for
both production runs. A first link attempt also exposed required CUDA runtime and
TinyExpr dependencies; the builder now includes explicit dependency arguments and
compiles TinyExpr from the same source tree without changing that tree.

These remain isolated checkpoint-continuation experiments, not new managed production
jobs visible in the normal job list. The real parent's box is visible on reopening the
job. Evidence and complete native outputs are retained under
`.development-artifacts/oxdna-submodel-production-20261109/`; `lineage.json`,
`execution.json`, `build.json` and file hashes bind the exact parents, frames, mask,
inputs and executable. No new `.nadoc` part is authored.

Reproduction uses `experiments.oxdna_submodel.production prepare OUTPUT WORKSPACE
PARENT_JOB_ID PREVIOUS_PILOT --attach-box`, then `production run OUTPUT/CASE BINARY`
for `local_relaxation` and `existing_relaxation`. Build with `build_md SOURCE LIB OUTPUT`
and explicit `--runtime-library` dependencies where required. Match `CXXFLAGS` to the
installed engine for the all-mobile equivalence control. `analyze_md OUTPUT CASE
DNANALYSIS_BINARY` measures pairing and mobile kinetic temperature using 168 mobile
DOFs, and checks exact immobility without alignment. Keep separate output directories
for independent runs; the runner refuses to overwrite existing logs.

Production results (100 saved frames per trajectory; native HB cutoff −0.1):

| Starting frame | Mobile bp initial → final | Minimum mobile bp | Mean mobile bp | Final mobile RMS displacement |
|---|---:|---:|---:|---:|
| Local downhill relaxation | 14 → 14 | 3 | 12.16 | 0.638 nm |
| Existing full-duplex relaxation | 14 → 14 | 13 | 13.98 | 0.185 nm |

Both runs had exactly zero fixed-position drift, fixed-axis drift, and fixed linear
and angular momentum across initialization, all saved frames and the final checkpoint.
The existing frame has 37/42 native-HB pairs initially and finally; its five pre-existing
unpaired pairs are outside the mobile region. This native energy-cutoff measurement
is distinct from the earlier job health retention metric. Mean instantaneous mobile
kinetic temperatures were 302.9 K and 289.7 K, respectively, using only mobile DOFs.
The local-start trajectory transiently melted and reannealed; final pairing alone
would conceal that behavior. The existing relaxed frame is the more stable starting
point in this single-seed comparison. Neither trajectory establishes convergence or
quantitative physical kinetics, and the two starts retain their slightly different
source temperatures/force-cap settings.

Phase validation: four focused numerical/patch-safety tests passed; the real-app
headless review passed and its rendered image was inspected; lint passed. The first
browser attempt could not find a normal job-list row because API-only fixture loading
does not initialize the file-browser workspace handle. The successful headless review
uses the real `displayJob` controller and submodel controller directly against real API
endpoints, then ray-picks the rendered box; it does not mock simulation data. That
first-attempt log is retained. This checks headless display and saved-box restoration,
not the job-list interaction path. All browser caches/workspace copies were removed,
and all 41 original parent files were verified unchanged. Both saved source-design
inputs independently replay all three construction operations and the document/loadout
history. No production backend/frontend runtime code changed in this phase;
`main.js` LOC Δ: **0**. The earlier broad-suite CPD failure/FULL deferral remains
separate regression debt; this phase used focused checks and requested native runs.

## Adjustable fixed shell pilot (November 9, 2026)

Both cards now persist `shell_nm` (0–1000 nm, default 3 nm) with the oriented
box. oxDNA also persists `visible`; NAMD follows its existing box/solvent master
visibility control. The translucent rounded surface depicts Euclidean distance
from the mobile box. Zero hides the shell surface, retaining the mobile outline.
These are selection settings: normal Run still does not crop or freeze a job.
Native submodel execution remains in the isolated experimental runner.

The new export-only extractor retains particles whose aligned backbone positions
fall inside the box or within the requested distance outside it, plus **every
directly bonded neighbour of a mobile particle**, even at zero radius. It removes
all other particles from the native simulation topology, reindexes neighbours,
splits disconnected strand components, and refuses cuts incident to mobile bases.
Original authoring documents are unchanged. Each extraction records source-index
mapping, mandatory neighbours, cuts and native terminal behavior, beside the
source document with its independently replayed construction history.

Starting from the existing full-duplex relaxation, the sweep used 28 mobile
nucleotides, two seeds per shell, 100,000 CPU MD steps per seed, and 100 saved
frames. Conditions and experimental fixed-particle integrator match the prior
existing-relaxation continuation. Eleven identical poses (initial plus ten
samples from the prior million-step full-duplex trajectory) additionally compare
mobile forces and lab-frame torques against the full model.

| Shell outside box | Simulated nts (fixed) | Time per 100k steps | Relative RMS force difference |
|---|---:|---:|---:|
| 0 nm | 32 (4) | 4.22 s | 0.158% |
| 0.5 nm | 34 (6) | 4.52 s | 0.100% |
| 1 nm | 37 (9) | 5.05 s | 0.0553% |
| 2 nm | 51 (23) | 7.22 s | 0.00128% |
| 3 nm | 69 (41) | 10.13 s | 0 at printed precision |
| Full duplex | 84 (56) | 12.91 s | reference |

All twelve runs remained finite and fixed particles had zero positional drift
and zero linear/angular momentum; fixed orientations were identical across saved
frames. Mobile pairing never fell below 13/14 pairs. At 3 nm both seeds retained
14/14 throughout. Thus **0 nm is the smallest tested runnable shell**, with about
3.1× speedup here; **3 nm is the smallest tested shell matching full-model forces
and torques across these poses**, and supplies the initial UI default.
Native force output has six significant digits: zero difference is not a proof
of bitwise force equality. The 2 nm shell is already close for this specimen.

These are short feasibility tests, not a universal minimum or convergence claim.
Cropping changes terminal electrostatics on fixed cut ends, as well as removing
nonbonded interactions. Identical seeds do not imply paired trajectories because
cropping changes random-number assignment. Crowded origami, different salt,
larger excursions, and different boxes require their own shell convergence checks.
The mask is chosen once at the starting frame, not updated during motion.

Evidence: `.development-artifacts/oxdna-submodel-shell-20261109/summary.json`,
per-case `extraction.json`, per-seed trajectories/results, eleven-pose
`mobile_forces.json`, source audit and input/binary hashes in `manifest.json`.
Reproduce with `python -m experiments.oxdna_submodel.sweep_shell SOURCE OUTPUT
EXPERIMENTAL_MD_BINARY DNANALYSIS_BINARY`; OUTPUT must be new.

Shell-phase validation: `just test-frontend` passed 883 files / 10,183 tests
(one skipped). Real-app headless review passed against an isolated copy of the
existing relaxation job, including API readback of radius/visibility, outline
picking, oxDNA visibility and NAMD's master toggle. Both visible and hidden
screenshots were inspected; a contrast issue in the number field was corrected
and the app check rerun successfully. The first attempt's ambiguous status
selector failure is retained in `visual-first-attempt.log`; it was a test locator
issue, not a save failure. Review images live in
`.development-artifacts/oxdna-submodel-shell-ui-20261109/duplex-box.png` and
`duplex-hidden.png`. Lint passed. This phase adds no main.js logic.

Backend `just test-smart` reported **decision: FAST  (fast suite only)**:
20,661 passed, 90 skipped, one pre-existing CPD packet-contract failure, 190.20 s.
The required slow-test triage identified a real C++ compile/execute test
(`test_native_recorder_is_opt_in_and_exclusive`, 5.12 s); it is now classified
slow/headless, with collection confirming that exact test. Guards/budgets are
unchanged; the broad suite was not repeated solely to remeasure aggregate time.

Verbatim deferral:
```
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

General `just smoke`: **25 passed** (1.5 min), using an isolated workspace.
All owned visual/smoke workspaces and caches were removed after completion;
retained evidence is limited to the documented reports, scripts and screenshots.
The original duplex SHA256 remains unchanged; the copied simulation source
exactly matches the independently audited source.

## Saved Submodel_tests specimen verification (November 10 UTC)

The user's specimen is `workspace/Submodel_tests.nadoc`; its existing queued
job is `093c7b60f98e`. The saved axis-aligned box spans
(3.93755, −1.08742, 26.72900) to (10.28178, 5.58641, 33.16847) nm,
with a **2 nm shell**. It selects **102 mobile + 80 fixed = 182 native
particles**, from the original 1,134. Source construction was independently
audited, and neither the original design nor the queued job was run or rewritten.

Define/Edit submodel and Retry save now use NADOC's shared `btn btn--sm`
classes. A scoped hidden-state rule preserves Retry save's visibility semantics
despite the shared button's `inline-flex` display. The real-app check compares
computed colors, border, radius, padding and height against a standard button,
restores the actual saved box, and inventories the ordinary visualization controls.
No molecular-authoring or main.js changes were needed.

Two isolated native protocols were tested, retaining the same 182-particle mask.
Both use CPU native execution with the previously validated fixed-particle
integrator; these are **not app-managed completed jobs**.

| Protocol | Native stages | Designed pairs touching mobile region |
|---|---|---|
| Downhill-only preparation | 20k masked MC steps, then 100k capped Brownian MD steps | MC 18→18; production 18→2 |
| Restrained preparation | From the downhill result: 1M capped Brownian MD steps with 108 remapped parent mutual traps; then 100k steps without traps | Relaxation 18→7 (minimum 0); production 7→6 (minimum 3) |

The longer relaxation took 323.49 s, its production 31.21 s. Both use 296 K,
0.5 M salt, dt=0.002; relaxation backbone caps 5/10 and production caps 50/100,
in native oxDNA units. Production therefore remains a **capped feasibility
pilot**, not unbiased production sampling. The exact parameter-file paths,
seeds, complete inputs, restraint mapping, checkpoints and trajectories are
retained. All saved poses are finite; fixed positions, fixed orientations across
saved frames, and fixed momenta have zero drift. Pairing is native hydrogen-bond
energy < −0.1, restricted to designed pairs touching mobile particles.
The observed pair loss prevents claiming a pairing-preserving, converged local
relaxation. It does not by itself identify shell size, starting geometry or
sampling length as the cause.

**End-to-end managed-job support is not verified and currently is not supported.**
Normal Run still ignores this selection (as the card states). The existing
display/trajectory readers require full source particle order and reject the
cropped topology: 182 particles versus the design's 1,134. Do not bypass that
guard, re-label a full-model run as local, or fabricate a completed job to unlock
controls. A dedicated native-to-source mapping, managed execution integration,
and downstream metric scoping are needed before this can be claimed to work.

The original queued job exposes Off and oxDNA display. RMSF, autorefine deviation,
local strain, job-chain trajectory, current-job trajectory and occupancy controls
are present but disabled. Their presence is not cropped-output visualization
acceptance. The diagnostic browser uses the real job panel's row selection
handler with the legacy all-designs filter enabled headlessly; it does not claim
to verify the normal library-open/unified-list path.

Evidence is under `.development-artifacts/oxdna-submodel-specimen-20261110/`:
`manifest.json`, `extraction.json`, `results.json`, `analysis.json`,
`restrained/` and `ui/visualization-options.json`. Source and input hashes,
native mapping, upstream construction audit and the failed first protocol are
preserved. Reproduction:
`python -m experiments.oxdna_submodel.specimen SOURCE PARENT_JOB NEW_OUTPUT`,
then `restrain_specimen OUTPUT` and `analyze_specimen OUTPUT/restrained`.
The scripts deliberately require new output directories for native runs.

This phase's validation: **883 frontend files / 10,183 tests passed**, one skipped;
the real-app saved-specimen/style/options check passed and its final screenshots
were inspected; lint passed. No production backend behavior changed, so the prior
backend FAST result/FULL deferral above is unchanged. Temporary browser workspaces
and server processes were removed. Final hash checks confirm unchanged source and
original job files, and both native production inputs exactly equal their preceding
relaxation checkpoints; see `verification.json`. The before-hidden-fix screenshot
and log remain available alongside the corrected screenshots.

### Editing copied NAMD jobs (2026-11-10)

Relaxation copies preserve the source job's model path even when its original
preparation request has a missing or outdated path. This keeps background job
refreshes from switching the editor away during a box drag. Explicitly selected
legacy copies without a path also remain selected during refresh, and both job
lists recover their membership from the recorded project ID. No saved job data
is rewritten. Changing
documents still clears selection; frozen production topology rules are unchanged.

The opt-in `frontend/e2e/submodel_edit.spec.js` exercises the real new-job wizard
and copy menu, pointer transforms, shell input, refresh during drag, and saved-box
restoration. It requires `NADOC_SUBMODEL_ZOOM_SOURCE` and an isolated
`NADOC_WORKSPACE`; the caller must remove the workspace and bridge in `finally`.
It reads an existing source and creates disposable job records only.

### Fractional terminal charge in NAMD crops

Whole-residue cropping preserves CHARMM partial charges. Natural 5′ and 3′
terminal residues carry −0.47 and −0.53 e, respectively; a spatial crop need not
retain them in pairs. Consequently a valid crop can have noninteger net charge
although its complete source topology is integer charged.

New preparations record a hash-bound `charge_policy` in `submodel.json`. The
source must pass the ordinary all-atom topology audit. Counterions are chosen
from the actual cropped PSF charge rounded to the nearest integer, leaving at
most 0.5 e residual. Both dry and solvated audits check the specific recorded
charge; the final residual and `neutral: false` remain explicit in
`charge_audit.json`. No DNA charges, atoms, coordinates or terminal patches are
changed to force neutrality. This is an approximate periodic-PME boundary for
screening, not an exactly neutral whole molecule. Whole-model audits still
require integer charge and neutral solvated packages. Historical packages are
not rewritten; prepare a new copy to use this policy.


Validation on 2026-11-12 used the user's saved 24hb_2xT selection in managed
RunPod pilot `ddea66693a54`: 4,800 minimization steps and 205 ps across the
shortened relaxation ladder, including 50 ps of final 4 fs dynamics without
internal DNA ENM restraints. All four target extra Ts were mobile; fixed atoms
remained unchanged, final core positional restraints were zero, and the uniform
heavy-shell coefficient remained 0.1. All 22 native stages exited normally with
finite energies and all 201 output files were verified. Campaign GPU cost was
$0.54 of a $3 budget, with both pods destroyed. No local NAMD jobs were started.
This is preliminary execution validation; it does not establish equilibration
or validate calibrated restraints. The original failed job and design were kept.

## Matching a full-model reference for NAMD comparisons

A registered `submodel_reference_job_id` now supplies a frozen native physics
profile to new submodel preparations. A per-design binding in
`workspace/submodel_reference_profiles.json` applies automatically to new jobs;
register it with `python -m backend.core.namd_submodel_reference --workspace
workspace --reference-job JOB_DIRECTORY`. The current importer supports a
whole-model production reference with neutralizing Mg(H₂O)₆ only. It verifies
actual PSF ion counts, rather than treating nominal legacy Mg concentration as
added salt. Explicit `counterion='mg'` permits zero added MgCl₂ without changing
ordinary zero-Mg requests, which still use sodium counterions.

The wizard supplies the selected region and source path to the same resolver used
by preparation. Reference-controlled values appear as forced settings. The
profile is embedded in `submodel.json` and inherited by production descendants;
existing jobs and their inputs are untouched. New production off a pre-binding
submodel is refused because its old ion box cannot be changed by editing a conf.
Copies can be prepared under the new binding. Reference settings override stage
physics edits, while run lengths and output intervals remain editable. Topology
agreement is recorded but not required for configuration-only screening variants;
no reference coordinates are transferred by this feature.

For `24hb_2xT.nadoc`, the reference is `fc12195d0636`: 300 K, 1 ps⁻¹ damping,
4 fs HMR, rigid bonds, matching force-field file hashes, PME and nonbonded settings,
zero added NaCl/MgCl₂ and magnesium counterions. The fixed-shell implementation
still uses NVT and CUDA offload. Cell dimensions, boundary restraints, preparation
ladder, run duration and ion number density differ; the receipt explicitly lists
these exceptions. This is configuration matching, not a claim of ensemble equality
or new native stability validation.

The observed-pose investigation and repeatable comparison commands are documented
in `experiments/namd_shell_calibration/README.md`. Moving shell coordinates alone
would stretch connecting bonds; coherent initialization of all retained atoms and
restraint references from a recorded whole-model frame is the next candidate to
investigate. No altered molecular pose has been installed by these settings changes.
