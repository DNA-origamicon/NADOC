# Audit 07 — Multi-domain & multi-jointed overhangs — FINDINGS + Alt A foundation

Started as audit-only; the user authorized landing the **Alt A foundation**
(data model field + chain helpers + cascade-delete + validator + tests) in the
same commit. The chain-link **builder** (DNA-topology question) and the chain
**rotation composition** through deformation.py are explicitly deferred — see
"Deferred to next session" at the bottom.

The user has clarified scope (chained OHs, one ball-joint per OH segment,
two-step linker arm as the first concrete use case) and confirmed Alt A.
A new requirement — per-segment cluster + color — is naturally addressed by
Alt A: each chain segment gets its own helix and own strand, so `Strand.color`
and `cluster.helix_ids` already provide per-segment color and cluster
membership without new fields.

## Scope clarifications (answered up-front, 2026-05-09)

- **Multi-domain shape**: **Chained** (multiple `OverhangSpec` records linked
  end-to-end). Each segment keeps its own `helix_id` and `pivot`.
- **Multi-jointed**: **One ball-joint per OH segment** (each segment's pivot
  doubles as the chain joint between predecessor and self).
- **First concrete use case**: **Two-step linker arm** — `OH₁ → joint → OH₂ →
  tip`. Branched / bundle-as-OH not in scope yet.

These answers favour the smallest data-model delta: a chain is a tree of
single-domain segments, NOT a multi-domain spec.

## Single-domain assumption inventory — backend

Format: `file:line — assumption — break mode under chained OHs — fix shape`.
"fix shape" tags: **MODEL** = needs new field, **PER-SEG-LOOP** = code that
runs once per OH must run once per chain segment (loop is naturally written
already, just wrong starting point), **COMPOSE** = rotation/transform must
compose with predecessor instead of bundle frame, **BUILDER** = builder must
accept a parent OH instead of a staple-end as the anchor, **OK-AS-IS** = the
helper is per-`OverhangSpec` and stays correct because the chain is just N
specs.

