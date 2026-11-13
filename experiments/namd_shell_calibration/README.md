# 24hb_2xT shell-calibration pilot

Offline framework prepared November 12, 2026. **No local or remote NAMD jobs
are launched by this module.** Existing jobs and native inputs are read-only.
This experiment produces analysis arrays and parameter proposals, not NADOC
structures or deployable simulation packages. Native restraint installation,
remote trial execution and physical qualification remain subsequent work.

User clarification: the intended application is cheap, fast candidate screening
before whole-model simulations. Deliberately varying local ionic conditions
while retaining a boundary learned at another condition is allowed. Treat this
as an approximation to the surrounding structure, not a requirement to reproduce
a whole-system ensemble at every screened salt condition. Matched-condition
benchmarks help quantify error; they are not prerequisites for exploratory use.

## Historical smaller-box experiment

These identifiers and counts describe the initial smaller-box analysis, not the
current selection pilot. Use the repeatable selection comparison section below
for `ddea66693a54`; the old control may no longer be present in managed job storage.

- RunPod relaxation control: `85c3dc72dc59`, under
  `/media/jojo/Archive/nadoc_jobs/85c3dc72dc59`.
- Whole-model production: `fc12195d0636`, under
  `/media/jojo/Archive/NADOC_archive/fc12195d0636`; parent relaxation
  `31c22b344ede`. The production is paused with 215.5 ns locally available,
  despite its requested/file-name length of 400 ns.
- Use the control's **saved 2 nm shell**, whole-residue and bonded-support
  selection: 8,143 retained DNA atoms, 549 core atoms, 2,366 restrained shell
  heavy atoms, and 3,913 fixed atoms (hydrogens included in core/fixed counts).
- The core includes four extra thymines across the reciprocal crossover pair
  between `h_XY_2_2` and `h_XY_1_2`, at levels 55/56:
  `ec429129-8499-4362-8fca-832f5c024601` and
  `9c73f442-3739-40a5-bc92-7e39b56079d7`.
  Saved atom mappings identify D00K:31–32 and D01H:26–27; these are package
  residue identifiers, not editor base labels.

The mapping reuses `exp46_xb_placement.xb_map` without rebuilding geometry.
It checks source PSF/PDB hashes, retained atom identities/types/charges against
both packages, and selected crossover definitions against the reference design.
Upstream snapshots and histories remain in their original jobs.

## Frame and measurements

The saved oriented box defines axes and origin (converted from nm to Å).
Each sampled frame undergoes a proper rigid fit using the **123 phosphates
in the control's fixed outer shell**, then is transformed into box coordinates.
The core is excluded from the fit. This measures local crossover motion relative
to its surroundings; it removes shell rigid motion relative to the whole origami.
It does not model whole-origami translation, rotation or global mode kinetics.

The current reader requires `wrapAll off` in the matching native configuration.
It checks retained covalent bonds and local Watson–Crick support for split
periodic images; it refuses unsupported images instead of silently wrapping
atoms independently. Triclinic image handling is not implemented. A broad region
can legitimately span more than half a cell; this alone is not an image error.

Outputs include per-atom means and 3×3 covariance, first/second-half statistics,
alignment residuals and mean shifts. Crossover traces include four C1′ positions,
four ring centroids, six insert-pair ring-centroid distances and unsigned
ring-normal dot products, and 13 core/flank Watson–Crick C1′ distances.
These are geometric observables, not hydrogen-bond occupancy or stacking-state
classifications. There is no autocorrelation/friction fit or effective sample
size estimate yet. Sparse samples must not be interpreted as resolved kinetics.

## Commands

Run from the repository with `.venv/bin/python -m
experiments.namd_shell_calibration.workflow`. The CLI has three subcommands:

