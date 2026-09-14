# Reusable CHARMM photoproduct parameterization workflow

## Scope and release rule

This workflow develops classical, additive CHARMM36-compatible parameters for the
electronic ground state of an already formed DNA photoproduct. It does not model UV
excitation, the bond-forming reaction, quantum yield, or automatic conversion during a
trajectory.

No product is simulation-ready because a topology file exists. Readiness is derived from
all nine evidence gates in
`backend/data/forcefield/photoproduct_registry.json`, followed by asset existence and
SHA-256 verification. A requested or partially parameterized product remains available as
design intent while every simulation/export path fails closed.

Passing a gate rechecks the required curated asset's bytes. Human review can pass only
the `chemical_definition` identity gate; it may mark any later gate blocked, but cannot
pass QM, fit, topology, engine, solution, or release gates. Those later gates use
`record-metric-gate`, which requires a curated
`nadoc.photoproduct-metric-gate-evidence.v1` envelope with the complete gate-specific
check set, a passed source audit, and SHA-256 pins for that audit, the required asset, and
the current acceptance policy. The `chemical_definition` gate additionally parses the released definition schema, verifies
its registry product ID/product/stereochemistry, and requires its ordered graph delta to
match the compact registry graph. For a newly requested photoproduct whose graph is still
empty, the explicit human pass records that hash-pinned definition graph in the registry;
a filename or arbitrary JSON document cannot advance the gate.

The diagnostic decisions available to a reviewer are enumerated in
`docs/photoproduct_human_review_checklist.md`; they supply annotations, not parameter
authority. Automated candidate generation cannot sign a human decision, and a human
decision cannot manufacture a quantitative pass.

While a form is unavailable, manual intent uses deterministic canonical key order and is
marked `canonical-key-order:parameters-unavailable`. After that form is released, create
preflight evaluates both directional endpoint-to-template assignments with proper
rotations only, ranks passing placements by anchor RMSD and maximum base displacement,
and persists `released-template-assignment-v1`. Older intent must be removed and recreated
before simulation; package generation never silently changes improper/patch orientation.

## TT-CPD catalog

NADOC tracks eight ordered, DNA-attached stereoisomers. This is the level required by a
design editor because endpoint identity and each sugar/backbone attachment are retained:

1. cis-syn-I (stored as the backward-compatible `cis-syn` key)
2. cis-syn-II
3. trans-syn-I
4. trans-syn-II
5. cis-anti-I
6. cis-anti-II
7. trans-anti-I
8. trans-anti-II

Taylor (2023), DOI `10.1111/php.13694`, distinguishes these eight DNA-level products and
assigns ordered C5 configurations R,S; S,R; S,S; R,R; S,S; R,R; R,S; and S,R,
respectively. Removing sugar/backbone identity collapses the cis-syn and trans-anti pairs
by symmetry, leaving the six hydrolysis products measured by Yang et al. (2026). The
six-product analytical catalog must therefore not be used as the NADOC design catalog.

These names and C5 assignments are discovery identities, not complete atom-level
definitions. The
`chemical_definition` gate for a product cannot pass until ordered endpoint atom maps,
signed stereocenters, protonation/tautomer state, and supported DNA contexts are encoded.
The canonical cis-syn-I entry currently has authoritative connectivity/geometry
references. The seven other entries remain definition-pending.

The six-hydrolysis-product experimental catalog in Yang et al. (2026), DOI
`10.1021/jasms.6c00014`, also fixes an important regioisomer distinction: syn TT-CPDs
are head-to-head (C5-C5 and C6-C6), whereas anti TT-CPDs are head-to-tail (C5-C6 and
C6-C5). The downloaded supporting-information PDF is pinned in
`photoproduct_structural_references.json`. It reports optimized sodium-adduct energies
but does not distribute coordinates, atom maps, or ordered absolute configurations, so
it supports the catalog/connectivity correction without passing the five pending
chemical-definition gates.

## Evidence gates

### 1. `chemical_definition`

- Define the complete ordered reactant-to-product atom map.
- Record bonds added/removed/retained, bond-order environment changes, protonation,
  tautomer, formal charge, and atom conservation.
- Encode absolute stereochemistry as signed atom quadruples; do not rely on a name or a
  mirrored template.
- Identify fitting and boundary-validation model compounds.
- Separate support claims for adjacent intrastrand, non-adjacent, crossover-extra, and
  interstrand contexts.

### 2. `qm_reference_data`

- Optimize all relevant product conformers using the recorded CGenFF-compatible QM
  protocol.
- Confirm minima by frequency analysis.
- Generate dipoles and model-compound/TIP3P water interactions for charge fitting.
- Generate Hessian/internal-coordinate data for changed bonds and angles.
- Generate relaxed torsion scans, including coupled surfaces for cyclobutane pucker and
  glycosidic coupling where one-dimensional scans are inadequate.
- Retain raw inputs, outputs, software versions, convergence records, and hashes.

The baseline additive protocol is MP2/6-31G(d) for geometry, Hessian, and torsion target
data and HF/6-31G(d) model-water interactions. Higher-level conformational single points
may supplement this protocol, but changing the primary target method requires an explicit
method decision and validation plan.

### 3. `parameter_fit`

- Use standard CHARMM36 terms unchanged only where the chemical environment is unchanged.
- Treat ParamChem/CGenFF assignments as initial guesses; penalty scores are not
  validation.
- Use the pinned CGenFF 5.0 `BMDU`/`BH2U` models as saturated-thymine-ring references
  and `CBU` as a cyclobutane-strain reference. Do not splice their values together and
  call the result a TT-CPD parameter set; the fused product response is the fit target.
- Fit joint product charges to the CHARMM water-interaction/dipole targets while enforcing
  exact pair charge.
- Fit changed bond/angle/Urey-Bradley terms to QM geometry and response.
- Fit dihedral phases, multiplicities, and amplitudes to training conformers/scans, and
  retain independent conformers as a test set.
- Refit Lennard-Jones parameters only if no existing type is chemically transferable;
  new LJ types require a separate condensed-phase validation plan.

Numerical parameters may be shared across stereoisomers only after an explicit
atom-type/graph permutation audit. Additive CHARMM bonded terms are ordinarily achiral,
but patch atom ordering, signed improper targets, and coordinate templates are not.
Therefore a shared `.prm` never implies a shared `PRES`, template, chemical-definition,
or context-validation gate.

The automated comparison follows the published CGenFF separation of responsibilities:
water interaction energies include both Coulomb and Lennard-Jones contributions, neutral
QM energies are scaled by 1.16, target distances are offset by −0.2 Å, and the neutral
dipole is targeted at 1.3 times the gas-phase QM vector. Endpoint-exchange charge symmetry
is imposed only after the constitutional graph (ignoring R/S labels) is audited as an
automorphism. Endpoint 1 is the fit set and endpoint 2 is held out. The initial comparison
must therefore be generated only after the LJ hypotheses are explicit:

```bash
uv run python scripts/photoproduct_workflow.py build-atom-type-candidates \
  --cgenff-topology /path/to/top_all36_cgenff.rtf \
  --model-manifest "$work_dir/models/n1-methyl/model_manifest.json" \
  --output "$work_dir/fit/atom_type_candidates.json"
uv run python scripts/photoproduct_workflow.py fit-nonbonded-hypotheses \
  --charge-targets "$work_dir/fit/charge_targets.json" \
  --atom-type-plan "$work_dir/fit/atom_type_candidates.json" \
  --cgenff-parameters /path/to/par_all36_cgenff.prm \
  --output "$work_dir/fit/nonbonded_hypothesis_fit.json"
```

This fit is a hypothesis comparison, not a release. It uses constrained least squares
followed by nonlinear fitting of parabolically interpolated water minima, dipole
components, and regularization to the starting charges. The selected charges must be
rechecked after bonded fitting at the MM minimum. The CGenFF 5.0 objective also uses ESP;
NADOC protocol 1.4 generates a deterministic four-shell Bondi surface and Psi4
`GRID_ESP` values. The first comparison reports ESP as held-out validation rather than
silently changing the established water/dipole fit objective. A later reviewed objective
may assign ESP a documented weight.

The current cis-syn-I comparison deliberately selects neither type hypothesis. The
general-carbon and cyclobutane-carbon candidates have nonlinear objective costs 16.18
and 16.44, held-out water-energy RMSEs 0.214 and 0.220 kcal/mol, and ESP RMSEs 0.01015
and 0.01016 atomic unit, respectively. Those small model-compound differences cannot
decide a bonded/Lennard-Jones model before the coupled bonded fit and condensed-phase DNA
validation. The machine-readable report records
`selection_status: deferred_no_hypothesis_selected`.

Before constructing an MM fitting target, audit every bond, angle, and proper in the
complete capped model graph—not only the terms that will eventually enter the DNA patch:

```bash
uv run python scripts/photoproduct_workflow.py audit-model-parameter-coverage \
  --model-manifest "$work_dir/models/n1-methyl/model_manifest.json" \
  --nonbonded-fit "$work_dir/fit/nonbonded_hypothesis_fit.json" \
  --hypothesis-id valence-matched-general-carbon-v1 \
  --cgenff-parameters /path/to/par_all36_cgenff.prm \
  --output "$work_dir/fit/model_coverage_general_carbon.json"
```

The audit hash-checks the explicit graph, type/charge hypothesis, and CGenFF file and
conserves the model charge. For the current 36-atom/38-bond cis-syn model, the
general-carbon hypothesis leaves 43 uncovered terms (6 of 72 angles and 37 of 114
propers); the cyclobutane-carbon hypothesis leaves 66 (12 angles and 54 propers). Both
cover all 38 bonds. This difference is useful fitting-cost evidence, not a type-selection
criterion, and neither result supplies the still-required complete improper list.

```bash
uv run python scripts/photoproduct_workflow.py generate-esp-job \
  --product-id tt-cpd-cis-syn \
  --model-id n1-methyl-tt-cpd-cis-syn \
  --xyz "$work_dir/qm/geometry/optimized.xyz" \
  --atom-map "$work_dir/models/n1-methyl/atom_map.json" \
  --parent-manifest "$work_dir/qm/geometry/optimized_model_audit.json" \
  --output-dir "$work_dir/qm/esp"
uv run python scripts/photoproduct_workflow.py run-qm-job \
  --job-dir "$work_dir/qm/esp" --psi4 /path/to/psi4 \
  --scratch-dir /media/jojo/Archive/NADOC_archive/qm_scratch/esp-run-id
uv run python scripts/photoproduct_workflow.py audit-esp \
  --job-dir "$work_dir/qm/esp"
```

### 4. `topology_patch`

- Create an ordered two-residue CHARMM `PRES` patch.
- Preserve precursor atom names, atom count, glycosidic bonds, and backbones.
- Apply all product atom types and charges and add exactly the two reviewed registry
  crosslinks: C5(1)-C5(2)/C6(1)-C6(2) for syn or
  C5(1)-C6(2)/C6(1)-C5(2) for anti.
- Define the required impropers and regenerate every affected angle/dihedral.
- Keep design base keys out of the topology; psfgen residue identities are resolved from
  atomistic provenance at package time.

### 5. `coordinate_templates`

- Build a versioned template for every supported ordered stereoisomer/context.
- Record the experimental or optimized source and extraction script.
- Fit without reflection, verify signed chirality, preserve backbone connectivity, and
  reject excessive displacement, strain, clash, or molecular piercing.
- Emit a machine-readable placement report.

The piercing audit derives the four-membered atom cycle from the reviewed product graph,
including its retained intrabase single bonds. It therefore triangulates
`1:C5-1:C6-2:C6-2:C5` for syn connectivity and
`1:C5-1:C6-2:C5-2:C6` for anti connectivity; a malformed, branched, or incomplete ring
fails closed instead of being forced through a syn-only atom order.

A released template must also contain one explicit allowed length interval for every
added and retained ring bond, an authority string for each interval, and the SHA-256 of
the matching reviewed parameter asset. Candidate generation leaves these fields empty and
marked `parameter_review_required`. Product placement reports every measured interval and
rejects a missing, duplicate, extra, or violated bound; there is no generic cyclobutane
length fallback.

### 6. `static_topology_audit`

- Prove conserved atom count and expected charge.
- Prove the two crosslinks and both retained intrabase C5-C6 bonds.
- Prove product types, charges, angles, dihedrals, impropers, exclusions, and reverse
  identity mapping.
- Reject any psfgen warning, guessed product heavy atom, duplicate term, missing parameter,
  or unverified asset hash.

### 7. `namd_smoke`

- Run a zero-step NAMD load/energy evaluation.
- Run staged local minimization and a short, real 2 fs explicit-solvent trajectory.
- Require finite energies, retained bonds/backbones/chirality, and no configuration or
  parameter warnings.
- Keep HMR and 4 fs disabled.

After a released-asset package has passed its static topology audit, prepare the exact
ordered smoke sequence inside that package:

```bash
uv run python scripts/photoproduct_workflow.py prepare-namd-smoke \
  --package-dir /path/to/package \
  --output-dir /path/to/package/cpd_smoke \
  --local-steps 500 --global-steps 1000 \
  --dynamics-steps 1000 --dcd-freq 10 \
  --mobile-radius-angstrom 6
```

The generator hash-checks every packaged lesion asset, requires the passed static PSF
audit and lesion parameter directive, and writes four configurations: load-only,
lesion/local-environment minimization, unrestricted global minimization, and ordinary-
mass 2 fs dynamics. The local mask leaves both lesion residues, adjacent DNA residues,
and every atom within the declared radius mobile. The output is
`prepared_not_run`/`gate_effect: none`; its stages must be run in order and their logs,
restart files, DCD, crosslink/backbone geometry, and signed chirality must still pass the
smoke-result audit before the gate can advance:

```bash
uv run python scripts/photoproduct_workflow.py audit-namd-smoke \
  --package-dir /path/to/package \
  --smoke-plan /path/to/package/cpd_smoke/smoke_plan.json \
  --output /path/to/package/cpd_smoke/namd_smoke_report.json
```

The auditor requires successful, diagnostic-free logs and hashed coordinate/cell outputs
for every stage, at least two 2 fs DCD frames, finite ENERGY records, retained CPD and
glycosidic bonds, and the required signed chirality in every frame. Its report remains
gate-neutral until a human review attaches it. No current product can invoke this path
because no released topology/parameter/template package exists yet.

### 8. `solution_validation`

- Compare isolated-product QM and MM geometry, response, conformer energies, and torsion
  surfaces.
- Simulate dinucleoside/dinucleotide boundary models in explicit water.
- Simulate multiple independent duplex replicas and compare lesion and neighboring DNA
  ensembles with experimental structures/NMR where available.
- Validate each claimed DNA context separately. Intrastrand success does not establish an
  interstrand orientation.
