# Architecture review and completion sequence — October 15, 2026

The existing foundation is sound, but it is not a finished dependency or repair
system. Independent input replay, explicit empty/import roots, deterministic
identities, complete authoring-state comparison, failure-atomic recording and
revision-bound publication should be retained. Recovery snapshots remain useful
for undo/scrubbing and must never become evidence of native reproducibility.

The persistent implementation goal covers standard-part P3–P6. Assemblies remain
in `assembly_deferred.md`; part-local proteins, nanoparticles and duplexes do not.
The checkpoint before this review is `a8bc9fc9` (pushed).

## Findings that change the order of work

1. Dependency edges are mostly conservative whole-part barriers. They identify
   possible impact, not an exact missing reference or a proven blocked child.
   Several permissive native batch builders silently skip absent targets. Proof
   needs explicit reference preconditions so a reproducible no-op cannot conceal
   a dangling selection. Keep permissive historical recovery separate.
2. The native editor requires an already reproducible source. That protects
   unlogged work, but cannot repair a broken recipe. Add an explicit repair
   transaction, separate from ordinary edits, with a revision-bound candidate,
   precise diagnostics and an explicit decision about displaced geometry.
3. A thread deadline checked between commands cannot interrupt one long solver.
   Cancellation must stop isolated expensive evaluation before the admission
   slot is released. Keep ordinary recording, rendering and scrubbing free of
   full proof work; do not increase concurrency or relax existing test budgets.
4. Command availability is spread among recovery dispatch, proof dispatch and
   capability declarations. Consolidate versioned command metadata as contracts
   mature, keeping legacy decoders until persisted compatibility tests pass.
   Do not attempt a broad unmeasured rewrite of working native algorithms.
5. P3 also includes opaque `connectivity-core` generation. At review time compound
   branch construction/routing/budget work and CPD conversion were incomplete.
   A generator must emit native commands and their actual inputs. A copied
   candidate Design is not an executable construction recipe.
   The subsequent native joined/connectivity compiler and pinned CPD job
   contracts close this execution gap; see the latest `implementation.md`
   checkpoint and `validation_native_jobs.json` for evidence and limits.
6. Reproducibility, reference integrity and scientific validation are separate
   results. Existing `integrity_checked: false` is truthful; a verified replay
   alone must not become a general valid-design badge. Physical results remain
   display-only and require their own freshness provenance.

## Research and decisions