```bash
python -m experiments.namd_shell_calibration.workflow prepare \
  --control-job /path/to/control-job \
  --reference-job /path/to/whole-production-job \
  --out /existing/experiment-root/plan

python -m experiments.namd_shell_calibration.workflow profile \
  --plan /existing/experiment-root/plan/plan.json \
  --kind reference --dcd /path/to/whole-production-job/package/name/output/run.dcd \
  --start 10775 --stop 21550 --max-frames 32 \
  --out /existing/experiment-root/reference

python -m experiments.namd_shell_calibration.workflow profile \
  --plan /existing/experiment-root/plan/plan.json \
  --kind control --dcd /path/to/control-job/package/name/output/run.dcd \
  --start 0 --max-frames 32 --out /existing/experiment-root/control

python -m experiments.namd_shell_calibration.workflow compare \
  --plan /existing/experiment-root/plan/plan.json \
  --reference-profile /existing/experiment-root/reference/profile.json \
  --control-profile /existing/experiment-root/control/profile.json \
  --temperature 300 --out /existing/experiment-root/proposal
```

Frame bounds are zero-based, stop-exclusive, within one DCD. Select explicit
equilibrated windows for scientific use; the defaults do not establish
equilibration. First-half covariance drives proposals, second-half statistics
are held out as a diagnostic. Separate replicas/longer blocks are still needed.
Profiles from different plans or with changed statistic hashes are refused.
The fit temperature must match both native thermostat settings. Add
`--trial-job /path/to/production-child` to profile a uniform-control production
child with the same box, atom identities, core/shell/fixed selections and
baseline coefficient. Changed boundary recipes are refused; future iterations
with changed coefficients need explicit support for their actual per-atom forces.

`compare` emits **UNVALIDATED_PROPOSAL_NOT_NATIVE_INPUT** JSON. Its initial
isotropic update uses

`k_new = clip(k_old + gain * 3*kBT/2 * (1/MSF_target - 1/MSF_trial), 0, 0.5)`

with gain 0.25, Å and kcal/mol, and NAMD's `U=k*r²` convention. This is a
relative Gaussian stiffness correction, not an additional full inverse-
covariance potential. Clipped/unclipped coefficients are both retained.
Per-atom estimates are exploratory: correlated residues, anisotropy and low
sample counts can invalidate them. Means are compared but reference positions
are not moved. Fixed atoms are never included in coefficient fitting.

## Resource policy and evidence

While the user's local NAMD is running, use one numerical thread, low CPU/I/O
priority and a bounded analysis scope. The real-data checks used:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
systemd-run --user --scope --quiet \
  -p CPUQuota=25% -p MemoryMax=1G -p MemorySwapMax=0 \
  nice -n 15 ionice -c 3 .venv/bin/python -m \
  experiments.namd_shell_calibration.workflow ...