- Use matched reactant controls prepared by the same force-field and simulation protocol.

### 9. `release_review`

- Independently review chemistry, parameters, topology audit, trajectories, and licenses.
- Freeze the exact CHARMM36/CGenFF/NAMD dependencies and all asset hashes.
- State supported contexts and scientific limitations.
- Only then attach topology, parameter, template, and validation-report assets to the
  registry entry. Readiness is computed; there is no manual `available=true` shortcut.

## Local toolchain

The reproducible baseline is Psi4 1.11 in its own conda environment:

```bash
mamba env create -f environment.photoproduct-qm.yml
mamba run -n nadoc-qm psi4 --version
uv run python scripts/photoproduct_workflow.py doctor
```

This requires no `sudo` and no account. The current installation occupies approximately
1.9 GiB. Configure a dedicated scratch directory before production calculations and keep
scratch outside Git.

On this workstation `/media/jojo/Archive` is a writable 7.2-TiB ext4 volume. The doctor
reports its availability and recommends
`/media/jojo/Archive/NADOC_archive/qm_scratch`; each run must use its own child directory.
Durable manifests and final outputs stay outside scratch. Psi4 `PK` disk-integral water
jobs are rejected by the series runner because one 39-atom calculation consumed roughly
16 GiB of scratch. Protocol 1.3 uses density-fitted HF for those curves and requires
three identical-geometry comparisons against `DIRECT` HF with a maximum absolute
interaction-energy error of 0.02 kcal/mol before the approximation is accepted.

The installed VMD contains ffTK 1.1. It may help inspect parameterization targets, but the
reproducible driver generates Psi4 inputs and parses outputs without depending on
interactive GUI state. ForceBalance 1.9.5 and OpenMM 8.6 are pinned in the same
environment as an optimization harness; their output still requires the independent
CHARMM topology, parameter, and NAMD validation gates. Local NAMD 3 and psfgen are
available for integration tests.

Open Babel is installed in a separate `nadoc-stereo-audit` conda environment so its
stereochemical perception does not share RDKit implementation code. It requires no
account or `sudo`. Its audit proves hash-linked candidate coverage, independent isomeric
identifiers, and one constitutional graph for each syn/anti class, but cannot establish
the literature Roman-numeral mapping and does not replace human atom-mapped review:

```bash
mamba env create -f environment.photoproduct-stereo.yml
uv run python scripts/photoproduct_workflow.py audit-tt-cpd-stereo-openbabel \
  --series-manifest "$work_dir/stereo-candidates/candidate_series_manifest.json" \
  --candidate-audit "$work_dir/stereo-candidates/candidate_audit.json" \
  --openbabel "$HOME/miniforge3/envs/nadoc-stereo-audit/bin/obabel" \
  --output "$work_dir/stereo-candidates/openbabel_stereo_audit.json"
```

ORCA is an optional alternative that requires personal registration and acceptance of its
academic license; `/usr/bin/orca` on this workstation is the GNOME screen reader and is
explicitly rejected by the doctor. The CGenFF web service is also account/license-gated
and may only supply initial assignments, never a release decision.

## Requesting another product

Registering a future photoproduct creates only a definition-pending request:

```bash
uv run python scripts/photoproduct_workflow.py request \
  --id tt-six-four \
  --product TT-6-4PP \
  --stereochemistry configured \
  --label "TT (6-4) photoproduct" \
  --context adjacent-intrastrand
```

The command creates all nine pending gates and no assets. It cannot make the new product
simulation-ready. `list` and `doctor` are read-only:

```bash
uv run python scripts/photoproduct_workflow.py list
uv run python scripts/photoproduct_workflow.py doctor
```

## Compute policy

The first QM model compounds fit on the local 32-thread/30-GiB workstation. Conventional
Psi4 MP2 fitting work is CPU- and memory-dominated; the local RTX GPU and a cheap GPU pod
do not automatically accelerate one calculation. RunPod is nevertheless useful as
metered *CPU capacity* when a finite-difference Hessian, stereoisomer set, water series,
or torsion grid has already been split into immutable independent tasks and the measured
throughput justifies its cost. Reserve GPU acceleration for OpenMM candidate evaluation,
NAMD validation/production, or a separately benchmarked GPU-QM implementation. Never
change the QM target method merely to use available GPU time.

The workstation has an NVIDIA RTX 3080 Ti with 12 GB of device memory. The installed
NAMD Git-2025-12-04 executable reports CUDA 12.0 support and successfully binds to that
GPU. It is therefore the default device for product topology checks, staged minimization,
the mandatory ordinary-mass 2-fs smoke test, and modest explicit-solvent systems. Rent a
larger GPU only after the packaged system size or a short local throughput benchmark shows
that local memory or wall time is limiting; record that benchmark in the run manifest.

Use this stage boundary when deciding whether to offload work:

| Work | Useful accelerator | Policy |
| --- | --- | --- |
| One MP2 optimization or finite-difference Hessian | Shared-memory CPU | Keep the pinned Psi4 engine and method. A GPU pod is not presumed faster. |
| Independent stereoisomers, water points, conformers, or torsion points | Multiple CPU workers | May be distributed only as immutable, hash-linked jobs; reconcile and audit every returned output locally. |
| ForceBalance/OpenMM candidate evaluation | CUDA GPU, after an OpenMM representation exists | Useful for fitting iterations, but not release evidence in place of NAMD. |
| Explicit-solvent product minimization and dynamics | CUDA NAMD | Preferred use of rented GPU time; the ordinary-mass 2-fs NAMD smoke audit remains mandatory. |

RunPod publishes live Pod prices at <https://www.runpod.io/pricing> and bills Pod compute
and storage separately as described at <https://docs.runpod.io/pods/pricing>. Check the
deployment console immediately before spending money. On 2026-09-03 the public page
listed A40, RTX A6000, and L40S Pods at approximately USD 0.44, 0.53, and 0.99 per hour,
respectively; these observations are planning inputs, not reproducibility metadata. Record
the selected image digest, GPU model, NAMD version, wall time, and actual charge in the
validation evidence. Use an on-demand Pod for the non-resumable smoke test and set an
automatic shutdown; a preemptible Pod is acceptable only for checkpointed batch work.

Do not upload bulk Psi4 scratch or use a cloud volume as the evidence archive. Transfer
generated inputs plus manifests to a controlled container, and return final outputs,
engine/version records, and hashes. Keep the durable copy on the Archive drive. A remote
result does not pass a gate merely because its program exited successfully.

### Distributed numerical Hessians

Psi4 MP2 Hessians are finite differences of analytic gradients. NADOC can export the
exact Psi4 1.11 plan as independent QCSchema tasks without changing the method, basis,
displacement size, or symmetry reduction:

```bash
qm_python=/home/jojo/miniforge3/envs/nadoc-qm/bin/python
frequency_job="$work_dir/qm/stereo-frequencies/tt-cpd-trans-syn-i"
distributed="$frequency_job/distributed"

"$qm_python" scripts/photoproduct_workflow.py prepare-distributed-hessian \
  --job-dir "$frequency_job" --output-dir "$distributed"
```

When a prepared frequency job is being retained or resumed on Archive, materialize its
source geometry and passed optimized-model parent beside the job before the temporary
working tree is removed:

```bash
"$qm_python" scripts/photoproduct_workflow.py \
  materialize-frequency-job-provenance --job-dir "$frequency_job"
```

This writes byte-identical copies under `provenance/` and a hash-linked
`frequency_job_provenance.json`; it does not rewrite the immutable job manifest. The
validator prefers those local copies and fails closed if the relocation manifest or
either copy changes. The resumable local batch runner likewise accepts a distributed plan
copied to a new Archive path only when the supplied `job_manifest.json` and `input.dat`
still match the exact hashes embedded in the plan. Existing task run records therefore
remain valid—the plan bytes and plan SHA-256 are not changed merely to relocate storage.

Each task ID in `distributed_hessian_plan.json` can run independently, locally or on a
CPU-capable remote worker. Give every process its own scratch directory. For example, one
task is:

```bash
task_id=0001-0-1
"$qm_python" scripts/photoproduct_workflow.py run-distributed-hessian-task \
  --plan "$distributed/distributed_hessian_plan.json" \
  --task-id "$task_id" \
  --scratch-dir "/media/jojo/Archive/NADOC_archive/qm_scratch/fd-$task_id" \
  --threads 4 --memory-gib 6
```

The worker pins both QCEngine's sandbox and Psi4's process-global PSIO default to that
exact per-task directory. This is necessary because QCEngine 0.34's in-process PsiAPI
path creates its temporary sandbox under the requested location but does not itself set
the PSIO manager path. Without the explicit setting, multi-gigabyte DF/MP2 files fall
back to `/tmp`. A live trans-anti-II transition after the correction showed task 0074's
749 MB `psi.*.181` file open under its Archive task directory and no new `/tmp/psi.*`
file. Each run record now preserves both effective scratch paths for audit. It also
records the process working directory, which the local batch runner pins to the same
per-task Archive subtree so housekeeping files cannot accumulate in the repository.

The worker writes a complete QCSchema result and a run record beside that task. Do not
edit, concatenate, or hand-copy values between results. During a long campaign whose
source plan is temporarily outside Archive, checkpoint completed pairs periodically:

```bash
uv run python scripts/photoproduct_workflow.py checkpoint-distributed-hessian \
  --source-plan /temporary/work/distributed_hessian_plan.json \
  --destination-plan "$archive_root/distributed/distributed_hessian_plan.json" \
  --output "$archive_root/checkpoints/checkpoint-001.json"
```

The checkpoint command requires distinct plans with identical bytes, validates both task
input trees, and copies only complete successful result/run-record pairs. Existing pairs
must be byte-identical, half-pairs fail closed, and no destination evidence is overwritten.
Its report identifies copied, reused, and still-pending tasks and has no gate effect.

After every task returns:

```bash
"$qm_python" scripts/photoproduct_workflow.py assemble-distributed-hessian \
  --job-dir "$frequency_job" \
  --plan "$distributed/distributed_hessian_plan.json" \
  --output "$distributed/distributed_hessian_audit.json"

uv run python scripts/photoproduct_workflow.py audit-frequency \
  --job-dir "$frequency_job"
```

Assembly recreates the finite-difference plan from the pinned protocol and source
geometry, byte-compares every task input, verifies every result and engine version,
restores only QCSchema's JSON-to-array representation, and uses Psi4's own Hessian and
vibrational-analysis routines. It emits the same hash-audited Hessian and frequency-audit
artifacts consumed downstream. Missing, duplicated, altered, failed, or version-mixed
tasks fail closed. The canonical cis-syn Hessian was already in progress when this
facility was added and completed serially; subsequent unique TT-CPD Hessians should use
the distributed boundary.

The optional RunPod driver automates that exact task boundary. It is a CPU-capacity
offloader, not a GPU implementation of MP2. A read-only dry run is the default and writes
the live-market quote, immutable plan hash, proposed payload, and provider cutoff without
constructing the billing client:

```bash
uv run python scripts/runpod_photoproduct_hessian.py \
  --plan "$distributed/distributed_hessian_plan.json" \
  --output "$frequency_job/runpod-dry-run.json" \
  --storage-root "$archive_root" \
  --gpu-type-id "NVIDIA A40" \
  --budget-usd 2 --maximum-seconds 14400
```

Add `--execute` only after reviewing that report, together with a shared durable option,
for example
`--campaign-ledger /media/jojo/Archive/NADOC_archive/photoproduct_evidence/photoproduct-runpod-spend.json`.
Execution refuses to start without that ledger. The driver permits at most USD 10
cumulatively for this project, requires a live same-market Secure Cloud quote, requests an
absolute RunPod `terminateAfter` deadline, destroys the Pod when its context exits, and
starts a sibling user-systemd watchdog for that exact pod ID. The watchdog survives an
editor or terminal crash and destroys the pod if the controller identity disappears or
the local deadline arrives. It also refuses a second cloud offload while the shared ledger
contains an open billing Pod, so concurrent reservations cannot silently overbook the
campaign cap. It
uploads only the small source/protocol bundle and immutable QCSchema inputs, downloads
only expected regular result/run-record files, then assembles and audits locally. An
optional `--network-volume-id` caches the pinned environment, but pins capacity to that
volume's datacenter. Omitting it uses disposable container storage and allows placement in
any compatible datacenter; all evidence must be downloaded before teardown. Supply
rejection occurs before allocation and is recorded as a failed offload attempt, never as
scientific evidence. Completed task pairs are checkpointed locally every five minutes;
their hashes and parent-plan identity are rechecked before a later Pod may resume them.

The offloader recognizes both minimum-frequency plans and reviewed
`fixed_geometry_hessian` response plans. It selects the matching local assembly and
downstream audit without changing the generic remote gradient worker. Any `--execute`
invocation requires `--storage-root`; its transfer archives and temporary staging, plan,
report, and cumulative-spend ledger must all resolve beneath that root. Dry runs do not
allocate a pod. RunPod remains a CPU-capacity option for these Psi4 tasks—the attached
GPU does not accelerate the pinned MP2 calculations.

Size worker concurrency from `/sys/fs/cgroup/cpu.max`, not `nproc`: RunPod containers can
advertise every logical CPU on the host while enforcing a much smaller billing allocation.
The driver reads both CPU and memory cgroup limits after SSH and rejects an oversubscribed
request before installing or running Psi4.

The integration test `tests/test_photoproduct_distributed_hessian.py` runs a real
MP2/6-31G(d) nonlinear model both ways. Eleven independently serialized gradient tasks
reassemble to the same 9-by-9 Hessian as ordinary serial `frequency()` within a maximum
observed absolute element difference of `3.01e-8` hartree/bohr² (SCF numerical noise),
with the same three real vibrational modes. It then passes the standard NADOC frequency
and Hessian audit. This test is marked `slow` because it executes both real calculations;
mocks do not replace it.

