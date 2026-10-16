# Physical-result freshness — staged implementation

Audit and first additive API checkpoint, 2026-10-15. No simulations or scientific changes were run. Assemblies remain deferred. Authoring reproducibility and physical-result freshness remain separate claims.

## Implemented first checkpoint

oxDNA/NAMD list and detail responses now include `input_freshness` with status,
reasons, partial coverage, comparison subject and nullable `model_match`. Matching
legacy hashes report **unknown**, never complete current; known comparable
projection changes report stale. Missing, malformed, unsupported and differing
versions remain unknown. An unavailable archived MD record requires no snapshot
read to report unknown. The existing `out_of_date` predicate and selection guards
are unchanged for compatibility; it is not an alias for a complete current verdict.

The adapter reuses each existing fingerprint once per response and performs no
new model traversal, filesystem access, hashing, job write or simulation. It does
not yet add complete receipts, qualify consumed-model projections, certify source
bytes. Those remain required follow-up checkpoints.
The now-unused MD boolean response wrapper was pruned. Misleading v4 comments
claiming complete engine coverage were corrected without changing legacy hashes.

Validation: 29 new pure/route tests, 18 oxDNA staleness cases and 12 MD cases pass
(59 total). The old MD migration fixture failed both current and unchanged
`7886cd42` route/fingerprint modules because it claimed to represent a pre-recipe
file while retaining a newly authored recipe root. It now explicitly distinguishes
legacy snapshots (migration required) from authored snapshots (no unlogged cluster
insertion). Existing frozen-result and return-loadout assertions remain. No
production restoration or placement algorithm was changed to make that test pass.

The shared simulation-row model and renderer now show `Inputs unverified` for
unknown or incomplete evidence, with a distinct partial-match tooltip. Known
changes show `Inputs changed`; the existing warning action and run-completion
status remain independent. The shared render signature includes the displayed
evidence, avoiding unchanged-poll rerenders while reflecting actual status changes.
This covers oxDNA, NAMD and normalized unified rows without per-panel copies.
The 39 focused frontend cases pass; the full suite passes 8,192 tests with one
skipped across 709 files in 310.21 seconds.
App inspection is still pending under MV-46 because Archive is unavailable.

## Existing foundation and gaps

- `core/part_history_contract.py:38` classifies `chain_sim_projects`, `loadouts`, `atomistic_reference`, `active_loadout_id` and `last_editable_loadout_id` as physical. Proof excludes them explicitly (`part_history_proof.py:76`); `part_recipe_publication.preserve_document_state` retains them without certification. This separation is sound.
- `OxdnaJob` and `MdJob` already retain project/revision IDs, a frozen `design.json`, design fingerprint, history position, parent/seed job links and authored run settings (`run_config` / `prep_params` plus explicit-key metadata). NAMD manifests record resolved stages, seeds, force selections and file names. They do not provide one complete immutable solver/input/source receipt.
- `oxdna_staleness.job_out_of_date` returns false for absent or incomparable fingerprint evidence. Thus `out_of_date: false` means either current or unknown. A missing snapshot/old hash must not acquire a current certificate through that boolean.
- Its shared oxDNA/MD v4 projection omits `protein_assets`, `protein_attachments` and `nucleotide_transforms`. NAMD preparation uses `build_atomistic_model(..., include_proteins=True)` (`namd_gbis.py:155,219`), and atomistic placement applies nucleotide transforms. The old comment excluding cluster transforms is also stale: oxDNA's `_seed_geometry` calls canonical `design_geometry`; that path applies native cluster/slab poses and nucleotide transforms. Cluster membership is additionally consumed by anchor selection (`physics/oxdna_interface.py:2769`). These omissions require engine-specific consumed-input coverage before a complete current verdict.
- `AtomisticReference` stores only source/notes/topology_hash/atoms/bonds (`models.py:2949`). `atomistic_model_from_reference` accepts an empty hash, while the broad exclude-list hash now includes unrelated new fields such as repair drafts, recipe roots, portable sources and chain plans (`atomistic.py:556–597`). This permits unknown references and creates false invalidation for nonphysical edits. `build_atomistic_model` can prefer this reference as a preparation input; that use needs explicit source provenance, not merely a display label.
- Protected simulation loadouts already preserve the job's frozen branch, and state mutation gates reject edits to an active protected loadout (`state.py:444`). State setters advance revisions but do not establish physical validity. The current fingerprint cache is revision/object scoped and hashes outside the lock; keep ordinary mutations free of simulation traversals. Its mutable-object/revision assumptions must stay subordinate to the host publication work.