```

Direct-seek DCD reading avoids scanning the 350 GB file. Default sampling is
32 frames; the pilot reads about 520 MB. The code refuses more than 2 GiB of
frame reads or 128 MiB of retained sampled coordinates per invocation. No full
trajectory copies or persistent extracted coordinate trajectories are written.
The existing output directory must not be reused. Use `.development-artifacts`
or separately configured experiment storage, never managed job directories.

Evidence is under `.development-artifacts/namd-shell-calibration-20261112/`:
`plan-final/`, `reference-final/`, and `audit.json`. The initial 32-frame sample
spans 107.76–215.50 ns. Median shell RMSF is **3.296 Å** and the median
first/second-half mean shift is **2.099 Å**. These are exploratory estimates.

Two material comparison issues emerged:

1. Median rigid-fit residual of outer-shell phosphates to the control's
   preparation pose is **10.281 Å**. A fixed outer layer at that preparation
   pose cannot reproduce the relaxed full-model mean shape merely by changing
   inner-shell spring constants. A subsequent matched-start/reference experiment
   is needed to distinguish mean-shape mismatch from fluctuation stiffness.
2. The full reference uses NPT and the crop NVT. Both metadata recipes say
   12.5 mM Mg, but the whole-model parent records **neutralizing Mg only, no Cl**;
   the crop records added MgCl2 plus counterions. Matching nominal salt fields
   does not establish matching ionic environments. Relevant DNA/ion parameter
   files match; actual ionic densities and HMR mass policy still need comparison.

Follow-up shape diagnosis (same 123 outer-shell phosphates, rigid fits only):
the whole-model initial PDB matches the control preparation to 0.063 Å RMSD.
The whole-model equilibrated checkpoint differs by 6.181 Å; its late-production
mean differs by 9.668 Å. The late outer-P RMS fluctuation about that mean is
3.567 Å (root mean over atoms). Thus the discrepancy developed during whole-model
relaxation/production, rather than coming from a different initial local shape
or an uncompensated translation/rotation. The principal radii of the P cloud
change from [18.148, 22.476, 23.863] Å to [18.389, 27.354, 28.991] Å: substantial
expansion in two principal directions plus nonuniform deformation. This does
not isolate a causal force-field term, establish convergence, or prove which
helices moved. Details: `shape_diagnosis.json` in the evidence directory.

Do not fit relaxation transients as equilibrium fluctuations or promote proposals
to defaults. After the control finishes, profile its stages diagnostically;
use comparable production sampling for calibration. Validate the core extra-base
distributions, flanking pairing, mean shape and boundary strain, then assess
shell-width sensitivity. Anisotropic/coupled restraints and temporal-memory
models are follow-on capabilities, not implemented native features here.

Software verification: `just test-focused tests/test_namd_shell_calibration.py`;
analytic frame/covariance/stiffness tests plus a synthetic DCD-to-proposal
pipeline. These tests do not launch an engine. Broad suites are deferred during
the active local simulation. `frontend/src/main.js` LOC delta: 0.

## Repeatable selection-submodel comparison (November 12, 2026)

The current selection-derived pilot is **`ddea66693a54`**, superseding the
historical smaller-box control described above. Its saved crop contains 12,373
DNA atoms, 1,212 core atoms, 4,617 restrained heavy shell atoms and 3,974 fixed
atoms. Always prepare a new plan for a changed selection; old indices are invalid.

The `comparison` module adds multi-stage diagnostic comparison and reprocessing:

```bash
python -m experiments.namd_shell_calibration.comparison recipe \
  --plan .development-artifacts/submodel-comparison-20261112/plan/plan.json \
  --reference-dcd /media/jojo/Archive/NADOC_archive/fc12195d0636/package/24hb_2xT_namd_solvated/output/24hb_2xT_01_production_400ns_k0.dcd \
  --out /existing/analysis-root/recipe.json

python -m experiments.namd_shell_calibration.comparison run \
  --recipe /existing/analysis-root/recipe.json \
  --out /existing/analysis-root/run-01