The canonical cis-syn N-methyl model completed its independent Psi4 1.11
MP2/6-31G(d) frequency run on 2026-09-03. The audit found all expected 102 nonlinear
modes, zero imaginary modes, and a lowest mode of 41.5522 cm⁻¹. The Cartesian 108-by-108
Hessian has SHA-256
`82ee229681d2d93594c08af0e4488bc10ef04a03ba257fd26a5c7df26fc1c3ae` and maximum
symmetry error `1.11e-16` hartree/bohr². This passes the harmonic-minimum check only. Its
target bundle remains `partial_candidate_evidence_boundary_model_required` because the
N-methyl model cannot supply the two C1′–N1–C6 angle targets. A non-destructive evidence
copy, including the coordinate-template candidate, is stored under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions`.

The first full remote application, `tt-cpd-trans-syn-i`, ran 211 Psi4/QCEngine
displaced gradients on an on-demand RunPod L40S container. The GPU was unused; the
enforceable allocation was a 13.6-core cgroup despite `nproc` reporting 128 CPUs. Every
QCSchema result passed its hash, input-identity, engine-version, and success audit. Local
Psi4 assembly produced a 108-by-108 Hessian (SHA-256
`7ef8d86a69697308ae99e8895e863c4e898b530831c5ec7d1fad3e0deed4e2de`) with all 102
expected modes, no imaginary modes, and a lowest frequency of 38.3675 cm⁻¹. The billed
compute ledger records USD 1.819 for that Pod plus USD 0.034 for an earlier failed SSH
preflight, leaving USD 8.147 of the authorized USD 10 campaign.

During this first run, live `xargs` concurrency signals left the controlling SSH channel
waiting after all workers had exited. All 211 immutable result/run-record pairs were
checkpointed and independently assembled before the controller was interrupted; the Pod
was then confirmed destroyed. Consequently the original offload-controller report is
correctly `failed`, while the separate distributed-Hessian and frequency audits are
passed. The reusable driver now avoids that manual tuning, validates the cgroup quota,
checkpoints at a fixed interval, and supports hash-audited resume pairs.

The same driver completed `tt-cpd-cis-anti-i` on an A40 Pod with a measured 7.65-core,
50 GB cgroup allocation. All 211 records assembled, all 102 modes were real, and the
lowest mode was 56.4732 cm⁻¹; the Hessian SHA-256 is
`aedadc6b163b2385371687ee7c50512f8d02df0c084b3f007b2c80b3e9156d83`.
The controller exited normally, closed the spend ledger, and destroyed the Pod after
1.630 hours / USD 0.799. The locally distributed `tt-cpd-cis-anti-ii` calculation also
assembled all 211 records and passed with 102 real modes, lowest 57.2628 cm⁻¹, and Hessian
SHA-256 `9d306b8e5254c1f06c8be2f4d675b69412f33f391b54ba7bc3037c9b426f50b1`.
These are harmonic-minimum evidence only; both chemical definitions remain behind their
independent review gates. Campaign spend after cis-anti-I is USD 2.654, leaving USD 7.346.

### RunPod controller-loss incident and corrected safety boundary

On 2026-09-04, VS Code terminated the `tt-cpd-trans-anti-i` controller while its A40 Pod
`001tbe2hngei64` remained live. RunPod still reported the pod `RUNNING` roughly 6.3 hours
after the GraphQL `terminateAfter` timestamp. The exact pod was manually deleted through
the REST API and the account was then verified empty. Eight of 211 hash-paired gradient
tasks were recovered; no half-pair was accepted. The reconciled campaign estimate is USD
7.206, leaving USD 2.794 of the authorized USD 10.

Consequently, `terminateAfter` is retained only as provider-side defense in depth and is
not described as a hard billing boundary. `scripts/runpod_pod_watchdog.py` now polls the
provider from an independent user-systemd service, targets only its explicitly supplied
pod ID, recognizes the controller by PID plus `/proc` start time, retries provider/API
failures, and closes the campaign ledger only after the pod is absent from the account.
Launching a paid photoproduct offload fails closed if that service cannot be started. A
host reboot remains outside a transient user service's protection, so fully unattended
cloud use still requires a second off-host guard; no further campaign spend is authorized
on the provider timestamp alone.

The watchdog was exercised without renting a pod by starting its real user-systemd unit
against a deliberately nonexistent exact ID. The venv-preservation check first exposed and
then corrected an interpreter-symlink bug; the repeated run queried the live provider,
reported `provider_absent` with zero poll failures, appended both lifecycle records, and
collected its transient unit. Unit tests separately force owner loss, deadline expiry,
provider polling failure, PID reuse, and an unrelated live pod. No test performs a create
request.

The interrupted local `tt-cpd-trans-anti-ii` Hessian was initially restarted with four
workers, but user-systemd's OOM manager killed that 17.1 GiB service before it produced a
checkpoint. A two-worker recovery reached 92 complete result/run-record pairs. Those
pairs were hash-validated into the Archive plan, and the campaign was then resumed as
`nadoc-tt-cpd-trans-anti-ii-hessian-v4.service` with an 8 GiB declared QM memory envelope.
Its immutable plan, frequency job, task results, final batch report, and bulk scratch now
all live under `/media/jojo/Archive/NADOC_archive`; `/tmp` is no longer part of the live
campaign. This user service survives VS Code and terminal shutdown without relying on an
editor-owned process tree. No sudo access is required.

The trans-anti-II v4 calculation completed all 211 finite-difference gradients and
successfully assembled its 108-by-108 Hessian, then failed closed because the final
frequency auditor still dereferenced the retired parent `/tmp` path. The corresponding
trans-anti-I v2 waiter therefore exited without spawning QM. No calculation was lost or
repeated. The auditor now accepts only the same job-bound, hash-identical Archive
provenance copy used during planning and assembly. The local runner can recover from a
post-assembly audit failure only after revalidating every task input/result/run-record
hash, the assembly report, Hessian, QCSchema result, and run manifest.

That recovery produced passed trans-anti-II v5 batch-report SHA-256
`9917a7abb383c62b6f0e261f68e38f6de908b4b4a1496a65d1da8bd529e38403`.
It has 102/102 modes, zero imaginary modes, a 41.0574 cm^-1 lowest mode, and Hessian
SHA-256 `f83fdf6cf2c4113092cbc7989804b045011129f13ac47b45a4713713f949e67c`.
The independent trans-anti-I v3 campaign subsequently completed all 211 tasks under its
11 GiB service cap. Reopening every task pair and assembled artifact through the local
runner's recovery validators passed. The frequency audit has 102/102 modes, zero
imaginary modes, a 40.7600 cm^-1 lowest mode, and a 108-by-108 Hessian with maximum
symmetry error `1.11e-16` hartree/bohr². SHA-256 values are
`aede5689303b8368688185302edb3d9bc45fee93416567b76085c74981b42350`
for the Hessian,
`043f68b4ff451a87a2bebea5396ab596424e6fe52fdf6af54630b97c85e8a001`
for the frequency audit, and
`2059f111e559eba663c958a8482dba5fd9f9b8d3e55d85a1ceceb0416b246bed`
for the final batch report. The transient service exited with `Result=success`; its plan,
task outputs, scratch, and reports remain rooted below
`/media/jojo/Archive/NADOC_archive`.

Raw QM scratch, water boxes, and trajectories are experiment outputs and must not be
committed. Curated inputs, final outputs needed to reproduce the fit, compact validation
summaries, and hashes belong in the versioned photoproduct package.

The Archive drive is the authoritative bulk store on this workstation. The current durable
evidence snapshot is under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1`; active scratch
uses `/media/jojo/Archive/NADOC_archive/qm_scratch/<run-id>`. Snapshot copies omit live
scratch and are refreshed after audited milestones. The pinned February 2026 CHARMM
archive and its extracted public reference files are retained separately under
`/media/jojo/Archive/NADOC_archive/reference_forcefields/toppar_c36_feb26` (archive
SHA-256 `7d4d21ebdb216a48f600fadee862dc77d369a10d5753150635f35e09c3209e08`).

Repository storage is limited to source, tests, compact manifests, and intentionally
curated release assets. New QM campaigns, intermediate wavefunction/integral data,
parameter-fit workspaces, explicit-solvent systems, NAMD packages, and trajectories must
be created directly under the Archive root. A temporary path may be used only for an
ephemeral test whose output is neither authoritative nor expensive to regenerate.
The repository's ignored 22 GiB runtime `workspace/` tree was migrated byte-for-byte to
`/media/jojo/Archive/NADOC_archive/runtime/workspace` after a checksum-only rsync comparison
reported no differences. The original repository path is now a compatibility symlink to
that Archive directory, and the verified redundant root-disk copy was removed, increasing
free root space from 19 GiB to 41 GiB. The local API was restarted as the user service
`nadoc-api-archive-workspace.service`; its live operation log resolves through the symlink
onto Archive. This changes storage placement only, not simulation or chemistry state.
The local distributed runner also executes each Psi4 child with its per-task Archive
scratch directory as the process working directory. This contains Psi4's `timer.dat` and
`psi.*.clean` housekeeping files, which are independent of its configured PSIO path.

An audited frequency calculation can be converted into a stable-identity fitting input
without projecting coupled motion into ad hoc force constants:

```bash
uv run python scripts/photoproduct_workflow.py build-hessian-targets \
  --frequency-job-dir "$work_dir/qm/frequency" \
  --output "$work_dir/fit/hessian_targets.json"
```

The bundle hash-links the raw Cartesian Hessian (Hartree/bohr²), optimized coordinates,
frequency audit, chemical definition, and every affected bond/angle actually present in
that model. For the N-methyl model it returns
`partial_candidate_evidence_boundary_model_required` and lists the excluded C1′ boundary
terms; those require the separately reviewed d(TpT) model. It deliberately does not emit
final CHARMM values. Fit the coupled response in ForceBalance or an equivalently
documented optimizer, then validate held-out modes and conformers. ForceBalance 1.9.5
does not natively write CHARMM parameter files, so any OpenMM fitting representation must
be deterministically translated back and independently revalidated in psfgen/NAMD.

Join those targets to the complete model graph and one explicit coverage hypothesis
before constructing an optimizer representation:

```bash
uv run python scripts/photoproduct_workflow.py build-bonded-fit-plan \
  --model-manifest "$work_dir/models/n1-methyl/model_manifest.json" \
  --hessian-targets "$work_dir/fit/hessian_targets.json" \
  --model-coverage "$work_dir/fit/model_coverage_general_carbon.json" \
  --improper-convention-audit /path/to/improper_convention_audit.json \
  --output "$work_dir/fit/bonded_fit_plan_general_carbon.json"
```

This plan revalidates the 108-by-108 Hessian and exact graph-term enumeration, groups
uncovered terms by reversible CHARMM type signature, records every observed bond/angle/
proper coordinate, and carries the four signed-volume stereocenters. All force constants,
equilibrium values, Urey-Bradley values, and Fourier terms remain null. The current
general-carbon branch has 23 uncovered parameter groups (3 angle and 20 proper groups);
the cyclobutane-carbon branch has 25 (5 angle and 20 proper groups). The plans explicitly
forbid diagonal Hessian projection and require scans or multiple conformers for proper
Fourier choices. Neither plan selects a branch or advances a gate.

Every recorded proper and improper angle uses the explicit
`openmm_namd_four_atom_atan2_v1` convention. An earlier candidate plan used an auxiliary
geometry convention shifted by 180 degrees from OpenMM/NAMD for the same four-atom order;
those candidate plans are superseded and rejected by the fitting-system builder. The
corrected general-carbon and cyclobutane-carbon plan hashes are
`ab0004f013fe1145a4974475fda0991ac69d8ec9472bb51105e17359969d08bc` and
`d2c7ff2b32611737bc34f9120d6d7742412ff44d8c9f58f43bff4156d8480b91`.

The planner classifies each proper from the molecular graph before requesting a scan. It
removes the central bond and tests graph connectivity: a bond still connected by another
path is ring-constrained and must not be treated as a freely rotatable one-dimensional
torsion. In the general-carbon branch, all 37 uncovered proper occurrences are ring-
coupled. In the cyclobutane-carbon branch, 42 are ring-coupled and 12 are scan candidates
around the two base-methyl or fitting-cap methyl axes. Thus the expensive scan queue is
derived from topology rather than generated indiscriminately; cap-only scans cannot leak
into the DNA patch.

A deliberately incomplete OpenMM representation can now evaluate the covered branch
without filling any gap:

```bash
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-openmm-candidate-skeleton \
  --fit-plan "$work_dir/fit/bonded_fit_plan_general_carbon.json" \
  --nonbonded-fit "$work_dir/fit/nonbonded_hypothesis_fit.json" \
  --cgenff-topology /path/to/top_all36_cgenff.rtf \
  --cgenff-parameters /path/to/par_all36_cgenff.prm \
  --output-dir "$work_dir/fit/openmm-skeleton-general-carbon"
```

The builder converts CHARMM bond/angle/Urey-Bradley/proper and normal/1-4 nonbonded
conventions explicitly, preserves the stable atom map, and evaluates energy/forces on
OpenMM's Reference platform. It omits every uncovered term and all product impropers;
the XML is marked `simulation_ready: false` and must never be used for dynamics. The real
general-carbon skeleton includes 38/38 bonds, 66/72 angles, and 77/114 propers and gives
a finite diagnostic energy of -48.9908 kcal/mol. The cyclobutane branch includes 38/38,
60/72, and 60/114, respectively, and gives 8.3155 kcal/mol. These incomplete energies
are not comparable physical energies or a branch-selection criterion; they prove only
that the audited covered terms and nonbonded hypotheses have an executable fitting
representation. Both manifests and system hashes are archived outside Git.

Before importing either branch, the builder now verifies both input files against the
pinned CGenFF 5.0 / CHARMM36 February 2026 topology and parameter hashes in
`photoproduct_reference_forcefields.json`. A modified or substituted file fails before an
OpenMM system is constructed. The latest guarded, corrected-convention regenerations are
archived as `openmm-skeleton-valence-v4` and `openmm-skeleton-cyclobutane-v4`; their
manifest SHA-256 values are
`f0bf53be98f55d627bb8135d999773ab4cb756fc56af66bd6366d9801ce2bb3e` and
`64c8dfb5afce42330a8dd2d3e8e2c35479face18c746a061229f434bca587045`,
respectively. This strengthens provenance only and does not advance a chemistry gate.

The missing terms can be exposed to an optimizer without assigning them:

```bash
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-openmm-linear-fit-basis \
  --skeleton-manifest "$work_dir/fit/openmm-skeleton/candidate_skeleton_manifest.json" \
  --fit-plan "$work_dir/fit/bonded_fit_plan_general_carbon.json" \
  --output-dir "$work_dir/fit/openmm-linear-fit-basis"
```

For each missing angle this creates linear coefficients for theta-squared, theta, the
1--3 distance squared, and the 1--3 distance. For each missing proper it exposes signed
cosine coefficients for candidate CHARMM periodicities 1 through 6; periodicities must be
selected by regularized train/holdout fitting, not retained merely because they are in the
basis. Each ordered stereochemical improper gets a wrapped local quadratic and linear
coordinate. The physical transform is deterministic after fitting: positive harmonic
quadratic coefficients give K and the linear/quadratic ratio gives the equilibrium value;
signed proper coefficients map to positive K with phase 0 or 180 degrees. Nonpositive or
out-of-domain harmonic transforms are rejected.

