---
name: project-nanoparticles
description: Display-layer nanoparticle authoring and automation.
---

# Nanoparticles

**Status (2026-09-12): Gold nanospheres and quantum-dot catalog/import are implemented; gold nanorods remain a menu placeholder.**

Gold nanospheres are persisted as `Design.nanoparticles` display records with diameter (nm),
visibility, and a rigid pose. Creation, resize/move, and deletion use the
`nanoparticle-{create,patch,delete}` snapshot feature-log operations, so undo, timeline revert,
save, and reload use the standard design-state contract. The core itself never enters DNA
topology; thiol surface strands do, through the ownership records described below.

The frontend `nanoparticle_subsystem.js` owns metallic-gold sphere meshes, picking, canonical
`{kind: "nanoparticle", id}` selection, the shared protein-style transform gizmo behavior, and the
right-click Edit diameter / Conjugate Manager / Delete menu. REST endpoints live in
`routes_nanoparticles.py`; `window.__nadocTest.nanoparticles` is the stable Playwright facade.

**Thiol conjugation (2026-09-02).** `Design.nanoparticle_conjugations` owns a
versioned thiol surface specification and maps every surface site to a real
`Design.strands` strand on a `__np__...` virtual helix. The four initial presets
are direct thiol, alkyl-thiol, PEG-thiol, and PEG-thiol backfill. Coverage uses a
nonlinear 1/2/3/5/10/25%/50%/75%/100% control and reports both a central estimate
and literature-based range. Applying/replacing/removing a corona is one snapshot
feature operation. Unbound owned helices translate/rotate and resize with the
particle. A surface strand can be converted in-place (same strand ID) to an
ordinary `OH_BINDER` on a compatible overhang.

The gold core intentionally remains non-atomistic. Full representation draws the
surface-to-DNA connector; atomistic modes add S plus scheme-dependent C/O linker
atoms and explicit linker/surface bond segments. Automation lives at
`window.__nadocTest.nanoparticles.conjugation`; backend CRUD/estimate/validate/bind
routes are in `routes_nanoparticles.py`.

**Handle connections (2026-09-03).** The right-sidebar Overhang Connections card
has an NP-handle ↔ overhang mode with a compact two-option direct-connection
picker. The thiolated terminus is the handle root. UI and API independently
reject any attachment choice that would produce parallel rather than
reverse-complementary strand directionality. Applied versions materialize a
native measurable Duplex; collective N-anchor relaxation reorients rigid
handle/overhang duplexes before translating the particle and carries every owned
surface handle with the solved pose. Public workflow and automation documentation
lives in `docs/nanoparticle_conjugation.md`.

Playwright validation copies `workspace/NP_test.nadoc` to a prefixed file under
`workspace/playwright_tests/` and never mutates the original. Spec teardown,
global teardown, and the exit-time artifact cleanup reporter jointly remove the
fixture, screenshots, traces, reports, and `.last-run.json` on success or failure.


**Quantum dots (2026-09-12).** Tools → Nanoparticle → Quantum dot opens a vendor
catalog with 11 importable NN-Labs HECZ dots and 12 preview-only Thermo Fisher Qdot
coating variants (streptavidin, carboxyl, amino-PEG). `kind="quantum_dot"` shares the
gold nanoparticle scene picking/gizmo/pose/undo/save path, with nonmetallic emission
colors. `Nanoparticle.quantum_dot` freezes catalog provenance and spectral references;
scene diameter is constrained to the vendor total-size range (midpoint default).
The frontend bundles the catalog and original plot previews so startup simulation
polling cannot delay the popup. Both UI and API block functionalized-dot import and
quantum-dot thiol conjugation. Spectra are full vendor plots, not synthetic or raw
numerical samples. See `docs/quantum_dots.md`, `backend/core/quantum_dots.py`, and
`frontend/src/ui/quantum_dot_dialog.js`.

Quantum-dot lifecycle follow-up: nanoparticle rebuilds reanchor the movement
session after pose/history changes; free particles ignore unrelated metadata and
DNA geometry refreshes so previews survive autosave. Feature-log create entries
edit the current diameter even after later operations and disable when deleted.
Delete shortcut routes nanoparticle refs to the normal undoable deletion API.
Undo retains the open workspace even without helices. Automatic design animation
seeding uses `ensure_default` (idempotent display metadata, no undo/redo mutation),
avoiding a hidden animation-creation step after dot import.
# Gold quenching research and display (2026-09-12)

