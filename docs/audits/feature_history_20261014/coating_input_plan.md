# Coating and biotin inputs: P4 implementation gate

Static source audit, October 15, 2026. The audit agent did not execute placement,
parser, chemistry, simulation or benchmark work. The root agent subsequently ran
the serialized capture experiment recorded below. The numerical builders remain
the oracle. Assemblies remain out of scope.

## Decision

Extracting a pure coating builder is a small change; admitting its real output is
not. One bundled streptavidin tetramer already exceeds the current 30,000-node
capture allowance, even with `count_override=1`. Implement the source boundary
first, then qualify an explicitly bounded worker profile before enabling native
live routes. Do not raise ordinary capture limits, omit protein atoms from proof,
or substitute generated poses/atoms for source inputs to make admission pass.

The existing inline input table and optional project-store cache are sufficient
for a small portable source contract. Large repeated coatings need a separate
decision about immutable asset storage, capture and recovery duplication; merely
raising the worker's candidate-result limit does not solve those problems.

## Sources and current behavior

Static byte/record counts from `backend/data/proteins`, without invoking a parser:

| Source | Raw bytes | Base64 bytes | Relevant contents |
| --- | ---: | ---: | --- |
| `1STP-assembly1.pdb` | 329,994 | 439,992 | Four MODEL records, 3,604 ATOM records, 400 HETATM records; 121 C-alpha records per model |
| `streptavidin_coverage.json` | 846 | 1,128 | Three publication presets |
| `biotin_pockets.json` | 16,060 | 21,416 | Four pocket transforms/ligands, bond graph and source metadata |

SHA-256 values respectively:

```text
892478b3fbec8bb38fe9a2c5de12ad2b923b42327a43b61d2884d6c3fc59f3f9
c1f82e7a1b32049dbc66ccfec907a772e2df79b9ee2b3c1d27f48d1f982fb59a
6bdbde26f85581c159110627316aeb81232571c69e78b40c3e5565734329ed20
```

- `core/streptavidin.py:19` reads the bundled PDB through a process cache keyed
  only by mode. It flattens the four biological assembly MODEL records into
  chains A–D before the normal first-model PDB parser. Adsorption selects 3,604
  atoms; tether mode additionally keeps the 16 BTN atoms from model 1. It centers
  on protein atoms, assigns the existing asset ID, and writes source provenance.
  Preserve this preparation exactly; importing the raw PDB with the ordinary
  protein command alone would discard three assembly copies.
- `core/streptavidin.py:55` resolves the optional coverage preset, then applies
  an optional explicit count. Coverage bytes remain an input when an override is
  supplied: selection validation and the reported publication URL still use
  them. Keep the native mode-specific spacer defaults, count formulas, seeded
  random orientations, Fibonacci sites and clearance tests unchanged. Rejected
  sites are intentionally omitted by this existing algorithm; target and actual
  counts differ. This must not become an admission mechanism that silently caps
  the requested work.
- `core/models.py:3005` embeds one complete `ProteinAsset` in each coating, plus
  local placement matrices. It does not copy that asset per placement, but it
  does duplicate it across separately coated nanoparticles. Protein bonds and
  metadata also count toward proof/candidate size.
- `core/gold_strep_dna.py:20,110` reads a second, hidden tether-mode PDB template
  for pocket alignment, including when the actual coating uses adsorption.
  Attachment uses every nanoparticle core/coating and every occupied DNA domain
  in the passed design as obstacles. It tries native rigid orientations/phases
  and requires exact requested occupancy on every applied tetramer. No partial
  attachment is published on failure.
- `core/biotin_extensions.py:9` authors deterministic five-prime extensions
  named `__biotin_teg__{strand_id}`. The pure attachment command must create these
  explicitly; native file/response guards must not rely on a later legacy
  model-validation backfill to complete the recipe.