Both real branches expose all variables (140 general-carbon; 148 cyclobutane-carbon),
compile on OpenMM's Reference platform, reproduce the incomplete skeleton with exactly
zero energy and force change at their zero defaults, and show finite nonzero unit responses
for angle, proper, and improper variables. Their manifests are archived under
`openmm-fit-bases`; SHA-256 values are
`de9c0c3c86f08953be3ac51f321751093c879c64d489201fbc319768ddae2195` and
`42d344444c6e3d3ef2bfdcaf387393cad9275c3083ef531a726bfc7895a38b35`.
They remain `simulation_ready: false`: all coefficients are zero, multiplicities are
unselected, and improper ordering is still candidate-only.

Differentiate that parameterized representation at the exact optimized QM coordinates to
create the actual force/Hessian design matrices:

```bash
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-openmm-linear-response \
  --fit-basis-manifest "$work_dir/fit/openmm-linear-fit-basis/linear_fit_basis_manifest.json" \
  --hessian-targets "$work_dir/fit/hessian_targets.json" \
  --step-angstrom 1e-4 \
  --output-dir "$work_dir/fit/openmm-linear-response"
```

The response bundle retains all 108 gradient components and all 5,886 unique elements of
the symmetric 108-by-108 Cartesian Hessian; no diagonal projection is used. It converts
the audited QM Hessian from Hartree/bohr-squared to kcal/mol/angstrom-squared and records
finite-difference step-halving and raw-symmetry diagnostics. It also stores the full
mass-weighted vibrational matrix after an Eckart projector removes exactly three
translations and three rotations; this retains all vibrational couplings and is distinct
from projecting onto individual internal-coordinate diagonals. The real general-carbon and
cyclobutane-carbon response matrices have shapes 5,886-by-140 and 5,886-by-148. At a
relative singular-value threshold of 1e-8, their Hessian blocks have ranks 88 and 115,
respectively (88 and 114 after rigid-body projection), so one minimum cannot identify all
candidate coefficients. This is useful
negative evidence: a direct least-squares solution would be underdetermined and must not
be promoted. The remaining stereoisomer/conformer Hessians, regularization, explicit
train/holdout selection, and sensitivity to force-versus-Hessian weighting are required.
The archived response-manifest hashes are
`79f650f03cd51d38d183b48dbf33970f372ab203ce466259abdd26feec2e88f7`
and `e9c23d8402e0dcb25e0c7884b0f78ba9337e847cc3ac3e35d89261fcbd68dec2`.
They were regenerated entirely under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/fit/cis-syn/archive-rebuild-v1`
from a source-derived model manifest whose references and outputs also resolve on Archive;
no copied `/tmp` path is authoritative.
All three artifact layers record the exact executing OpenMM build
(`8.6.0.dev-c6173db`) and NumPy version (`2.5.2`) in addition to their input hashes.

Resolve the broad rank count into auditable parameter-space null directions before
choosing any scan campaign or reduced torsion basis:

```bash
uv run python scripts/photoproduct_workflow.py \
  audit-openmm-fit-identifiability \
  --response-manifest "$work_dir/fit/openmm-linear-response/linear_response_manifest.json" \
  --fit-plan "$work_dir/fit/bonded_fit_plan.json" \
  --relative-threshold 1e-8 \
  --output "$work_dir/fit/fit_identifiability.json"
```

This diagnostic retains the full right singular space even when the 108-row gradient
block is wider than its parameter count, reports exact zero-response and near-collinear
columns, and attributes null-space participation to stable parameter groups. For the
general-carbon branch the projected gradient/Hessian ranks are 40/140 and 88/140; for the
cyclobutane-carbon branch they are 64/148 and 114/148. A diagnostic joint block divides
each homogeneous block by its own largest singular value before stacking; its ranks are
88/140 and 115/148, so the cyclobutane gradient resolves one additional direction without
being mistaken for a chosen force/Hessian objective weight. All remaining joint null-space
participation is in proper-dihedral groups. The result therefore establishes that more
equilibrium angle fitting is not the missing information. The audit now hash-links the
bonded fit plan and reports target requirements per unresolved group. Every currently
unresolved cis-syn dihedral occurrence has a central bond in a cycle and is classified
`coupled_ring_response_no_independent_scan`; the needed evidence is therefore
stereochemistry-preserving ring-pucker conformers with Cartesian Hessians. An independent
torsion scan through any of those cyclic central bonds is explicitly forbidden. It does
not select periodicities or fit values. Archived audit SHA-256 values are
`6b925ea600bcf4481d77e029266968a76b439ccbee2aad354ef84c636487c830`
and `8bc86c5633973a13ee5d74e56f043fb730daca797e64728b79003abbae6eca3c`
for the general-carbon and cyclobutane-carbon branches, respectively.

As independent stereoisomer minima, deliberately distorted conformers, and torsion-scan
targets become available, assemble their response matrices into an explicit training and
holdout campaign:

```bash
uv run python scripts/photoproduct_workflow.py \
  build-openmm-response-campaign \
  --training-response "$archive_root/responses/cis-syn/linear_response_manifest.json" \
  --training-response "$archive_root/responses/trans-syn-i/linear_response_manifest.json" \
  --validation-response "$archive_root/responses/cis-anti-i/linear_response_manifest.json" \
  --output-dir "$archive_root/fit/response-campaign-v1"
```

The campaign builder requires byte-identical linear parameter maps and stable atom maps,
rejects duplicate or overlapping training/validation identities, and hash-validates every
response, Hessian target, and array. Only training rows are written to the combined
response arrays. Validation responses remain separately referenced holdouts. Its
v2 off-equilibrium targets are reopened and their human-assigned `training` or
`validation` partitions are enforced, so a caller cannot silently swap a reviewed
holdout into the fit. Optimized-minimum v1 targets predate conformer partitions; their
campaign role remains an explicit caller decision recorded in the manifest. The
order-preserving rank progression reports whether each added dataset resolves a genuinely
new parameter-space direction. For this diagnostic only, each dataset's gradient and
Hessian blocks are divided by their own largest singular values before stacking; these
normalizers are not proposed objective weights. The artifact remains
`simulation_ready: false` and `gate_effect: none` even if the training design reaches full
rank. A reviewed fit, physical bounds, weighting sensitivity, and independent holdout
performance are still mandatory.

Before fitting, materialize the preregistered training-only objective specification:

```bash
uv run python scripts/photoproduct_workflow.py \
  build-quantitative-response-fit-specification \
  --campaign "$archive_root/fit/response-campaign-v1/response_campaign_manifest.json" \
  --output "$archive_root/fit/response-campaign-v1/fit_specification.json"
```

The v1 response-fit policy fixes equal-dataset weighting, scales the force and Hessian
blocks by the inverse squared RMS of training targets only, supplies a sorted ridge grid,
and sets basis-specific physical coefficient bounds. Validation values are not read while
these choices are made. Parameter name, fit group, category, units, order, campaign hash,
policy hash, and the required null `selection` are revalidated. The older
`build-response-fit-specification` command remains available for diagnostic human studies,
but is not required by the autonomous path.

Evaluate every reviewed regularization candidate without selecting one:

```bash
uv run python scripts/photoproduct_workflow.py \
  evaluate-response-fit \
  --campaign "$archive_root/fit/response-campaign-v1/response_campaign_manifest.json" \
  --specification "$archive_root/fit/response-campaign-v1/fit_specification.json" \
  --output-dir "$archive_root/fit/response-campaign-v1/ridge-evaluation-v1"
```

SciPy's bounded least-squares solver sees training rows only. The report gives per-dataset
and aggregate projected force/Hessian errors for both training and untouched validation
sets, plus a hash-pinned coefficient array for every ridge value. It deliberately leaves
`selection: null`, `simulation_ready: false`, and `gate_effect: none`.

Select a candidate for CHARMM mapping and smoke testing without a human gate:

```bash
uv run python scripts/photoproduct_workflow.py \
  select-quantitative-response-fit \
  --evaluation "$archive_root/fit/response-campaign-v1/ridge-evaluation-v1/response_fit_evaluation.json" \
  --output "$archive_root/fit/response-campaign-v1/selected_response_fit_candidate.json"
```

This requires a full-rank training design, rejects coefficient rows that cannot be
algebraically transformed into positive-curvature CHARMM angle/improper terms, scores
untouched validation force and Hessian errors in the preregistered dimensionless units,
and uses fixed regularization tie-breakers inside a 5% score window. The result remains
`simulation_ready: false`; topology and NAMD tests, not selection itself, decide whether
the candidate is usable.

After evaluating two or more periodicity hypotheses against the same physical datasets,
collate them for a like-for-like review:

```bash
uv run python scripts/photoproduct_workflow.py \
  compare-response-fit-evaluations \
  --evaluation "$archive_root/fit/n1-n2/response_fit_evaluation.json" \
  --evaluation "$archive_root/fit/n1-n3/response_fit_evaluation.json" \
  --output "$archive_root/fit/periodicity_fit_comparison.json"
```

The comparison reopens every campaign, specification, and coefficient archive. It
requires distinct hypothesis IDs and identical ordered physical training and validation
dataset identities. It preserves every candidate's errors and active-bound count while
leaving `selection: null`; it does not rank models or prefer a more flexible Fourier
basis merely because its training error is lower.

Generate the final human decision form from that neutral comparison:

```bash
uv run python scripts/photoproduct_workflow.py \
  build-response-fit-selection \
  --comparison "$archive_root/fit/periodicity_fit_comparison.json" \
  --output "$archive_root/fit/response_fit_selection.json"
```

The reviewer must choose an existing hypothesis and ridge value, set finite positive
limits for validation force RMSE/max-error and Hessian RMSE/max-error, cap the number of
active coefficient bounds, and record identity/time/rationale. Extraction fails if the
chosen candidate exceeds any declared limit:

```bash
uv run python scripts/photoproduct_workflow.py \
  extract-selected-response-fit \
  --selection "$archive_root/fit/response_fit_selection.json" \
  --output "$archive_root/fit/selected_response_fit_candidate.json"
```

The resulting stable-key coefficient table retains each scale and bound and hash-links
the selection, comparison, evaluation, coefficient array, and campaign. Its status is
`human_selected_candidate_requires_charmm_mapping_and_validation`: a linear coefficient
is not automatically a CHARMM bond equilibrium, angle equilibrium, Fourier amplitude, or
stereochemical improper. Mapping those quantities, reconciling shared terms, completing
charges/Lennard-Jones values, and validating the actual topology remain separate reviewed
steps.

Apply the fitting basis's exact algebraic inverse as another non-releasing artifact:

```bash
uv run python scripts/photoproduct_workflow.py \
  transform-selected-fit-to-charmm \
  --selected-candidate "$archive_root/fit/selected_response_fit_candidate.json" \
  --output "$archive_root/fit/charmm_bonded_transform_candidate.json"
```

For a quadratic `a*x^2+b*x`, the candidate transform requires `a > 0` and emits
`K = a`, `x0 = -b/(2*a)`; angle equilibria must lie between 0 and 180 degrees and
Urey–Bradley distances must be positive. A zero quadratic and zero linear Urey–Bradley
pair is treated as absent. Signed `c*cos(n*phi)` terms map to `K=abs(c)` with phase 0
degrees for nonnegative `c` and 180 degrees for negative `c`. Improper offsets use the
same positive-curvature transform around the reviewed reference and must not cross the
wrapped-angle boundary. Units, basis name, periodicity, reference angle, ordered improper
atoms, occurrence count, and the source coefficient names are retained.

This transform still has no final atom types or occurrence-to-parameter mapping and emits
no `.rtf` or `.prm`. It cannot substitute for reviewing shared CHARMM types, constant
energy offsets, improper removal, the complete workbook, or the real topology/NAMD
validation gates.

The constrained torsion-job generator accepts only
`nadoc.photoproduct-torsion-scan-plan.v2`. Each reviewed plan must hash-pin the complete
stable-key model graph. The generator proves that the middle two torsion atoms share an
acyclic single bond before writing a Psi4 input; a multiple, missing, or cyclic central
bond fails closed. CPD ring terms must instead use stereochemistry-preserving coupled
conformer/Hessian targets. This graph check applies to future photoproducts as well as
TT-CPD and prevents a reviewed-looking point list from bypassing molecular topology.

Campaign roots and QM scratch directories should be placed under
`/media/jojo/Archive/NADOC_archive`; the low-capacity system volume is not an authoritative
evidence store. A copied snapshot does not make absolute source paths relocatable, so new
jobs must be generated and executed directly from their final Archive work root.

The CHARMM improper sign/order convention is covered by a real-engine micro-test,
`tests/test_photoproduct_namd_improper_convention.py`. It builds a four-coordinate center
with psfgen, evaluates a nonzero harmonic improper in the installed CUDA NAMD 3, and
reflects one substituent while preserving all bond lengths and angles. The ordered
improper energy changes and the intended hand remains lower, proving that NAMD
distinguishes the two signs for that atom order. This validates the convention mechanism
only; product atom orders, equilibrium values, and force constants still require the
chemical-definition and parameter-fit reviews.

```bash
uv run python scripts/photoproduct_workflow.py audit-namd-improper-convention \
  --psfgen /path/to/psfgen --namd /path/to/namd3 \
  --output-dir /path/outside/git/namd-improper-convention
```

The local real-engine audit passed with invariant bond/angle energies and improper
energies of 1.8638 versus 21.8719 kcal/mol for the declared and reflected hands. Its
report SHA-256 is
`5a4a3e51a14d622a67dd114da62227b0688168796f8d8caeec30ccc069b12590`;
the report hash-links both executables, inputs, configs, and logs and is archived under
`tt-cpd-work-v1-completions/engine-audits/namd-improper-convention-v1`.

### Reviewed workbook to CHARMM candidate assets

The parameter workbook is the human-review boundary between numerical fitting and file
generation. It starts with null values and cannot pass its audit. A completed workbook
must contain every final patched charge/type, every local bonded term, an explicit choice
to emit or reuse each parameter, custom-type masses and Lennard-Jones values, ordered
product impropers, and an explicit review of which precursor impropers must be removed.
In particular, the saturated C5/C6 atoms may not retain their reactant THY types.

After those values and their sources are populated, render a candidate bundle only from
the passed hash-linked audit:

```bash
uv run python scripts/photoproduct_workflow.py audit-parameter-workbook \
  --workbook "$work_dir/fit/parameter_workbook.json"
uv run python scripts/photoproduct_workflow.py export-charmm-candidate \
  --workbook "$work_dir/fit/parameter_workbook.json" \
  --workbook-audit "$work_dir/fit/parameter_workbook_audit.json" \
  --output-dir "$work_dir/charmm-candidate"