- Bundled literature data: `backend/data/photophysics/gold_quenching.json`; evidence and model limits: `docs/gold_quenching.md`.
- `frontend/src/scene/gold_quenching.js` evaluates donor-to-gold-surface NSET from eleven experimental FAM/Cy3B size/d0 points (Breshike Table 3.4). Cy3B must never alias Cy3. Interpolate sizes only inside measured limits; unknown and contact are not zero quenching.
- FRET Checker attenuates glow intensity continuously; View-only Details panel reports missing QD/dye/size calibration. Fluorescence alone remains reference emission. Existing dye–dye threshold/scale cue is unchanged.
- Current vendor QDs are NOT assigned an invented universal gold radius. Li 2011, Samanta 2014 and Ko 2013 findings are imported as evidence; donor/coating/geometry mismatch or incomplete numerical calibration prevents quantitative assignment.
- Live nanoparticle mesh poses override saved poses. Hidden gold remains physically present. Materials are owned per dot/glow, so brightness changes do not affect same-color neighbors.
# Gold creation optical popup (2026-09-12)

- Tools → Gold nanosphere opens `frontend/src/ui/gold_creation_dialog.js`; the popup is bundled at startup so background API requests cannot delay a first-click module fetch. Existing edit-diameter prompts and API are unchanged. Successful creation selects the normal gold gizmo.
- Popup shows size-dependent absorption/extinction/scattering curves, peak wavelengths, particle-molar epsilon, wavelength inspector and nominal nanoComposix BioPure reference table. Streptavidin coating is explicitly disabled.
- `scripts/build_gold_optics.py` generates the bundled 5–100 nm, 400–800 nm Mie reference grid using miepython 3.0.2 and CC0 Johnson–Christy bulk n/k; water n=1.333, no coating/surface-damping correction. Fractional sizes interpolate cross sections; out-of-range scene sizes can be created but have no optical estimate. See `docs/gold_optics.md` for provenance and units.
# Streptavidin coatings (2026-09-12)

Update 2026-09-16: mobile CUDA `DNA2GOLD` now includes a rough rigid strep coating,
permanent biotin pockets, flexible effective 5′ DNA linkers and monomer-sphere
sterics. New biotin-DNA creation sets `oxdna_fixed_core=False`; existing fixed
documents retain legacy behavior. See `docs/oxdna_mobile_strep.md`. Other engines
and plain DNA-only exports still reject coatings. Parameters, coating drag/mass
and origami equilibration remain unqualified. Development runs belong in
`experiments/mobile_gold/ws/`, never the main user workspace.

- Gold creation enables strep; right-click either gold or a custom QD → Streptavidin coating supports apply/change/remove. Default target floor(pi*d²/40), supported core sizes 5–100 nm, adjustable footprint 25–100 nm²; actual count excludes PDB heavy-atom clashes. No mixed thiol-DNA/strep layers yet.
- `backend/core/streptavidin.py` imports bundled `backend/data/proteins/1STP-assembly1.pdb`: flatten four biological-assembly MODELs into A–D, 484 CA/3604 protein heavy atoms. Adsorption uses seeded isotropic rotations; biotin mode retains one BTN and points its C10→C11 tail inward with a default geometric 4 nm spacer. Linker atoms/force field are not invented.
- `Nanoparticle.coating` owns one full ProteinAsset and local Mat4x4 poses. `streptavidin_renderer.js` instances the PDB chain traces under the particle mesh, following live transforms. Snapshot history handles create, resize, coat/remove, delete, undo/redo and save/load. Vendor functionalized Qdot presets still lack verified core/coating geometry and stay deferred; custom coatings work on imported QDs.
- See `docs/streptavidin_simulation_audit.md`. Full coated-system simulation is NOT ready. Guards prevent silent omission at NAMD package/protocol/topology, OpenMM implicit/checker, oxDNA topology/DNANM/live, CanDo/SNUPI/mrDNA creation and assembly flattening. Shared fingerprint includes physical coating data, ignores cosmetic name/visibility, and leaves uncoated hashes unchanged. `GET /design/nanoparticles/coating-simulation-audit` reports gaps.
- Coated-gold quenching is explicitly uncalibrated; gold creation optical spectra remain uncoated-core references.