```

Use the bounded resource wrapper above for real trajectories. Reprocess the same
recipe into `run-02` to keep identical frame selections, or generate a fresh recipe
to include newly available reference frames. No persistent coordinate cache or
simulation launch is involved. Outputs are never overwritten. Source-plan hash
mismatches require a new `workflow prepare`; unchanged molecular mappings may
be reused when only additional trajectory frames become available.

The default recipe uses all 50 final control frames, their five 10 ps endpoints,
the first five reference-production frames, eight separate five-frame late
reference windows, and 24 sparse late reference frames. Stage clocks are rebuilt
from executed configs, because overridden run lengths leave manifest step counts
stale. Five saved frames span 40 ps inside each 50 ps acquisition window. The early
reference window follows whole-model relaxation; it is not an unrelaxed start.
Do not pool the eight late windows to estimate within-window fluctuations.

Outputs: `comparison.json` (metrics, traces, sampling recipe, native configs,
source/code/dependency hashes, DCD size/mtime and sampled-coordinate hashes),
`residue_metrics.csv`, `observable_summary.csv`, `comparison.svg`, and
`outputs.json` (output hashes). The six extra-T pair distances and unsigned ring
normal dot products are alignment-invariant. All 26 local paired C1′ distances
are included. Neither quantity is a hydrogen-bond or stacking classification.
Each invocation deduplicates frame reads across groups and enforces a **global**
2 GiB DCD-read / 128 MiB selected-coordinate limit. The current recipe reads
1,596,823,860 bytes, rather than scanning the 350 GB reference.

Current selection results, with unbiased sample variance and the fixed-outer-P
rigid frame:

| Metric | Submodel final 50 ps, five frames | Eight late full-model 50 ps windows |
|---|---:|---:|
| Median core-heavy RMSF, Å | 0.475 | 0.638–0.793 |
| Median shell-heavy RMSF, Å | 0.390 | 0.655–0.729 |
| Median outer-P RMSF, Å | 0 (fixed) | 0.662–0.761 |

The late whole-model mean outer-P pose differs from the submodel by **9.649 Å
RMSD**; the early production mean already differs by **6.979 Å**. Principal radii
of that P cloud change from [22.596, 23.809, 27.524] Å to
[23.548, 27.874, 31.959] Å. Rigid fitting cannot remove this internal deformation.
The late sparse core RMSF (3.225 Å) spans 107.74 ns and must not be compared as a
matched fluctuation estimate against the 50 ps control.

For the two extra Ts on D00K:31–32, mean ring separation is **9.217 Å** in the
control versus **13.072 Å** in the late whole-model sample (sampled ranges
8.529–9.952 and 11.688–14.415 Å). D01H:26–27 gives 6.127 versus 7.942 Å with
substantial range overlap. These are descriptive discrepancies, not equilibrated
effect sizes or established stacking states.

Corrections to prioritize:

1. Test a boundary/start pose derived from a representative relaxed whole-model
   frame before fitting spring constants. A different spring coefficient cannot
   move the fixed outer layer to the full-model mean. This is a proposed future
   simulation comparison; no molecular placement or native restraint was changed.
2. Match thermostat damping in a future calibration control: the pilot uses
   **5 ps⁻¹**, whole production **1 ps⁻¹**. Short-window RMSF mixes damping,
   stiffness and incomplete relaxation. Do not infer a spring multiplier here.
3. Extend the unrestrained-core sampling and compare independent windows before
   assigning candidate-ranking confidence. NVT/NPT and added-MgCl2 versus
   neutralizing-Mg-only remain explicit confounds. Different ionic conditions are
   still permitted for exploratory screening; exact ensemble agreement is not
   its acceptance criterion.

No coefficient correction is installed automatically. The metrics support a
mean-boundary correction experiment, but do not identify calibrated spring
constants. Evidence: `.development-artifacts/submodel-comparison-20261112/`.

Verification for this addition: five focused comparison tests passed, including
real synthetic-DCD reprocessing and changed-source refusal. The real-data second
pass reproduced every metric and sampled-coordinate hash; current code and output
hashes verified. `just test-smart` selected FAST: 20,813 passed, 90 skipped. FULL
remains deferred without a test-dedicated session. No NAMD jobs were launched.

## Reference settings and boundary-pose investigation

New 24hb_2xT submodel preparations are bound to whole production `fc12195d0636`
through `workspace/submodel_reference_profiles.json`. The generic registration
command freezes the actual native configuration and audited PSF ion census:

```bash
python -m backend.core.namd_submodel_reference \
  --workspace workspace --reference-job /path/to/whole-production-job