```

The deterministic exporter translates NADOC/PDB names such as `C7` to the CHARMM/PSF
name `C5M` and writes a two-residue `PRES`, a parameter file, a topology-audit
specification, and a SHA-256 manifest. It never fits or guesses a value. Its manifest is
fixed to `gate_effect: none` and
`candidate_requires_psfgen_namd_solution_and_release_review`; these assets must still
survive the real static topology, NAMD smoke, context-validation, and independent-release
gates before they may be attached as released registry assets.

When the topology gate is eventually passed, attachment must preserve the exact patch
identity used by psfgen:

```bash
uv run python scripts/photoproduct_workflow.py attach-asset \
  --product-id tt-cpd-cis-syn --kind topology \
  --asset backend/data/forcefield/photoproducts/tt-cpd-cis-syn/photoproduct.rtf \
  --patch-name TCPDCS1
```

Omitting or misspelling the `PRES` name makes the registry asset audit fail closed.

## Reproducible cis-syn model-compound commands

Structural downloads are explicit, cached outside Git, and accepted only when they match
the hashes in the reviewed chemical definition. The first charge model retains the full
two-base CPD ring from CCD `TTD`, replaces each deoxyribose attachment with an N-methyl
cap, and audits all four signed stereocenters after construction:

```bash
work_dir=/path/outside/git/tt-cpd-cis-syn
uv run python scripts/photoproduct_workflow.py fetch-references \
  --cache-dir "$work_dir/references"
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py build-charge-model \
  --reference-dir "$work_dir/references/tt-cpd-cis-syn" \
  --output-dir "$work_dir/models/n1-methyl"
uv run python scripts/photoproduct_workflow.py generate-qm-job \
  --product-id tt-cpd-cis-syn \
  --model-id n1-methyl-tt-cpd-cis-syn \
  --xyz "$work_dir/models/n1-methyl/model.xyz" \
  --atom-map "$work_dir/models/n1-methyl/atom_map.json" \
  --model-manifest "$work_dir/models/n1-methyl/model_manifest.json" \
  --kind geometry_optimization --charge 0 --multiplicity 1 \
  --memory-gib 20 --threads 16 \
  --output-dir "$work_dir/qm/geometry"
uv run python scripts/photoproduct_workflow.py run-qm-job \
  --job-dir "$work_dir/qm/geometry" \
  --psi4 "$HOME/miniforge3/envs/nadoc-qm/bin/psi4" \
  --scratch-dir "$work_dir/scratch"
```

The runner rejects input-hash changes and refuses to overwrite existing output. A
successful run is recorded as `completed_unreviewed` with `gate_effect: none`; review,
frequency confirmation, target extraction, and validation remain required.

Model construction also emits a hash-linked `model_graph.json`. It records the complete
stable-key atom ordering, elements, formal charges, aromatic flags, and exact bond orders
independently of RDKit or an engine-specific topology. Downstream parameter fitting must
consume this graph instead of reconstructing connectivity from XYZ distances.

The 36-atom N-methyl model is appropriate for joint base charge/water-interaction targets
and changed ring terms. It is explicitly insufficient for sugar, phosphate, glycosidic,
or sugar-coupled torsion parameters. The separate DNA boundary model remains
review-only until its caps, protonation state, and charge constraints have been reviewed.
The implemented candidate is the cis-syn d(TpT) dinucleoside monophosphate extracted
from model 1 of RCSB 1N4E. It retains both deoxyriboses and the intervening −1
phosphodiester and adds explicit 5′-OH/3′-OH caps:

```bash
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-dna-boundary-model-candidate \
  --reference-dir "$work_dir/references/tt-cpd-cis-syn" \
  --chain B --endpoint-resid 15 --endpoint-resid 16 \
  --output-dir "$work_dir/models/dtpdt-boundary-chain-b"
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-dna-boundary-model-candidate \
  --reference-dir "$work_dir/references/tt-cpd-cis-syn" \
  --chain D --endpoint-resid 115 --endpoint-resid 116 \
  --output-dir "$work_dir/models/dtpdt-boundary-chain-d"
uv run python scripts/photoproduct_workflow.py audit-dna-boundary-replicates \
  --manifest "$work_dir/models/dtpdt-boundary-chain-b/candidate_manifest.json" \
  --manifest "$work_dir/models/dtpdt-boundary-chain-d/candidate_manifest.json" \
  --output "$work_dir/models/dtpdt-boundary-replicate-audit.json"
```

Both crystallographic copies retain the required four ring-center signs. A proper-rotation
heavy-atom comparison gives 0.181 Å RMSD (maximum 0.338 Å) without reflection. This is
experimental-copy variability, not an automatic acceptance threshold. The model has 63
atoms and charge −1; it remains blocked on independent cap/phosphate review before QM.
Its SDF uses the charge-separated P(+)/OP1(−)/OP2(−) Lewis form so resonance-equivalent
nonbridging oxygens do not create a false phosphorus stereocenter; the QM XYZ carries
only elements, coordinates, and total charge. This serialization choice is not parameter
authority.

The independently hashed `patch_charge_scope.json` prevents the fitting model boundary
from leaking into the NAMD patch: the 28 thymine-base atoms are retyped/recharged and sum
to zero, while both sugar C1′ atoms retain their CHARMM36 types/charges and appear only in
the affected bonded-term audit. Each neutral N-methyl cap is fitting-only.

The verified TTD graph can also produce all eight *review candidates* without reflection:

```bash
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  build-tt-cpd-stereo-candidates \
  --reference-dir "$work_dir/references/tt-cpd-cis-syn" \
  --output-dir "$work_dir/stereo-candidates"
mamba run -n nadoc-qm python scripts/photoproduct_workflow.py \
  audit-tt-cpd-stereo-candidates \
  --series-manifest "$work_dir/stereo-candidates/candidate_series_manifest.json" \
  --output "$work_dir/stereo-candidates/candidate_audit.json"
```

The generator preserves the canonical RCSB TTD endpoint face, inverts C5 and C6 together
for any selected endpoint (the suprafacial constraint), and rewires only C5-C5/C6-C6 to
C5-C6/C6-C5 for anti products. It checks the resulting ordered C5 labels against Taylor
(2023), conserves 36 atoms and zero charge, and records full four-center CIP assignments.
ETKDG/UFF coordinates and derived C6 labels remain candidate evidence. The audit says
`gate_effect: none`; independent atom-mapped review and QM minima are still mandatory.
Each candidate also carries the same engine-neutral `model_graph.json` contract as the
canonical charge model. The series audit reconstructs that graph independently from the
hash-linked SDF and rejects any atom, bond-order, or stable-key difference. A real
eight-member regeneration produced eight 36-atom/38-bond/net-zero graphs with unchanged
XYZ, atom-map, and SDF hashes relative to the preceding candidate series.

Ordered labels do not automatically mean distinct gas-phase model compounds. A narrowly
scoped equivalence audit is available when two independently perceived structures have
the same isomeric identifier and both optimizations pass identity/chirality checks:

```bash
uv run python scripts/photoproduct_workflow.py audit-model-equivalence \
  --first-job-dir "$work_dir/qm/cis-syn-i-geometry" \
  --second-job-dir "$work_dir/qm/cis-syn-ii-geometry" \
  --independent-stereo-audit "$work_dir/stereo-candidates/openbabel_stereo_audit.json" \
  --output "$work_dir/qm/cis-syn-i-ii-model-equivalence.json"
```

For the current cis-syn-I/II N-methyl pair, endpoint exchange plus a proper rotation
(determinant +1) overlays 20 heavy atoms at 9.29e-6 Å RMSD, their MP2/6-31G(d) energies
differ by 9.33e-10 hartree, and Open Babel gives the same full stereochemical InChIKey.
The immutable protocol snapshots also prove identical geometry-optimization settings.
Once the source frequency/Hessian itself passes audit, this permits a reviewed,
atom-permuted reuse of gas-phase N-methyl geometry/response targets and is why the
generated cis-syn-II frequency job need not be run. The equivalence report does not
claim that the source target has completed. It does not
equate the ordered DNA products, share coordinate templates, validate a DNA context, or
pass a registry gate. Other pairs may share data only if this exact audit passes; a name
or presumed enantiomer relationship is insufficient.

The reusable handoff is explicit rather than implicit. `build-equivalent-hessian-reference`
requires the passed source frequency audit and matrix, the source-to-target equivalence
audit, complete bijective stable-atom maps, the target optimization job, zero imaginary
modes, and matching hashes. It retains the source Cartesian frame and matrix order and
relabels only stable endpoint identity, so it performs neither an unrecorded Hessian tensor
rotation nor interpolation:

```bash
uv run python scripts/photoproduct_workflow.py build-equivalent-hessian-reference \
  --source-frequency-job-dir "$work_dir/qm/frequency-v1.4" \
  --equivalence-audit "$work_dir/qm/cis-syn-i-ii-model-equivalence.json" \
  --target-product-id tt-cpd-cis-syn-ii \
  --output "$work_dir/qm/cis-syn-ii-equivalent-hessian-reference.json"
```

The Archive-backed cis-syn reference passes this audit for all 36 atoms and the 108 × 108
Cartesian Hessian. Its review-packet label is
`passed_equivalent_source_candidate`, explicitly says that no independent cis-syn-II
frequency run occurred, and remains gate-neutral. The same command fails before writing
if the source matrix, minimum, geometry, target job, independent identifier, or atom
permutation is missing or changed.

Relocated optimization directories are accepted only when their job-local
`optimized.xyz` exactly matches the SHA-256 embedded in the immutable optimization audit.
The equivalence report records both declared and effective paths and whether relocation
occurred. The current trans-anti-I/II candidates do **not** pass the prerequisite: their
independent Open Babel stereochemical InChIKeys differ, so the audit fails closed before
any response reuse. Their frequency/Hessian calculations remain independent pending the
atom-mapped definition review.

Completed frequency jobs can likewise be made relocatable without rewriting their
immutable job manifests. `materialize-frequency-job-provenance` accepts explicit relocated
source geometry and parent-audit paths only when both hashes match the manifest, copies
them into the frequency job on Archive, and records declared and effective identity. The
Hessian-target builder consumes only that hash-linked copy. This recovery mode is allowed
after execution; new distributed plans still reject a frequency directory that already
contains execution evidence.

After the Open Babel audit, a hash-linked review artifact can be generated for each of
the seven noncanonical forms. It is intentionally not accepted by the runtime chemical-
definition loader and cannot pass the registry gate:

```bash
uv run python scripts/photoproduct_workflow.py build-tt-cpd-definition-candidate \
  --product-id tt-cpd-trans-syn-i \
  --candidate-manifest \
    "$work_dir/stereo-candidates/tt-cpd-trans-syn-i/candidate_manifest.json" \
  --candidate-audit "$work_dir/stereo-candidates/candidate_audit.json" \
  --independent-audit "$work_dir/stereo-candidates/openbabel_stereo_audit.json" \
  --output "$work_dir/definition-candidates/tt-cpd-trans-syn-i.json"
```

The output exposes the ordered C5 assignments, derived C6 assignments, signed-volume
references, syn/anti graph, and all source hashes for atom-by-atom human review. A failed,
missing, or hash-mismatched independent audit prevents even this review artifact from
being built.

Its embedded charge boundary is explicitly a `patch-charge-scope-candidate`: it
identifies the conserved base/sugar boundary but does not carry the canonical cis-syn
definition hash forward as if it belonged to a different isomer, and it approves no
charge or parameter transfer. Likewise, every noncanonical DNA boundary model has a
product-specific pending identity; 1N4E is not silently reused as its coordinate
template.

After a candidate model has a passed optimization and frequency audit, replace the
initial embedding used only for stereograph generation with the exact audited minimum:

```bash
uv run python scripts/photoproduct_workflow.py \
  build-minimum-backed-definition-candidate \
  --definition-candidate "$archive_root/definitions/tt-cpd-trans-syn-i.json" \
  --minimum-evidence "$archive_root/qm/tt-cpd-trans-syn-i/frequency_audit.json" \
  --optimized-xyz "$archive_root/qm/tt-cpd-trans-syn-i/provenance/source_geometry.xyz" \
  --optimized-model-audit \
    "$archive_root/qm/tt-cpd-trans-syn-i/provenance/optimized_model_parent.json" \
  --frequency-job-manifest "$archive_root/qm/tt-cpd-trans-syn-i/job_manifest.json" \
  --output "$archive_root/definitions-minimum/tt-cpd-trans-syn-i.json"
```

The command verifies the job/parent/XYZ/frequency/Hessian/output hash chain, stable atom
map, finite energy, zero imaginary modes, element identities, and all four signed-volume
sentinels. For a proved endpoint-exchange-equivalent form, pass its
`nadoc.photoproduct-equivalent-hessian-reference.v1` as `--minimum-evidence` and omit the
three direct-evidence path options. That branch retains the source coordinate frame,
records that no independent target frequency was run, and adds a specific human-review
blocker. Both branches remain candidate-only and have no gate effect.

Collate all seven candidates into one independently checkable human-review packet after
generating them individually:

```bash
uv run python scripts/photoproduct_workflow.py \
  build-tt-cpd-definition-review-packet \
  --definition-candidate "$archive_root/definitions/tt-cpd-cis-syn-ii.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-trans-syn-i.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-trans-syn-ii.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-cis-anti-i.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-cis-anti-ii.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-trans-anti-i.json" \
  --definition-candidate "$archive_root/definitions/tt-cpd-trans-anti-ii.json" \
  --candidate-audit "$archive_root/stereo-candidates/candidate_audit.json" \
  --independent-audit "$archive_root/stereo-candidates/openbabel_stereo_audit.json" \
  --frequency-audit "$archive_root/qm/tt-cpd-trans-syn-i/frequency_audit.json" \
  --output-dir "$archive_root/review/definition-packet-v1"
```

The builder independently verifies every definition, candidate manifest, SDF/XYZ/atom
map/graph, series audit, Open Babel record, and optional frequency audit. Hash-identical
Archive copies may replace stale embedded temporary paths, so the resulting packet does
not depend on `/tmp`. Its Markdown comparison displays orientation, ordered C5 and C6
assignments, exact crosslinks, independent InChIKey, and available minimum evidence, then
leaves explicit `APPROVE`/`REJECT`/`REVISE` fields blank for a human reviewer. It cannot
write a reviewed definition or change a gate.

The current real packet is stored at
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-human-review-packet-v7`.
It contains all seven noncanonical forms, all six independently computed noncanonical
minima, and the hash-proved cis-syn-II endpoint-exchange equivalent-Hessian reference.
Each definition's ring-coordinate sentinels now come from that exact direct or equivalent
minimum; the packet embeds the independently revalidated evidence record and exposes its
origin in the reviewer-facing comparison table.
It has no effective `/tmp` dependency and recursively passes all path/hash checks.
SHA-256 values are
`06f20e5b04ac4ae178a778b17e0cc326fb897d8ae386e8f61e1786a202322782`
for JSON and
`f8cff65cbef951f4d4fee43006dd15c97c8956bb68cd9ccdc8358b0aebeb8f50`
for Markdown. Its status remains `human_review_required`, `simulation_ready: false`, and
`gate_effect: none`; the complete minimum evidence does not substitute for the required
independent atom-mapped decisions.