Literature follow-up 2026-09-12: docs/streptavidin_literature.md records direct
Gurtovenko et al. 2019 Martini/GROMACS strep–AuNP simulation (DOI
10.1021/acs.jpclett.9b00065; SI figshare file14405075), assumed 50% occupancy,
25nm² contact area, counts1/6 for5/10nm; amino-group gold bonds are CG assumptions.
Dutta2022 GolP/GROMACS flat Au biotinPEG gives orientation/height precedent.
2017 14.1nm AuNP paper estimates25geometric/30optical, vs current15 default;
40nm² is preparation-specific, 25min excludes inferred20.82effectivearea.
Research only: runtime defaults unchanged. Future separate coverage fraction,
physical footprint/effective area, attachment chemistry, center/anchor spacing.

Gold creation now size/optics only. Conjugate Manager has Thiol–DNA/Streptavidin tabs; strep uses shared publication JSON (2007 area40,2019 area50,2017 optical30at14.1), count_override1–1500 and persisted coverage_reference/source. Resize scales preset unless explicitoverride. QD context strep editor shares controls.

### Fixed-core oxDNA minimal build (2026-09-13)
Conjugate Manager strep pane: apply count 1, reopen, attach 2–200-base 5′ biotin
DNA with pocket and linker reach. Persisted BiotinDNA record + owned helix/strand,
feature history and rigid movement. CPU jobs expand coating to 484 CA DNANM beads,
fixed exterior gold repulsion, three protein traps and symmetric DNA pocket tether.
Manifest nanoparticles.json; absolute frame and dt cap .0001 through all stages.
Not mobile gold or calibrated adsorption/binding. NAMD/live/CUDA still guarded.
See docs/streptavidin_simulation_audit.md for model parameters and limits.
Tests: tests/test_gold_strep_dna.py (real MC/MD/equil engine), frontend/e2e/gold_strep_dna.spec.js.

Conjugate Manager now uses one persistent Conjugation scheme selector (four thiols
plus streptavidin). Thiol handles can use an overhang complement, a typed standalone
sequence, or the existing server-side random sequence generator. Editing/generating
clears the selected binding target; only an explicitly selected overhang is bound.
Streptavidin DNA also offers generation with length 2–200. Browser regression:
frontend/e2e/nanoparticle_standalone_sequence.spec.js.

Streptavidin manager uses the same three-column 960×600 window as thiols:
Coating controls left, shared orbitable gold/PDB preview center, DNA controls right.
Compact mode moves explanations/publication URLs to control and option tooltips.
Read-only streptavidin-preview endpoint reuses the Apply packing builder; debounced
and serialized preview requests avoid parallel packing jobs. Preview labels core
size, actual placed tetramers, and attached DNA per tetramer (not inferred occupancy).

Testing compact strep UI exposed an initial workspace-save response race:
acknowledge_workspace_save preserved concurrent DNA edits in server state but the
route returned the pre-I/O snapshot under the acknowledgement's newer revision.
The route now returns a current snapshot captured under the acknowledgement lock;
confirmed autosaves still omit full snapshots. Regression assertion added to
 tests/test_design_identity_api.py's interleaved save test.

### Explicit DNA occupancy (2026-09-14)
The existing compact manager now requires an applied coating before DNA attachment;
unsaved coating edits disable attachment. `dna_per_strep` requests 1–4 strands for
adsorption or 1–3 for biotin tether (pocket A reserved), on every applied tetramer.
Placement is atomic and rejects a count that the finite geometric search cannot
fit. Native B-form rise/twist/radius remain unchanged; rigid directions/phases
are searched against core, coating and DNA obstacles. First backbone bead is at
the linker endpoint. Particle rotation now preserves helical phase. Preview uses
actual scene nucleotide positions. See docs/streptavidin_dna_placement.md.

BiotinDNA stores tetramer_index (legacy default 0) and placement_version (legacy 1,
new 2). Version 2's separate extended oxDNA seed starts at the native 5′ bead and
is also clash-screened. CPU/GPU fixed-core export includes every tetramer and
occupied pocket; the old one-tetramer/one-DNA and CPU-only restrictions above are
historical. NAMD/live remain guarded; GPU sampling/convergence is still open.