## Smallest safe contract

Add a small strict physical-input receipt beside each newly prepared job, not sampled results in feature-log rows:

1. Versioned engine/projection identity; project/branch/revision lineage; an authoring/recipe fingerprint for provenance. A whole-authoring hash is not the sole freshness comparison because names, colors and other harmless metadata should not invalidate simulation inputs.
2. A consumed-model fingerprint covering the exact selected engine's topology, sequence, canonical placement, attached assets and force selector ownership. Unsupported model families yield unknown coverage; do not silently fall back to the current DNA-only projection.
3. Canonical resolved protocol/parameter/seed digest, selected input descriptors and hashes of actual packaged templates/force-field/topology/initial-coordinate bytes. Record parent job **and exact consumed restart/frame digest**, not job ID alone.
4. Solver implementation/build identity and the relevant runtime/backend policy. Record the run's solver; an installed upgrade alone does not invalidate a historical result for that recorded solver. Comparing against a newly requested solver is a distinct compatibility comparison. No promise of bit-identical stochastic trajectories.

Derive `{status: current|stale|unknown, reasons, coverage, compared_to}`; never persist a mutable `is_valid` flag. Current requires complete comparable evidence matching the requested subject. A known differing model/parameter/source/seed/solver component is stale. Missing, malformed, unavailable or version-incomparable evidence is unknown with a reason. Artifact availability, completion/health, and scientific validity remain separate fields; a matching recipe is not successful simulation validation. Keep `out_of_date` as a temporary compatibility alias for `status == stale`, with the UI displaying unknown explicitly.

Legacy snapshots may establish a limited model comparison, but cannot reconstruct the solver/force-field bytes actually used. Do not silently upgrade them to complete current. Viewing/exporting the old run against its own frozen branch remains possible. Operations mapping **current** selections onto frozen particle indices should require proven selection compatibility or an explicit switch to the frozen branch; unattended chains use their own recorded parent input rather than whichever part is open.

No result coordinates may be written back into helices, domains, deformation features or native proof rows by freshness evaluation. Preserve result/reference data after edits and report stale/unknown. A deliberate future “import result as editable source” operation needs its own pinned import contract. Reruns remain explicit; no automatic scientific work during editing or status polling.

## Implementation and validation order

First add a pure receipt/comparison module and additive job-list freshness fields with honest legacy unknown coverage. Next qualify complete projections and immutable receipt emission at oxDNA/NAMD preparation, then guarded reference/result use. Do not mass-rewrite old job JSON. Atomistic-reference compatibility should receive a versioned positive projection and provenance descriptor separately.

Compute hashes once from the already-owned preparation input and stream packaged-file hashes during existing I/O. Reuse one cached current projection per session/revision/profile; publish only after identity/revision recheck. On unavailable/budget-limited comparison return unknown instead of blocking the UI or retrying indefinitely. Never traverse trajectories, loadout snapshots or large atom references in ordinary setters. Hashing a stable retained descriptor is enough during routine polling; changed or explicitly imported artifacts require bounded integrity work outside the global lock.

Meaningful tests: topology/sequence/cluster/residue pose/protein/force-selector changes become stale; camera/color/proposal/recovery-only changes do not; old/missing/version-mismatched receipts remain unknown; source/package tampering and parent restart replacement cannot appear current; source restoration and undo can recover current; session close/reopen and concurrent mutation cannot reuse another comparison; failed/cancelled preparation publishes no receipt; repeated polls reuse cached work; all status paths leave topology and result bytes unchanged. Reuse `test_oxdna_staleness`, `test_md_staleness`, protected loadout and artifact-catalog tests. No production simulation is required for this contract qualification.

## Next finite checkpoint: owned local DNA-only oxDNA inputs

Read-only implementation map, 2026-10-15; no simulation or production change.
Implement the next receipt at a real preparation/launch boundary, rather than
adding an unused receipt library or describing all engines as complete.

**Ownership prerequisite:** `routes_oxdna.py:850` takes the current design's
`without_reference_geometry()` projection. `models.py:3521,3553` implements that
projection with shallow `model_copy` calls, retaining nested mutable authoring
objects. Geometry is derived at `routes_oxdna.py:1106`; the design then enters
threaded preparation at `1122`. Neither a revision label nor a separately
computed hash proves that these consumers observed the same state. Capture one
bounded owned physical-input projection before geometry or package I/O, using
the existing isolation primitives and exact session/source/revision guard. A
native feature-log proof is a separate claim and is not required to prepare a
legacy design honestly. Do not widen ordinary capture limits.