### Ingesting completed chemical-definition decisions

Do not edit a candidate into the runtime force-field tree directly. A qualified reviewer
first fills every `human_decision` object in the JSON packet, changes only the top-level
`status` to `human_review_complete`, and signs one exact SHA-256 per decision:

- `APPROVE` signs the proposed released-schema chemical-definition JSON;
- `REJECT` or `REVISE` signs a separate evidence/rationale file; and
- any atom-map, endpoint-order, graph, coordinate, or stereocenter correction is
  `REVISE`, followed by candidate regeneration and a new review packet. It is not an
  approval of an altered candidate.

An approved file must use `nadoc.photoproduct-chemical-definition.v1`, include immutable
source/license records, omit candidate-only status/evidence/charge-scope fields, and retain
the exact reviewed chemical identity. Audit the completed packet from Archive, supplying
one mapping argument per product decision:

```bash
uv run python scripts/photoproduct_workflow.py audit-tt-cpd-definition-review \
  --packet "$archive_root/review/definition-packet-v1/definition_review_packet.json" \
  --reviewed-definition \
    tt-cpd-trans-syn-i="$archive_root/review/releases/tt-cpd-trans-syn-i.json" \
  --decision-evidence \
    tt-cpd-cis-anti-i="$archive_root/review/decisions/tt-cpd-cis-anti-i-revise.md" \
  --output "$archive_root/review/definition-packet-v1/ingestion_audit.json"
```

Repeat `--reviewed-definition PRODUCT_ID=PATH` for every `APPROVE` and
`--decision-evidence PRODUCT_ID=PATH` for every `REJECT`/`REVISE`. The command reopens the
registry snapshot, candidate and Open Babel audits, each candidate manifest/output,
optional direct/equivalent Hessian evidence, every candidate definition, and every signed
decision artifact. It also recomputes the four signed-volume sentinels in each approved
release. The resulting `nadoc.tt-cpd-definition-review-ingestion-audit.v1` remains
`simulation_ready: false` and `gate_effect: none`; rejected/revision products are listed as
unresolved.

Only after that audit passes should the exact approved definition and the compact audit be
curated under `backend/data/forcefield/photoproducts/<product-id>/`, attached with
`attach-asset`, and independently passed through `review-gate`. Those explicit operations
remain separate so packet ingestion cannot mutate the registry. Running the command on
the blank packet fails before output creation, as intended.

Generated jobs of one kind can be grouped into a fail-fast, resumable series:

```bash
uv run python scripts/photoproduct_workflow.py build-qm-series \
  --job-dir /path/to/job-a --job-dir /path/to/job-b \
  --output /path/to/series_manifest.json
uv run python scripts/photoproduct_workflow.py run-qm-series \
  --series-manifest /path/to/series_manifest.json \
  --psi4 "$HOME/miniforge3/envs/nadoc-qm/bin/psi4" \
  --scratch-root /media/jojo/Archive/NADOC_archive/qm_scratch/run-id \
  --max-parallel 2
```

Only a bounded number of children are submitted. After the first observed failure, no
new child is started; already running children finish and retain their evidence.

An optimization that reaches only Psi4's iteration limit can be continued without
editing or overwriting its evidence. The retry builder accepts no other failure class,
extracts the final complete Cartesian geometry, verifies the failed input/output/run and
model-manifest hashes, and regenerates the same method, basis, charge, multiplicity, and
convergence criterion with only a larger iteration ceiling:

```bash
uv run python scripts/photoproduct_workflow.py retry-geometry-job \
  --failed-job-dir /path/to/failed-geometry-job \
  --maximum-iterations 100 \
  --output-dir /path/to/new-retry-job
uv run python scripts/photoproduct_workflow.py run-qm-job \
  --job-dir /path/to/new-retry-job --psi4 /path/to/psi4 \
  --scratch-dir /media/jojo/Archive/NADOC_archive/qm_scratch/retry-id
```

The retry manifest records the parent job, run, and raw-output hashes and the failed
final energy. It remains unreviewed and has no capability-gate effect; a successful
continuation still requires the ordinary reconciliation, chirality, and frequency
audits. A chemically changed protocol or a convergence failure other than the iteration
limit must instead become a new, explicitly reviewed calculation.

The first exercised retry was trans-syn-I. Its original 50-step job missed only the
maximum-displacement threshold (6.40e-5 versus 6.00e-5); restarting from that exact final
geometry completed normally at −983.9500268106 hartree without relaxing convergence.
The four signed stereocenters remained correct and the four product-ring bonds were
1.5436–1.5834 Å. This is passed candidate-identity evidence, not a minimum or chemical-
definition approval: frequency confirmation and independent atom-mapped review are still
required.

Generate the topology-term inventory before assigning any product atom type:

```bash
uv run python scripts/photoproduct_workflow.py inventory-bonded-terms \
  --product TT-CPD --stereochemistry cis-syn \
  --output "$work_dir/bonded_term_inventory.json"
```

For the reviewed local thymine graph, the two crosslinks generate 2 bonds, 12 angles, and
42 proper-dihedral paths once both crosslinks and their neighboring bonds are considered.
The complete local retyping audit covers 12 bonds, 38 angles, and 86 proper dihedrals, in
addition to the two C5=C6 to C5−C6 order changes. These are topology paths, not a claim
that all require unique numerical parameters: after product types are assigned, the
parameter matcher must prove which terms are existing validated CHARMM terms and which
require fitting. Four stereochemical impropers are listed as `review-required` rather
than inferred from connectivity.

The official CGenFF 5.0 `1MTH` residue supplies a reproducible initial charge guess for
the N-methyl model. Extraction verifies the 6.2 MiB topology file against its pinned hash,
maps all 36 atoms, checks total charge and both neutral methyl caps, and deliberately
leaves every final product type/charge null:

```bash
uv run python scripts/photoproduct_workflow.py extract-initial-charges \
  --cgenff-topology /path/to/toppar/top_all36_cgenff.rtf \
  --model-manifest "$work_dir/models/n1-methyl/model_manifest.json" \
  --output "$work_dir/fit/initial_charges.json"
```

This operation does not require the licensed CGenFF assignment binary because `1MTH` is
already part of the public, pinned force-field distribution. It performs no product atom
typing and does not pass a gate.

Candidate type assignments must be checked against both the pinned CGenFF 5.0 and
CHARMM36 nucleic-acid parameter files before fitting. The audit retains every source line
and Fourier multiplicity, handles forward/reverse and `X` wildcard matching, and is
explicitly gate-neutral:

```bash
uv run python scripts/photoproduct_workflow.py audit-parameter-coverage \
  --atom-type-plan "$work_dir/fit/atom_type_candidates.json" \
  --hypotheses backend/data/forcefield/photoproduct_nonbonded_fit_hypotheses.json \
  --cgenff-parameters /path/to/par_all36_cgenff.prm \
  --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
  --output "$work_dir/fit/parameter_coverage.json"
```

For cis-syn-I, the general-carbon hypothesis matches all 12 bond instances but leaves
8 of 38 angle and 41 of 86 proper-dihedral instances unmatched (49 total; 6 unique angle
and 32 unique dihedral type patterns). The cyclobutane-carbon hypothesis also matches all
12 bonds but leaves 12 angles and 48 dihedrals unmatched (60 total; 6 and 25 unique type
patterns). These counts are coverage evidence, not a preference between hypotheses.
They prove that a product parameter file requires substantial coupled QM fitting; neither
candidate can be released by copying its matching terms and guessing the remainder.

## Help-menu trajectory release

`Help ▸ TT-CPD Model Trajectories…` reads the same eight-isomer registry. The viewer labels
each missing gate and makes no animation available until the product is fully
`simulation_ready` and has a hash-verified `help_trajectory` asset. Thus a passed
`namd_smoke` alone cannot publish a candidate that still lacks solution validation or
independent release review. The asset schema stores
stable atom keys, elements, bonds, coordinates in ångström, the exact 2 fs sampling
interval, and NAMD provenance. This is deliberately distinct from the KIMMDY
reactant-propensity visualization.

The backend rejects missing, hash-mismatched, wrong-product, or malformed trajectory
assets. It also requires the trajectory's parameter and NAMD-smoke-report hashes to match
the corresponding current registry assets. At least two frames, finite coordinates,
strictly increasing source-frame indices, unique non-self bonds, and supported element
labels are required. A future release therefore adds the real downsampled NAMD trajectory
to the product package; it must never substitute an interpolated bond-forming cartoon.

After a real 2 fs smoke report and static PSF audit pass, the release asset is built from
the actual DCD. The exporter resolves the two ordered residues from audit metadata,
rechecks the registry's exact syn/anti crosslinks in the PSF, verifies the DCD timestep,
and downsamples existing frames only:

```bash
uv run python scripts/photoproduct_workflow.py build-help-trajectory \
  --product-id tt-cpd-cis-syn \
  --dcd /path/to/smoke.dcd --psf /path/to/product.psf \
  --parameters /path/to/product.prm \
  --static-topology-audit /path/to/static_topology_audit.json \
  --namd-smoke-report /path/to/namd_smoke_report.json \
  --output backend/data/forcefield/photoproducts/tt-cpd-cis-syn/help_trajectory.json
```

## Archive storage and coupled-conformer evidence

All photoproduct CLI commands accept a global `--storage-root` (or
`NADOC_PHOTOPRODUCT_STORAGE_ROOT`). It resolves symlinks and rejects generated output,
cache, scratch, job, plan, or series paths outside that root before dispatch. On this
workstation, use:

```bash
export NADOC_PHOTOPRODUCT_STORAGE_ROOT=/media/jojo/Archive/NADOC_archive
```

The selected storage root remains explicit, so portable installations can choose another
durable filesystem. The local distributed Hessian runner has its own storage-root check,
and Psi4 subprocess working directories also live beneath Archive scratch.

On this workstation the shared guard additionally verifies that `/media/jojo/Archive` is
an actual mounted filesystem before any CLI, local Hessian/response runner, or RunPod
controller accepts a storage root beneath it. If the drive is unmounted, the command fails
before dispatch instead of writing into the system disk's empty mount-point directory.
Other explicitly selected durable roots remain portable and supported.

An optimized minimum has zero target gradient, but a deliberately puckered fitting
geometry does not. QM protocol 1.5.0 adds `fixed_geometry_hessian`: it accepts only a
hash-pinned, explicitly human-reviewed coupled-conformer plan, performs no optimization
or reflection, preserves stable atom order, and records both the analytic gradient and
full Cartesian Hessian. Target-bundle v2 feeds the actual QM gradient into the OpenMM
residual (`QM - base MM`) instead of assuming zero. Every artifact remains
`simulation_ready: false` and `gate_effect: none`.

Reviewed fixed-geometry jobs can use the same independent displaced-gradient worker
boundary without inheriting the harmonic-minimum interpretation of a frequency job:

```bash
fixed_job="$archive_root/qm/coupled-response/conformer-001"
distributed="$fixed_job/distributed"

"$qm_python" scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  prepare-distributed-fixed-hessian \
  --job-dir "$fixed_job" \
  --output-dir "$distributed"

"$qm_python" scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  run-distributed-hessian-task \
  --plan "$distributed/distributed_hessian_plan.json" \
  --task-id 0000-reference \
  --scratch-dir "$archive_root/qm_scratch/fixed-conformer-001-0000" \
  --threads 4 --memory-gib 4

"$qm_python" scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  assemble-distributed-fixed-hessian \
  --job-dir "$fixed_job" \
  --plan "$distributed/distributed_hessian_plan.json" \
  --output "$distributed/distributed_fixed_hessian_audit.json"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  audit-fixed-geometry-hessian --job-dir "$fixed_job"
```

For a full local campaign, the resumable runner performs the same worker calls with
bounded parallelism, validates already-complete task pairs, assembles both derivatives,
and writes a final gate-neutral batch report:

```bash
"$qm_python" scripts/run_local_photoproduct_response.py \
  --plan "$distributed/distributed_hessian_plan.json" \
  --job-dir "$fixed_job" \
  --scratch-root "$archive_root/qm_scratch/fixed-conformer-001" \
  --output "$fixed_job/local_fixed_hessian_batch.json" \
  --storage-root "$archive_root" \
  --max-parallel 2 --threads 4 --memory-gib 4
```

The runner is crash-resumable at complete result/run-record pairs, refuses altered or
half-written pairs, and can revalidate a prior assembly/audit without overwriting it.
Its child working directories are the per-task Archive scratch directories, keeping
Psi4 housekeeping files off the low-capacity repository volume.

Preparation revalidates the accepted conformer, its human-assigned training/validation
partition, stable atom map, exact geometry hash, no-reflection/no-optimization policy,
and the `fixed_geometry_hessian` protocol key before importing Psi4. Assembly recreates
and byte-compares every QCSchema input and preserves Psi4's center gradient as well as
the full symmetric Hessian. The downstream audit also requires and retains the finite
center electronic energy and binds it to the exact geometry hash. It is evidence for a
later reviewed relative-energy objective; it is not automatically fitted because an
absolute MM/QM offset and cross-isomer comparison policy must be chosen explicitly. The
assembler performs no frequency analysis and cannot label the distorted structure a
minimum. A separate ordinary fixed-geometry audit is still needed before building
target-bundle v2.

The review audit compares identity, structure, labels, booleans, and integers exactly.
Finite derived metrics alone use a `1e-12` relative/absolute tolerance because the main
and pinned QM environments may use different BLAS/LAPACK builds whose proper-rotation
SVD differs in the final floating-point bits. This tolerance is far below every geometry
review threshold and does not relax hash, chirality-sign, or pass/fail checks.

The real integration test
`tests/test_photoproduct_coupled_conformer.py::test_real_psi4_distributed_fixed_hessian_round_trip`
ran 43 independently serialized Psi4 1.11 MP2/6-31G(d) gradient tasks from an intentionally
small synthetic model, assembled a finite 24-component gradient and 24-by-24 symmetric
Hessian, and passed the normal fixed-geometry response audit. After the electronic-energy
requirement was added, a clean Archive-backed repetition passed in 84.12 seconds and
retained the finite `-4.080819004689648` hartree center energy bound to its exact geometry
hash. This validates execution and transport only; the synthetic model provides no TT-CPD
chemistry evidence.

Candidate generation ranks mass-weighted minimum-Hessian modes by proper-rotation
four-membered-ring pucker/torsion response while penalizing ring-bond strain, then applies
paired displacements. Every result is checked for all four signed stereocenters, graph-
bond distortion, nonbonded clashes, atom order, and proper-rotation RMSD. This is a
sampling heuristic, not conformer authority; a human must accept/reject each structure
and reserve an independent validation partition.