Conjugate-manager follow-up: attaching/removing biotinylated DNA now refreshes the
existing manager and native preview in place, preserving the orbit camera. Step 1
coating controls are left; Remove coating is the last control in that list. Step 2
DNA controls are right, with a final Apply footer. Apply finishes an unchanged
coating/DNA setup without recreating the coating or adding an undo entry.

Manager integer fields retain always-visible native up/down steppers (including
thiol length/count). Step 2 puts Length and Generate sequence on one row;
Playwright clicks all five integer steppers and verifies no vertical overflow
in the DNA column at the standard 960×600 manager size.

### Biotin visualization (2026-09-14)

NAMD follow-up (2026-09-16): `backend/core/strep_biotin_namd.py` and
`scripts/prepare_strep_biotin_namd.py` export isolated gold-free atomistic
components and explicit ligand/DNA/protein identity. Preserve the biotinylated
5′ phosphate: standard CHARMM 5TER deletes it. Native protein psfgen mapping and
CHARMM36m coverage pass, but full-complex NAMD remains blocked on qualified
Biotin-TEG/BTE5 charges and parameters. Do not treat the generated preparation
recipe as a runnable NAMD package. See `docs/strep_biotin_namd.md`.
Literature audit (2026-09-16): published models exist: Comer et al. 2012
(10.1002/elps.201200164) used custom CHARMM-compatible biotin/linker/DNA patches;
Sedlak et al. 2020 (10.1126/sciadv.aay5999) used CGenFF biotin/PEG in GPU NAMD.
Raw assignments and exact Biotin-TEG–5′-DNA equivalence remain unverified.
Prefer reuse plus targeted qualification; do not infer missing published
parameters from the local library audit. See `docs/strep_biotin_parameter_literature.md`.
Parameterization setup: `experiments/strep_biotin_namd/prepare_parameterization.py`
builds an isolated all-H, charge -1 methyl-phosphodiester model, preserves biotin
stereochemistry, copies unchanged CHARMM references with hashes, and defines
boundary/QM targets. `validate_parameterization.py` checks chemical roundtrip and
native psfgen coverage of reference NMA/DME/DMEP/UREA. Final evidence stays in
`experiments/strep_biotin_namd/ws/parameterization_final/`. Literature ligand files
not recovered; no licensed CGenFF executable found. User supplied website-generated
`ws/parameterization_final/BTMP.str` (program 4.0/library 5.0). Atom graph, charge
−1 and coverage pass: 68 atoms, 69 bonds, 129 angles, 171 dihedrals, two impropers.
Maximum bonded/charge penalties 26/16.547; preserve this unvalidated seed and
prioritize biotin ring/pocket and actual DNA boundary checks. See
`assignment_qualification_plan.json` and `docs/validation/biotin_cgenff_assignment_2026-09-16.json`.
`audit_assignment.py` handles current/legacy version headers; five importer tests
pass. Subsequent junction work adds a 60-atom BTE/BTE5 candidate with explicit
mixed-term source families, methyl-H charge folding into C5′, native DNA P2/types,
and unchanged ligand charges. All four bases and ACGT controls pass coverage and
−1 e attachment-charge checks. Full complex: 7,291 atoms, −16 e, 3,796 source
heavy atoms preserved exactly; complete coverage. C7 ligand-name alias regression
fixed in preparation formatter. Local GPU-resident NAMD passes 20 ps on 94,121
atoms (~244 steps/s); O–P 1.500–1.664 Å. No RunPod spending. Two earlier CUDA
initialization failures were unused NBFIX type references; the isolated runner
filters only pairs absent from the actual PSF. This is experimental numerical
validation, not production/affinity qualification. See `docs/biotin_dna_junction.md`.
- Full and manager preview: one yellow bound-ring marker per occupied DNA pocket, using shared PDB-derived `biotin_pockets.json`; per-tetramer simulation deltas now independent.
- Native atomistic/VDW/sticks/surface: actual biotin-TEG heavy-atom graph, constrained tail/spacer fit with fixed ring and tetrahedral 5′ phosphate approach. New manager/API reach default 1.8 nm; saved values unchanged. Failed fits show a real unconnected spacer + warning rather than stretched DNA bond. Display chemistry does not stale oxDNA jobs.
- `docs/biotin_display.md` describes sources, assumptions and limitations. This is display geometry, not NAMD parameters or an equilibrium model. Dynamic atomistic protein/ligand reconstruction still needs integration/validation; do not interpret native-pose biotin in atomistic trajectory display as simulated ligand motion.