| Boundary | Current source | Required evidence |
|---|---|---|
| Preparation | `routes_oxdna.py:833`; `_seed_geometry:179`; resolved stages and seeds at `1010–1030` | Owned positive model projection, selected protocol, resolved defaults and seed; no reconstruction from sampled output |
| Final package | `oxdna_runner.prepare_oxdna_job:541–708` | Final `topology.top`, `conf.dat`, `forces.txt`, copied average-sequence parameter bytes and resolved `stages_spec.json`; any accepted optional file must be in the explicit closure |
| Actual launch | `oxdna_runner.run_job:1683`, final `render_stage_input:1879`, `_run_oxdna_async:1122/1138` | Actual rendered input and selected files, solver executable/build/backend and relevant runtime identity; requested engine flavor is insufficient |
| Restart/retry | `_starting_conf:1214`, `resume_point:1377`, retry helpers `1530/1645` | Exact consumed restart frame/configuration digest and actual retry parameters/seed for each attempt; parent job ID is insufficient |
| Copy/settings/children | `routes_oxdna.py:1249`, `1323`, `1679` and later field/surface children | Refresh the new receipt or mark coverage unknown; never inherit complete receipt authority after changing seed, protocol or frame |

Initial coverage should be a bounded local standard-part DNA2 preparation with
no particles, proteins, CPD, auxiliary linker geometry, surface/anchor/field
forces, remote seed chain or atomistic reference. Account explicitly for every
accepted DNA input: topology and sequence, loop/skip placement, crossovers and
forced ligations, deformation paths, cluster/domain poses, nucleotide poses and
ordinary unbound-overhang placement. A closed nested-field inventory must reject
unreviewed future fields/families. The DNA comparison display DTO is not an
appropriate physics authority: its deliberately reduced presentation fields do
not define all physical consumers. Scope admission is a separate small profile;
final numerical limits require measured preparation/capture qualification.

Use separate preparation and per-attempt receipts. Preparation completion does
not prove that a process used those files; retries can change the selected
configuration and resolved protocol. Seal the attempt after final input
rewrites, immediately before actual spawn. Hash the exact selected frame, never
an entire trajectory. File closure must be fixed and bounded, with path/symlink
admission and coordination against NADOC writers; a digest taken before a
concurrent overwrite is not evidence of the bytes consumed by the solver. The
receipt records observed input identity, not guaranteed bit-identical stochastic
output. Solver identity belongs to the actual run; installing a different solver
later does not itself make that historical run stale.

Keep the existing additive `input_freshness` response and legacy behavior. A
complete comparable model projection can distinguish current/stale; unavailable
or incomplete evidence remains unknown. Execution success, artifact availability
and scientific validity remain independent. Cache current projection comparison
once per document/revision/profile after the usual source recheck. Polling and
ordinary mutations must not derive geometry, scan trajectories or hash solver
executables. Source/file integrity work happens during preparation/launch or an
explicit bounded verification, outside the global state lock.

The implementation target is a cohesive pure projection/receipt module,
optional `OxdnaJob` metadata, and thin hooks in the existing create/package/launch
flow. Preserve existing formulas, stage generation, seed choices and retries.
Legacy receipts are never retroactively upgraded. Unsupported settings, copies,
remote jobs and child families remain explicitly unknown until their exact
closure is supported.

Required tests before claiming complete input coverage:

- Mutation during threaded preparation cannot change the owned projection or
  create mixed package/lineage evidence; failed or cancelled preparation emits
  no complete receipt. Session close/reopen cannot reuse a stale comparison.
- Sequence, loops, cluster/domain/nucleotide poses, deformation and overhang
  changes become stale; color, names, camera, repair drafts and history-only
  metadata do not. Unknown shapes and old receipts remain unknown.
- A fake subprocess captures the actual argv/rendered input/files. Changed
  restart frames, recovery of the last complete frame, retry seed/dt, or a
  replaced binary change the appropriate attempt evidence. No solver run is
  needed for these boundary tests.
- Copy and settings edits cannot retain the old complete receipt; missing or
  altered package data cannot appear current through a matching legacy hash.
