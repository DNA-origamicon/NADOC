# TRAP — the "one ends up the length of the other" bug (user-reported 2026-06-30) — supporting detail

[Topic head](../../project_overhang_duplex_foundation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