- `core/biotin_atomistic.py:22,75,279` loads a separate pocket catalog and warms
  derived atomistic display fits. Its SQLite/LRU cache is disposable, and the
  fitting solver may attempt three runs of up to 160 evaluations per linker.
  `prepare_biotin_display` returns no authored geometry: the current route calls
  it for display preparation. Keep this work outside recipe replay and outside
  the authoring lock. A claim of reproducible atomistic display would additionally
  require the pocket catalog and its other atomistic template/runtime inputs;
  pinning the PDB alone is not that claim.

## Minimal pure extraction

1. In `core/streptavidin.py`, extract
   `streptavidin_asset_from_text(text, mode)` and
   `build_streptavidin_coating_from_inputs(diameter_nm, ..., asset, coverage_data)`.
   Move the existing bodies, preserving iteration order, parser options, ID,
   preparation metadata and all numerical statements. Existing file-based
   wrappers continue to supply the same bundled inputs for legacy callers.
   Cache only by source digest, importer version and mode; cached mutable models
   must not be shared with document edits. Apply the current deep-copy boundary.
2. Add `api/part_streptavidin_commands.py` with strict versioned schemas,
   `resources`, `validate_inputs`, pure `build`, and a thin capture/record adapter.
   Reuse `InputSource`, `EmbeddedResolver`, `SourceContractError`, typed references
   and the existing job publication CAS. Replay never reads a path, URL, catalog
   service or process-global asset cache as authority.
3. Capture raw PDB bytes and, when selected, the complete 846-byte coverage JSON
   before submission. Validate the coverage shape, unique known IDs, finite
   positive area and bounded URL strings; preserve native selected values.
   Extend `command_sources` so package manifests, revision/source audit,
   loadouts, missing-source repair and scoped replay include both descriptors.
   Their absence/corruption is unverified input evidence, never permission to
   delete downstream geometry.
4. Use a separate coating feature after particle creation. A proposed command
   envelope is `_proof_version=1`, `coating_version=1`, `importer_version=1`,
   `nanoparticle_id`, `pdb_source`, optional `coverage_source`, `mode`,
   `coverage_reference`, `count_override`, `footprint_nm2`, explicit resolved
   `spacer_nm`, and `seed`. Do not accept atoms, placement matrices, target count,
   a complete nanoparticle or arbitrary output metadata as inputs. Preserve the
   current actual native IDs; coating itself has no independent model ID.
5. Start with source-based set/replace/remove on a bounded gold particle with no
   attached biotin DNA, thiol handles or unsupported incoming ownership. A missing
   particle is a typed missing reference. Replacing/removing an occupied coating
   requires an explicit dependent-feature edit/delete; do not detach its DNA as
   an invisible side effect. Model the coating as a derived resource owned by the
   nanoparticle, or use an equally explicit typed coating selector. Legacy QD
   coatings remain available until their combined source closure is supported.

Suggested source admission for qualification, not approved production limits:
PDB at most 350,000 bytes and at most 4,100 ATOM/HETATM records; coverage JSON at
most 4,096 bytes and three validated presets. The first live version may restrict
the PDB descriptor to the audited bundled assembly digest. General source edits
need bounded structural validation (four models/chains, matching C-alpha counts,
required BTN C10/C11, finite coordinates and bond/output limits), not arbitrary
new PDB layouts that happen to fit the byte limit. A new bundled source version
is an explicit descriptor edit, not an automatic process-cache refresh.

Initial qualification should cover a single particle and 1, 16 and 64 requested
sites; these are test points, not scientifically justified limits. Select the
production site/work cap from measured wall time and memory. The native builder
can request over 1,500 sites via the densest coverage preset at 100 nm even though
`count_override` itself stops at 1,500; budget the computed request before looping.
There must be no `min(request, cap)` or unreported coverage adjustment.

## Admission, transport and storage gate

`core/part_verification_capture.py:14` currently permits 30,000 nodes, a
2,000,000-byte conservative string charge and 25 ms cooperative capture under
the state lock. Each atom is a model plus nine scalar fields (`models.py:2804`):
3,604 atoms alone require at least 36,040 nodes, before bonds or anything else.
Pinned PDB base64 charges another 1,759,968 bytes under that walk. This establishes
node refusal, not a measured total time/byte refusal.

