# Topology and conversion audit — review before implementation

Date: 2026-09-22. Source HEAD: `6d0691fd55874cd259170adfc2359dd75304c56d`.

**Historical pre-implementation audit.** R1–R9 were subsequently addressed with user
authorization; see [routing resolution](routing_resolution.md). C1–C7 and the
export dialog are covered in [conversion resolution](conversion_resolution.md). The original
`results.json` and `manifest.json` remain the pre-fix evidence.

**At the time of this audit, no application code, guards, molecular geometry, or existing tests were changed.**
This directory contains an audit harness, observations, source fingerprints, and
proposals for review. Existing photoproduct test edits and unrelated untracked
files were present before this task and were left untouched.

The audit recorded **126 probes**, including controls. This is a count of
observations, not 126 passing tests. One malformed caDNAno target raises a
`KeyError`; the HTTP import wrapper converts exceptions to HTTP 400. That case is
an existing rejection, not silent acceptance.

## Review table

P0 means silent molecular alteration or a fundamental integrity failure to close
before claiming a workflow is dependable. P1 means an important qualification,
diagnostic, or behavior-contract issue. These are proposed priorities, not new
runtime severity levels.

| ID | Priority / evidence | Case and observed behavior | Proposed behavior for review | Exceptions / decision needed |
|---|---|---|---|---|
| R1 | P0 — reproduced, public core routing functions | Seamed, matched, bounded, and seamless routes can extend scaffold into occupied slots on **both low and high faces**, on **HC and SQ**. All 32 targeted extension probes collide; 31 still pass `validate_design`. The original six-base HC obstacle also reproduces with LINKER, OH_BINDER, and STAPLE. Separate duplicate-strand and self-overlapping-scaffold models survive model construction and validation. | One active nucleotide owner per physical slot; check each proposed extension and the complete result. A conflicting candidate must not commit overlapping topology. | Opposite-direction pairing is allowed. Reference strands are not active owners. Virtual linker domains need resolved physical identities, not blanket exclusion by strand type. Choose fail-whole-route versus return an explicitly partial route; do not silently reroute inward without reviewing the resulting topology. |
| R2 | P0 — reproduced, reset primitive | A scaffold with one domain on a stapled helix and another on an unstapled helix loses the entire **76-base unstapled domain** on reset. The manual crossover record remains. No reset warning is emitted; the post-reset validator does flag a nicked crossover. The input transition was constructed at a valid lattice site. | Preserve all unaffected domains and manually authored connectivity. Compare nucleotide coverage and protected edges before/after reset; reject unintended loss. | This is a reset-level reproduction, not a claim every public router reaches the same final output. Fresh and previously routed designs both need explicit coverage contracts. |
| R3 | P1 — reproduced, reset primitive; policy decision | Two scaffold fragments `[0..20]` and `[30..83]` under a continuous staple interval become `[0..83]`. **Nine previously absent positions are added**, the separation disappears, and no warning is emitted. Validator passes. | Preserve the union of intended scaffold intervals; treat filling a gap or joining separate scaffold components as an explicit routing choice. | Routing is expected to add some scaffold at end turns. The decision is which additions are permitted by the selected routing mode, not a universal ban on adding bases. Multiple scaffolds are supported. |
| R4 | P1 — reproduced, public core route | Adding an inactive reference LINKER changes the HC seamed result from **one active scaffold / six crossovers** to **two active scaffolds / four crossovers**. A type-mismatch warning cites the reference linker. | Exclude inactive reference geometry consistently from routing ownership/type lookups and candidate obstruction decisions. | Active LINKER/BINDER material still constrains routing. Dedicated autobreak/merge controls preserve reference staples; do not generalize this finding to every operation. |
| R5 | P1 — reproduced, crossover primitive | `_place_xover` nicks first, then rejects a mismatched-index crossover; strand count changes **8 → 10**, with no new crossover. | A rejected candidate returns its exact input topology. Validate/preflight or roll back the candidate's nicks/extensions. | The bad-index reproduction targets the primitive; it does not prove an ordinary generated route produces mismatched indices. A batch may retain other successful placements if that partial-result policy is explicit. The manual builder has a separate exception path. |
| R6 | P0 — reproduced, model construction + validation | A FORWARD domain with descending endpoints survives `Design.model_validate` and passes `validate_design`; directional traversal produces **zero** bases from an 84-base range. scadnano `start == end` also creates a reversed empty interval that passes. | Validate endpoint order against declared direction and reject empty imported domains. | A one-base domain with equal inclusive endpoints is valid. Negative/global coordinates are valid. Do not use `bp >= 0` or the original helix length as universal bounds. |
| R7 | P0 — reproduced, model construction + validation | Crossovers naming missing helices, an orphan forced ligation, a duplicated crossover record with a fresh ID, and a routed strand with all crossover records removed each pass validation. `validate_crossover` alone also approves a lattice site beyond all strand coverage. | Reconcile realized backbone transitions with records, check endpoint existence and unique use, and distinguish missing/stale records from deliberately pending bonds. | Pending circular-closure markers are an existing authoring state. Explicit ForcedLigation and periodic seams are valid noncanonical connections. Do not reject all non-neighbor transitions or all unligated editing states. The manual placement builder has additional coverage gates beyond `validate_crossover`. |
| R8 | P0 — reproduced | With one insertion, `strand_sequence_length` requires **85 bases**. Validator rejects an 85-base sequence and accepts an 84-base sequence. | Use the established sequence-accounting contract, with explicit ownership of inserted bases and terminal/junction sequence. | Overhang/binder sequence spans intentionally differ from ordinary loop/skip counting. Junction `extra_bases` are stored separately; do not count them twice in `Strand.sequence`. |
| R9 | P1 — reproduced, reset primitive; policy decision | Reset of a never-routed sequenced bundle silently changes **336 assigned scaffold bases → 0**, even with identical occupied slots. Staple sequences remain. | Preserve assignments where identities are unchanged; when routing invalidates assignment, report exactly which sequences/strand identities were cleared. | Reordering scaffold traversal may legitimately invalidate its sequence assignment. Choose explicit invalidation versus identity-preserving remapping; do not preserve misleading sequence order merely to retain strings. |
| C1 | P0 — reproduced, complete core round-trip | A valid periodic bundle produced by seamed routing + `route_for_polymerization` has **840 domain nucleotide positions, zero overlaps**. caDNAno export/import yields **1,100 positions and 344 overlapping slots**, with no warnings and validator success. Four periodic seam flags disappear. The same scadnano round-trip retains 840 positions but drops all four ForcedLigation records and their periodic flags. | Preserve ordered nucleotide paths, junctions, and periodic intent, or fail the export as unsupported with a concrete loss report. Verify the decoded result against the input before calling a conversion lossless. | Periodic seams are intentional, not invalid long bonds to reject. A format may need a versioned NADOC sidecar/extension, or an explicitly acknowledged lossy export. See C2 for a directly isolated caDNAno parser cause. |
| C2 | P0 — reproduced, malformed/unsupported caDNAno input | A nonreciprocal previous pointer produces **82 duplicated scaffold positions**, without warning. A same-helix next-pointer jump `2 → 5` across inactive positions is collapsed to a continuous domain, inventing positions 3 and 4. | Check link reciprocity, range, node ownership, and graph components before conversion. Preserve discontinuous paths as representable junctions, or reject them explicitly. | Same-helix jumps can also arise from legitimate NADOC periodic/forced connectivity; classify them rather than automatically filling or rejecting all such connections. Missing-target input already fails, though its diagnostic could improve. |
| C3 | P0 — reproduced, valid scadnano loopout input | `8 bp + TTT loopout + 8 bp` imports as **16 bases instead of 19**. The sequence becomes `AAAAAAAACCCCCCCC`; no junction extra bases or warning survive. | Preserve loopout identity, sequence, and connectivity in the corresponding supported junction representation; otherwise stop the import with an unsupported-content report. | Same-helix loopouts and unknown sequence need their own representation decisions. Do not silently substitute a direct backbone connection. |
| C4 | P0 — reproduced, both exporters | A NADOC crossover carrying `extra_bases="TT"` exports and reimports through both caDNAno and scadnano with **zero junction extra bases**. caDNAno compatibility returns an empty list; neither import warns. | Inventory every sequence-bearing component for export; encode the junction bases faithfully or reject/require explicit lossy conversion. | Junction extras are different from duplex insertion columns; do not silently rewrite one into the other. Terminal modifications and other unsupported annotations need the same capability inventory, though not all were dynamically audited here. |
| C5 | P1 — reproduced, conflicting scadnano input | Two domains declare insertion counts 1 and 2 at the same helix position. The latter silently overwrites the former in a shared helix map; no warning, validator success. | Detect incompatible modification declarations before building a helix-level model; require a representable consistent mapping. | NADOC uses helix-level modifications. Decide whether valid asymmetric source designs require a richer model or explicit unsupported-input rejection. Do not silently symmetrize them. |
| C6 | P1 — reproduced, declared import loss | caDNAno drops a circular scaffold component of **84 bases** with a warning. scadnano retains circular scaffold bases by linearizing at a sequence origin, but drops circular non-scaffold strands with a warning. | Distinguish scaffold linearization from deleting a molecule. Do not replace the active design with a strand-dropping conversion before the user reviews the loss. | **Correction to the broad earlier review:** NADOC intentionally models the circular scaffold linearly at a sequence-assignment origin. This alone is not a defect or a reason to prohibit circular-scaffold import. Supporting truly cyclic staple backbones is a separate model decision. |
| C7 | P1 — reproduced + route source inspection | An unknown scadnano grid is silently treated as HC. Duplicate helix indices produce an invalid design rather than parser rejection. Import routes install the design before computing its validation report. | Validate source schema and declared capabilities before installation; retain the previous document when a strict import fails. Permit invalid inputs only in an explicit inspection/repair mode. | The existing `grid="none"` rejection is clear and should remain; it is a capability limitation, not corruption. Do not turn recoverable draft diagnostics into unexplained data loss. |
| M1 | P1 — source-confirmed split; historical numerical result | mrDNA display uses the required nucleotide manifest decoder, but `build_md_seed_override` still uses the legacy per-helix reconstruction. Maintenance records a **0.691 nm mean zero-step error vs 0.10 nm criterion** for that legacy path. | Qualify MD seeding against the same nucleotide identity/frame contract as display, with complete identity coverage and zero-step reference agreement. | The historical number was **not rerun** here. No native engine, force field, phase constant, or molecular placement was changed. Any replacement geometry requires an explicit isolated comparison, not simply copying display coordinates. |

