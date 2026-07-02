---
name: overhang-connections-panel
description: "Right-sidebar 'Overhang Connections' section (v1, 2026-06-28) — connection-type icon picker + two overhang dropdowns + live 5'/3' pairing feedback. Picker-only (no create action yet). Shared ct_icons.js gained additive exports; old Overhangs Manager modal kept live."
metadata: 
  node_type: memory
  type: project
  originSessionId: 411c7065-557d-4292-881a-1efe67847be9
---

# Overhang Connections sidebar section (v1 — 2026-06-28)

New right-sidebar `.panel-section#overhang-connections-section` reworking the
Overhangs Manager's connection-type picker into a compact sidebar surface.
Built per user request to "rework the UI for the overhang manager."

## Scope (user-confirmed, built incrementally)
- **Picker + dropdowns** (2026-06-28): two `<select>` dropdowns listing all
  overhangs (Side A / B) + the 12-variant connection-type icon button + popover.
  Button updates polarity markers + the yellow ⚠ forbidden overlay live from the
  two selected overhangs' 5'/3' ends — exactly like the manager button.
- **Collapsible + repositioned** (2026-06-28): the section is a collapsible
  `.panel-section` (heading + chevron, default collapsed) placed **directly
  below the `#overhang-panel` "Overhangs" section**. The popover opens
  **leftward** (`_openPopover` aligns its right edge to the button's right edge,
  clamped to viewport) so the 4-wide grid isn't clipped by the screen edge.
- **Full create flow** (2026-06-28): linker-length field (`#oconn-length`,
  hidden for direct + indirect variants), a **Generate button** that is
  "Generate Linker" (→ `createOverhangConnection`) for linker/indirect variants
  and "Make complementary" (→ `patchOverhang` RC-sync of B + `createOverhangBinding`)
  for the two direct variants, and an **interactive list** (`#oconn-list`) of
  created linkers + bindings. Click a linker row → re-selects its overhangs +
  variant (via `ctVariantForConnection`); × deletes (with confirm). Backend
  mutations sync the design → store → the module's subscriber → list refreshes.
- **Auto-populate from 3D selection** (2026-06-28): while the section is OPEN,
  scene-selected overhangs auto-fill the A / B dropdowns as a **2-slot LRU**.
  One merged signal `_selectedOverhangIds(state)` = `multiSelectedOverhangIds`
  (overhang filter) ∪ `multiSelectedDomainIds` resolved to `overhang_id` (domain
  filter) ∪ `selectedObject.data.overhang_id` (single), deduped + validated.
  `_onSelectionChange` derives the **picks** (cur.length===1 → that id; ≥2 →
  ids new vs the previous selection, in order) and feeds each to `_placePick`:
  **fill an empty slot first, else evict the slot populated LESS recently**
  (per-slot monotonic stamp `_slotTA`/`_slotTB`, `++_clock`). Already-shown id =
  no-op. So OH1,OH2,OH3 → A=OH3,B=OH2; then OH4 → A=OH3,B=OH4 (B was older).
  **Earlier "sliding window" (A=older,B=newer, reassigns both) was WRONG and was
  replaced** — the slot a pick lands in is stable; only the LRU slot is evicted.
  Manual dropdown change + list-row select also stamp the slots so the LRU stays
  correct. Gated on `!_collapsed`; expanding snaps to current slots. The store
  fields are written by `selection_manager.js` for lasso / ctrl-shift /
  sequential (see [[selection]]).