### Data model
- [`backend/core/models.py:178-202`](../backend/core/models.py#L178) —
  `OverhangSpec` has one `helix_id`, one `strand_id`, one `pivot`, one
  `rotation`, one `sequence` — **MODEL**. Alt A adds `parent_overhang_id:
  Optional[str] = None`. None = anchored to bundle (current). Non-None = chain
  link, anchored to that other OH's free tip.

### Topology builders
- [`backend/core/lattice.py:2360-2634`](../backend/core/lattice.py#L2360)
  `make_overhang_extrude` — anchors to a **staple end** at
  `(helix_id, bp_index, direction)`, registers ONE crossover, creates ONE
  helix and ONE domain — **BUILDER**. Chained mode needs a sibling builder
  (or a mode flag) that anchors to an existing OH's free tip rather than a
  staple end. Reuses ~80% of the geometry math; the U-turn rule and
  neighbour-cell selection still apply (replace `(helix_id, bp_index,
  direction)` with the parent OH's tip cell).
- [`backend/core/lattice.py:2660-2814`](../backend/core/lattice.py#L2660)
  `_reconcile_inline_overhangs` — assumes one inline OH per (strand, end) —
  **OK-AS-IS** for inline; chains will be extrude-only in Alt A (no inline
  reconcile change needed).
- [`backend/core/lattice.py:2851-3072`](../backend/core/lattice.py#L2851)
  `autodetect_overhangs` — registers one OH per scaffold-free terminal
  domain. Won't auto-chain. Chain is user-built — **OK-AS-IS**.
- [`backend/core/lattice.py:3087`](../backend/core/lattice.py#L3087)
  `_find_overhang_domain` returns *first* match —
  **OK-AS-IS** for chained (each segment has unique id; one domain per spec).
  Refactored this session to use a list helper for forward-compat.

### Linker / connection helpers
- [`backend/core/lattice.py:3109`](../backend/core/lattice.py#L3109)
  `_make_complement_domain` — one OH domain in, one complement out —
  **OK-AS-IS**.
- [`backend/core/lattice.py:3232`](../backend/core/lattice.py#L3232)
  `_make_virtual_linker_helix` — bridges between exactly two OHs —
  **OK-AS-IS** under Alt A (chain joints are NOT linkers; linkers stay 2-OH
  inter-segment objects).
- [`backend/core/lattice.py:3363`](../backend/core/lattice.py#L3363)
  `generate_linker_topology` — **OK-AS-IS**. Per Q4 (open question), chain
  joints are *internal* to the chain and use `OverhangSpec.rotation`, not
  `OverhangConnection`.
- [`backend/core/lattice.py:3486`](../backend/core/lattice.py#L3486)
  `assign_overhang_connection_names` — names connections, not segments —
  **OK-AS-IS**. Segment naming reuses `OverhangSpec.label`.

### Mutation API (crud.py)
- [`backend/api/crud.py:5452-5474`](../backend/api/crud.py#L5452) `POST
  /design/overhang/extrude` — payload assumes anchor is a staple end —
  **BUILDER**. New variant payload (or `parent_overhang_id` field) needed for
  chain links.
- [`backend/api/crud.py:5484-5722`](../backend/api/crud.py#L5484)
  `patch_overhang` — extrude branch (5556-5600) resizes the dedicated helix
  with junction held fixed; lookup at 5546-5552 finds the junction crossover.
  **OK-AS-IS** post-Bug-06 because the junction lookup is by
  `xo.{half_a,half_b}.helix_id == spec.helix_id` (one xover per OH helix
  today; two xovers on a chain link would be parent-side AND
  child-side — see "Risk for chain links" below).
- [`backend/api/crud.py:1497-1535`](../backend/api/crud.py#L1497)
  `_delete_regular_strands_from_design` — strand deletion cascades OH
  cleanup by `o.strand_id in id_set`. Chain link OHs may live on different
  strands; if user deletes the parent strand, child OHs become orphans —
  **PER-SEG-LOOP**. Need a chain-walk: deleting OH₁ cascades to OH₂…OHₙ
  (children).
- [`backend/api/crud.py:466-595`](../backend/api/crud.py#L466)
  `_emit_bridge_nucs._anchor_for` — per-side anchor lookup for an
  `OverhangConnection` — **OK-AS-IS** under Alt A. Chain joints are not
  bridges.
- [`backend/api/crud.py:6231-6253`](../backend/api/crud.py#L6231) `DELETE
  /design/overhangs` — bulk clears all OHs by setting `overhang_id=None` on
  every domain. **OK-AS-IS** (a chain is just N specs; bulk clear nukes the
  lot).
- [`backend/api/crud.py:6197-6228`](../backend/api/crud.py#L6197)
  `_resplice_overhang_in_strand` — strand-level sequence resplice —
  **OK-AS-IS**. Each chain link has its own strand on its own helix.

### Geometry / deformation
- [`backend/core/deformation.py:589-673`](../backend/core/deformation.py#L589)
  `apply_overhang_rotation_if_needed` — pivot derived from junction bead
  position; rotation applied to the OH-tagged domain + same-helix LINKER
  complements (Bug-06 fix) — **COMPOSE**. For chain link OH₂, the pivot lives
  on OH₁'s helix (NOT the bundle), and the rotation must compose with OH₁'s
  rotation. The synthetic transform's `domain_ids` mask must include
  OH₁'s descendants (everything downstream in the chain) so the chain rotates
  rigidly from the joint outward.
- [`backend/core/deformation.py:1245-1262`](../backend/core/deformation.py#L1245)
  `_apply_ovhg_rot_to_samples` — rotates helix axis samples for one
  extrude-OH around its pivot — **COMPOSE**. Chain link OH₂'s helix samples
  must inherit OH₁'s rotation in addition to OH₂'s.
- [`backend/core/deformation.py:1280-end`](../backend/core/deformation.py#L1280)
  `_apply_ovhg_rotations_to_axes` — same per-OH iteration; same
  inheritance gap — **COMPOSE**. Walks `design.overhangs` in list order; chain
  composition needs an explicit chain-root-first walk so OH₂ sees OH₁'s
  already-rotated frame.

### Linker relax
- [`backend/core/linker_relax.py:47-53`](../backend/core/linker_relax.py#L47)
  `_overhang_helix_id` — first match — **OK-AS-IS**.
- [`backend/core/linker_relax.py:56-102`](../backend/core/linker_relax.py#L56)
  `_overhang_owning_cluster_id` — picks smallest cluster containing the OH's
  helix — **OK-AS-IS**. Chain link clusters are independent.
- [`backend/core/linker_relax.py:659-672`](../backend/core/linker_relax.py#L659)
  `_oh_attach_nuc` and
  [`:674-713`](../backend/core/linker_relax.py#L674)
  `_anchor_pos_and_normal` — per-side anchor lookup — **OK-AS-IS**. The
  attach end can be a chain-tip OH; `is_five_prime`/`is_three_prime` flags on
  nucs already work.

### Assembly
- [`backend/api/assembly.py:2049-2067`](../backend/api/assembly.py#L2049)
  `get_instance_geometry` calls `_apply_ovhg_rotations_to_axes` — same
  composition gap as the design-level call — **COMPOSE**.
- [`backend/api/assembly.py:2089-2128`](../backend/api/assembly.py#L2089)
  `get_assembly_geometry` — same — **COMPOSE**.

### Validator / import-export
- [`backend/core/validator.py`](../backend/core/validator.py) — no
  overhang-specific rules currently. Chain mode would benefit from one:
  *chain must form a tree* (no cycles, every link's parent exists). Defer.
- [`backend/core/cadnano.py:576-579`](../backend/core/cadnano.py#L576) —
  refuses to export designs with overhangs ("caDNAno has no overhang
  concept"). **OK-AS-IS** — chains stay un-exportable too.
- [`backend/core/scadnano.py`](../backend/core/scadnano.py) — no
  overhang-specific paths found. **OK-AS-IS**.
- [`backend/core/atomistic.py:628`](../backend/core/atomistic.py#L628),
  [`:775,791`](../backend/core/atomistic.py#L775) — overhang nucs use the
  geometry-pipeline backbone positions; no per-OH special case. **OK-AS-IS**.
- [`backend/core/cg_to_atomistic.py`](../backend/core/cg_to_atomistic.py) —
  same. **OK-AS-IS**.

## Single-domain assumption inventory — frontend

### main.js — 4-stage lookup pipeline (read-only this session)
- [`frontend/src/main.js:1240-1350`](../frontend/src/main.js#L1240) —
  `_ovhgSpecMap` / `_ovhgDomainMap` / `_ovhgJunctionMap` / `_ovhgRootMap`.
  Each is `id → entry`, 1:1 with `OverhangSpec`. Chain mode keeps the maps
  shape — each chain segment is a separate spec with its own id —
  **OK-AS-IS** for the maps themselves.
- [`frontend/src/main.js:1289-1307`](../frontend/src/main.js#L1289)
  `_buildJunctionMapFromXovers` — the parent domain at `domIdx-1` (or
  `domIdx+1` for first-domain OHs) determines the junction crossover. For
  chain link OH₂ on its own dedicated helix, the parent domain is OH₁'s
  domain (not a bundle staple domain). This still **works generically** —
  the parent helix lookup just ends up matching OH₁'s helix instead of a
  bundle helix. **OK-AS-IS**, but flag it.
- [`frontend/src/main.js:1314-1322`](../frontend/src/main.js#L1314)
  `_buildJunctionMapFromDomains` — `domIdx === 0 ? end_bp : start_bp`. Chain
  link OH₂'s strand may have multiple domains (from OH₁'s tip, across the
  joint, into OH₂'s helix). **PER-SEG-LOOP** — verify the OH-tagged domain
  is the chain-link's terminal domain on the strand, not a mid-strand one.
  Adding an explicit `is_first_domain_on_strand` check (or routing via
  `nuc.domain_index`) is safer.
- [`frontend/src/main.js:1326-1335`](../frontend/src/main.js#L1326)
  `_buildRootMap` — uses `helixCtrl.lookupEntry(...)`. Once junction is
  correct, root lookup is generic. **OK-AS-IS**.

**Map-key migration note**: under Alt A no map keys change. Each chain
segment is still one `(id → entry)`. The migration cost on the frontend is
limited to:
1. Rotation gizmo: when user rotates a chain link, the gizmo transform must
   include the predecessor's rotation (compose chain-root-first).
2. Selection: when user ctrl+clicks any chain segment, optionally highlight
   the whole chain. Today selection_manager caps at 2 OHs (for linkers).

### Scene / selection / assembly
- [`frontend/src/scene/selection_manager.js:1631`](../frontend/src/scene/selection_manager.js#L1631)
  `[..._multiOverhangIds, ovhgId].slice(-2)` — 2-OH selection cap.
  **PER-SEG-LOOP** — chain ops will want to address all segments at once
  (e.g. "rotate the whole chain rigidly"). Defer; not blocking.
- [`frontend/src/scene/overhang_link_arcs.js:416`](../frontend/src/scene/overhang_link_arcs.js#L416)
  `_linkerAttachAnchor` — per-side anchor lookup for one
  `OverhangConnection` — **OK-AS-IS**. Per LESSONS E2 / project_overhang_*
  gotcha #1 this implementation MUST stay in lockstep with backend
  `_anchor_pos_and_normal` and `_anchor_for`. Do not consolidate.
- [`frontend/src/scene/assembly_renderer.js:1096-1320`](../frontend/src/scene/assembly_renderer.js#L1096)
  `getInstanceBluntEnds`, `_isFree`, `ovhgBpToPos` — already known fragile
  per `project_mate_connectors.md` (cache invalidation, duplicate
  connectors). Chain mode adds more endpoints per "OH stack" — every
  intermediate chain link's tip becomes another candidate endpoint. **HOLD**
  until the fragile-area fix lands.
- [`frontend/src/scene/overhang_locations.js`](../frontend/src/scene/overhang_locations.js) —
  per-OH gizmo placement uses `OverhangSpec.helix_id` + pivot. **OK-AS-IS**;
  rotation gizmo will need chain-pose composition (handled in main.js
  rotation flow, not here).

## Already-correct-by-construction

These places iterate strand domains generically and don't assume a single OH;
chain mode adds new specs/domains but the loops cover them naturally.
- `lattice.py make_nick`, `_ligate`, `_merge_adjacent_domains`,
  `_ligate_and_merge` — all preserve `overhang_id` per-domain via
  `model_copy(update={"overhang_id": ...})` and remap surviving
  `OverhangSpec`s.
- `lattice.py make_autobreak` (line 2144) — iterates `for dom in
  strand.domains: if dom.overhang_id is not None` to skip OH bp ranges from
  nick targets. Generic.
- `_strand_nucleotide_info` — emits `nuc.overhang_id` per nucleotide; geometry
  consumers see chain segments seamlessly.
- `cluster_reconcile` (rebuilds `cluster.domain_ids` from bp-range overlap)
  — chain segments get their own clusters via the same path.
- `OverhangConnection` polarity rules and per-end uniqueness — operate on
  `(overhang_id, attach)` pairs; chain segments are just more pairs.
- `_overhang_end` (parses `_5p`/`_3p` suffix from id) — chain link ids
  can keep the same suffix convention (e.g. `ovhg_<parentid>_tip_5p`) so
  `_check_linker_compatibility` continues to work.
- `assign_overhang_connection_names` — names connections, indifferent to
  whether the OH is bundle-anchored or chain-anchored.

## Cross-cutting risks (steered around this session)

- **`_PHASE_*` constants (`lattice.py`)** — locked. Chain extrudes reuse the
  same phase math; do NOT touch.
- **`make_bundle_continuation` (lattice.py:577, ~474 LOC)** —
  deformation-sensitive; flagged in `LESSONS.md` E1. Not touched.
- **`linker_relax.py` `bridge_axis_geometry`, `_optimize_angle`,
  `_arc_chord_lengths`** — recent commits 5b432da, 7d8e093, 7d8e093. User is
  iterating. Not touched.
- **`_BRIDGE_PHASE_OFFSET`** synchronization across `_bridge_boundary_radials`
  and `_emit_bridge_nucs` — LESSONS E2. Not touched.
- **Three anchor implementations that must agree** — `_anchor_pos_and_normal`
  (linker_relax), `_anchor_for` inside `_emit_bridge_nucs` (crud), and
  `_linkerAttachAnchor` (overhang_link_arcs.js). Per
  `project_overhang_connections.md` "Critical gotcha #1" they must stay in
  lockstep. Not consolidated; refactor brief explicitly forbids.
- **Chain-link junction lookup vulnerability**: `_overhang_junction_bp` (new
  helper this session) finds the FIRST crossover whose half_* matches the
  OH's helix. Today an extrude-OH helix has exactly one crossover; for a
  chain link, the dedicated helix would have TWO crossovers — one to the
  parent OH (root side), one to its child OH if any (tip side). The helper's
  contract under Alt A must change to "first crossover whose other-side helix
  matches the parent OH" or "the crossover at the lower bp endpoint". Flagged
  for the next session; the current helper is documented as
  single-chain-link-safe.

## Open questions for the user (block model migration)

1. **Chain anchor topology — same strand or new strand?** When the user
   creates OH₂ anchored to OH₁'s tip, does OH₂'s strand TRAVERSE from OH₁'s
   free tip via a new crossover into a new helix (i.e. one continuous strand
   spans OH₁ + OH₂)? Or is OH₂ a SEPARATE strand with its own staple-like
   nick at OH₁'s tip? This decides whether `make_overhang_extrude` can be
   reused with `(helix_id=OH₁'s helix, bp_index=OH₁'s tip bp,
   is_five_prime=match polarity)` (continuous case) or whether a new
   "anchor-to-OH" builder is needed (separate-strand case).
2. **Joint pivot location**: For "OH₁ → joint → OH₂", is the joint pivot at
   OH₁'s **tip** bp (so OH₂ rotates around the chain junction)? Or at OH₂'s
   **root** bp (which is geometrically the same point, but the implementation
   pivot would be OH₂'s rotation vs. OH₁'s rotation)? Today extrude-OHs use
   `OverhangSpec.pivot = junction-axis-point at create time`; for OH₂ this
   would default to OH₁'s tip world-position. **Three-Layer note**: pivot is
   geometric (derived); only `parent_overhang_id` should be topological.
3. **Chain rotation composition order**: Chain root rotates first, then each
   subsequent link composes its rotation onto the predecessor's frame
   (rigid-body chain). Confirm this matches the intended UX. Specifically:
   if user rotates OH₁ by 30°, does OH₂ visibly swing along (rigid arm) or
   stay at its absolute orientation (independent arm)?
4. **Cluster ownership for chain links**: Does each chain segment get its own
   cluster (so `_overhang_owning_cluster_id` returns N different clusters
   for N chain links, and the joint between them lives in
   `design.cluster_joints`)? Or does a chain occupy ONE cluster with N
   internal joints? The user's "one ball-joint per OH segment" answer
   suggests N clusters / N-1 joints (or N joints if each segment has its own
   joint to its predecessor).
5. **Sequence model**: Is sequence per-segment (one `OverhangSpec.sequence`
   per chain link, regenerated independently), or per-chain (one continuous
   sequence whose substring lengths must match each segment's bp count)?
   Per-segment is the smaller delta and matches Alt A.
6. **Linker between chain segments**: When the user wants a "linker" between
   two chain segments — is that:
   - (a) a `ClusterJoint` (the joint angle controls the chain articulation),
   - (b) an `OverhangConnection` (a separate ss/ds linker bridge), or
   - (c) a direct strand traversal across a chain crossover (no separate
     linker object)?
   The two-step linker arm name suggests (a) or (c). Confirm.
7. **Free-tip exposure for assembly mate connectors**: For a chain, only the
   tip-most segment has a "free tip" available for inter-part mating — OR
   should every chain link's tip be a candidate for `getInstanceBluntEnds`?

## Proposed model alternatives (DO NOT implement this session)

### Alt A — `parent_overhang_id` link on `OverhangSpec` (RECOMMENDED)

**Data delta**: one nullable field on `OverhangSpec`:
```python
parent_overhang_id: Optional[str] = None   # None = bundle-anchored
                                            # str  = anchored to that OH's tip
```

**Topology semantics**: `OverhangSpec`s form a forest (each spec has at most
one parent). A chain is a path through the forest. Roots have
`parent_overhang_id is None`.

**Geometry composition**: `_apply_ovhg_rotations_to_axes` walks the forest in
parent-first order; each spec's rotation is right-multiplied onto its
parent's accumulated transform. Pivot for spec[i] = junction bead world
position derived AFTER applying spec[parent].rotation (so chain link OH₂'s
pivot is at OH₁'s rotated tip, not OH₁'s un-rotated tip).

**Impact on `OverhangConnection`**: none — connections still bridge two
specs; whether those specs are bundle-anchored or chain-anchored is
irrelevant to the bridge geometry (bridge anchors at the OH's `attach` end
nuc, which gets the chain-rotated position naturally).

**Impact on rendering**: rotation gizmo + locations sprite must read
the chain-composed pose instead of the spec.pivot. ~10-line change in
`overhang_locations.js` + the rotation drag handler.

**Impact on persistence**: one new optional field; `.nadoc` files round-trip
via Pydantic's default. Old files load with `parent_overhang_id = None` and
behave as today.

**Migration path**: phase 1 add the field (no behavior change since defaults
keep all OHs bundle-anchored). Phase 2 add `POST /design/overhang/extrude`
mode that sets `parent_overhang_id`. Phase 3 thread chain composition through
deformation + rendering. Each phase is shippable independently.

### Alt B — `OverhangChain` aggregate

**Data delta**: new model `OverhangChain { id, segments: List[OverhangSpec],
joints: List[...] }`. `Design.overhang_chains: List[OverhangChain]`. Existing
`Design.overhangs` reserved for bundle-anchored singletons.

**Pros**: clean separation; chains as first-class objects.

**Cons**: every place that reads `design.overhangs` needs a parallel pass
over `design.overhang_chains`. The 4-stage frontend lookup pipeline + every
backend iteration over `design.overhangs` doubles. Migration is invasive.

### Alt C — bundle-as-OH

**Data delta**: a chain becomes a small auto-clustered sub-bundle
(`is_overhang_chain: bool` flag on cluster + parent reference to bundle).

**Pros**: leverages cluster + crossover + deformation infrastructure
wholesale.

**Cons**: massive overkill for a 2-segment linker arm. The chain inherits
deformation/atomistic/scaffold-routing semantics it doesn't want or need.
Also forces the user to think of "two OHs" as "a sub-bundle".

### Recommendation: Alt A

Smallest delta. Captures the user's stated use case (two-step linker arm =
chain of length 2). No rename/migrate of existing data; the field defaults
preserve every existing design. Composition cost is contained to the two
deformation helpers (`apply_overhang_rotation_if_needed`,
`_apply_ovhg_rotations_to_axes`) and a frontend rotation-gizmo update.

## What landed in this commit

### Phase 0 — preparatory helpers (no behavior change)
- **`_overhang_junction_bp(design, helix_id)`** in
  [`backend/core/lattice.py`](../backend/core/lattice.py) — extracts the
  "look up the junction bp from `design.crossovers` for an extrude-OH helix"
  pattern that was inlined in `crud.patch_overhang`. Used in
  `patch_overhang` (replaces 7-line inline loop). Today there's exactly
  one crossover per OH helix; the helper docstring flags the chain-link
  ambiguity (parent-side vs. child-side junction) as the next-session
  extension point.
- **`_overhang_domains(design, ovhg_id) -> list[(Strand, int)]`** in
  `lattice.py` — list-form helper. `_find_overhang_domain` and
  `_find_overhang_domain_ref` now route through it, preserving "first
  match" behavior.
- **`_linker_complement_domain_refs(design, helix_id, oh_domain)`** in
  [`backend/core/deformation.py`](../backend/core/deformation.py) — named
  extraction of the LINKER-strand same-helix Watson-Crick partner
  enumeration formerly inlined in `apply_overhang_rotation_if_needed`.
- Comment tightening: "the OH-tagged domain on this helix" instead of "the
  OH domain" so readers don't internalise the singular assumption.

### Phase 1 — Alt A foundation (data model + topology layer)
- **`OverhangSpec.parent_overhang_id: Optional[str] = None`** in
  [`backend/core/models.py`](../backend/core/models.py). `None` =
  bundle-anchored (current behavior, default for every existing OH). Non-None
  = chain link, anchored to that other OH's free tip. Round-trips through
  Pydantic; legacy `.nadoc` files load with `parent_overhang_id=None`.
- **Chain-walk helpers** in `lattice.py`:
  `_overhang_chain_root`, `_overhang_chain_path`,
  `_overhang_chain_descendants`, `_overhang_chain_links_root_first` (a
  topological sort that drops cycles).
- **Validator rule** in
  [`backend/core/validator.py`](../backend/core/validator.py): each
  spec's `parent_overhang_id` must reference an existing
  `OverhangSpec`, and the parent chain must form a tree (no cycles).
- **Cascade-delete** in
  [`backend/api/crud.py:_delete_regular_strands_from_design`](../backend/api/crud.py):
  when the strand owning an OH is deleted, descendant OHs and their strands
  are recursively deleted too. Without this, child OHs would orphan with
  `parent_overhang_id` pointing at a missing record.
- **17 new tests** in
  [`tests/test_overhang_chain.py`](../tests/test_overhang_chain.py)
  covering: round-trip, legacy load, root walk, path, descendants, branch,
  topological order, cycle drop, validator (missing parent + cycle),
  cascade-delete (full chain, mid-chain, unrelated chains).

### Per-segment cluster + color
No new fields. Each chain segment is its own `OverhangSpec` with its own
`helix_id` and `strand_id`, so:
- **Color**: set via the segment's `Strand.color`.
- **Cluster membership**: add the segment's `helix_id` to a cluster's
  `cluster.helix_ids` list.
- **Joint between segments**: each segment's cluster gets a
  `ClusterJoint`; the existing `cluster_joints` / linker-relax machinery
  drives articulation. (Phase 4 below wires the geometric composition that
  makes the joint actually move OH₂ when OH₁ rotates.)

## Verification

Baseline (pre):
- `just lint` → exit 1, **301 errors** (pre-existing; the NADOC tree has
  carried lint debt before this session).
- `just test` pass 1 → 875p / 7f / 9e. Pass 2 → 876p / 6f / 9e.
  **Stable failure set: 15** (intersection of the two passes). The
  `test_animation.py::test_geometry_batch_*` and
  `test_seamless_router.py::test_teeth_closing_zig` tests are flaky between
  runs.

Post (Alt A foundation):
- `just lint` → exit 1, **301 errors** (Δ = 0).
- `just test` runs 1+2 → 892p/7f/9e and 893p/6f/9e. **+17 chain tests
  passing**; stable failure set still 15. Failure-set diff vs.
  pre-stable: **empty**.

## What was deliberately NOT changed

- `_PHASE_*` constants in `lattice.py`.
- `make_bundle_continuation`.
- `linker_relax.py`'s `bridge_axis_geometry`, `_optimize_angle`,
  `_arc_chord_lengths`, `_BRIDGE_PHASE_OFFSET`.
- The three anchor-implementation triplet (`_anchor_pos_and_normal` /
  `_anchor_for` / `_linkerAttachAnchor`).
- `OverhangSpec` shape, `make_overhang_extrude` signature, any API route.
- Frontend (read-only this session per the audit brief). Map-key migration
  notes captured above for the next session.

## Deferred to next session

These were intentionally NOT landed in this commit. Each requires either a
DNA-topology decision the prompt rules forbid me from making alone, or a
multi-step geometry-pipeline change that deserves its own session.

### Phase 2 — chain-link extrude builder (BLOCKED on open question #1)
A new path through `make_overhang_extrude` (or a sibling builder) that anchors
an OH at another OH's free tip rather than at a staple end. Open question:
does the new chain link's strand TRAVERSE from the parent OH's tip via a
crossover into the new helix (continuous strand), or is it a NEW strand whose
nick coincides with the parent OH's tip? Per `feedback_overhang_definition`
+ `feedback_crossover_no_reasoning`, this needs explicit user direction
before implementation. The per-segment color requirement implies the
**separate-strand** option (one strand per segment → one color per segment),
but confirm before building.

### Phase 3 — rotation composition through chains
- `apply_overhang_rotation_if_needed` (per-helix, called inside the helix
  loop) needs to apply ANCESTOR rotations to OH_k's helix nucs in addition
  to OH_k's own rotation around its own pivot.
- `_apply_ovhg_rotations_to_axes` needs a parent-first walk so OH_k's
  pivot is derived from the post-ancestor-rotation junction position.
- Cleanest approach: pre-pass at the start of `_geometry_for_helices` that
  computes a cumulative `(rotation, pivot)` per OH via
  `_overhang_chain_links_root_first` (already shipped). Pass this map down
  to both helpers.
- Regression tests: `tests/test_overhang_chain_rotation.py` — chain of 2,
  rotate root, assert child helix nucs follow.

### Phase 4 — chain-link extension to `_overhang_junction_bp`
The helper currently returns the *first* crossover whose half_* matches
the OH's helix. A chain-link helix has TWO such crossovers (parent-side
junction at root, child-side junction at tip). Extend the helper to take
an optional `exclude_helix_id` (or `prefer_other_side`) so callers can
disambiguate. Used by future `patch_overhang` chain resize.

### Phase 5 — frontend rotation gizmo composition
The gizmo currently reads `OverhangSpec.pivot` and applies the spec's
rotation locally. For chain links, both the pivot and the rotation must
include the cumulative parent transform. Single touch point in
`overhang_locations.js` + the rotation drag handler in `main.js`.

### Phase 6 — chain UI surface
- Selection: "select all chain segments downstream of OH_k" (today's
  multi-OH selection caps at 2).
- Color picker: per-segment color via `Strand.color`.
- Delete confirmation: "deleting OH_k will cascade to N descendants".

## Open questions still pending (block phase 2+)

The 7 questions in the "Open questions for the user" section earlier in
this document remain unanswered. The most critical for phase 2:
1. **Chain anchor topology** — continuous strand (one strand spans both
   segments) vs. separate strand (each segment is its own strand).
   Per-segment color requires separate. Confirm.
2. **Joint pivot location** — at parent's tip, or child's root? Same
   geometric point but different implementation.
3. **Linker between segments** — `ClusterJoint` (joint angle articulates
   the chain) vs. `OverhangConnection` (separate ss/ds linker bridge) vs.
   direct strand crossover (no separate object).

## Pass 6 status

Still paused. Resuming after phases 2-5 land.
