---
name: overhang-duplex-foundation
description: "The Duplex graph (Proposal B) — register-bearing hybridization edges over helix bp intervals. The pairing MODEL of record for overhangs: multivalency, mismatches, toeholds, different lengths. Phases 0-4b shipped; Phase 6 (retire OverhangBinding) never started. Rank P1."
metadata:
  node_type: memory
  type: project
---

# Overhang Duplex foundation (Proposal B)

**Rank:** P1 — the model is live, wired and is the direction the assembly tier already
committed to; two concrete Phase-4b follow-ups remain and Phase 6 is untouched.

**Status (probed 2026-07-30, `/audit-plan`).** Phases 0-4b **shipped and wired**: model,
routes, classifier, migration-on-load, producer, driver toggle, relocation, and the
2026-07-01 linker-bridge relax rewrite are all live. History is in
`project_overhang_duplex_foundation_archive.md` — **don't read it in a routine loop**;
everything current is below.

**The one thing to know before editing anything here:**

> The Duplex is the pairing model **by intent**, not yet in fact. Today it **coexists** with
> `OverhangBinding`, and which one you get depends on **length, not connection type**:
>
> | Caller | Equal-length | Different-length |
> |---|---|---|
> | **Connections panel** | binding **+** duplex — the binding relocates; the duplex is *display* (the panel's own comment `overhang_connections_panel.js:592` says "the display duplex") | **duplex only** — binding skipped `crud.py:7652`, `relocate_duplex` does the move |
> | Raw API / headless `apply_connection_version` | binding only | **NEITHER — silent no-op** |
> | Raw API / headless `connect_duplex` | duplex only | duplex only |
>
> The panel always calls `_ensureDuplexForPair` (`:595`, gated on `ctIsDirect` — **type only,
> no length or binding check**), so a UI connect always makes a duplex; `crud.py:7645-7655`
> says the duplex "is created separately by the frontend's `_ensureDuplexForPair`" — **the
> backend deliberately relies on the frontend to finish the job**, which is why the headless
> row has a hole. On the common (equal-length) path the **binding** still moves geometry and
> serves Relax: `lattice.py` and `deformation.py` read `overhang_bindings`, never `duplexes`;
> the panel's Relax precedence is linker > binding > duplex (`:438-450`), so `relaxDuplex`
> never fires there. Frontend render reads duplexes at one site (`helix_renderer.js:111`,
> unioned with bindings, only picking 360° vs 180° cylinders) — **nothing draws the
> connection**; the bond is visible because the driven tip was relocated in topology.

## Locked decisions (user, 2026-06-30) — invariants, do not drift

- **Coordinate (Q1):** reuse the existing helix bp index. `DuplexEnd = {overhang_id,
  start_bp, end_bp}` in that overhang's backing-domain helix coordinate; order encodes 5'→3'
  (mirrors `sequences.py` `bp = d.start_bp + offset*sign(end-start)`). No per-overhang slot index.
- **Register vs apply (Q1):** when APPLIED both ends are co-located on the driver's helix; the
  *relative* bp positioning on that shared helix IS the register. Moving overhangs while
  UNAPPLIED must NOT change the stored applied register.
- **Slide (Q2):** a cadnano drag UPDATES the register, never breaks the handler. Sliding to
  zero overlap is allowed — warn, don't error.
- **Mismatches yes, bulges deferred (Q3):** both ends EQUAL length (no gapped alignment).
  Per-base WC check → paired/mismatch. Bulges deferred indefinitely.
- **Driver explicit (Q4):** `Duplex.driver: 'left'|'right'`, user-set. Multivalent v1 rule:
  longest overhang drives.
- **Process (Q5):** automation + validation per phase before the next.
- **Length preservation:** connecting two DIFFERENT-length overhangs must NEVER resize either.
  The duplex pairs the shorter window (`length = min(lenA, lenB)`, anchored at each attach end);
  the longer keeps its full length and its excess becomes a **toehold**. No create/apply step
  touches `Domain.start_bp/end_bp`. Pinned by `test_duplex_crud.py:114`
  (`test_connect_different_lengths_preserves_both`) + `test_duplex_length_preserve.py`.

### TRAP — the "one ends up the length of the other" bug (user-reported 2026-06-30)

A `patch_overhang` **sequence write resizes the backing domain** to `len(sequence)`
(`crud.py:4778`, `new_length_bp = len(new_seq)`). The old connect flow set `B = RC(full A)`,
which silently resized B to A's length. Two guards keep it fixed, and **both must survive any
rewrite of the connect/Gen path**:

1. frontend `capSequenceToLength` (`design_queries.js:186`) caps every RC write to the target's
   current length (mirrors backend `_cv_sequence_for_live_overhang`, `crud.py:7454`);
2. backend `_cv_create_bound_binding` (`crud.py:7622`) **skips different-length pairs**
   (`crud.py:7648-7655`) — the Duplex represents them instead.

Related: RC-of-partner is **register-aware** (`overhangRcOfPartner`, `design_queries.js:364`) —
it overwrites only the paired-window bases and preserves the toehold. The old blunt
`capSeq(reverseComplement(fullPartner))` was wrong for different-length pairs.

## Code map (every line probed 2026-07-30)

### Backend

| Thing | Where | Note |
|---|---|---|
| `DuplexEnd` / `Duplex` | `models.py:493` / `:515` | fields `id`541 `name`542 `left`544 `right`545 `driver`546 `bound`547 `binding_mode`548 `allow_n_wildcard`549 `target_joint_id`551 `locked_angle_deg`552 `connection_type`553 `prior_driven_topology`558 |
| `Design.duplexes` / `_validate_duplexes` | `models.py:2260` / `:2475` | short-circuits when empty (`:2492`) |
| `OverhangBinding` / `Design.overhang_bindings` | `models.py:579` / `:2255` | **still fully live** — see Phase 6 |
| `core/duplex.py` | classifier + graph ops | `classify_duplex_pairing`174, `overhang_pairing_map`197, `duplex_wc_ok`219, `smallest_unused_duplex_name`235, `longest_driver`243, `connect_register`256, `relocate_duplex`295, `revert_duplex_relocation`347, `shift_duplex_ends`359, `drop_invalid_duplexes`381, `sync_duplexes_from_bindings`406, `summarize_duplexes`427, `synthesize_duplexes_from_bindings`62 |
| `routes_duplex.py` (carved out of crud.py) | registered `main.py:65,242` | 9 routes: GET`:138` POST`:144` connect`:177` sync-from-bindings`:223` PATCH`:236` DELETE`:283` relax`:296` pairing`:336` pairing-map`:343`; `_propagate_driver_to_binding`:116 (called once, `:269`) |
| migration-on-load | `crud.py:6297` `_derive_duplexes_if_empty` | both call sites live: `/design/load` `crud.py:1367`, `/design/import` `:1401` |
| cadnano-drag robustness | `crud.py:2611` `_build_domain_shift` → `shift_duplex_ends`+`drop_invalid_duplexes`; `:2571` `_build_strand_end_resize` → `drop_invalid_duplexes` | register preserved on move, dropped on out-of-range resize |
| driver → geometry | `routes_duplex.py:272` → `crud.reapply_binding_driver` (`crud.py:8796`) | revert + re-bind with the new driver (equal-length/binding-backed only) |
| relocation (binding-less) | `duplex.relocate_duplex:295` → `binding_relax.compute_bind_topology:193` with `target_start_override`198/`target_end_override`199 | relocates the driven's WHOLE domain onto only the driver's paired window |
| relax | `direct_relax.relax_direct_binding:320`, wired `routes_duplex.py:310` | linker-bridge method (see below) |
| validator | `validator.py:270-282` | flags a duplex register with zero complementary bases |
| headless / oracles | `headless_build.py` `connect_duplex`869 `relax_duplex`896 `add_strand_extension`932; `tests/automation_harness.py` `assert_duplex_relocated`1130 `assert_extension_present`1235 `assert_duplex_relaxed`1854 | |
| tests (all fast, none `slow`) | `test_duplex_model.py`15 · `test_duplex_crud.py`19 · `test_duplex_relax.py`6 · `test_duplex_classifier.py`6 · `test_duplex_automation.py`5 · `test_extensions_automation.py`4 · `test_direct_connection_unified.py`10 · `test_duplex_geometry.py`**1** · `test_duplex_relocate.py`**1** · `test_duplex_length_preserve.py`**1** | frozen fixtures `tests/fixtures/relax_2x2_binding.nadoc`, `relax_2x2_closebond.nadoc` — the live `workspace/2x2_OH_test.nadoc` is hand-edited between sessions, never depend on it in a test |

### Frontend

| Thing | Where |
|---|---|
| pure JS mirror of `core/duplex.py` | `scene/design_queries.js`: `capSequenceToLength`186, `classifyDuplex`317 (kernel `classifyAntiparallel`332), `overhangRcOfPartner`364, `overhangDuplexCoverage`412, `overhangHasDuplex`431, `overhangDuplexSegments`495 |
| client fns | `api/overhang_endpoints.js`: `createDuplex`285 `patchDuplex`292 `deleteDuplex`298 `connectDuplex`303 `syncDuplexesFromBindings`311 `relaxDuplex`317 |
| the only consumer panel | `ui/overhang_connections_panel.js`: `_boundDuplexForPair`424 `_onSecondary`438 `_duplexLineEl`510 `_renderDriverToggle`540 `_ensureDuplexForPair`595 `_ensureComplementarySequences`862 `_genSide`942 |
| sidebar coverage line + ▶ driver marker | `ui/overhang_sequences_panel.js:109` / `:114-119` |
| Gen flow | `ui/overhang_gen.js:59` `runOverhangGen` (injected `rcOfPartner`) → `ui/primitives/choice.js:32` `showChoice` |
| extensions reach from an overhang bead | `ui/overhang_orientation_menu.js:119-132` → `selection_manager.js:4089` `openExtensionsForStrands` (wired `main.js:2983`) |
| render read (the only one) | `scene/helix_renderer.js:111-115` — collects duplex endpoint overhang ids, gated on `bound !== false && DIRECT_CONNECTION_TYPES.has(connection_type)` |
| tests | `design_queries.test.js` (duplex cases `:102-211`) · `overhang_gen.test.js`10 · `overhang_orientation_menu.test.js`20 · `overhang_connections_panel.{duplex,driver,lengthcap}.test.js` **1/2/1** |
| e2e | `e2e/duplex_pairing_display.spec.js` (derive-on-load colouring + driver flip), `e2e/fluorophore_toggle.spec.js` |
| **deleted 2026-07-01, confirmed gone** | `scene/overhang_binding_lines.js`, `ui/overhang_binding_menu.js` — zero dangling refs |

### The relax that is actually running (2026-07-01 rewrite — supersedes every earlier swing description)

`relax_direct_binding` no longer swings the overhang about its root. Three steps:
1. **Arc minimization via cluster kinematics** — anchors are the two embedded-staple root beads;
   rotate the connecting joint (`linker_relax._optimize_chord_angle`) or rigid-translate the
   driven cluster to bring `|P_A−P_B|` → `span + n_bonds·target`. Same rigid body ⇒ no motion.
2. **Re-seat** at the oriented midpoint (`duplex_midpoint_placement` → writes the driver's
   `OverhangSpec.rotation` **and** `OverhangSpec.translation`, `models.py:274-282`), so both
   root bonds land equal at `target_nm`.
3. **Clash spin of the DUPLEX ONLY** (`_min_clash_rotation`) about the root→root axis; the
   clusters are not touched. Compose about the *un-seated* junction pivot:
   `q_final = q_clash⊗q_seat`, `t_final = R_clash·(p0u+t_seat−P_A)+P_A−p0u`.

Two-sided target (opens an over-compressed bond back to 0.67 nm) — this **supersedes LESSONS E7's**
one-sided "never back off" floor. `info["mode"]` ∈ `same_body`/`joints`/`translate`; `swing_*`
fields are gone (0 hits). A 1-DOF revolute joint can't always reach a large gap — partial close,
bonds still symmetric. Axis-line gotcha: `_apply_ovhg_rotations_to_axes` (`deformation.py:1871`)
must **de-apply the translation** to recover the pre-transform pivot, or the shift double-counts.

## Open items (rewritten against the probe — these are what is genuinely left)

1. **Phase 4b(1) — driver flip for a binding-LESS relocated duplex.** `patch_duplex` re-places
   only binding-backed duplexes (via `reapply_binding_driver`); a different-length duplex keeps
   the field edit with no geometry change. Flipping to make the SHORTER side the driver is also
   ill-defined (it would stretch the longer down) — likely constrain the toggle to longest-drives
   for different lengths. **Unclaimed by every sibling doc.**
2. **Phase 4b(2) — relax for the binding-less duplex.** `overhang_duplex_cluster` gave it a
   *placement* (midpoint seat + cluster, 2026-07-01) but not a settle. Note the doc's old claim
   that `relax_direct_binding` 422s when the driven tip isn't on the driver helix is **wrong**:
   the 422 (`direct_relax.py:108`) fires on *no relocated tip domain found*; helix identity is
   only an unasserted comment at `:373`.
3. **Phase 6 — retire `OverhangBinding` — never started, and it is not close.** `overhang_bindings`
   is READ from ~35 sites in `crud.py` plus `lattice.py:3614`, `deformation.py:1023,1135`,
   `primitive_placement.py:60`, `routes_duplex.py:127,208,274`, and **11 frontend modules**
   (`animation_player`, `helix_renderer`, `client`, `overhang_connections_panel`,
   `overhang_pathview`, `overhang_sequences_panel`, `animation_panel`, `overhangs_manager_popup`,
   `domain_designer_panel`, `assembly_overhangs_manager_popup`,
   `assembly_overhang_connections_panel`). The **assembly tier already executed this pattern** —
   `AssemblyOverhangBinding` is docstring-marked superseded + migrated-on-load
   ([[assembly_overhang_bindings]]) — so copy that playbook, don't invent one.
4. **Orphans in a "shipped" surface.** `revert_duplex_relocation` (`duplex.py:347`) has **no
   caller at all** — so a binding-less relocation cannot be reverted; `summarize_duplexes`
   (`:427`) is test-only; and the client fns `createDuplex` / `deleteDuplex` /
   `syncDuplexesFromBindings` have **zero callers** although their routes are live and registered.
   Either wire them or delete them.
5. **Reserved fields that stayed reserved.** `binding_mode`, `target_joint_id`,
   `locked_angle_deg` are **never read anywhere** — they were the Phase-4 geometry-coupling slots
   and the geometry went through `OverhangSpec.rotation/translation` instead.
6. **Stale docstring.** `models.py:537` still says *"Phase 0: this model exists and validates but
   NOTHING consumes `Design.duplexes` yet"* — contradicted by the load/import bridge, the
   validator, 9 routes and two panels. One-line fix.
7. **Four "NOT hand-driven" gestures were never filed as manual-validation debt.** Nothing in
   `manual_validation_debt.md` (repo **root**) covers: the Gen-click→choice dialog; Relax on a
   binding-less duplex; right-click-overhang-bead→extensions; the post-rewrite Relax on
   `2x2_OH_test.nadoc` (both bonds close, ONLY the duplex reorients — the clusters must not spin).
   The MV rows that do exist (MV-CONNLINK / MV-DUPMENU / MV-DUPTAUT / MV-DUPPIVOT) belong to
   [[overhang_duplex_cluster]], not to this plan.
8. **Test depth is lopsided for the phases called shipped.** `test_duplex_geometry.py`,
   `test_duplex_relocate.py`, `test_duplex_length_preserve.py` are **one test each**, and the three
   panel duplex specs are 1/2/1 cases — for Phases 4/4b, the ones that move geometry.

### Coexistence hazards (found 2026-07-30 resolving the contradicting peer — none covered by any test)

9. ~~Different-length pairs are excluded from overhang co-motion.~~ **CONFIRMED BY TEST, THEN
   FIXED 2026-07-30.** The prediction was right: a 90° driver rotation moved the WC pair distance
   from **1.93 nm → 5.25 nm** — the driven overhang stayed behind — and the materialized duplex
   cluster's `domain_ids` held only `('oh_strand_a', 0)`, omitting the driven domain entirely.
   Root cause was **one lookup read by three sites**: `driven_to_driver` (co-rotation partners),
   `driven_bound_oh_ids` (the driven-side self-rotation skip), and transitively
   `_duplex_domain_refs` → `materialize_duplex_cluster` (the gizmo-drag scope) all built their map
   from `design.overhang_bindings` **only**, while `relocate_duplex`'s `__duplex_reloc__` binding
   is transient and never persisted (`duplex.py:311`).
   **Fix:** new `deformation._bound_driver_driven_pairs(design)` returns `driven → driver` from
   **both** bound bindings and bound duplexes (bindings win on conflict — they agree anyway, since
   `_propagate_driver_to_binding` syncs duplex→binding); both call sites now use it, which fixes
   the cluster scope for free. **Pinned by** `tests/test_overhang_binder_rotation.py`
   `test_diff_length_duplex_partner_follows_rotated_driver` (geometry: WC pair distance preserved
   through a 90° driver rotation) + `test_diff_length_duplex_cluster_contains_the_driven_domain`
   (structure: the driven domain is in the cluster's `domain_ids`). Both assert the no-binding
   precondition first, so they fail loudly if the length fork ever changes. Still **not
   app-verified** — the in-app check is: connect a 10-mer to a 24-mer, rotate the duplex, confirm
   the driven overhang follows.
10. **Driver sync is one-directional.** `PATCH /design/duplexes/{id}` pushes duplex→binding
    (`_propagate_driver_to_binding` + `reapply_binding_driver`). **Nothing pushes binding→duplex** —
    `patch_overhang_binding` (`crud.py:8586`) has zero `duplexes` references, so flipping the driver
    through a binding-side route leaves `Duplex.driver` stale and the panel's toggle shows the
    wrong side.
11. **Deleting either record leaves the other dangling.** `delete_duplex`
    (`routes_duplex.py:283-294`) never touches bindings; `delete_overhang_binding`
    (`crud.py:8887`) never touches `duplexes`.
12. **Re-Connect on the same pair reuses a stale duplex.** `apply_connection_version`'s teardown
    (`crud.py:7741-7759`) reverts topology and strips `overhang_bindings` but **never strips
    `duplexes`**, so the follow-up `connect_duplex` 409s ("already connected by a duplex") and the
    panel swallows it — the old register survives a reconnect.
13. **Headless can't produce what the UI produces.** No headless method makes both records; a
    different-length `apply_connection_version` makes **neither**. Any automation oracle built on
    the headless path is therefore testing a state the app never produces (and vice versa). This is
    also why the disjoint test sets never caught items 9-12: apply-path tests assert bindings and
    never inspect duplexes, connect-path tests assert duplexes and never inspect bindings, and
    **no test exercises the panel's apply→connectDuplex sequence** (`connectDuplex` has zero hits
    in any `*.test.js`).

**Phase 5 (attachments) needs no work** — fluorophores/quenchers/biotin are the pre-existing
`StrandExtension.modification` feature (full CRUD, Bézier-arc bead geometry on a `__ext_` helix,
emission glow + FRET). To label an overhang: add `StrandExtension{strand_id, end,
modification:'cy3'}` on the overhang's staple terminus. A duplicate `Attachment` model was built
and fully reverted (user caught it). If internal-base labels are ever wanted, EXTEND
`StrandExtension` — never a second model.

## The doc fork (read this before trusting a sibling)

Nothing supersedes this file — it is the only definition of `DuplexEnd`,
`classify_duplex_pairing`, `overhang_pairing_map` and the length-preservation law. But it is no
longer the only entry point, and two heavily-trafficked siblings are **duplex-blind**:

| If the task is… | Open | Caveat |
|---|---|---|
| pairing model / register / multivalency / toehold | **this file** | — |
| "connect two overhangs in the app" | [[overhang-connections-panel]] | **RESOLVED 2026-07-30** — it was duplex-blind (its ★ UNIFIED section describes the pipeline purely in `OverhangBinding` terms); a correction block with the truth table above now sits under that header. It is still the right doc for the version/apply/teardown machinery — just read its ⚠ blocks first |
| duplex geometry / pose / gizmo | [[overhang-duplex-cluster]] | its head still says "planning; no code" — false, P0–P3 shipped 2026-07-01 |
| cross-part pairing | [[assembly_overhang_bindings]] | the **most current** duplex doc (2026-07-11); owns `AssemblyDuplex` + the shared `classify_antiparallel` kernel |
| sub-domain metadata / Domain Designer | [[overhang_subdomains]] | **duplex-blind**; its Phase 5/6 is exactly what Phase 6 above retires |

## Related

[[overhang_binding_extensions]] (the `compute_bind_topology`/`apply_bind_topology`/
`revert_bind_topology` primitives this plan reuses — inverted dependency: the Duplex wraps them
via a transient binding carrier) · [[bond_relax]] · [[overhang_sequence_display]] ·
[[protein_attachment]] · [[oh_binder]] (a *third* pairing representation,
`Domain.binds_overhang_id` — this plan has never accounted for it).
