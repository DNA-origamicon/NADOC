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
bytes, or change frontend labels. Those remain required follow-up checkpoints.
The now-unused MD boolean response wrapper was pruned. Misleading v4 comments
claiming complete engine coverage were corrected without changing legacy hashes.

Validation: 29 new pure/route tests, 18 oxDNA staleness cases and 12 MD cases pass
(59 total). The old MD migration fixture failed both current and unchanged
`7886cd42` route/fingerprint modules because it claimed to represent a pre-recipe
file while retaining a newly authored recipe root. It now explicitly distinguishes
legacy snapshots (migration required) from authored snapshots (no unlogged cluster
insertion). Existing frozen-result and return-loadout assertions remain. No
production restoration or placement algorithm was changed to make that test pass.

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

## Official CAD precedent

SOLIDWORKS exposes separate mesh/result states, including Out of Date, and reruns a required parent study when explicitly running a dependent study. This supports retaining stale output separately from the current model, rather than claiming feature regeneration refreshed physics. [Run Specified Studies](https://help.solidworks.com/2026/english/SolidWorks/Cworks/HIDD_RUN_SPECIFIED_STUDIES.htm).

Onshape asynchronous simulations record document version, configuration, named position and solver version. Existing results are reused when the assembly state matches; solver improvements can change later results. This supports exact input/configuration lineage and explicit solver identity. The documented feature is an assembly workflow; NADOC's proposed standard-part metadata policy is an inference from that precedent, not assembly implementation work. [Asynchronous Simulation](https://cad.onshape.com/help/Content/Assembly/asynchronous_simulation.htm?TocPath=Assemblies%7CSimulation%7C_____2).