## Additional observations requiring interpretation

- **Ordinary caDNAno round-trip:** a nonperiodic routed bundle preserves the 756
  domain positions and has no duplicate occupancy, but six crossover records
  become two crossovers plus four forced ligations. No warning is produced.
  This is an observed change of junction classification; its geometric cause
  and downstream consequences need separate investigation. It is not evidence
  of four missing covalent bonds. The export offset in this probe is 21 bp.
- **Deleted crossover columns:** the automatic staple-crossover builder,
  iterated to the same fixed point as its API wrapper, places 24 crossovers when
  the corresponding nominal columns are marked deleted. The range lookup does
  not resolve actual nucleotide availability. A clear endpoint convention is
  needed before deciding whether to reject such a candidate or map it to an
  adjacent surviving nucleotide. This deliberately adversarial probe is not a
  proposed physically realistic deletion pattern.
- **Pending closures:** the same automatic builder on the clean control already
  returns crossover-terminal validation failures. Existing code explicitly
  supports pending closure markers rather than circular strand objects. Thus a
  final guard needs separate notions of valid draft state and a fully realized
  export/simulation topology. This audit does not relabel all pending markers
  as newly discovered routing corruption.

## Positive controls and limits

- All eight clean HC/SQ × seamed/matched/bounded/seamless bundle controls have
  zero duplicate active slots and pass `validate_design`.