| Boundary | Current bound | Coating implication |
| --- | --- | --- |
| Ordinary capture | 30k nodes / 2 MB / 25 ms | Real single tetramer cannot pass node bound |
| Verification and evaluation worker input | 2 MB pickled admitted capture | Must measure separately; capture charge is not pickle size |
| Evaluation candidate result | 16 MB JSON | Includes full authored result and regenerated recovery rows |
| Recipe recovery encoding | 8 MB cumulative encoded payloads | Repeated complete asset/source snapshots can dominate a long recipe |
| Portable document | 256 MiB decompressed; bounded ZIP/peer transport | Adequate source storage does not establish interactive admission |

`scripts/benchmark_coating_inputs.py` measures native cached/cold preparation,
source sizes, parsed atom/bond counts, full authoring charge, actual pickle/JSON
sizes, pre/post recovery encoding and unchanged default capture. It includes
0/1/16 independent coating assets and a single 16-site coating. It also calls
capture with an explicitly experimental 100k-node/4MB/100ms profile. This does
not change production configuration or prove that 100 ms under the UI lock is
acceptable. Its synthetic fixtures carry no executable coating recipe and must
not be reported as verified. Run it serially and keep the JSON as evidence.

Smallest possible shipping option, conditional on measurements: a dedicated
single-particle worker admission profile with separately bounded source bytes,
asset nodes, candidate bytes, recovery and execution time. Preserve the ordinary
profile and require revision-bound publication. The present evaluation append
allowlist only covers CPD/duplex jobs, so adding a pure command to the registry
alone does not enable this path. Source capture and parameter validation must be
cheap before any packing or imported bond inference. Async computation does not
by itself remove state-lock capture/deep-copy cost.

If that profile cannot preserve the interactive lock budget, the prerequisite
is an immutable resource/capture boundary, not a still larger global timeout:

- Store source bytes once by digest, as today, retaining portable inline bytes
  at document/package boundaries. The derived CAS remains optional and cannot
  become an undeclared requirement for opening plain `.nadoc` files.
- Represent reusable parsed asset content with an immutable, fully verified
  handle; compact authoring state references the handle and placements. This
  requires an explicit schema/migration and renderer/exporter contract because
  coatings currently embed mutable `ProteinAsset` objects.
- Capture only safely immutable resources plus a bounded mutable authoring
  header under the lock; validate/hash/serialize resources outside it and publish
  only against the same source revision. A digest cached on a mutable model is
  insufficient: it would bless later atom edits without inspecting them.
- Keep complete authoring comparison: verify the immutable asset content as well
  as placements/inputs. Do not mark `coating.protein` as presentation or trust
  candidate-provided hashes. Deduplicate recovery blobs separately; raw source
  deduplication does not remove repeated regenerated asset snapshots.

Native pose/diameter changes to supported coated particles are part of completion.
Pose-only changes can retain the pinned local asset/poses. Diameter changes must
replay coating with its recorded source/options or edit the upstream particle
feature and rebuild descendants; they cannot reread the current bundled file.
Define this before enabling the ordinary coating UI, otherwise the next drag or
resize falls back to an unverified legacy row. Combined create-with-coating UI
also needs atomic multi-row publication or an explicitly reviewed compound
command with both parameter sets; avoid publishing a bare particle when coating
fails. Existing atomic-failure behavior must remain.

## Biotin attachment is the next, separate contract

First extract optional explicit tether-template and identity-factory inputs into
`pocket_geometry`/`build_dna_set`, preserving all existing alignment, search and
clearance formulas. Propose a versioned `nanoparticle-biotin-dna` add/delete schema
with nanoparticle/coating reference, pinned tether PDB, sequence, pocket choice,
occupancy, linker length, history seed and explicit owned-record selection for
deletion. Derive helix/strand IDs by feature scope plus tetramer index and pocket;
do not record chosen axes or sampled coordinates. A source/coverage edit that
removes a referenced site must surface missing dependency repair, not transfer
an old pocket identity to a different geometric site silently.

