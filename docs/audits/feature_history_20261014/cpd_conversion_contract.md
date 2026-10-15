# CPD conversion: remaining P3 contract

Audit date: 2026-10-15. Scope: standard parts only. This is a source audit and
implementation proposal; no solver, tests, molecular placement or production
behavior was changed for this audit.

**Decision:** make conversion an explicit, versioned, expensive native feature.
Keep the current scientific algorithm and ordinary five-second verification
budget. Add a separate bounded process job for creation, verification and recipe
edits that need conversion. First make its geometry source explicit: the current
builder can consume a physical simulation reference that proof deliberately
excludes. Increasing the timeout alone cannot close P3.

## What the current code actually consumes

| Stage | Evidence | Contract consequence |
|---|---|---|
| Route | `backend/api/routes_photoproducts.py:193` records `base_keys`, `stereochemistry`, `history_seed`, `method=convert`, and runs the solver inside `mutate_with_feature_log`. | IDs are explicit, but source selection, template identity and engine compatibility are not. Work currently occupies the mutation lock. |
| Template | `backend/core/cpd_design.py:22` checks current registry capability, selects the coordinate template, verifies its SHA-256 and validates released/preliminary template schema. | Keep these gates. Pin which template was selected; replay must never silently substitute a newer template. |
| Source model | `cpd_design.py:527` calls `build_atomistic_model(design)` with defaults. `backend/core/atomistic.py:1959` prefers a usable `Design.atomistic_reference`; `:579` accepts an atom-bearing reference when its topology hash matches, or when the hash is absent. | Current conversion can depend on physical coordinates and bonds absent from the recipe. `part_history_contract.py:41` classifies this reference as physical state. |
| Endpoint resolution | `cpd_design.py:529` sorts and resolves two distinct canonical base keys; requires crossover-extra thymidines with atoms and rejects already-consumed endpoints. | References must remain canonical, producer-bound and repairable. No simulation serials as recipe addresses. |
| Placement | `cpd_design.py:101` fits the template to actual bonded flanking atoms and searches rigid pose plus six single-bond torsions against the surrounding model atoms. | Inputs include the upstream part's poses, sequences, bonds and nearby environment, not just the two crossover IDs. Start with a conservative whole-part dependency barrier. |
| Output | `cpd_design.py:453` projects two nucleotide poses and exact local product coordinates; `:548` stores them and optimizer diagnostics in `PhotoproductJunction`. | These are regenerated outputs. Saved `design_coordinates`, torsions or a snapshot cannot become proof inputs. |
| Proof | `backend/api/part_proof_commands.py:40` rejects conversion before execution; `backend/core/part_history_proof.py:136` compares every authoring field exactly. | A supported-but-expensive contract needs distinct admission, not an unknown-contract label. Float and diagnostics reproducibility must be demonstrated; do not relax comparison to hide drift. |

Current cis-syn template registration is
`backend/data/forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/template.json`,
SHA-256 `cfb5cd66b05f210b8e6f5e95478373ad169d9de3dfbfcff91a2b0c9fe908c0d6`
(`photoproduct_registry.json:137`). This is an audited observation, not a new
hardcoded scientific approval. `minimize_attachment_bonds()` itself reloads
`design_template()` with the default cis-syn at line 134. The first contract must
therefore admit **cis-syn only**; extending stereochemistry requires separate
scientific review rather than relying on the request enum.

## Explicit source and minimum versioned inputs

Use a dedicated conversion schema, independently versioned from the general
proof envelope. Required inputs:

- `method=convert`, `conversion_version=1`, `product=TT-CPD`, `stereochemistry=cis-syn`.
- Exactly two canonical `base_keys` plus immutable `history_seed` UUID. Preserve
  current sorted endpoint/patch order and existing-pose ID behavior.
- `source.kind=native`: explicitly build from the replayed authoring prefix,
  ignoring physical display/reference state **only inside this new command**.
  Implement selection on an isolated input copy or a narrowly explicit builder
  input; call the unchanged placement algorithms. Do not reinterpret old rows
  or change global atomistic defaults. A caller must select this source; a
  legacy/default request remains unverified until intentionally recreated.
- A template reference containing product/registry identity, schema version,
  template SHA-256 and coordinate/endpoint conventions. Resolve immutable bytes
  from a verified asset manifest; missing/mismatched bytes are actionable
  failures. Current capability and evidence gates are checked independently;
  a historical hash is not permission to bypass a withdrawn qualification.