- **Connection VERSIONS (candidate library, persisted)** (2026-06-28): explore
  several alternative connections for the SAME overhang pair (different sequences
  /GC, bridge length, or type) with at most ONE materialized at a time.
  - **Backend (persisted):** `ConnectionVersion` model + `Design.connection_versions`
    ([backend/core/models.py](backend/core/models.py)); CRUD endpoints
    `POST/PATCH/DELETE /design/connection-versions` ([backend/api/crud.py](backend/api/crud.py),
    `_cv_*` helpers + `_assign_connection_version_names` V1/V2-per-pair +
    `_cv_enforce_applied_mutex` one-applied-per-pair). Survives .nadoc save/reload
    (pin `tests/test_connection_versions.py`, 7 tests). Client:
    `createConnectionVersion`/`patchConnectionVersion`/`deleteConnectionVersion`.
  - **Buttons** (3 inline, flex:1): **[Connect / Add version] [Apply] [Bind / Relax]**.
    Leftmost = **"Connect"** when the A/B pair was never paired (runs the
    Pair/Generate-Linker op + records an APPLIED version), **"Add version"** once
    the pair has a connection/version (snapshots the form as a DRAFT). **Apply**
    (purple, middle) materializes the SELECTED version: set sequences + tear down
    the pair's current conn/binding + (re)create the version's type, then PATCH
    `applied:true` (mutex clears the prior). Enabled only for a non-applied
    selected version.
  - **List** = header per pair (`OHA ↔ OHB · <applied type>`) + indented version
    rows (`Vn`, type, `Nnt`, `GC %`, `bridge bp`, ●applied badge, × delete). Click
    a version → loads it + Apply enables; details panel edits its A/B + bridge
    sequences (`patchConnectionVersion`). Legacy conns/bindings with no version
    group still render as flat rows.
  - **Apply = BACKEND atomic endpoint** (2026-06-28, replaced the v1 frontend
    orchestration): `POST /design/connection-versions/{id}/apply`
    ([backend/api/crud.py](backend/api/crud.py) `apply_connection_version`, one
    `mutate_with_feature_log` → one undo). It (1) sets both overhang sequences via
    `_build_overhang_patch` which **resizes each overhang to len(sequence)** — so
    OVERHANG-LENGTH changes work now; (2) tears down the pair's current
    connection/binding (`remove_linker_topology` + binding filter); (3) recreates
    the version's type (linker via `generate_linker_topology`, or a direct
    `OverhangBinding`); (4) marks applied + clears the pair's others. Backend
    CT-mapping helpers `_cv_attach_pair/_cv_is_direct/_cv_is_indirect/_cv_linker_type/
    _cv_sub_domain_at_attach` mirror ct_icons.js. Frontend `_onApply` →
    `applyConnectionVersion(id)` (the gate + `_materializeVersion`/`_createForType`
    were removed; `_teardownPair` kept for delete-applied). Pins:
    `test_connection_versions.py` (12: +apply linker/resize/direct/replace/404),
    `overhang_connections_panel.versions.test.js` (6).
  - **★ UNIFIED DIRECT CONNECTIONS (2026-06-30) — SUPERSEDES the end-to-root splice +
    the old direct-relax bullets below.** Both `root-to-root` AND `end-to-root` now
    materialize as ONE non-consuming, relocated `OverhangBinding`; the end-to-root
    binder *splice* (`lattice.apply_end_to_root_binder`, which CONSUMED overhang B) was
    **deleted**, as was the version-keyed `relax-end-to-root` route + `end_to_root_relax.py`.
    The only per-type difference is the attach/connection point.
    - **Apply** (`crud._cv_create_bound_binding`, called from `apply_connection_version`
      for every direct type): create `OverhangBinding(bound=True, driver_oh_id=A,
      driven_oh_id=B, connection_type=…)` + relocate via `binding_relax.compute_bind_topology
      (driver_side="a")` → `apply_bind_topology`. **A is the driver (its helix HOSTS the
      duplex); B is driven (its tip domain relocates onto A's helix, antiparallel).
      NEITHER overhang is consumed** — both stay in `design.overhangs` (fixes the
      "overhang disappears from the list" bug). No cluster relax → B's tip↔root bond
      left STRETCHED. `compute_bind_topology` gained a `driver_side` override (bypasses
      the same-cluster/cluster-None guards; relocation is pure topology). Teardown/unapply
      reverts the relocation (`revert_bind_topology`) before dropping a shared bound binding.
    - **caDNAno display = relocated crossover → ForcedLigation (2026-06-30):** after
      relocation the driven overhang's overhang-extrude crossover would land on the
      driver's (non-adjacent) helix at a MISMATCHED bp — an invalid lattice crossover
      that the cadnano 2D editor draws to the WRONG end of the overhang (user-reported,
      end-to-root). `binding_relax.apply_bind_topology` now **drops that crossover and
      emits a `ForcedLigation`** for the root↔tip backbone bond (multi-domain driven
      staple w/ an extrude crossover only; `compute_bind_topology` builds the FL into
      `BindTopology.forced_ligation` + the snapshot; `revert_bind_topology` removes it on
      unbind). Mirrors what the old end-to-root splice did, generalized to EVERY direct
      relocation (root-to-root too). **NEW validator** `validator.validate_design` flags any
      crossover whose two halves are at mismatched bp ("Improper crossover(s) at invalid
      lattice positions") — the guard against this class of bug; verified no false positives
      across the full suite. Pins: `test_direct_connection_unified.py::
      test_validator_flags_improper_crossover` (fires on synthetic / passes valid),
      `test_headless_build.py::test_apply_end_to_root_cadnano_clean_after_apply` (real 6hb:
      +1 forced ligation, zero mismatched-bp crossovers), and the
      `assert_direct_binding_applied` oracle clause 5 (no improper crossover + validate_design
      agrees).
    - **Co-rotation** (the "other overhang doesn't track" fix): `deformation.
      _overhang_binding_partner_refs` now also treats the relocated DRIVEN overhang of a
      bound binding as a co-rotation partner of the driver; the driven side is SKIPPED in
      the overhang-rotation self-loop (it rides as A's partner only). Editing A's
      orientation co-rotates B. Pin: `test_overhang_binder_rotation.py::
      test_relocated_direct_binding_partner_follows_rotated_driver`. **Gizmo block/redirect
      of B's own orientation handle = NOT yet done (manual item); grabbing B is currently a
      harmless no-op (self-rotation skipped).**
    - **Relax** = unified `relax_overhang_binding` (`POST /design/overhang-bindings/{id}/relax`)
      → `direct_relax.relax_direct_binding(design, driver_oh_id, driven_oh_id)`: closes the
      DRIVEN overhang's tip↔root chord to ~0.67 nm by swinging the driver's overhang duplex
      (persisted as the driver's `OverhangSpec.rotation`; driven co-rotates) + cluster
      kinematics (joint-rotate, else rigid-translate the driven root cluster; same body →
      swing only). `direct_relax.py` is the generalized former `end_to_root_relax.py`
      (`_find_driven_tip_and_root` keyed on `overhang_id`, not `binds_overhang_id`). The OLD
      sub-domain-junction target is gone. Frontend `_onSecondary` = single `relaxOverhangBinding`
      for ALL direct types (no unbind/rebind dance; `relaxEndToRoot` removed). Pins:
      `test_direct_connection_unified.py`, `test_headless_build.py` relax tests,
      `test_automation_harness.py` (`assert_direct_binding_relaxed_pose`),
      `test_connection_versions.py` (relocate apply + non-consume),
      `overhang_connections_panel.bindrelax.test.js`. Oracles renamed:
      `assert_end_to_root_binder`→`assert_direct_binding_applied`,
      `assert_end_to_root_relaxed_pose`→`assert_direct_binding_relaxed_pose`. **NOT yet
      hand-driven in-app (3D duplex render + cadnano + gizmo co-rotation).** Everything from
      here to the "Group header" bullet describes the OLD splice model and is historical.

  - **Apply ⇄ Unapply + secondary always "Relax"** (2026-06-28): the middle button
    is **"Apply"** for a draft and **"Unapply"** for the applied version
    (`_applyTargetVersion` = selected version, else the pair's applied one).
    Unapply tears down the materialization (`_teardownPair`) + sets the version
    `applied:false` → overhangs left FREE (version preserved as a draft). The third
    button is **always "Relax"** = "settle the geometry", SAME RULE both kinds
    (rotate the joint if one connects the clusters, else rigid-translate):
    - LINKER → `relaxLinker` (joint optimize so the connector arcs collapse).
    - DIRECT binding (root-to-root) →
      **`relaxOverhangBinding(id)`** (no body) = endpoint
      `POST /design/overhang-bindings/{id}/relax` ([crud.py](backend/api/crud.py)
      `relax_overhang_binding`) that reuses the shared **`core_relax_bond`**
      (`backend/core/bond_relax.py`) on the two overhang anchors
      (`_sub_domain_junction_anchor`) + cluster pair → joint-rotate (1-DOF/N-DOF)
      or rigid-translate the driven cluster (0-DOF, `side_to_move` from
      `_resolve_driver_side`). **The cluster move must run while the overhangs are
      SEPARATE**, so `_onSecondary` does **un-relocate (unbind) → relax → re-relocate
      (bind)** — ends bound + cluster-moved. (2026-06-28: earlier direct Relax just
      toggled `bound` = relocate-only, no cluster move; the bound-toggle alone never
      moves clusters — that was deliberately decoupled 2026-05-14.) Pins:
      `test_overhang_bindings.py` (joint-rotate moves cluster / no-joint translates
      / 404), `bindrelax` frontend test (unbind→relax→bind order).
    (`Apply`/`Unapply` create/tear-down the binding *record*; `Relax` settles it.)
  - **END-TO-ROOT Apply = REGENERATE B AS A's RC BINDER (2026-06-29; Relax now LIVE — see the kinematic-solve bullet below):**
    Apply is LIVE again for `end-to-root` (the `_onApply` early-return + render
    `disabled=true` special-case were removed; it now calls `applyConnectionVersion`
    like the other direct types). Backend `apply_connection_version`'s `end-to-root`
    branch calls `lattice.apply_end_to_root_binder(d, a_id, b_id)`:
    - Reuses the binder generator via extracted helper `lattice._binder_domain_for_overhang(d, a_id)`
      → `(_make_complement_domain(A's dom), RC(A) seq)` (binder on A's helix, A's bp
      range, antiparallel, `binds_overhang_id=a_id`). `make_binder_for_overhang` now
      calls the same helper (verbatim — `test_oh_binder.py` re-pins it).
    - **Splices** that binder domain into overhang B's root staple **in place of B's
      free tip** (B's terminal domain idx 0 if `_5p` else last) → one continuous
      strand (B-root → binder). No explicit crossover record — the renderer/atomistic
      walk bonds consecutive `strand.domains` across helix jumps. **B is consumed**:
      its `OverhangSpec` is removed (a domain can't be both an overhang and a binder),
      so A is the sole free overhang afterward. Strand `sequence=None` → re-synced by
      `assign_staple_sequences` via `binds_overhang_id`.
    - **Old extrude geometry cleaned up (2026-06-29):** because the binder lands on
      A's helix (not B's old overhang helix), `apply_end_to_root_binder` also: (1) adds
      a **`ForcedLigation`** for the root→binder junction (the parent→tip backbone jump
      is now across non-adjacent helices = a forced ligation, not a lattice crossover);
      (2) **drops B's stale overhang crossover** (B's root helix ↔ B's tip helix) — else
      the caDNAno view keeps drawing a line to the deleted helix/old bp (user-reported);
      (3) **deletes B's now-orphaned overhang helix** (else a dangling axis line in 3D)
      + scrubs its id from cluster-transform `helix_ids`. The `_seed_end_to_root` synthetic
      case (B's root+tip on the SAME helix) correctly keeps the helix (still used by root)
      and has no crossover to drop. Caveat: A's overhang + the binder are BOTH staples on
      A's helix at the same bp (antiparallel) → in cadnano EXPORT they collide in the
      single `stap[]` cell (pre-existing OH_BINDER limitation, not introduced here).
    - **Round-trip guard (load-bearing):** `autodetect_overhangs` (lattice.py:3370) now
      also skips terminals with `binds_overhang_id is not None` — without it, save→load
      re-tags the spliced binder as a phantom B overhang (proven red by the oracle's
      round-trip clause).
    - **CONNECT routes through apply too (bug fix, 2026-06-29; generalized to ALL
      direct types 2026-06-30):** the leftmost **Connect** button (`_onConnect`, first
      pairing of a never-paired pair) used to run `_pair → _createBindingForPair` for
      ALL direct types — for end-to-root that created the OLD `OverhangBinding` record
      and only flagged the version applied (`_captureVersion({applied:true})`), so
      `apply_end_to_root_binder` never ran (user reported "I see the old method"). The
      `_onConnect` direct branch now mirrors **Add version** for **every** direct type
      (the `_typeId === 'end-to-root'` guard was widened to `ctIsDirect(_typeId)`,
      2026-06-30, per user request that root-to-root work the same as end-to-root):
      `_ensureComplementarySequences` (A drives B=RC(A), extracted from `_pair`) →
      `_captureVersion({applied:false})` → `applyConnectionVersion(newId)`. Apply then
      does the type-appropriate thing at the appropriate connection point —
      `apply_end_to_root_binder` splice for end-to-root, or the `elif direct:` branch's
      `OverhangBinding` at each side's **root** sub-domain for root-to-root (already
      pinned by `test_connection_versions.py::test_apply_direct_creates_binding_not_linker`).
      So BOTH Connect and Add-version run the apply endpoint for ALL direct types;
      `_pair`/`_createBindingForPair` (and `_onGenerate`'s `ctIsDirect` branch) are now
      **dead code** kept only as the old reference path. Only the missing-sub-domain
      **toast** ("Binding needs sub-domains defined on both overhangs") was preserved
      inline in the direct Connect branch (root-to-root only — end-to-root splices, so
      needs none) so bare overhangs don't silently materialize an empty connection; the
      old length-mismatch refusal is NOT preserved (apply creates the binding regardless).
      **Relax** for root-to-root is unchanged — still `relaxOverhangBinding` (unbind →
      `relax_overhang_binding` cluster move → bind), which IS the direct-binding analogue
      of end-to-root's kinematic `relax_end_to_root` (end-to-root needs the bespoke solver
      because B is consumed and has no `OverhangBinding` record). Pins:
      `overhang_connections_panel.versions.test.js` "Connect for root-to-root creates a
      version then APPLIES it … not the old OverhangBinding" + "Connect for end-to-root
      …" (both proven red without the branch); `seqpair.test.js` "Connect with only B
      missing fills B with RC(A), then routes through apply".
    - **END-TO-ROOT RELAX = KINEMATIC SOLVE (2026-06-29, LIVE — replaces the old
      "inert" stub):** Relax now closes the spliced ForcedLigation chord (B-root ↔
      binder) to one backbone bond (0.67 nm) by solving the design's kinematic model
      the way dsDNA-linker relax does. DOF = **2-DOF duplex swing about A's root bead**
      (persisted as A's `OverhangSpec.rotation`; the binder co-rotates via
      `binds_overhang_id`, so it's a real undoable orientation edit + an
      `OverhangRotationLogEntry`) **+ cluster kinematics** (joint-rotate when
      ClusterJoint(s) connect A's and B's clusters — the common 1-DOF case; rigid-
      translate B's root cluster when the clusters differ with no joint). 2-swing +
      1-joint = 3 DOF, exactly enough to close a 3-D gap. **Same rigid body** (both
      clusters identical) → swing only, NO cluster move, no hard refuse (user
      overrode the original "warn & refuse" ask via AskUserQuestion 2026-06-29).
      Backend solver `backend/core/end_to_root_relax.py` (`relax_end_to_root(design,
      overhang_a_id)`); endpoint `POST /design/connection-versions/{id}/relax-end-to-root`
      ([crud.py](backend/api/crud.py) `relax_end_to_root_version`, version-keyed →
      resolves A from `version.overhang_a_id`). Frontend: `relaxEndToRoot(versionId)`
      ([overhang_endpoints.js](frontend/src/api/overhang_endpoints.js)) + `_onSecondary`
      end-to-root branch (acts on `_appliedEndToRootVersion()`) + Relax enabled when an
      applied end-to-root version exists. Pins: `tests/test_end_to_root_relax.py` (7:
      translate→exact 0.67, 1-joint→0.668 from 5.0, swing-persists-as-rotation,
      same-body swing-only-no-cluster-move, 422, endpoint, 404) + `bindrelax`
      frontend test (end-to-root applied→`relaxEndToRoot(id)`; no-version→disabled).
      `relax_overhang_binding`'s old strut path stays removed (the new solver does NOT
      reuse it).
    - **Headless + oracle (AF-style):** `headless_build.create_connection_version` +
      `apply_connection_version` wrappers (route coverage 50→52) +
      `automation_harness.assert_end_to_root_binder` (binder geometry + splice + B
      consumed + RC + `.nadoc` round-trip). Pins: `test_headless_build.py::
      test_apply_end_to_root_regenerates_b_as_rc_binder_of_a` (real routed 6hb, two
      extruded overhangs — exercises the guard), `test_connection_versions.py::
      test_apply_end_to_root_splices_rc_binder_into_b` (HTTP endpoint, 2-domain B seed),
      `test_headless_build.py::test_apply_end_to_root_cadnano_clean_after_apply`
      (caDNAno-editor validation: orphan helix deleted, stale crossover gone, forced
      ligation present, `export_cadnano` clean with no dangling vstrand pointer),
      `bindrelax` test (end-to-root Relax now solves; see the kinematic-solve bullet). The oracle
      `assert_end_to_root_binder` now also pins clauses 6–8 (no orphan helix / no stale
      crossover / forced ligation at the root→binder junction). NOT hand-driven in-app yet.
  - **Group header** (2026-06-28): clickable chevron (▸/▾) collapses the version
    sublist (`_collapsedGroups` Set of pairKeys); title is connection-TYPE-AGNOSTIC
    — `OHA ↔ OHB · N versions` (no type).
  - **Newest version auto-applies** (2026-06-28): `_onAddVersion` now creates the
    draft THEN `applyConnectionVersion(newId)` — the most recently created version
    is always the materialized one. (Connect's version is already applied via its
    `_captureVersion({applied:true})` + the `_onGenerate` materialize.)
  - **One-applied-per-OVERHANG protection** (2026-06-28): an overhang can be in at
    most one APPLIED connection. `apply_connection_version` now tears down +
    unapplies EVERY materialized connection/binding AND version that shares either
    overhang (`_involves` = a_id or b_id in the entity), not just the exact pair —
    so applying OH2↔OH3 unapplies a prior applied OH1↔OH2. Covers Add-version +
    Apply (both route through the endpoint). **Connect** (which goes through
    `_onGenerate`, not apply) gets the same via frontend `_teardownConflicts(a,b)`
    (unapply versions + delete conns/bindings sharing a or b) before materializing.
    Pins: `test_connection_versions.py::test_apply_unapplies_connection_sharing_an_overhang`,
    `overhang_connections_panel.versions.test.js` (Connect-teardown).
  - **Spreadsheet rows** (2026-06-28): every ConnectionVersion (applied + drafts)
    shows as a read-only row in [spreadsheet.js](frontend/src/ui/spreadsheet.js)
    `_appendConnectionVersionRows` (mirrors `_appendAssemblyLinkerRows`). Sequence
    cell = `seqA · bridge · seqB`; **Notes cell = `V2 of 3 (applied)`** (name + per-pair
    total + applied state). Auto-refreshes (version CRUD replaces `currentDesign`).
- **Per-side sequence fields + complement-aware Gen + Pair** (2026-06-28):
  under each dropdown a sequence input + **Gen** (`#oconn-seq-{input,gen}-{a,b}`,
  shown only when that side has a selection). Input blur → `patchOverhang({sequence})`.
  **Gen is complement-aware for DIRECT types**: if the OTHER overhang already has
  a sequence, Gen fills THIS side with its reverse complement (`_genSide`);
  otherwise (linker types, or other side empty) → `generateOverhangRandomSequence`
  (Johnson). **Non-complementary warning** (`#oconn-pair-warning`,
  `_refreshPairWarning`): for a direct type when both overhangs have sequences
  that aren't RC of each other. The direct action button is renamed
  **"Make complementary" → "Pair"** (`_pair`, replaced `_makeComplementary`):
  neither has seq → gen A random + B=RC(A); one missing → fill it with RC(other);
  both present but non-complementary → A drives (B=RC(A)); both complementary →
  no seq change; then create the OverhangBinding (`_createBindingForPair`,
  selects the new binding row). Pair enable gated only on both-selected +
  not-forbidden polarity (no longer requires A to be pre-sequenced).
  **Both Gen paths are Johnson et al.** (already, backend): per-side overhang Gen
  → `/design/overhang/{id}/generate-random`, bridge Gen → `/design/random-sequence`
  — both call `overhang_generator.generate_overhang_sequences` scored vs the
  scaffold+staple corpus. Each random-Gen now surfaces the "Using the Johnson et
  al. overhang algorithm — DOI:…" toast (matching the manager). For linker types
  the per-side Gen is ALWAYS random Johnson (complement branch is direct-only).
- **Bind / Relax secondary button** (2026-06-28): `#oconn-secondary`, inline to
  the right of the Pair/Generate-Linker button (both `flex:1` in a flex row).
  Label + action follow `_typeId`: **direct → "Bind"/"Unbind"** on the pair's
  binding (`_bindingForPair` → `patchOverhangBinding({bound:!bound})`, same op as
  the right-click binding-line menu `overhang_binding_menu.js` + the details Bound
  checkbox); **linker → "Relax"** on the pair's linker (`_linkerForPair` →
  `relaxLinker(connId)`, no-arg = backend auto-picks 1-DOF, same as the right-click
  "Relax linker"). Disabled when no matching binding/linker exists for the A/B pair
  (`_onSecondary`).
- **Scrollable list + selected-row sequence/details** (2026-06-28): `#oconn-list`
  is a fixed-height (160px) bordered scrollable field. Clicking ANY row (linker
  OR binding) selects it (`_selRow = {kind,id}`, replacing the old `_selConnId`)
  and fills `#oconn-details`:
  - **linker** → live-computed colored sequence (verbatim port of the manager's
    `_linkerStrandSegments`: complement = RC of the bound overhang's seq in
    cyan/magenta, bridge = `conn.bridge_sequence` in white/ss or red+green/ds) +
    a **bridge-sequence editor** (input → `patchOverhangConnection({bridge_sequence})`
    on blur; **Gen** → `generateRandomSequence(lenBp)` → patch). Mid-edit guard:
    `_renderDetails` skips rebuild while `#oconn-bridge-input` is focused.
  - **binding** → the two sub-domain sequences (`_resolveSubDomainSeq`) + a
    **Bound** checkbox → `patchOverhangBinding({bound})`.
  `_renderDetails` is called from `_render` (re-reads live design each time).
  Backend now wired: create/delete (prior) + `patchOverhangConnection`
  (bridge), `patchOverhangBinding` (bound), `generateRandomSequence`.
- **Cyan/magenta overhang highlight** (2026-06-28): while the section is OPEN,
  an additive **glow** sits over the beads of the overhang in each dropdown —
  cyan (0x00e1ff) for A, magenta (0xff36c6) for B, matching the dropdown border
  colours. Two `createGlowLayer` overlays (`scene/glow_layer.js`, named
  `oconnGlowA`/`oconnGlowB`) — **separate additive draw calls that never touch
  bead colours**, so they don't fight the selection system's colour/restore
  tracking (the safe-overlay choice per the rendering rules). `_updateGlow`
  re-fetches `designRenderer.getBackboneEntries()` each call (tracks rebuilds /
  position overlays) and filters by `overhang_id`; called from `_render` (every
  A/B change), the collapse handler (clears on collapse), and a
  `currentGeometry`-change branch of the design subscriber. **Deps are INJECTED**
  (`{ scene, designRenderer, createGlowLayer }` from main.js) — NOT statically
  imported — because `glow_layer.js`'s top-level canvas IIFE (`_GLOW_TEX`) throws
  under jsdom; injection keeps the unit tests free of that import (they pass a
  fake factory). Highlight is gated on `!_collapsed`.
- **Old Overhangs Manager modal kept LIVE** (Tools → Overhangs Manager still
  works). Nothing archived/deleted — user chose "keep modal live too". The
  section coexists in parallel; both read/write the same `design.overhang_*`.

## Files
- [frontend/src/ui/overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js)
  — new factory `initOverhangConnectionsPanel({ store })`. Singleton (module
  state + `_inited` guard, like the popups). Subscribes to `currentDesign`
  changes → repopulate dropdowns (drop stale selection) + re-render icon.
- [frontend/src/ui/ct_icons.js](frontend/src/ui/ct_icons.js) — **additively**
  gained `CT_VARIANTS`, `endOf`, `ctIsForbidden`, `ctForbiddenReason`, then
  `ctAttachPair`, `ctIsDirect`, `ctIsIndirect`, `ctLinkerType`,
  `ctVariantForConnection`. Existing exports (`oppPolarity`, `polarityMarker`,
  `warningOverlay`, `ctTileSvg`) UNTOUCHED → assembly popup unaffected. The new
  variant→backend helpers are byte-equivalent to the two popups' private copies.
- [frontend/index.html](frontend/index.html) — new section after
  `#properties-section`. Reuses GLOBAL `.ct-button-box`/`.ct-popover`/
  `.ct-option`/`.ct-tile` CSS (defined near the manager modal). Popover floats
  `position:fixed` under the button (right panel clips overflow).
- [frontend/src/main.js](frontend/src/main.js) — +2 lines only (import + init).

## Key facts
- Overhang ids encode polarity as a `_5p`/`_3p` suffix
  (`ovhg_{helix}_{bp}_{5p|3p}`, lattice.py:3003). `endOf` parses it; that's the
  whole basis of the live 5'/3' button update — mechanical, no topology
  reasoning (per [[crossover_no_reasoning]] style).
- **THREE copies of the polarity-forbidden rule now exist** (consolidation
  opportunity): per-part popup `_ctIsForbidden`, assembly popup `_isForbidden`,
  and the new shared `ct_icons.ctIsForbidden`. All byte-identical. A future
  cleanup could repoint the two popups at the shared export.

## Tests (frontend-only; backend suite skipped, no Python touched)
- `ct_icons.test.js` — 11 pure tests (endOf, CT_VARIANTS shape, ctIsForbidden
  across direct/same-attach/mixed-attach, ctForbiddenReason, ctTileSvg ⚠).
- `overhang_connections_panel.test.js` — jsdom factory (singleton; sequential
  `it`s): populate, live forbidden ⚠, valid-type clears ⚠, collapse toggle,
  length-field + Generate-Linker enable, direct→Make-complementary disabled,
  list render + row-select, stale-selection drop.
- `overhang_connections_panel.selection.test.js` — separate file (fresh module →
  clean singleton) for the 2-slot-LRU auto-populate: spec example (OH1-4),
  ctrl-add eviction, re-pick no-op, domain-filter, collapsed-gating + snap.
- `overhang_connections_panel.glow.test.js` — separate file; injects a FAKE
  `createGlowLayer` + fake `designRenderer` (avoids the real glow_layer canvas
  import) → asserts cyan/magenta layers created, bead counts per dropdown, clear
  on collapse.
- `just test-frontend`: 1748 pass (only pre-existing `keyboard_shortcuts`
  number-hotkey flake fails — fails on clean master too). Build clean. Smoke
  render + assembly-exit teardown gates pass (isolated).

## NOT hand-driven (manual-validation debt)
The picker/collapse/leftward-popover gestures were **user-verified** ("Good.
verified."). The **create/delete round-trip** (Generate Linker → backend →
list updates; Make complementary; × delete) was pinned via jsdom (controls,
list render, row-select) + smoke (boot/render/teardown) but NOT hand-driven
against a real backend with an overhang-bearing design. Verify on e.g. a hinge
with extruded overhangs: generate a ds linker, confirm the 3D bridge appears
and the list row shows; delete it; try Make complementary on two sub-domained
overhangs.

## Sequence previews: N-padding + complementary coloring (2026-06-30)
Mirrors the sidebar overhang-resize fix into this section. New pure helpers in
[design_queries.js](frontend/src/scene/design_queries.js): `overhangDomainLength`
(backing-domain length = `abs(end_bp-start_bp)+1`, the AUTHORITATIVE current
length when an overhang is dragged longer), `pairingSegments` (antiparallel
classify of two sides → `paired`/`unpaired`/`excess` runs, anchored at the bound
region), `isComplement`. Panel renders colored preview lines:
- **Per-side A/B rows**: a `.oconn-seq-preview` line is inserted under each seq
  input. Direct type + both sides → pairing colors (green=complementary,
  amber=mismatch/N, grey=excess/undefined-N-tail) anchored at the attach
  sub-domain; else just greys undefined N bases of the selected side.
- **Binding details**: pairing preview anchored at the binding's STORED
  `sub_domain_a_id`/`sub_domain_b_id` (no polarity guessing — register was the
  user-confirmed "anchor at bound/attach end, excess at free tip").
- **Version details (direct only)**: "Current overhang pairing" colored preview
  from the LIVE overhangs; editable snapshot fields unchanged.
- Linker details left as-is (already N-pads + colors complement vs bridge).
Undefined bases come from `assembleOverhangSequence(ovhg, overhangDomainLength)`
padding to the backing-domain length. Tests: `design_queries.test.js`
(+pairingSegments/overhangDomainLength/isComplement), new
`overhang_connections_panel.seqpreview.test.js`. `just test-frontend` 1824 pass.
**NOT hand-driven**: the live drag-resize-then-open-section gesture wasn't
checked against a real backend.

## Next steps (deferred, when user asks)
1. Optionally archive/retire the old modal once the section reaches parity. The
   section still lacks vs the manager: inline name/length editing on rows, Relax
   linker, the Domain Designer tab. (Per-side seq inputs + Gen, Pair, bridge
   editing, Bound toggle, sequence display are now DONE here.)
2. Consolidate the 3 forbidden-rule copies (+ the now-3 attach/direct/linker-type
   copies) onto the shared `ct_icons` exports — repoint the two popups.
3. Length-unit (nm) toggle — the section currently always sends `length_unit:'bp'`.

Related: [[overhang_connections]] (linker data model), [[ct_tab]] (manager CT
tab this re-houses), [[assembly_overhang_bindings]] (other ct_icons consumer).