The cis-syn-I v3 set contains 36 safe structures from six mode pairs at
0.03/0.06/0.10 Å active-ring RMS displacement. Three additional modes failed the
smallest-amplitude graph/chirality precheck. Its Archive manifest SHA-256 is
`c90dcf6a16d806df8c4e6a5cc352414342ab43e478cd2e08835ff36058c3044c`.

A cheap OpenMM screen differentiates the fit basis at each candidate before QM. The
resulting complexity ladder is:

| Periodicities tested | Parameters | Minimum rank | Screened rank |
| --- | ---: | ---: | ---: |
| 1–2 | 68 | 68 | 68 |
| 1–3 | 88 | 86 | 88 |
| 1–4 | 108 | 102 | 108 |
| 1–6 | 148 | 115 | 143 |

The overcomplete n=1–6 nullity is concentrated in four six-term proper-dihedral groups;
it is a model-selection warning, not permission to launch unlimited Hessians. The
machine-readable comparison at
`$NADOC_PHOTOPRODUCT_STORAGE_ROOT/photoproduct_evidence/tt-cpd-work-v1-completions/fit/cis-syn/periodicity-hypotheses/periodicity_rank_comparison_v1.json`
has SHA-256 `e613b718a473a89c575aeda036ffd9160889dbebf6930e0926448a598e545535`
and deliberately leaves `selection` null. Fit the nested hypotheses with regularization
and physical bounds, compare force/Hessian/relative-energy/geometry errors on held-out
QM structures, then record an independent human decision.

Four high-information structures are collated in Archive packet
`coupled-conformer-review-v1` (SHA-256
`bd45a05ff7baffc101ea6dc06ff857e3157b0d42bcb86cde32f903f079323722`).
Its review, partition, and decision fields are blank. No fixed-geometry QM job can be
generated until a qualified reviewer completes them.

### All-form conformer review preparation

The seven noncanonical TT-CPD definitions can be prepared for conformer review without
weakening the chemical-definition gate. `build-coupled-conformer-mode-source` emits a
`nadoc.photoproduct-conformer-mode-source.v1` artifact with
`contains_parameter_targets: false`. It verifies the full minimum/frequency/hash chain,
stable atom order, zero imaginary modes, and product chirality, but it is deliberately not
accepted as a Hessian fit-target bundle. For an audited endpoint-exchange equivalent, the
builder permutes the geometry atoms and both Cartesian Hessian axes in lockstep. It applies
no mirror, spatial transform, tensor rotation, or interpolation.

Use that source to generate a review queue, then collate pristine queues into a compact
cross-product index:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-mode-source \
  --frequency-job-dir "$archive_root/qm/product/frequency" \
  --model-graph "$archive_root/models/product/model_graph.json" \
  --atom-map "$archive_root/models/product/stable_atom_map.json" \
  --stereochemistry-evidence "$archive_root/definitions/product.json" \
  --output "$archive_root/fit/all-forms/mode-sources/product.json"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-candidates \
  --mode-source "$archive_root/fit/all-forms/mode-sources/product.json" \
  --model-graph "$archive_root/models/product/model_graph.json" \
  --atom-map "$archive_root/models/product/stable_atom_map.json" \
  --stereochemistry-evidence "$archive_root/definitions/product.json" \
  --active-atom 1:C5 --active-atom 1:C6 \
  --active-atom 2:C5 --active-atom 2:C6 \
  --output-dir "$archive_root/fit/all-forms/candidates/product"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-review \
  --product-id tt-cpd-product --model-id n1-methyl-tt-cpd-product \
  --mode-source "$archive_root/fit/all-forms/mode-sources/product.json" \
  --model-graph "$archive_root/models/product/model_graph.json" \
  --atom-map "$archive_root/models/product/stable_atom_map.json" \
  --stereochemistry-evidence "$archive_root/definitions/product.json" \
  --candidate-manifest \
    "$archive_root/fit/all-forms/candidates/product/coupled_conformer_candidates.json" \
  --candidate-selection-policy top-two-modes-both-signs-largest-amplitude-v1 \
  --output "$archive_root/fit/all-forms/review/product/review.json"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-review-index \
  --review-plan "$archive_root/fit/all-forms/review/product-a/review.json" \
  --review-plan "$archive_root/fit/all-forms/review/product-b/review.json" \
  --output-dir "$archive_root/fit/all-forms/review-index-v1"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-review-visualization \
  --review-index \
    "$archive_root/fit/all-forms/review-index-v1/coupled_conformer_review_index.json" \
  --output-dir "$archive_root/fit/all-forms/review-visualization-v1"

uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  build-coupled-conformer-review-decisions \
  --review-index \
    "$archive_root/fit/all-forms/review-index-v1/coupled_conformer_review_index.json" \
  --output "$archive_root/fit/all-forms/conformer-review-decisions-v1.json"
```

The deterministic queue selects both signs of the two modes with the largest active-ring
fraction at the largest generated displacement. That policy is only a manageable review
queue, not a claim that those four structures are optimal training data. A qualified
reviewer must inspect each XYZ, accept or reject it, assign every accepted structure to a
training or validation partition, and explain the decision. Fixed-geometry QM generation
then independently requires that the released chemical definition exactly match the
reviewed candidate's ordered stereocenters.

After editing one source plan, produce a deterministic review receipt before spending QM
time:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  audit-coupled-conformer-review \
  --plan "$archive_root/fit/all-forms/review/product/review.json" \
  --output "$archive_root/fit/all-forms/review/product/review_audit.json"
```

The audit recomputes all hashes, chirality, geometry, deterministic candidate selection,
and training/validation completeness. It writes a gate-neutral receipt only. The later
fixed-geometry generator deliberately revalidates the source plan again and, for a
noncanonical form, also requires an exact released chemical definition.

The current comprehensive Archive index is
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-index-v2`.
It revalidated all eight ordered DNA products and 32 queued conformers; all chirality and geometry checks
passed, but every decision remains blank. Its JSON and Markdown SHA-256 values are
`1c8b46afc04a72af492aec8380a99a9ba9c99b361c96f777c915de1d52e27ca8` and
`bdfdb6c2f3182c580e2ed83617bb4b4e6fdc38eb4a0fe1b4cabf3d1750ed5b1a`.
It contains no `/tmp` reference, passes no gate, and authorizes no QM calculation.

For visual inspection, the hash-linked Archive bundle
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-visualization-v1`
contains one four-model PDB per product. Its manifest SHA-256 is
`5432b28d1436e313a593dc4d22bf1db5a5cf941af087f9f569a540aa4463f6b6`.
The builder reopens and revalidates the index, plans, graphs, stable atom maps,
stereochemistry evidence, candidate manifests, and every XYZ before creating the output.
Each PDB `MODEL` record maps its atom serials back to stable atom keys in the manifest.
These are static review frames with no timestep or simulation engine. They are not NAMD
trajectories, cannot be attached to the Help viewer, make no scientific decision, and
advance no registry or parameterization gate.

The generated decision overlay keeps human input separate from the hash-pinned generated
plans. A reviewer fills the small overlay, changes its status to
`human_review_complete`, and then materializes new reviewed plans without modifying the
pristine sources:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root "$archive_root" \
  apply-coupled-conformer-review-decisions \
  --decisions "$archive_root/fit/all-forms/conformer-review-decisions-v1.json" \
  --output-dir "$archive_root/fit/all-forms/materialized-conformer-reviews-v1"
```

The materializer requires a timezone-qualified reviewer identity and timestamp,
substantive per-product rationale and per-conformer notes, exact source plan/candidate/XYZ
hashes, and at least one accepted training and validation conformer for each product. It
recomputes geometry and chirality before creating output. A rejected conformer cannot have
a partition. The resulting audit receipts remain gate-neutral; fixed-geometry QM reopens
the reviewed plan and separately requires the matching released chemical definition.
The current blank all-eight overlay is
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-decisions-v1.json`
with SHA-256
`2358994190573dcdb04e35501a1cb1921b19ca2ceb6ad2932a25692d14ffc494`.

### Archive-backed working storage

All durable photoproduct evidence and all large or engine-generated intermediates must
resolve beneath `/media/jojo/Archive/NADOC_archive`. The shared guard confirms that
`/media/jojo/Archive` is actually mounted before starting work; a writable mount-point
directory on the system volume is not accepted as a fallback. Set the workflow guard for
every production invocation:

```bash
export NADOC_PHOTOPRODUCT_STORAGE_ROOT=/media/jojo/Archive/NADOC_archive
```

For integration tests that execute Psi4, also put pytest's base temporary directory on
Archive.  Psi4 may create `timer.dat` and cleanup metadata in its process working
directory even when `PSI_SCRATCH` is set:

```bash
mkdir -p /media/jojo/Archive/NADOC_archive/test_scratch
pytest --basetemp /media/jojo/Archive/NADOC_archive/test_scratch/pytest-photoproduct-<run-id> ...
```

Use a unique run ID and retain or archive the directory with the corresponding test
report.  The workflow's `--storage-root`/environment guard rejects configured cache,
scratch, job, plan, series, and output paths that resolve outside the selected root,
including paths that escape through symlinks.

## Literature-driven complete-ring correction variants

The first cis-syn-I NAMD candidate transferred the covered generic CGenFF cyclobutane
bonds, internal angles, and ring propers.  The literature comparison now requires those
terms to be fitted as one CPD-specific ring block.  Materialize the new null-valued plan
before rebuilding the OpenMM skeleton:

```bash
archive_root=/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  promote-bonded-refit-terms \
  --fit-plan "$archive_root/fit/cis-syn/charmm36-hybrid-v1/bonded_fit_plan.json" \
  --policy backend/data/forcefield/photoproduct_bonded_refit_policy.json \
  --output "$archive_root/fit/cis-syn/ring-refit-v1/promoted_bonded_fit_plan.json"
```

The command must report exactly four promoted bonds, four angles, and four propers.  The
OpenMM skeleton builder removes these terms from the base CGenFF system before adding the
linear basis, so the fit is a replacement rather than an undocumented additive
correction.  The four ordered product impropers remain fitted with their equilibria fixed
to the atom-mapped QM references.

After the response campaign, selection, CHARMM transform, candidate workbook, and
workbook audit have been regenerated, export an explicitly related corrected variant:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  export-charmm-candidate \
  --workbook "$archive_root/fit/cis-syn/ring-refit-v1/parameter_workbook.json" \
  --workbook-audit "$archive_root/fit/cis-syn/ring-refit-v1/parameter_workbook_audit.json" \
  --variant-id cis-syn-ring-refit-v1-a \
  --parent-candidate-manifest "$archive_root/fit/cis-syn/charmm36-hybrid-v1/candidate-v3/charmm_candidate/candidate_manifest.json" \
  --correction-policy backend/data/forcefield/photoproduct_bonded_refit_policy.json \
  --output-dir "$archive_root/fit/cis-syn/ring-refit-v1/charmm_candidate"
```

The parameterization runner accepts any registered TT-CPD candidate product and uses the
patch name from that exact hash-checked manifest.  It records the variant lineage in the
engine report and always uses the candidate's own parameter stream:

For all-form campaigns, pass
`backend/data/forcefield/photoproduct_candidate_assembly_policy_v2.json` to the assembler.
That policy resolves the product identity from the fit plan and assigns one unique
ordered patch name (`TCPDCS1`, `TCPDCS2`, `TCPDTS1`, `TCPDTS2`, `TCPDCA1`, `TCPDCA2`,
`TCPDTA1`, or `TCPDTA2`). It never selects or transfers numerical parameters between
forms. All eight registry entries now also have a hash-pinned atom-conserving charge
boundary. Seven use the shared `tt_cpd_patch_charge_scope_v2.json`, which pins every
chemical-definition hash and revalidates the exact 28-base-atom/2-C1′ partition on load;
the existing canonical scope remains valid for cis-syn-I.

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  run-candidate-engine-smoke \
  --candidate-manifest "$archive_root/fit/cis-syn/ring-refit-v1/charmm_candidate/candidate_manifest.json" \
  --dna-boundary-model "$archive_root/fit/cis-syn/dna-boundary-quantitative-screen-v1/chain-b.json" \
  --nucleic-topology backend/data/forcefield/top_all36_na.rtf \
  --nucleic-parameters backend/data/forcefield/par_all36_na.prm \
  --psfgen /home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/psfgen \
  --namd /home/jojo/.local/bin/namd3 \
  --output-dir "$archive_root/fit/cis-syn/ring-refit-v1/engine-smoke-v1"
```

This is an actual psfgen/NAMD run, but it is deliberately gate-neutral.  It cannot make
the candidate available to ordinary NADOC production jobs.  Production explicit-solvent
packaging continues to resolve only released registry assets.  The corrected candidate
must pass the MM-versus-QM, nonbonded, intrastrand/interstrand solution, and release gates
in `photoproduct_parameter_acceptance.json` before those paths open.

The first execution of this sequence produced variant
`cis-syn-ring-refit-v1-a`.  A real 100 ps NAMD run (50,000 ordinary-mass steps at 2 fs)
passed with 5,000/5,000 chirality-valid frames and finite energies.  Its complete,
hash-bearing report is
`fit/cis-syn/ring-refit-v1/engine-smoke-100ps-v1-a/candidate_engine_smoke.json`
under the Archive evidence root.  Candidate assembly also has a regression guard that
requires a fitted Urey--Bradley angle pair to be exported together; it may no longer be
silently discarded.  Repeat this exact promotion, assembly, lineage export, topology
audit, and engine sequence for each ordered product as its QM response campaign becomes
complete.  Passing it authorizes comparison work only, not normal NADOC production.

## Alpine response campaigns and geometry-aware refinement

The policy-2.1.0 all-form campaign completed as Alpine Slurm array job
`32131449_[0-23]`.  It covers the six products lacking complete current-policy response
data, with four conformers and 211 QCEngine tasks per conformer.  The local campaign plan
and all collected results are Archive-backed.  The live collector can be inspected with:

```bash
systemctl --user status nadoc-cpd-alpine-qm-collect.service --no-pager
tail -n 100 \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/\
alpine-qm-campaign-policy-2.1.0-v1/watch-and-collect.log
```

Array elements from the first submitted bundle may finish in Slurm state `FAILED` after
all 211 QM records were written.  The failure is a post-compute receipt-ordering error,
not permission to assume that data are complete.  `repair_case_completions.py` validates
the immutable campaign and plan hashes, exact task cardinality, result/run-record pairs,
and the hash recorded by every original run record.  Only then does it create a marked
recovery receipt.  `watch_and_collect.sh` fetches terminal campaigns even when Slurm
reports those failures, performs this strict repair, and passes the ordinary collector
and assembler.  The completed run repaired 24 receipts only after checking all 5,064 task
pairs; 24/24 Hessians then assembled and passed their response audits.  If any QM record
is missing or inconsistent, the workflow fails closed.
Future bundles use the corrected `run_case.sh`, which synchronizes before creating the
receipt.