- An engine manifest ID/hash covering `canonical-torsion-search-v2`, native
  placement version (`native-full-o5-v1`), relevant implementation/data hashes
  and numerical-runtime compatibility. In particular the native duplex path
  reads `backend/core/data/measured_atomistic_template.json`; extra-base
  placement uses its own existing templates/algorithm. A template-only hash is
  insufficient. A manifest should cover this dependency closure, not every
  unrelated repository file. Record/check NumPy/SciPy and BLAS policy; pin a
  supported compatibility version rather than asserting universal bitwise
  portability.

Do not store an immutable upstream-authoring hash as an edit-blocking feature
parameter: a repaired/edited upstream part must regenerate the feature from its
new inputs. Use that hash in a job/result/cache key instead. A job captures source
document/revision and the complete recipe fingerprint separately.

An alternative `source.kind=pinned-reference` requires an explicit immutable
source asset containing atoms, stable nucleotide mapping, bonds, frame/units,
digest and provenance, with an exact compatibility rule for its upstream
topology. This is an **imported geometry dependency**, never a fully native
editable construction. Reject this variant until P4 asset capture/portability
exists. Do not obtain it implicitly from the live `atomistic_reference` field or
allow LLMs to disguise arbitrary coordinates as native conversion inputs.

Creation and replay should both use the same spawned worker and numerical-thread
policy. If exact output equality cannot be maintained on a supported engine,
report an engine compatibility/reproducibility failure and investigate. Numerical
normalization, alternative search selection or changed tolerances are separate
decisions, not silent fixes to pass history checks.

## Where the cost is, and what can safely avoid it

The recorded evidence is **70.70 seconds for conversion plus replay together**
(`validation_p3_expansion.json:127`, `implementation.md:214`). It does not provide
per-stage timing or establish that one conversion takes 70 seconds.

Static code identifies two potentially substantial stages: whole-part atomistic
construction, including native extra-base placement, and local CPD optimization.
The latter runs 24 cube-orientation starts through bounded least squares
(`cpd_design.py:322`, 180 evaluations each), polishes the best two with L-BFGS-B
(`:341`, 500 iterations/1,000 function evaluations), then attempts constrained
SLSQP (`:382`, 200 iterations). Residuals/Jacobians repeatedly compare moving
atoms against the nearby environment. Add stage timing to the job report, outside
authoring output, before claiming a quantitative bottleneck.

There is no currently authored planner choice that safely removes this search.
A winning orientation index alone cannot reproduce the existing selection:
all 24 candidates determine the best two, both are polished, and final acceptance
compares objectives/clearance. Persisting optimized torsions or coordinates would
turn a solved output into an input. Replaying only one stored start changes the
algorithm and requires isolated A/B scientific review before production use.

Safe first optimizations are orchestration: independently replay once per job,
retain one verified prefix for suffix edits (`part_recipe_prefix.py` already does
this within a request), and avoid invoking conversion during scrub, selection or
ordinary edits. Later, a bounded server-owned cache can reuse a result only for
the complete input/engine/template fingerprint. Cold independent verification
must remain available and must never trust saved document output as that cache.

## Bounded execution and editing policy

1. Separate pure contract/reference validation from execution cost admission.
   The ordinary worker keeps `TIME_BUDGET=5.0`; known long features return
   `long_job_required` before placement, with the affected feature ID. Cheap
   missing-reference checks remain available without solving.
2. Add an explicit long-operation job mode using the existing spawned-process
   supervisor, single global admission slot, no queue, bounded memory-only
   input/result, one native numerical thread, and parent wall deadline. A
   proposed initial ceiling is 180 seconds **per whole job**, subject to the
   focused fixture timing; expose the limit and fail unverified on timeout.
   This is a separate execution policy, not a raised ordinary-worker budget.
3. Bound estimated atom count and command count before model construction;
   nucleotide count alone does not bound every asset expansion. Fail closed on
   unsupported asset families. Keep the two-megabyte capture/result transport
   bounds initially; bounded scientific output that cannot fit is a reported
   limit, not permission to spill into scratch or return partial geometry.
4. Creation, proof, repair and parameter-edit jobs run against captured input
   outside the document lock. Parent publication verifies document identity,
   revision and requested recipe fingerprint again, validates the complete
   candidate, and publishes one atomic undo/history transaction. Worker code
   never imports or mutates a live document session. Cancellation, source change,
   deadline or worker failure leaves the document and undo/redo untouched.
5. Terminate/kill and reap before releasing admission, as in the existing proof
   worker. OS-uninterruptible process states can delay reaping; expose stopping
   status and keep the slot held. Job progress can identify the feature/stage;
   never claim a guessed percent complete.