The smallest v1 can admit one coated particle with no pre-existing DNA or other
particles, then expand obstacle support separately. A general contract must
include the complete current obstacle set, including absence/collection changes,
or a declared all-prior-design query. Recording only the selected target misses
real inputs: changing another particle or occupied domain can change the search
result. Geometry dependencies and unsupported authoring ownership must be
checked before native computation. Do not copy obstacle coordinates into params.

Budget both actual coating sites and up to four pocket attempts per site, each
with up to 37 directions times eight phases. Also bound source atom clouds,
total existing helix work (currently recomputed per domain), and sampled segment
counts: `_segments` allocates according to physical segment length, not merely
sequence length. A nucleotide-count limit alone does not bound arbitrary
pre-existing helix geometry. Keep exact occupancy failure and all-or-nothing
publication. Reuse typed incoming strand/helix/nucleotide closure for delete and
move, including extensions, binding/duplex/Join, CPD and protein consumers.

The extension is authoring state and belongs in the command. Atomistic linker
cache warming is separate derived display work after a successful commit;
cache absence, corruption or cancellation must not change replayed authoring.
If display/source reproducibility is later promised, pass a pinned pocket catalog
explicitly and include its digest in the existing fit cache key. Do not promote
cached fitted coordinates into recipe inputs.

## Validation and vendor precedent

Preserve and reuse `tests/test_streptavidin.py` (tetramer assembly, native packing,
tether orientation, publication counts, atomic UI failure),
`test_gold_strep_dna.py`, `test_strep_dna_occupancy.py`,
`test_biotin_extensions.py`, `test_biotin_display.py` and `test_biotin_cache.py`.
Add registered cold replay with recovery payloads poisoned and local bundle
access blocked, native full-authoring equality for both modes, explicit source
update/repair, changed coverage and source-tamper rejection, upstream diameter
edit, stable IDs, stale/cancelled job commit, owned dependency guards, portable
save/package/peer/loadout source closure, and budget refusal before computation.
Do not remove scientific/legacy compatibility tests merely because new recipe
tests pass. Qualify both maximum single-feature and repeated-feature cases.