- Repeated list/detail calls reuse comparison work and leave topology, physical
  result bytes and simulation configuration untouched. Benchmark bounded
  preparation capture and concurrent lightweight requests without a simulation.

NAMD remains the next separate closure. Saved draft loading at
`routes_md.py:2932` produces a private `Design`; direct current preparation at
`2938` uses the same shallow projection issue. `_prepare_job_bg:3685` branches
through oxDNA/mrDNA/BLADE/vacuum seeds. `namd_gbis.py:58` packages PSF/PDB,
CHARMM files, ENM selections and resolved configurations; `namd_topology.py:784`
also invokes psfgen/atomistic construction. `namd_runner.py:1902/1929` chooses
actual binary/thread/device arguments, while other paths select restart
coordinates/velocities/box files and alter configurations for retries. Even GBIS
therefore needs a larger source/toolchain closure than the first oxDNA slice.

### Concrete package and ownership seams confirmed in follow-up review

`copy_oxdna_job` (`routes_oxdna.py:1295`) copies topology, configuration,
snapshot and force/ANM files, but omits the prepared
`oxDNA2_average_sequence_parameters.txt`. At launch, `oxdna_runner.py:1886`
passes that path only if it exists; `render_stage_input` then falls back to the
current bundled parameter file (`oxdna_protocol.py:445`). A copied DNA2 job can
therefore use different parameter bytes from its source. Write a characterization
test for this concrete gap before the narrow copy fix; receipt inheritance must
remain unknown until the copied closure is exact. The official input contract
makes `seq_dep_file` mandatory when `use_average_seq=false`, and separately
identifies configuration, topology and RNG seed as consumed inputs.
[oxDNA input documentation](https://lorenzo-rovigatti.github.io/oxDNA/input.html).

The settings route (`routes_oxdna.py:1323`) checks editable status and later
rewrites `stages_spec.json` (`1401`, `1479`) without the reservation held by
start/resume (`1577`). This permits a check/write race with start. Coordinate
settings and source-copy reads with the existing nonblocking runtime lease;
do not invent another job owner. Initial preparation is also outside the
execution lease and needs an explicit preparing-package completion boundary.
The runtime contract covers cooperating NADOC writers, not arbitrary external
filesystem modification. Receipt language must retain that distinction.

Final attempt observation belongs after `configure_adaptive_memory_input`
(`oxdna_runner.py:1137`), because that helper rewrites actual input options.
Resume changes remaining step count and output cadence (`1780` onward), and
retry helpers overwrite resolved specs. Store immutable preparation evidence
and append a separate attempt record, including the runtime generation, selected
restart bytes, actual parameters and executable identity. A later overwrite of
`last_conf.dat` must not rewrite earlier attempt provenance. Path hashing alone
does not freeze subsequently consumed bytes; use a bounded attempt-owned input
closure or proven descriptor pinning while retaining the same numerical inputs.
Never substitute a newly installed solver for the historical attempt's identity.

Extend the test-first sequence with copy-parameter preservation, a deterministic
settings/start reservation race, and a fake subprocess that inspects the final
adaptive-memory input and every referenced file. Unknown `forces_file`/`parfile`
paths, symlinks outside the admitted closure, missing packaged parameters and
unsupported child families cannot acquire a complete receipt. No simulation is
needed for these ownership and transport tests. Current-projection comparison
should initially be an explicit bounded inspection; mutable aliases remain a
barrier to treating a session/revision memo as authoritative. Ordinary job polls
must not add model traversal, geometry generation or file hashing.

## Official CAD precedent

SOLIDWORKS exposes separate mesh/result states, including Out of Date, and reruns a required parent study when explicitly running a dependent study. This supports retaining stale output separately from the current model, rather than claiming feature regeneration refreshed physics. [Run Specified Studies](https://help.solidworks.com/2026/english/SolidWorks/Cworks/HIDD_RUN_SPECIFIED_STUDIES.htm).

Onshape asynchronous simulations record document version, configuration, named position and solver version. Existing results are reused when the assembly state matches; solver improvements can change later results. This supports exact input/configuration lineage and explicit solver identity. The documented feature is an assembly workflow; NADOC's proposed standard-part metadata policy is an inference from that precedent, not assembly implementation work. [Asynchronous Simulation](https://cad.onshape.com/help/Content/Assembly/asynchronous_simulation.htm?TocPath=Assemblies%7CSimulation%7C_____2).