- Opposite-direction material at the tested end zone produces no duplicate
  ownership. The reference obstacle produces no *active* collision; its effect
  on routing, documented in R4, is a separate problem.
- Four routing runs on committed `teeth.nadoc` and `10-6-10hb_seamed.nadoc`
  fixtures preserve every original active slot, introduce no duplicate slots,
  and pass validation. This does not certify every gap-extension distance.
- Six autobreak/short-staple-merge controls leave tested LINKER, OH_BINDER, and
  reference-STAPLE objects unchanged. The automatic crossover control with
  reference-only staples places no crossovers and preserves those references.
- Bad caDNAno link targets fail; scadnano arbitrary-position grids already fail
  explicitly. Neither is reported as a silent-acceptance defect.
- Counts called `domain_nt` in `results.json` count active ordinary traversal
  slots, excluding skipped columns. They intentionally do not expand inserted
  copies, terminal extensions, or junction extras. The 840/1,100 periodic probe
  has none of those extras, so its position-count comparison is exact for that
  construct. R8 uses the separate existing sequence-count function.
- Models used for the validator corruption probes are reconstructed through
  `Design.model_validate`, except the insertion-sequence accounting comparison.
  Their acceptance is not merely a consequence of unchecked `model_copy`.
- Most reproductions call public core functions. R2/R3/R5/R9 specifically isolate
  primitives; the report does not assert identical outcomes through every GUI
  path. API source was inspected, but no HTTP server or browser was exercised.