### Atomistic loading audit (2026-09-14)
- Cold biotin fitting consumed >99% of backend time; replaced Python-loop Jacobian + sparse LSMR with vectorized Jacobian + dense LM (same objective/acceptance, A/B failure counts unchanged). Versioned bounded disk/memory fit cache, prepared on attach/document load; no design/job fingerprint changes.
- Corrected coated PDB drawing: Full CA traces now swap to complete imported atoms/bonds in VDW/Ball & Stick/Stick. `streptavidin_atomic_renderer.js` shares GPU buffers across rigid tetramers; group transforms move atoms AND bonds. No extra PDB requests.
- Backend prepared 6-strand build ~14 ms vs same DNA-only ~13 ms; cold fit formerly seconds. Native-view and matched-atom-count browser benchmark: `frontend/e2e/biotin_loading.spec.js`, fixtures from `scripts/biotin_loading_fixtures.py`, results in `workspace/validation/biotin_loading_20260914/`; details in `docs/biotin_display.md`.
- Protein spheres use existing analytic sphere impostors. Native cache misses clear the renderer's retained previous-part atoms before switching; identity-only saves preserve the in-flight atom request. `nanoparticle_render_dependencies.js` prevents identical save responses rebuilding coating GPU resources, while molecular/placement edits and undo still invalidate them.
- Coatings opt into `unitSphereImpostors`: one material/program across elements and sphere modes, with actual radii in instance transforms. Final headless matched-atom benchmark: first painted Ball & Stick 956 ms coated / 1504 ms DNA; VDW 1263 / 1651 ms. Repeat switch setup faster in all three modes, but Stick painting remains slower (317 / 214 ms). Do not claim universal frame-time parity. 18 backend, 95 frontend, and two Playwright checks passed; final log and full metrics retained in the validation directory above.

### Biotin terminal extensions and Alpine validation (2026-09-16)
- `biotin_extensions.ensure_biotin_extensions` adds missing modification-only 5′ Biotin-TEG extension records on create/Design parsing (stable strand-based ID, idempotent, existing explicit extensions preserved). Biotin counts as an extension, never a nucleotide; canonical duplex relocation/reversion retains it. Generic 3′ extension metadata works, but existing conjugate chemistry/atomistic patch remains 5′ only.
- Modification-only extensions retain the real DNA 5′ terminal flag; nucleotide tails still replace it. Handle/particle deletion removes owned extensions and undo restores them. 59 focused tests + live bound-handle extension rendering/editor passed; FAST broad suite still has 29 failures/9 errors (8619 passes).
- Alpine Slurm **32611941**, `ah200` H200, 5 ns continuation from the validated local 20 ps checkpoint; 94,121 atoms, NVT300K/1fs, GPUresident, 8h limit. Last observed pending on Priority, not yet validated. Remote `/scratch/alpine/jojo6687/nadoc_validation/biotin_dna_5ns_20260916`; receipt/config/hashes/logs in ignored `experiments/strep_biotin_namd/ws/junction_alpine_5ns/`. No RunPod spend. Check receipt before submitting anything else; do not duplicate. See `docs/biotin_dna_junction.md` for monitoring/qualification limits.

- **Alpine replacement 2026-09-16:** user reports H200 concurrency prevents this validation alongside their other H200 job. Canceled **32611941** (sacct confirmed), submitted **32620740** on `artxpro6000`, `gpu:rtx_pro_6000:1`, GPU-resident NAMD; same 5 ns/checkpoint/8h limit. Latest status PENDING (Priority). Authoritative receipt/evidence: `experiments/strep_biotin_namd/ws/junction_alpine_5ns_rtx6000/`; remote `/scratch/alpine/jojo6687/nadoc_validation/biotin_dna_5ns_rtx6000_20260916`. Monitor replacement, never resubmit original.

- Latest Alpine result: **32620740 FAILED (6 s, exit 1:0)** before NAMD because `gcc/11.2.0` is unavailable on the RTX Pro 6000 node. Zero MD steps; module environment must be corrected before retry. No replacement of this failed job has been submitted. Supersedes the pending status above.