6. `part_recipe_edit.change_recipe()` currently has a cooperative five-second
   checkpoint around commands. It cannot interrupt a running SciPy call. Keep
   long commands out of that path. The long edit worker must perform original
   source proof and candidate suffix regeneration, including rebuilding recovery
   data, with a bounded result protocol. The existing verdict-only worker cannot
   publish an edited model without this additional protocol.

A cancelled/timed-out solve is an incomplete verification, not evidence of broken
geometry. Missing endpoint producers and changed base identities are separate
reference errors with repair targets. Parameter edits may change all downstream
CPD poses because the steric environment is an input; conservative invalidation
is required until a proven narrower dependency rule exists.

## Existing display/export behavior to preserve

`atomistic_reference` is a persisted simulation-derived coordinate source. The
ordinary all-atom builder intentionally honors it. `apply_nucleotide_transforms`
also applies saved CPD local coordinates; `add_design_bonds` adds the two product
crosslinks (`atomistic.py:458`, `cpd_design.py:563`). These outputs support normal
display/PDB paths; they do not certify regeneration.

PDB export uses the cached atomistic builder with `fast_bridges=True`
(`routes_export_structure.py:321`), and visualized PDB export explicitly supports
simulation coordinates. Preserve both. `Design.without_reference_geometry()`
removes editor backdrop strands/helices; despite its name, it does **not** clear
`atomistic_reference` (`models.py:3500`). Do not use it as native-source selection.

NAMD construction retains independent capability, preliminary-context and product
placement gates (`namd_topology.py:795`, `cpd_forcefield.py:78`). Current extra-base
test conversions are not qualified by the adjacent-internal-TT preliminary
release (`cpd_preliminary.py:81`, `tests/test_cpd_design.py:55`). History success
must not widen simulation/export qualification. Any actual molecular algorithm
change still requires the A/B artifact and explicit authorization in
`memory/feedback_geometry_change_authorization.md`.

`photoproduct-relax` is a related unfinished contract: its route logs only a
photoproduct ID, calls the same expensive solver, and also builds an unposed
source model (`cpd_design.py:593`, `routes_photoproducts.py:217`). Either give it
the same explicit source/template/engine/job contract as a separate feature, or
retain explicit unsupported coverage. Do not claim the CPD family complete while
this active authoring path remains outside coverage.

## Integration sequence and acceptance evidence

1. Add strict source/asset/engine schema and cheap reference checks. Test native
   source isolation, legacy non-upgrade, template/engine mismatch, missing or
   consumed endpoints, and unsupported stereochemistry with a forbidden-solver
   stub. Ordinary proof remains fast and exposes the long-job requirement.
2. Add process job creation/proof/edit lifecycle and bounded candidate transport.
   Barrier-based tests cover cancellation, stale documents/revisions, deadline,
   malformed/oversized output, failed start, cleanup and publication rollback;
   retain a real spawned blocking-child reap test. No solver is needed for these.
3. Run the smallest real CPD fixture as a focused slow regression under the
   existing validation guard. Create from native recipe inputs, poison/remove
   recovery snapshots, replay in a fresh spawned process and compare the full
   authoring state. Save/reload and replay again; edit a producer and verify a
   new solve; delete a producer and check the precise broken reference. Preserve
   the existing template/chirality, backbone attachment, unchanged-neighbor,
   atomic undo and simulation-rejection assertions in `test_cpd_design.py`.
4. Verify new native creation with an unrelated physical reference produces the
   same authored result as native creation without it, while ordinary PDB/display
   behavior is unchanged. Reject unsupported reference-based legacy conversion
   rather than recertifying it by silently switching source. Measure cold full
   job and main-thread responsiveness; report limits honestly.
5. Add explicit progress/cancel/repair entry points and remove or route legacy
   synchronous conversion only after the replacement is reviewable and tested.
   Preserve compatibility until then. Update capability/coverage ledgers only
   after a real cold regeneration succeeds; a rejection test is not completion.

## CAD precedent

Onshape reports individual features exceeding ten seconds and total regeneration
exceeding 30/60 seconds as performance information/warnings. This supports keeping
execution cost separate from dependency validity. [Onshape Performance Panel](https://cad.onshape.com/help/Content/Home/performance_panel.htm)

Onshape recommends inspecting per-feature times, pausing regeneration, suppressing
expensive details while working, and putting expensive features later in history;
immutable version references avoid needless regeneration. Its timeout recovery
offers rollback/history restore or continued waiting. NADOC should adopt explicit
cost/progress and deferred recomputation, while still proving the native recipe
when requested. This is an architectural inference, not evidence that Onshape
uses NADOC's proposed process protocol. [Onshape Performance Considerations](https://cad.onshape.com/help/Content/Home/performance_considerations.htm)
