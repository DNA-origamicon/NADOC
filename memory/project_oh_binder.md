---
name: oh-binder-strands-overhang-binding-oligos
description: StrandType.OH_BINDER + Domain.binds_overhang_id; convert/pen/linker creation paths; bidirectional RC sequence sync; keystone scaffold-coverage fix
metadata: 
  node_type: memory
  type: project
  originSessionId: 83865b89-5e31-489d-9a2d-eb2cf99080df
---

Shipped 2026-05-29. First-class "overhang binding oligo" — the strand that
hybridizes to an overhang (fluorophore detection strand / strand-displacement
input). Groundwork for un/hybridization + TMSD reactions.

## Data model (locked, user-confirmed)
- `StrandType.OH_BINDER = "oh_binder"` ([backend/core/models.py](backend/core/models.py) ~L53).
- `Domain.binds_overhang_id: Optional[str]` → the `OverhangSpec.id` this domain
  pairs with (antiparallel, same helix, same bp range). THE single unifying link:
  set on standalone OH_BINDER strand domains AND on auto-generated LINKER
  complement domains. Drives the Overhangs-Manager binder listing + RC sequence sync.
- `Strand.is_oh_binder` property. Overhang stays the canonical sequence source;
  binder = its reverse complement.

## KEYSTONE FIX (do not regress)
`_scaffold_coverage_by_helix` ([lattice.py](backend/core/lattice.py) ~L2710) now
gates on `strand_type == SCAFFOLD and not is_reference`. The OLD predicate
(`!= STAPLE and not is_reference`) counted LINKER + OH_BINDER complement domains
(which sit on a real bundle helix at an overhang's bp range) as scaffold coverage,
which corrupted `autodetect_overhangs` / `_reconcile_inline_overhangs` for OTHER
staples on that helix. Binders behave like STAPLES everywhere (ordering, geometry,
sequence assignment) — NOT like scaffold. `autodetect`/`reconcile` already skip
non-STAPLE as overhang *subjects* (correct — binders aren't overhangs themselves).

## Creation paths (all in lattice.py)
- `convert_strand_to_binder(design, strand_id)` — for each domain, find the
  antiparallel partner via `_antiparallel_partner_domains` (same helix, opposite
  direction, overlapping bp; excludes the binder itself + other binders/linkers).
  Links to an already-tagged overhang, else tags a STAPLE partner as a NEW overhang
  (`ovhg_binder_{strand}_{domIdx}` + whole-domain SubDomain, mirrors `autodetect_overhangs`).
  Raises ValueError only when NO antiparallel partner exists. Endpoint:
  `POST /design/strands/{id}/convert-to-binder` (crud.py, `mutate_with_feature_log('overhang-bulk')`).
- `tag_painted_binder(design, strand)` — pen tool: a freshly-painted STAPLE that
  antiparallel-overlaps an EXISTING tagged overhang auto-becomes OH_BINDER. Wired in
  `add_strand` (crud.py) — frontend pen unchanged; server decides type+color.
- Linker unification: `_make_complement_domain(oh_dom, binds_overhang_id)` threads the
  overhang id from both `generate_linker_topology` call sites → linker complements
  register as binder domains.
- `make_binder_for_overhang(design, overhang_id)` — right-click an OVERHANG →
  "Generate OH binding strand" creates a NEW strand antiparallel to the overhang
  (`_make_complement_domain`, same helix + bp range, opposite direction), tagged
  OH_BINDER + magenta; `sequence` = reverse complement of the overhang's assembled
  bases when it has one, else None. Endpoint `POST /design/overhang/{id}/generate-binder`
  (201, 404 if missing; `mutate_with_feature_log('overhang-bulk')`). Allows multiple
  (unique `ohbind_{ovhg}_{hex}` ids) — e.g. a competing displacement strand. Menus:
  3D `_showOverhangOrientMenu` (main.js, single-overhang block), cadnano
  `#overhang-menu-generate-binder` button (`_ovhgMenu`). `generateBinderForOverhang`
  in BOTH api clients. Auto-appears in 3D/cadnano/spreadsheet (it's a real strand).
- `convert_binder_to_scaffold(design, strand_id)` — INVERSE of convert. Right-click an
  OH_BINDER strand → "Convert to scaffold": retypes → SCAFFOLD, color → None, clears
  `binds_overhang_id`, and removes any `ovhg_binder_`-prefixed overhang the original
  conversion auto-created ONCE orphaned (no other binder binds it + not referenced by
  overhang_connections/overhang_bindings) — untags partner + drops spec. Pre-existing
  overhangs (linked, not created) are kept. Endpoint
  `POST /design/strands/{id}/convert-to-scaffold` (200, 404; `overhang-bulk`).
  `convertBinderToScaffold` in both clients; menu item in `_showColorMenu` (3D, oh_binder)
  + `_showStrandCtxMenu` (cadnano, oh_binder). scaffold→binder→scaffold is a clean round-trip.

## RC sequence sync (sequences.py)
- `_assemble_overhang_5to3(spec, domain_len)` factored out (sub-domain overrides →
  parent slice → N, pad/trim). Overhang→binder: a domain with `binds_overhang_id`
  gets, per bp, the WC complement of the overhang base at the same (helix,bp) —
  antiparallel. Verified WC via `is_watson_crick_complement` in tests.
- Generate propagation: `generate-overhang-sequences` adds binder strands to
  `affected_strand_ids`; single-overhang `generate-random` reuses
  `_resplice_overhang_in_strand` per bound binder.
- "Vice versa": overhang is canonical. Frontend spreadsheet Sequence cell shows the
  binder RC LIVE (`_liveBinderSequence`, pad-then-RC per LESSONS F3) even before
  assign; right-click → "Set binder sequence…" writes RC onto the bound overhang via
  `patchOverhang` (single-bound-overhang case).

## Frontend (color = magenta #c050d0)
- Palettes: `CLR_OH_BINDER` in pathview/palette.js + `C.oh_binder` in
  helix_renderer/palette.js; fallbacks in `stapleColorOf` + `nucColor/Slab/Arrow`
  (after the custom-color check, so user recolor still wins).
- Convert menu item: 3D `selection_manager.js` `_showColorMenu` (scaffold, single);
  cadnano `main.js` `_showStrandCtxMenu` (scaffold, single). `convertStrandToBinder`
  added to BOTH api clients (client.js + cadnano-editor/api.js — separate clients!).
- Spreadsheet: `sheet-oh-binder` row class (magenta text, CSS in index.html +
  cadnano-editor.html), Start-cell type tooltip ("OH binder"), effectiveColor fallback.
  Binders already list as their own rows (non-scaffold bucket).
- Add-extension already works for binders (non-scaffold selectable + extension menu).
- Overhangs Manager: Domain-Designer cross-refs panel gets a "Binders (n)" subsection
  (`_renderBindersSection` in domain_designer_panel.js).

## Strand Animation (sidebar section — supersedes the one-shot "Animate binding")
See [[strand_animations]] for the full integration. The throwaway one-shot "Animate binding"
context-menu items + `overhang_unzip_overlay.updateBinder` + `_animateBindingForOverhang` were
REMOVED and replaced by a proper sidebar section that drives the REAL overhang+binder beads
with the strand-anim sandbox's actual unzip math (delta-from-φ=1, both strands peel, straight/
helical, melt). Test design `workspace/OH6hb_test.nadoc` (2 overhangs, each a binder).

## Tests
`tests/test_oh_binder.py` (14, all green): enum/field/round-trip, convert (link /
tag-partner / 422-no-partner / endpoint 200+404), scaffold-coverage regression,
pen-tag, overhang→binder RC + partial-pad, linker complement binds. Full suite
**1612 passed** (2 fails = pre-existing router flakes `test_advanced_seamed_*` +
`test_teeth_closing_zig`, order-dependent, unrelated).

## Overhang orientation co-rotates binders (2026-06-29)
Editing an overhang's orientation ("Edit Orientation" → `OverhangSpec.rotation`)
now co-rotates its binding domain — including a binder's toehold extending past
the overhang on the same helix, and end-to-root binders spliced into a STAPLE
strand. The geometry-time co-rotation predicate (`_overhang_binding_partner_refs`
in deformation.py, Layer 1) keys on `binds_overhang_id`, not strand type. Frontend
live-preview parity via `ovhgBinderDomainIds` + `domsForOverhang` (orientation
panel). See [[overhang-connections]] gotcha #7. Tests:
`tests/test_overhang_binder_rotation.py`.

## Caveats / NOT done
- **Frontend UI not click-tested in a live browser** — build is clean and wiring
  mirrors working patterns, but menus/colors/spreadsheet/manager were not exercised
  in a running app. Phase/base-pairing visual check is a USER TODO.
- `Examples/Hinge_scaff_test.nadoc` (user's chosen verify design) + `hingeV4.nadoc`
  do NOT load under the current backend — legacy crossover format (no `half_a/half_b`),
  PRE-EXISTING, unrelated to this work. `NS_trans_fix.nadoc` loads (used for the
  real-design integration check: pen-tag→oh_binder, generate persists overhang seq,
  geometry rebuild — all OK).
- "Vice versa" only covers single-bound-overhang binders via context menu; no
  inline-editable binder Sequence column.
- Convert uses `'overhang-bulk'` snapshot kind (no new SnapshotOpKind literal).