[Onshape's FeatureScript introduction](https://cad.onshape.com/FsDoc/intro.html)
documents the feature tree as calls with parameters, geometry as build output,
and regeneration as execution. Determinism excludes external input, time and
randomness. NADOC's registered inputs and chosen identity namespaces follow this
model; arbitrary Python may orchestrate those commands but is not itself a
native feature contract.

[Onshape feature errors](https://cad.onshape.com/FsDoc/output.html) roll back the
failing feature's effects. [Reference repair](https://cad.onshape.com/help/Content/Document/repairing.htm)
retains editable definitions and uses a prior healthy view to identify and
replace references, with optional downstream propagation. For NADOC, keep a
failed definition, its diagnostics and clearly labelled last-good geometry
distinct. Never silently drop failed features to make a badge green.

These are architectural precedents, not claims that those vendors enforce an
LLM-specific policy. A process with authority to rewrite NADOC's server or files
is outside application-level enforcement. Strict policy must live at the trusted
mutation boundary and cannot be downgraded by an agent's request fields.

## Implementation checkpoints and acceptance

| Checkpoint | Scope | Required evidence |
|---|---|---|
| P3 hardening | Explicit reference failures; process-bounded expensive evaluation; remaining branch/connectivity and CPD contracts | Missing/partial targets cannot certify; cancellation frees resources; all native inputs replay without saved outputs; no scientific algorithm changes |
| P4 standard-part assets | Pinned content and availability checks; protein/NP/duplex creation and attachment commands; imported-source labels; physical-result freshness | Offline deterministic replay from declared assets; source/parameter tampering fails; undo and persistence work |
| P5 repair | Structured failure/blocked/independent status; reference replacement; keep-broken drafts; same candidate for preview/commit; passive desktop and part-VR diagnostics | Repair from an invalid source, cancel/race/undo/reload tests, running-app checks, no hidden geometry or modal spam |
| P6 policy and cleanup | Atomic registered command batches; trusted strict policy; generic setter/import/headless bypass checks; retire superseded dispatch only with compatibility evidence | Editable native output from agent batches; unsupported/injected state rejected; human drafts and explicit imports preserved |

Cheap checks belong at the command boundary. Full cold replay is the oracle and
an explicit/background operation. Reuse an independently verified prefix first;
only reuse independent suffixes once declared reads/writes and equivalence tests
justify it. Record cold/warm latency and memory for representative small and
large documents; a microbenchmark is not evidence of interactive responsiveness.

Each checkpoint updates tests and the implementation ledger, runs required
validation, records existing regression debt separately, and is committed before
the next consequential choice. No bulk user-document migration or assembly
implementation is authorized by this sequence.

## Additional primary-source precedents

Research checked October 15, 2026. Vendor behavior below is documented; the NADOC
actions are design recommendations, not claims about vendor internals.

- **Retain repairable children when appropriate.** SOLIDWORKS documents deleting
  a parent while retaining sketch-based children with dangling sketch-plane
  references, then continuing or stopping to repair. This is a specific supported
  case, not a guarantee for every child feature. P5 should retain failed feature
  definitions in a draft and offer reference replacement; cascading deletion must
  be explicit. [Sketch plane references](https://help.solidworks.com/2021/english/solidworks/sldworks/t_Sketch_Plane_References.htm)
- **References describe intent, not just identity.** Onshape queries encode
  criteria and resolve against the current modeling context. Its library offers
  identity-preserving and split/merge tracking plus validation of mandatory
  nonempty selections. Deterministic IDs alone cannot establish that an input
  still exists or resolves unambiguously. Start P3 hardening with typed target
  checks; evolve toward producer/role/selector/cardinality contracts in P5. Repair
  should change the authored reference, not only patch a separate dependency
  graph. [Modeling](https://cad.onshape.com/FsDoc/modeling.html),
  [Tracking and required-query validation](https://cad.onshape.com/FsDoc/library.html#startTracking-Context-map)
- **Prefix reuse is a reasonable first performance strategy.** Onshape documents
  executing the changed feature and everything after it. SOLIDWORKS distinguishes
  rebuilding changed features from force rebuilding all features. Keep NADOC's
  independently verified prefix and an uncached full replay oracle before adding
  more complex independent-suffix reuse. Neither source establishes that a full
  dependency-aware incremental engine is required for a professional first
  implementation. [Onshape regeneration and profiling](https://cad.onshape.com/FsDoc/debugging-in-feature-studios.html),
  [SOLIDWORKS rebuild tools](https://help.solidworks.com/2020/English/SolidWorks/sldworks/c_fundamentals_rebuid_tools_help.htm?id=84a4ec680d184f3cb3416294b777b92d)
- **Cheap checks and deep verification have different jobs.** SOLIDWORKS normally
  checks new/changed features against adjacent entities; its broader verification
  checks all faces/edges and explicitly costs more CPU and time. Onshape exposes
  per-feature timing and paused regeneration. Keep reference validation local to
  execution; cold proof is explicit/background work, not a prerequisite for every
  passive status read or display interaction. [Verification on rebuild](https://help.solidworks.com/2017/english/SolidWorks/sldworks/HIDD_ASSYXPERT_VERIFY.htm),
  [Feature list and regeneration controls](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)
- **Pin external inputs.** Onshape requires external data to be uploaded before
  FeatureScript can reference it; references outside the workspace use a selected
  version. P4 should make asset bytes or immutable content hashes declared inputs,
  check availability, and distinguish reproducible imports from native editable
  construction. [FeatureScript imports](https://cad.onshape.com/FsDoc/imports.html)
- **Automation should create ordinary editable features.** Onshape's Features API
  example creates a parameterized cube which can then be edited in the GUI.
  SOLIDWORKS macro features have edit-definition and rebuild callbacks. Onshape
  also documents AI completion of FeatureScript; these sources establish no
  vendor-wide prohibition on LLM-generated custom features. NADOC's requirement
  for individually editable construction steps is therefore an explicit product
  policy: require registered features or expandable compound features with
  meaningful inputs, regardless of whether a human or script submits them.
  [Onshape Features API](https://onshape-public.github.io/docs/api-adv/featureaccess/),
  [SOLIDWORKS macro features](https://help.solidworks.com/2023/english/api/sldworksapiprogguide/Macro_Features/Overview_of_Macro_Features.htm?id=1.4.36.0),
  [FeatureScript Co-Complete](https://cad.onshape.com/help/Content/Home/featurescript_co_complete.htm)

The reviewed primary sources do not establish an asynchronous arbitrary
FeatureScript execution contract or a hard regeneration timeout. Process
isolation for expensive NADOC evaluation is our engineering recommendation, not
a claimed vendor precedent. Timeouts, cancellation and unsupported commands must
remain separate from missing-dependency diagnostics. Reproducibility alone does
not certify reference integrity, scientific validity or useful edit granularity.

## Generated scope identity and reference mapping

The audit below drove the version-2 scope implementation in the next checkpoint.
Explicit typed field descriptors now preserve authored text, check ownership and
closure, map canonical base keys and functional linker identities, and reject
ambiguous aliases. Selected subsequences retain native order while independent
objects retain their relative order. Legacy scopes execute only when the old and
new meanings agree; unsafe old definitions require an explicit upgrade. Nonempty
unclassified compatibility payloads remain unsupported, including old binding
topology snapshots and some legacy CPD/animation fields. This is not blanket P4
asset-command coverage. See the implementation ledger and focused evidence.

The original prerequisite, before admitting additional P4 commands, was to replace the
untyped string walker in `generated_native_scope.py` with explicit identity and
reference traversal. Complete-output comparison alone does not establish
that a scoped command acted on the intended object. The audit found:

- **Authored text changes (open).** A small in-memory scope probe creating a
  helix with both `id="raw"` and `label="raw"` changed its label to
  `gen_<group>_raw`. Names, notes, sequences, filenames and arbitrary asset
  metadata can likewise change when they equal an object ID.
- **Aliases edit the wrong object (guard added in this checkpoint).** With
  retained helix `raw` at length 10 and generated `gen_<group>_raw` at length 20,
  an actual native `helix-update(helix_id="raw", length_bp=30)` left the retained
  helix at 10 and changed the generated helix to 30. Inversion aliased both local
  IDs; dictionary composition hid the collision. The new guard rejects retained
  collisions and duplicate inverse aliases before builder execution. It does
  not solve typed ownership or text remapping.
- **Nested IDs do not establish closure (open).** A subdomain ID without its
  owning overhang passes the existing-input check but is omitted from the local
  model, which selects only top-level records. Strands, frames, cluster parents
  and assets likewise require their referenced owners. Missing closure needs
  a structured diagnostic, not implicit expansion into unrelated user geometry.
- **Embedded identities need codecs (open).** Linker helices/strands are derived
  as `__lnk__{connection.id}` and `__lnk__{connection.id}__a|__b`; independently
  namespacing them breaks ownership even if their prefix survives. NP helices
  must retain `__np__`, and Join connector families retain `join_`. CPD canonical
  base keys embed helix/crossover IDs, including keys of `design_coordinates`;
  the current walker handles neither embedded IDs nor dictionary keys.

Use model-class field descriptors, not an “all `_id` fields” suffix rule.
`photoproduct_id` is a product token, `process_id` is provenance, and protein
chain IDs/source residue tokens are asset-local identities. The minimum mapping
inventory is:

| Model/family | Identity/reference fields requiring explicit traversal |
|---|---|
| Authoring collections / subdomains | Actual record `id`; nested subdomain `id` and owning overhang; never arbitrary metadata `id` keys |
| Helix / lattice frame | `lattice_frame_id`; `placement_cluster_id` |
| Strand / domain | `domains` and `routing_seed`: `helix_id`, `overhang_id`, `binds_overhang_id` |
| Cluster / joint / Join constraint | `helix_ids`, `domain_ids[].strand_id`, `parent_cluster_id`, `overhang_duplex_driver_id`; joint `cluster_id`; Join `first/second.cluster_id` and `source/target.helix_id` |
| Deformation | `affected_helix_ids`, `cluster_ids`, `target_ranges` helix/strand refs; discriminated `targets` (`id`, `strandId`/`strand_id`); sweep `params.preceding_op_ids` |
| Crossovers / constraints / forced ligations | `half_a/b.helix_id`; `helix_ids_a/b`; `three_prime_helix_id`, `five_prime_helix_id` |
| Overhang / connection / binding / version | Helix/strand/parent-overhang refs; `overhang_a/b_id`, `sub_domain_a/b_id`, `target_joint_id`, `driver_oh_id`, `driven_oh_id`; known `strand_anim_setup.binder_strand_id` |
| Duplex / prior binding topology | `left/right.overhang_id`, `target_joint_id`; explicit snapshot schema for driver/driven IDs, driven Helix, strand/domain, prior helix, crossovers and forced ligation |
| Nucleotide transforms / CPD | `helix_id`, `crossover_id`; parse/remap/format `base_key_1/2` and `design_coordinates` keys via canonical base-key grammar; legacy stable IDs need a separate declared adapter |
| Flexible marks/connections | `strand_id`, `cluster_a/b_id`, strand refs in `anchor_a/b` and `segment_bead_keys` |
| Extensions / staple groups | `strand_id`; `strand_ids` |
| Protein / nanoparticle | Attachment `asset_id`, `binder_strand_id`, discriminated target overhang; particle `biotin_dna` strand/helix refs; conjugation particle plus surface-strand helix/strand/overhang/bound-overhang refs; NP version particle/strand/overhang/duplex refs |

Keep identity allocation, reference remapping and ownership closure separate.
Index typed identities and owners once; require injective local/destination maps;
traverse declared fields; preserve independent records and authored text exactly.
Fail closed for unclassified reference-bearing families. Reuse this registry for
dependency diagnostics instead of maintaining another untyped ID inventory.
`feature_dependencies._object_refs` is incomplete and cannot serve unchanged as
this registry. Existing explicit mapping in `cluster_copy.py` offers examples;
`element_copy.py` has the same generic string-walker risk and needs P4 review.

Version corrected scope semantics for new recordings. Existing histories retain
saved definitions and recovery behavior. Never silently rewrite saved IDs or
metadata to fit a new mapper: unsafe old scopes become explicitly unverified and
receive a reviewable upgrade/repair path. Test both persisted scope versions.

Required acceptance cases: user text equal to an object ID stays unchanged;
retained/generated alias rejection before execution; equal text IDs in different
typed resource families; nested subdomain, frame/cluster and parent closure;
linker create/edit/delete with correctly derived IDs; NP/Join prefix recognition;
CPD base-key and dictionary-key round trips with colon-bearing owner IDs;
incomplete asset closure; independent geometry preservation; existing ordinary
generated recipes replay without saved outputs; and cold/warm measurements with
no new full-model scan on unscoped commands.