`assemble_photoproduct_qm_completion.py` combines those batches, the four independently
reconciled trans-syn-I batches, and the four earlier cis-syn-I batches into one explicit
32-conformer, 6,752-task receipt.  The efficient post-QM systemd trigger now watches that
receipt and validates every source path, hash, product identity, conformer identity, and
task count before running the all-TT KIMMDY analysis and shortlist.  This downstream step
continues to describe reactant-state geometric opportunity only; it does not assign
isomer yield or reinterpret propensity as product stability.

Before another cis-syn-I export, use the corrected skeleton that retains the four native
THY planar impropers.  `build-openmm-fit-basis` also requires an explicit
`--angle-urey-bradley-mode fit` or `omit` choice.  Archive branches comparing both modes
and n1--n2, n1--n3, and n1--n4 bases show a best heavy-atom MM-minimum RMSD of 0.1464
angstrom after force/geometry weight sensitivity, above the fixed 0.10 angstrom gate.
Consequently none of those workbooks is eligible for export or production registration.
The next fitting increment must iteratively re-evaluate geometry at updated parameters
(ForceBalance 1.9.5 is already installed in the `nadoc-qm` environment) and retain the
same validation conformers and numerical gates.  No gated download or sudo action is
currently required for that step.

The first iterative geometry-aware cis-syn-I refinement is preserved under
`fit/cis-syn/ring-refit-v6c-geometry-aware-continuation`.  It stopped at the second
preregistered curvature-penalty stage and passed the candidate checks: 0.04306 angstrom
heavy-atom RMSD from the QM minimum, no negative projected modes, and all four signed
stereocenters retained.  The separate `audit-geometry-refinement` command then performed
a tighter re-minimization and a fresh Cartesian finite-difference Hessian on the actual
refined system.  The stored minimum reproduced within 2.50e-7 angstrom, the maximum force
was 9.33e-6 kcal/mol/angstrom, and the lowest of 102 vibrational projected curvatures was
0.20231.  The hash-bearing audit is `geometry_refinement_audit.json` beside the candidate.
The candidate was subsequently assembled and exported as
`cis-syn-geometry-refined-v6c-a`.  Real psfgen and NAMD 3.0.2 passed the static topology
audit, 2,000 minimization steps, and 50,000 ordinary-mass steps at 2 fs.  All 5,000 saved
frames retained the required chirality, all energy records were finite, product-ring
bonds remained between 1.408 and 1.710 angstrom, and the minimum nonbonded heavy-atom
covalent-radius ratio was 1.622.  The report is
`engine-smoke-100ps-v1/candidate_engine_smoke.json` beside the candidate.

This result remains gate-neutral and `simulation_ready: false`: it is an isolated d(TpT)
candidate stress test, not explicit-solvent DNA validation.  Two C5-centered fitted
improper constants are numerically negligible (approximately 4.3e-15 and 4.2e-13
kcal/mol/radian-squared), although the complete proper-torsion network retained all four
chirality signs in the smoke trajectory.  Do not invent a lower bound or treat the engine
pass as stereochemical transferability evidence; evaluate this partition against the new
low-energy QM targets and DNA-context replicas.

Two non-duplicative Alpine follow-up campaigns were submitted immediately after the
all-form Hessian collection:

- Slurm `32134901_[0-5]` evaluates 324 HF/6-31G(d) CHARMM water-interaction points for
  the six products with independent QM minima.  The six reviewed donor/acceptor site
  definitions are transferred by exact stable atom key and all generated probes pass a
  severe non-target clash screen.  cis-syn-I already has these curves; cis-syn-II uses
  its passed exact ordered-endpoint equivalence instead of duplicating the same neutral
  electronic calculation.
- Slurm `32135208_[0-7]` evaluates 72 MP2/cc-pVTZ relative-energy points: each product's
  minimum plus 25% and 50% proper-rotation interpolations toward each of its four audited
  coupled conformers.  This fills the preregistered <=12 kcal/mol validation region that
  the original cis-syn-I 18--64 kcal/mol response conformers do not cover.

The water array completed successfully.  Its collector hash-checked and parsed all 324
outputs and produced 36 passed fixed-geometry curve audits in
`alpine-qm-water-campaign-v1/collection_report.json` under the Archive photoproduct
evidence root.  This supplies fitting targets; it does not itself pass a charge or
force-field release gate.

The relative-energy array also completed with zero Slurm failures.  Its collector
hash-checked and parsed all 72 MP2/cc-pVTZ outputs; every ordered product has five to seven
points in the preregistered <=12 kcal/mol region.  For an available candidate, evaluate
those targets without optimizing the validation geometries:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  audit-refined-relative-energies \
  --refinement "$candidate/geometry_refinement_report.json" \
  --targets "$relative_campaign/bundle/cases/$product/relative_energy_targets.json" \
  --output "$candidate/relative-energy-audit-v1.json"
```

For v6c cis-syn-I this audit passed at 0.978 kcal/mol low-energy RMSE and 1.914
kcal/mol maximum absolute error, against targets of 1.0 and 2.0 respectively.  The command
checks every geometry hash, atom order, candidate-system hash, and parameter identity.
It remains gate-neutral and explicitly records that these are fixed-geometry coupled
conformers, not relaxed torsion scans.

Do not reuse the cis-syn-I charge vector across all products.  The independent transfer
audit failed the unchanged water-energy target (0.406 versus 0.2 kcal/mol RMSE).  A joint
six-product fit improved held-out RMSE to 0.218 but also failed.  Separate trans-syn-I and
trans-syn-II candidates passed at 0.039 and 0.052 kcal/mol held-out RMSE.  Both anti
families still failed when O4 sites were held out, even after a versioned policy removed
the chemically inappropriate endpoint-exchange charge constraint.  All of these are
comparison candidates only.

The bundle at `alpine-qm-water-validation-campaign-v2/` adds alternate water-plane
orientations for all six sites and products (324 HF/6-31G(d) points). It used the same
distance grid and exact stable atom map, accepted deterministic quantitative screening in
place of a human visual gate, and had a minimum non-target covalent-radius ratio above
1.764. Slurm `32151909_[0-5]` completed and passed all import and curve audits. The
independent evaluation rejected all four earlier fixed-LJ candidate families; the
post-water report is intentionally `completed_with_candidate_rejections`.

The submission command was:

```bash
ssh -M -S /tmp/nadoc-alpine-$(id -u)/control.sock -o ControlPersist=8h \
  jojo6687@login.rc.colorado.edu
bash scripts/alpine_qm_water_campaign/submit_from_local.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/\
alpine-qm-water-validation-campaign-v2 \
  /scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-water-validation-v2
```

The SSH login may require CU Duo.  The bundle is already complete; reconnecting does not
repeat any local generation.  No gated package download or `sudo` command is needed.

Both arrays use 64 CPU cores per product case.  Persistent collectors hash-check every
input and output, materialize ordinary NADOC run records, and write all durable results
under `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/`.  These calculations need
neither a gated download nor `sudo`.

The post-frequency handoff also materializes an exact fit input for each ordered product
under `alpine-qm-boundary-fit-inputs-v1/`.  `build-boundary-fit-inputs` joins the screened
V2000 product graph, 63 stable atom keys, passed optimized coordinates, and Cartesian
Hessian only after all source hashes and identities agree.  Its deliberately small SDF
reader accepts explicit single/double V2000 bonds and never sanitizes or reperceives the
strained fused ring.  Each resulting graph must contain 63 atoms, 68 bonds, formal charge
-1, and exactly the registered ordered CPD graph.  The same handoff then runs
`build-boundary-nonbonded-specification`: 35 sugar/phosphate/terminal atoms are frozen at
the effective CHARMM36 `THY` + `DEOX` + `5TER`/`3TER` charges and types, while exactly the
28 registry patch atoms remain charge variables.  Their initial native-THY charge sums to
zero, the fixed boundary sums to -1, methyl hydrogens are constrained within each
endpoint, and endpoint-exchange symmetry is explicitly disabled for ordered products.
The type assignment remains the named `charmm36-hybrid-cyclobutane-v1` candidate; this
preparation assigns no fitted charge or bonded value and passes no release gate.

Psi4 writes `GRID_ESP` potentials in atomic units while `grid.dat` uses the molecule's
declared coordinate unit.  For the NADOC Å grids, a unit point-charge prediction is
therefore `q * 0.529177210903 / r_angstrom`, not `q / r_angstrom`.  The fit/validation
code uses this conversion, matching Psi4's reference RESP implementation.  Any future
boundary fitter must preserve the same conversion and report separate training and held-
out surface errors.

Full-boundary ESP jobs explicitly select immutable QM protocol 1.6.0. They request
`GRID_ESP` and `DIPOLE` from the same HF/6-31+G(d) wavefunction and emit the dipole through
the parse-stable `NADOC_DIPOLE_AU x y z` marker. The job manifest declares both
properties and the e·bohr units; the audit fails when a declared dipole is absent,
non-finite, or excluded from the hashed `output.dat`. Protocol 1.5.0 and older ESP
artifacts remain valid GRID_ESP-only evidence and are not rewritten.

After fit inputs and all eight ESP/water collections pass, the
`nadoc-cpd-post-boundary-charge-fit.service` handoff runs
`fit-boundary-charge-campaign`. Each fit uses the full 63-atom electrostatic and
water-interaction model while exposing only the 28 product-base charges as variables;
the other 35 values and their Lennard-Jones types stay exactly CHARMM36. A finite,
policy-pinned 54-member hyperparameter grid is evaluated. The optimizer sees four H3/O2
water curves and 80% of the deterministic ESP grid, while both O4 curves and every fifth
ESP point select the candidate. Molecular dipole and restraint residuals are group-
normalized so the much larger ESP grid cannot dominate merely by point count. A failed
grid remains a useful, hash-linked diagnostic but cannot pass a force-field gate.

The next automatic handoff builds one complete-graph coverage audit and OpenMM linear
response per product. It uses the all-form ring-promotion policy, fixed-QM improper
equilibria, torsion periodicities 1--6, and the previously superior no-Urey-Bradley model
form. A preregistered bounded-ridge fit holds out every fifth projected gradient and
Hessian row and rejects coefficient rows that cannot be algebraically transformed into
positive-curvature CHARMM bonds, angles, and stereochemical impropers. This row split is
only a regularization diagnostic; independent conformer, relative-energy, and DNA
validation remain explicit blockers.

Physical rows proceed through full-d(TpT) candidate assembly policy v3, which maps the
model and DNA patch by identical stable atom keys and forbids the obsolete N1-methyl cap
substitution. Each candidate then attempts real NAMD 3.0.2 topology generation, 2,000
minimization steps, and a 100 ps ordinary-mass 2 fs trajectory. Per-product failures are
preserved while the remaining isomers continue. A successful isolated candidate smoke
does not make the registry simulation-ready. A separate hash-linked solution handoff then
uses GROMACS only to place TIP3P water, neutralizes the -1 e d(TpT) solute, adds 150 mM
NaCl, and runs real NAMD through load, 5,000-step minimization, 10 ps heating at 1 fs,
and 100 ps ordinary-mass dynamics at 2 fs. Every saved frame is audited for product
chirality, both crosslinks, both retained cyclobutane bonds, both glycosidic bonds, and
nonbonded heavy-atom contacts. This remains a gate-neutral isolated-solute validation:
it neither proves duplex/origami transferability nor exposes a released Help-menu
trajectory. Those require the explicit-solvent DNA-context and release audits.

`build-candidate-context-topology` provides the next safe separation of concerns. It
accepts one hash-audited candidate manifest and one NADOC design containing a single
matching lesion, resolves the persistent base keys through atomistic provenance, builds
matched reactant/product PSFs with real psfgen, and runs the exact product graph/type/
charge/improper audit. Its output is always topology-only and gate-neutral: it records
that product coordinates are not fitted and refuses to authorize dynamics. A real
reciprocal-crossover 1xT/1xT test has already proved cross-segment `__xb__` endpoint
routing. The subsequent coordinate preconditioner must convert the flexible local DNA
pose, reject strained placements, and only then hand the audited product PSF to solvation.

The coordinate preconditioner is now available as
`run-candidate-context-precondition`. It does not accept the earlier screened graft as a
QM template when an optimized fit model is available: the optimized XYZ must hash-match
the XYZ named by the product's passed full-boundary QM release report, and that report's
optimization and frequency audits are rechecked for the matching product, retained
chirality, and zero imaginary modes. The placement uses no reflection and moves only the
two selected base heavy-atom sets before psfgen. NAMD then minimizes a plus/minus-two-
residue neighborhood for 10,000 steps while harmonically restraining the nonlocal
structure. Policy `photoproduct_context_precondition_policy.json` fails closed on
chirality loss, ring/glycosidic/flank bond strain, nonbonded overlap, non-finite energy,
unclassified warnings, or excess nonlocal motion. The output remains
`simulation_ready: false` and `gate_effect: none` because a local coordinate seed is not
an equilibrium DNA validation. The all-product watcher records failures independently of
the isolated d(TpT) vacuum and solution smoke paths. It produces 24 independent attempts:
all eight ordered products in crossover-extra interstrand, adjacent-native intrastrand,
and antiparallel-native interstrand contexts.

A passing context seed is then consumed by
`run-candidate-context-solution-smoke`, which hash-checks the transient endpoint mapping
and preconditioned PSF/PDB before adding TIP3P and 150 mM NaCl. The unattended campaign
runs 5,000 minimization steps, 5 ps at 1 fs, and 10 ps at 2 fs with ordinary masses for
each of the 24 cases. The DCD audit uses the actual per-design segment/residue identities,
checks chirality and covalent geometry on every saved frame, and remains gate-neutral.
Long matched reactant/product replicas are still required for scientific stability
claims.

### Recovery-cycle branching after the first full-boundary runs

The 24-hour, 64-thread all-product optimization strategy is superseded for new work by
`photoproduct_qm_cycle_policy_v2.0.1.json`.  Keep all eight ordered design identities,
but begin parameter evidence with cis-syn-I, cis-syn-II, trans-syn-I, and cis-anti-I.
Recover a hash-valid completed result rather than repeating it; restart only from a
complete printed geometry that retains the stable atom order and registered chirality.
Run large optimization cases at 32 threads with protocol 1.7.0's bounded OptKing step and
periodic checkpoints.  Add trans-anti-I in the second wave after the anti pilot diagnoses
the optimizer path.  Compute the remaining independent full-boundary minima or Hessians
only when a preregistered held-out family-transfer metric fails.  A family-sharing
hypothesis never substitutes for product-specific stereochemistry, topology, placement,
and explicit-solvent NAMD validation.