```

The API can explicitly select a registered `submodel_reference_job_id`; otherwise
it uses the binding for `design_source_path`. Whole-model jobs and other designs
are unchanged. Binding changes affect new preparations; existing jobs retain their
inputs. A new production child from a pre-binding submodel is refused until a new
relaxation has prepared the correct ions. No old solvent box is edited in place.
The profile is embedded in each derived package and carried to production children.
Reference/config and force-field mismatches fail preparation instead of silently
falling back. The receipt records whether topology matches the reference;
configuration-only inheritance permits screening variants and never transfers coordinates.

The current profile matches 300 K, Langevin damping 1 ps⁻¹, 4 fs, HMR, rigid bonds,
cutoff/switching, PME, interaction frequencies, wrapping and pairlist distance.
It explicitly uses **Mg(H₂O)₆ counterions with zero added MgCl₂ and zero NaCl**.
`ion_counts(counterion='mg')` decouples counterion identity from added-salt
concentration; default `auto` retains existing whole-model behavior. With the
unchanged crop charge, the recipe gives 193 Mg and no Na/Cl, retaining the already
recorded −0.47 e crop residual. These are recipe counts, not a newly simulated box.
Odd integer DNA charges can require one balancing chloride. The legacy full-model
audit's nominal `n_mg_bulk=84` was not actually placed; profile import verifies the
PSF's real census (3,660 Mg, no Na or Cl), rather than propagating that stale field.

Explicit differences remain: fixed-shell NVT versus whole-model NPT, CUDA offload
versus GPU-resident, cell dimensions, retained boundary restraints, staged DNA ENM
during relaxation, and initialization/run length. Matching a neutralization recipe
does not match total Mg number density when the DNA/solvent ratio changes. The
wizard now passes its actual selected submodel and design path into the plan, shows
reference-controlled fields as forced, and previews fixed-cell stages consistently.

Reprocess the pose investigation with:

```bash
python -m experiments.namd_shell_calibration.boundary_pose \
  --plan .development-artifacts/submodel-comparison-20261112/plan/plan.json \
  --recipe .development-artifacts/submodel-comparison-20261112/recipe.json \
  --out /existing/analysis-root/pose-01
```

Use the bounded resource wrapper above. This compares **existing trajectory
frames**, never publishes a new structure or installs coordinates. It selects the
observed medoid of the 24 late sampled frames using outer-P RMSD in the rigid box
frame. For the current sample that is zero-based frame **16864, 168.65 ns**. Its
outer-P pose differs from the control's final frame by **9.426 Å RMSD**.

Mixed-frame bond-endpoint diagnostics show why a shell-only transplant is unsuitable:

| Endpoints taken from full-model frame | Crossing bonds | Mixed endpoint distances >2 Å | Maximum |
|---|---:|---:|---:|
| Fixed layer only | 57 | 56 | 20.172 Å |
| All non-core atoms | 28 | 28 | 19.346 Å |

Those distances are arithmetic diagnostics, not an authored hybrid molecule.
The coherent observed full-model frame preserves the same crossing bonds at
maximum 1.666 and 1.636 Å, respectively. Therefore the candidate to investigate
next is **one coherent relaxed frame for the entire retained crop and all of its
restraint references**, preserving atom identities and selection membership.
Do not average atomic poses or move only the fixed shell. Selection membership
must remain tied to original identities even if the relaxed atoms cross box faces.

There is also strain in the current control: the fixed/mobile boundary bond
D00P:59 GUA O3′ → D00P:60 THY P grows from **1.439 Å** at preparation to
**2.326 Å** in its final frame; it is **1.532 Å** in the observed medoid.
This is a boundary diagnostic, not a claim of converged behavior or isolated cause.
Per-junction numbers and same-frame atom/bond projections are saved under
`.development-artifacts/submodel-reference-20261112/pose-02/`; the original
source bond check is `boundary-bond.json`. No geometry was promoted, no new
NAMD job launched, and no additional RunPod budget spent. A publishable molecular
candidate still requires its real recorded initialization path and separate review.

Verification of reference matching: eight focused backend tests initially passed;
final targeted FAST checks passed nine tests (two unrelated matching tests skipped),
including forced production-setting provenance. The broad FAST run passed 20,821
with 90 skipped before that final provenance-only adjustment. Frontend: 10,420
passed, one skipped. The isolated real-backend wizard check passed, with zero job
mutations and verified cleanup/source hashes. Live API checks distinguish new
reference-bound plans from the old control's unchanged historical settings.
Full backend coverage remains deferred without a test-dedicated session.