- Hinge-specific realizers, arbitrary assemblies, all hand-routed workspace
  constructs, direct PDB import, and every simulation converter are not exhaustively
  covered. Native mrDNA decoding/MD initialization and oxDNA/atomistic geometry
  were source-reviewed only. No scientific simulation was run.

## Proposed enforcement contract — not implemented

1. **Physical identity:** active nucleotide ownership must be unambiguous, with
   explicit namespaces for ordinary, inserted, linker, extension, and junction
   nucleotides. Reference geometry must not participate in material ownership.
2. **Backbone integrity:** a realized bond joins one 3′ continuation to one 5′
   continuation, uses existing identities, and agrees with ordered strand paths.
   Pending bonds must be distinguishable from realized ones. Do not infer a
   physical bond merely from a displayed crossover record.
3. **Operation contract:** preserve protected material, manual connections, and
   explicitly retained sequences. Report intended additions/removals separately.
   A rejected routing candidate must leave its input unchanged.
4. **Conversion contract:** preserve nucleotide inventory, direction, ordered
   connectivity, junction sequence, modifications, and supported periodic
   metadata—or report exactly what cannot be represented before committing.
5. **Workflow contract:** invalid drafts may be opened for repair; irreversible
   downstream use needs a qualified realized topology. Do not silently destroy
   the user's current document or auto-repair molecular topology on load.

Review decisions before coding:

| Decision | Recommended default | Alternative that changes behavior |
|---|---|---|
| Route meets occupied material | Reject the conflicting candidate; only commit a clearly reported, invariant-safe result. | Search inward or alter end geometry to retain a single scaffold; requires reviewing that changed routing policy. |
| Reset would fill/remove user material | Preserve the original coverage; stop with a localized diagnostic if the route cannot be rebuilt safely. | Explicit rebuild mode that authorizes the listed additions/removals. |
| Rerouting invalidates sequences | Preserve assignments only where identities/traversal still agree; explicitly mark remaining assignment invalid. | Clear selected assignments after showing affected strands. |
| Import/export cannot preserve a molecule | Fail a strict conversion with a loss report and retain the source/current document. | Explicit lossy export or repair-mode import, separate from a faithful conversion. |
| Existing malformed `.nadoc` files | Allow inspection/recovery; block unsafe new edits/exports according to scope. | A migration or repair assistant, which must propose concrete changes rather than silently rewrite files. |
| Pending closure, manual ligation, periodic seam | Keep explicit authoring semantics and validate the realized physical graph at the relevant boundary. | New circular-topology support is a separate feature, not an incidental guard change. |

## Evidence and reproduction

- [Probe script](probe.py): synthetic models plus two committed fixture reads.
- [Machine-readable observations](results.json): all 126 case outcomes.
- [Source/fixture fingerprints](manifest.json): exact local files used for review.

From the repository root:

```sh
.venv/bin/python docs/audits/topology_conversion_20260922/probe.py > /tmp/nadoc-topology-audit.json
```

The harness writes only stdout; it does not start a server, run native engines,
load a live workspace, change application state, or implement any guards.

Primary code locations:

- `backend/core/seamed_router.py`: `_place_xover`, `_extend_scaf_domain_lo/hi`.
- `backend/core/scaffold_reset.py`: `reset_scaffold_to_structure`.
- `backend/core/validator.py`: overlap exemptions, length checking, record checks.
- `backend/core/crossover_positions.py`: range/type lookup and record extraction.
- `backend/core/sequences.py`: `domain_bp_range`, `strand_sequence_length`.
- `backend/core/cadnano.py`: `_trace`, `_path_to_domains_and_xovers`, exporter.
- `backend/core/scadnano.py`: loopout slicing, shared modification map, exporter.
- `backend/api/crud.py`: import installation, crossover builders, closure markers.
- `backend/api/routes_design_interchange.py`: export endpoints.
- `backend/core/mrdna_runner.py`: manifest display vs legacy MD seed mapping.
- `docs/maintenance_2026_09.md`: historical mrDNA result and its limitations.

Implementation is intentionally pending the user's review of this table.