Onshape documents external uploaded data as a prerequisite for reproducible
FeatureScript regeneration. Reference parameters expose data choices to users;
references to other documents are fixed to a version and updated explicitly.
This supports pinned PDB/coverage inputs as editable source parameters, not
implicit access to whichever bundled file happens to be installed.
[Official FeatureScript imports](https://cad.onshape.com/FsDoc/imports.html).

Onshape also explains that import updates attempt to retain references when the
model changes modestly, and recommends repairing reference geometry when it
does not. This supports explicit pocket/site dependency repair after an input
change, rather than guaranteed index preservation across arbitrary source edits.
[Official import-reference guidance](https://www.onshape.com/en/resource-center/tech-tips/tech-tip-how-to-maintain-references-on-updated-imports).

SOLIDWORKS exposes separate edit, update-model and break-link operations for
supported imported bodies. It does not describe an imported body as an editable
history of its original creation. NADOC should similarly label these designs
`reproduced_import` while keeping native coating/attachment parameters editable.
That labeling is NADOC's inference, not a vendor requirement or an LLM policy.
[Official SOLIDWORKS import operations](https://help.solidworks.com/2026/english/SolidWorks/sldworks/t_importing_dxf_dwg_file.htm?id=18.20.11).

## Measured gate decision: explicit single-coating job

The root agent ran the memory-only experiment; evidence is
[coating_capture_experiment_p4.json](coating_capture_experiment_p4.json).
These fixtures are not recipes and the run does not establish cold proof,
publication latency, contention, rendering or chemical validity. Capture has
three repeats per fixture; this is feasibility evidence, not a tail-latency study.

| Measured case | Capture nodes | Experimental capture median / max | Admitted pickle | Cumulative recovery base64 |
| --- | ---: | ---: | ---: | ---: |
| One adsorption coating, PDB only | 47,275 | 52.91 / 54.75 ms | 882,241 B | 421,284 B |
| One adsorption coating, coverage pin | 47,278 | 49.69 / 51.31 ms | 883,485 B | 424,132 B |
| One tether coating, PDB only | 47,486 | 52.24 / 86.47 ms | 884,211 B | 421,984 B |
| One tether coating, all three pins | 47,492 | 49.53 / 49.88 ms | 906,984 B | 434,988 B |
| One adsorption coating, 16 requested/placed sites | 47,548 | 49.80 / 50.10 ms | 886,171 B | 426,984 B |
| Sixteen independent one-site coatings | 644,758 | Refused | Not admitted; fixture pickle 7,292,291 B | 38,889,072 B |

All single-coating fixtures failed the unchanged default node allowance. The
experimental profile was **100,000 nodes / 4,000,000 charged bytes / 100 ms**;
it remains prospective, not a production budget change. Single-coating admitted
pickles fit the existing 2 MB worker input. Candidate designs without history
were roughly 0.98–1.01 MB. The sixteen-asset fixture failed both capture profiles
and also exceeded existing worker input and cumulative recovery bounds; its
candidate plus recovery lower bound was approximately 47.95 MB.

Cold asset preparation took 109.08 ms for adsorption and 150.15 ms for tether.
The resulting assets contain respectively 3,604/3,620 atoms and 3,692/3,709 bonds.
Warm native builds took 32.08–66.39 ms for the one-site cases and 82.39 ms for the
16-site case. One modeled pre/post recovery pair took approximately 20–21 ms to
encode. These costs belong outside interactive mutation/capture locks; moving
only packing into a worker while retaining parsing/encoding in a route would
miss a substantial part of the work.

**Recommendation: proceed with the bounded, explicitly requested single-coating
job before an immutable-asset redesign.** A roughly 50 ms one-time capture is a
reasonable engineering tradeoff for an explicit regeneration operation with
progress, cancellation and atomic publication. This is a judgment about this
workflow, not a claim that 50 ms is imperceptible or a vendor-defined threshold.
The existing `state._lock` is global, so another request may wait during capture.
The observed 86.47 ms maximum matters: do not advertise a 50 ms maximum from the
medians or infer tail behavior from three repeats.

This narrow option preserves ordinary capture defaults and avoids a broad asset
schema/renderer migration before there is a demonstrated need. Implement it as:

1. A server-owned named capture profile available only to an explicit coating
   evaluation/rebuild request after cheap eligibility. The caller cannot supply
   arbitrary node/byte/time limits. Require zero or one current coating and at
   most one resulting coating; initially use one undecorated gold particle with
   no DNA, biotin or additional imported assets. Reject unsupported scope before
   capture or native packing. Keep a separate small authored-node/history bound
   so the extra allowance cannot turn into a generic large-model bypass.
2. Qualify at most 16 requested sites initially: this run exercised 1 and 16, not
   64 or 1,500. This is a provisional software work cap, not a change to packing
   math. Requests above it receive an explicit budget diagnostic before the
   placement loop; keep the existing legacy workflow available. Do not silently
   reduce counts, manufacture poses, or round source-derived counts to fit.
3. Use one acquisition of the existing job slot and one isolated capture per
   request. Start from the existing 180-second supervised evaluation machinery,
   revision/source identity checks and cancel/reap behavior. Parse pinned source,
   pack, replay, compare complete authoring and encode recovery in the worker.
   Preserve the 2 MB input, 16 MB result and 8 MB recovery limits. A 4 MB capture
   charge is not permission to send a 4 MB pickle.
4. Give explicit job edit/delete/verify operations the same qualified profile
   when rebuilding the admitted coating recipe. Without this, creation would
   succeed but subsequent regeneration would hit the default node refusal.
   Ordinary audit and edit paths retain their default limits and can report that
   this recipe requires explicit evaluation. Never escalate automatically on a
   capture failure, background response, selection, drag event or preview poll.
5. Keep the larger profile out of the live drag loop. Preserve the native
   pose/resize and combined-create atomicity completion gates above before
   broadly enabling the existing UI. A job-only capability can ship earlier
   with its limited entry point clearly described; it is not completion of all
   coating lifecycle support. Over-budget history remains unavailable for that
   operation, not geometrically invalid or permission for cascade deletion.

Exit criteria before enabling that job capability:

- Real registered empty-root gold→coating cold replay in both modes, pinned
  bundle access blocked, poisoned recovery, source tamper/missing-source repair,
  changed source/coverage/diameter parameters, repeat rebuild and save/load must
  reproduce complete native authoring. Include a coating edit and removal so
  source and candidate capture paths are both exercised.
- Measure actual submit capture, worker parse/packing/replay, commit validation,
  `state.set_design` undo snapshot, response size and retained memory separately.
  The existing experiment omits commit's source deep copy and complete feature
  history. Keep expensive work outside the state lock wherever the current
  transaction contract allows it; do not weaken revision or source checks.
- Use a longer controlled run (at least 30 samples for each supported boundary)
  to report p50/p95/max lock holds and concurrent lightweight-request latency.
  A provisional qualification target is p95 lock holds below 100 ms with no
  systematic deadline overshoot. Capture's timer is cooperative and a nested
  deep copy is not preemptible: no claim of a hard 100 ms real-time ceiling.
  Repeat on representative retained history and document state, not just an
  empty synthetic fixture. Compare ordinary workflows with jobs disabled and
  after the profile integration; they must not invoke this profile or acquire
  additional proof work.
- Confirm progress remains responsive while the child runs, cancellation leaves
  geometry/history unchanged, stale results cannot commit, a busy slot cannot
  create a second capture loop, and a failed capture releases admission. Polling
  must not recapture the design or clone its candidate.
- Exercise repeated edits until the cumulative recovery bound is reached and
  confirm an atomic, actionable budget refusal. Qualify input/result envelopes
  with actual history rows, not only the smaller design-only JSON sizes above.

If these gates fail because of repeated lock cost, recovery growth or admission
instability, do the immutable resource/capture work before expanding this slice.
The measured sixteen-asset case already justifies that work **before multi-
particle coatings or general asset-heavy interactive proof**, but does not make
it a prerequisite for one explicitly regenerated particle. Avoid expanding the
profile repeatedly to chase larger cases.

The workflow has CAD precedent without implying identical implementation:
Onshape exposes a distinct paused-regeneration mode for batching parameter
changes, with explicit regenerate/discard controls and documented restrictions.
It also exposes per-feature timing and identifies features taking over ten
seconds. Those are regeneration costs, not UI-lock budgets; they support making
expensive work visible and deliberate, not borrowing a ten-second interactive
latency allowance. [Onshape regeneration controls](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm),
[Onshape performance panel](https://cad.onshape.com/help/Content/Home/performance_panel.htm).
SOLIDWORKS similarly documents freezing unchanged feature regions to avoid
rebuilding them on every model change, while noting that other rebuild costs
remain. [SOLIDWORKS Feature Freeze](https://blogs.solidworks.com/products/solidworks/solidworks-freeze-saves-you-time/).

## Bounded pure contract and numerical compatibility (2026-10-15)

The pure adapter now exposes `nanoparticle-patch` with strict `coating_version=1`
and explicit `set`, `move`, and `remove` actions. `set` records the complete PDB
descriptor, nullable coverage descriptor and selection, mode, footprint, spacer,
seed and count override; optional diameter means recompute from those inputs.
The unchanged preparation and packing bodies now accept explicit source text
and data. Legacy bundle wrappers retain their original math and evaluation
order. `move` preserves the local coating and uses native rigid movement;
`remove` needs no new source read. One unowned gold particle, no other authored
geometry, the known 1STP digest, bounded coverage schema and at most 64 requested
sites form the software contract. The 64-site cap is **pending qualification**,
not an expansion of the earlier measured 16-site envelope or a production
capture change. Pure tests passed before the numerical-pin increment; registered
proof, pin, transport and 64-site results must be reported separately.

`scripts/benchmark_coating_contract.py` is an unexecuted qualification harness
at this writing. It constructs 1/16/64-site recipes in both modes, then measures
set, resize, move and removal separately, with real history/recovery pairs,
source closure, JSON reload, default capture refusals, the experimental
100k-node/4 MB/100 ms profile, and registered spawned cold proof. Worker input
remains 2 MB. This memory-only harness does not qualify the global state lock,
live publication or concurrent lightweight requests; those earlier exit gates
still apply. The registered test's longer capture clock only removes CI timing
flakiness, and is not the prospective production profile.

**Decision: pin the set/repack numerical engine before public enablement.** A
seed is insufficient evidence of replay compatibility across library upgrades.
NumPy limits its repeatable-stream guarantee to matching generator, seed, call
sequence, build, environment and machine. It permits stream changes and changes
to `default_rng`'s default generator. These are documented limits rather than
an observed NADOC regression. [NumPy random compatibility policy](https://numpy.org/doc/stable/reference/random/compatibility.html).
SciPy documents using a supplied generator for repeatability and its transition
from `random_state` to `rng`; it does not promise cross-release bitwise rotation
results. The native call still passes its existing generator unchanged; this
work does not migrate RNG APIs or substitute a new generator.
[SciPy Rotation.random](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.transform.Rotation.random.html).

The practical consequence is stronger than small coordinate drift: a changed
sample or floating-point result can cross the native radial or 0.25 nm clash
threshold and change which sites survive. NADOC's current full-authoring
comparison would detect a mismatch when verifying an old model, but an explicit
edit could otherwise adopt changed packing without identifying the environment
change. A numerical pin makes this dependency and failure actionable.

The implementation uses `part_streptavidin_contract.py` and the existing
`part_numerical_runtime` helper, with a fixed engine family, server-generated
implementation/runtime hashes, and checks immediately before native atom
preparation and after candidate construction. Its manifest covers executed
preparation, PDB parser/bond inference, tether rotation, gold replacement,
models and the adapter; imported simulation/rendering functions are excluded.
PDB and coverage are separate content-addressed feature inputs, with neither
bundled data nor output coordinates smuggled into the implementation manifest.
Library/platform/thread identity follows the already established CPD and duplex
relaxation policy. Whole-file hashing is conservative: an unrelated edit inside
one listed scientific module can require requalification. Avoid broad unrelated
application files, but do not claim function-level version retention that NADOC
does not implement.

Ordinary source/reference admission does not initialize the numerical runtime.
Only `set` carries a mandatory engine pin; pose-only movement and removal do
not add new packing execution or a new pin. Replay never fills in or refreshes a
missing/stale pin. The future public append adapter must select current pins in
its isolated worker and reject caller-supplied pins. Engine/runtime mismatch is
an unverified dependency, preserving geometry and history until an explicit,
checkpointed upgrade path is available. Pins detect incompatibility; NADOC does
not yet archive executable environments or promise replay on arbitrary machines.
Do not mark numerical reproducibility complete solely because same-runtime
tests pass.

This matches the direction of CAD versioning without claiming equivalent
infrastructure: Onshape links external custom features to specific document
versions and makes later versions an optional explicit update. Feature Studios
also expose standard-library version selection. NADOC should retain the old pin
and offer an explicit requalification/update operation, rather than silently
adopting the installed engine. [Onshape custom feature updates](https://cad.onshape.com/help/Content/PartStudio/add_custom_features.htm),
[Onshape standard-library version selection](https://cad.onshape.com/help/Content/FeatureStudio/feature_studios.htm).

Other existing procedural NADOC commands mostly use semantic command versions,
identity scopes and native geometry builders, while CPD/duplex already pin their
numerical environments. This is an incremental boundary, not proof that every
existing procedural command is portable across arbitrary runtime upgrades.
Coating's seed-dependent discrete rejection makes it a clear case for the
established stronger contract. A future common upgrade policy should inventory
other solver/discrete-selection families without adding runtime probing to
ordinary edits or changing their algorithms.
