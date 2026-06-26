---
name: project_route_for_polymerization
description: Route for Polymerization — routing-menu action that fills bare scaffold ends with connector staples + periodic-seam bridges so a part is end-to-end polymerizable. Shipped 2026-06-10.
metadata: 
  node_type: memory
  type: project
  originSessionId: d4117f1a-d7b2-4745-9019-10ce5fe5b50e
---

# Route for Polymerization (shipped 2026-06-10)

New action in the **Routing submenu of BOTH editors** (3D part editor + cadnano editor),
`menu-routing-polymerization`, between Full Autostaple and Add Loops/Skips. Takes an origami
with **single-stranded scaffold at its two terminal faces** and makes it end-to-end
polymerizable in assemblies.

## What it does (user-validated topology decisions — do not silently change)
- **Seam carrier = bridging STAPLES**, scaffold stays a per-copy plasmid. Generated connector
  staples are what physically stitch copy N's far end to copy N+1's near end.
- **One FIXED connector strand per bare end** (no tick/grow/merge length rules — that's normal
  autostaple; a polymer connector is deliberately simple). Built via `_make_complement_domain`
  semantics (antiparallel, opposite slot, same bp range).
- **Every face-helix with BOTH ends gets a bridging staple, and EVERY bridge is flagged
  `is_periodic_seam`** (corrected 2026-06-10 after user feedback — the original "flag only one"
  left 21/22 strands NOT routed through the boundary; user wants all end strands periodic so the
  duplex is continuous across copies on every helix, and so all render through-boundary in the
  cadnano PB view). Flagging all is NOT an over-constraint: `derive_periodic_delta` least-squares-
  averages the per-helix repeats (more robust; on a clean bundle still ~0° rotation, on the ragged
  Arm_pulley_v1 it's 0.82° — negligible). The assembly mate still uses ONE seam
  (`principal_seam_connectors` returns `frames[0]`), so multiple flags don't fight there.
  `principal_seam_id` = the first bridge, for reporting.
- **Ends fully duplexed** (no tip toehold).
- **Warn, never block**: missing Autoscaffold op (no `auto-scaffold*` feature-log entry AND no
  `auto_scaffold_*` crossover) → warning that faces may not be translation-matched; a one-sided
  helix → warning; **hard-errors (422) only when there is nothing to route at all**.

## KEY topological insight (the thing not to re-derive wrong)
The bridging ligation joins the two connectors at their **CAP tips** (the helix low-bp / high-bp
terminal faces), NOT their inner edges. That puts the seam endpoints on the terminal
cross-sections, so the derived repeat period = whole part length. An inner-edge ligation would
yield a far-too-short period. The 3'-donor connector is picked by **domain orientation**
(`near_dom.end_bp == low cap` → near is the 3' donor), so it's correct for either scaffold
polarity without geometric guessing. `derive_periodic_delta` keys off the seam `(helix,bp)`
endpoints with a **direction-independent** cross-section frame (`_section_frame_from_arrs`) that
only needs the bp duplexed — so a STAPLE seam works for geometry once connectors duplex the bp
(it does NOT require a scaffold seam). See [[periodic-boundary]] / [[polymerize-origami]].

## Code
- Core (pure, testable): [backend/core/polymer_router.py](backend/core/polymer_router.py) —
  `route_for_polymerization(design) -> (Design, PolymerRouteResult)`; helpers `_bare_end_runs`
  (unpaired-scaffold runs touching a cap, via `unpaired_bead_keys` + `_scaffold_coverage_by_helix`),
  `_complement_strand`, `_bridge` (cap-tip ligation + ForcedLigation record), `_has_autoscaffold`.
- Route: `POST /design/route-for-polymerization` in [backend/api/crud.py](backend/api/crud.py)
  (just before `assign-scaffold-sequence`), via the shared `_run_auto_scaffold_with_feature_log`
  helper → one atomic undo/feature-log entry, op_kind `route-for-polymerization` (added to
  `SnapshotOpKind` in models.py). Response adds `warnings`, `connector_strand_ids`,
  `seam_ligation_ids`, `principal_seam_id`.
- Frontend: client `routeForPolymerization()` in [frontend/src/api/client.js](frontend/src/api/client.js)
  AND a separate one in [frontend/src/cadnano-editor/api.js](frontend/src/cadnano-editor/api.js)
  (the cadnano editor has its OWN api.js wrapper, `mutate(req=>req('POST',...))` — easy to miss).
  Menu items in `index.html` + `cadnano-editor.html`; thin click handlers in each editor's main.js
  (toast bridge count + first warning). No new closure logic.

## Tests
[tests/test_polymer_router.py](tests/test_polymer_router.py) (7) — connector-per-bare-end,
ends-fully-duplexed, exactly-one-principal-seam, seam-endpoints-on-caps, **the geometric oracle
`test_derived_period_is_pure_axial_translation`** (derive_periodic_delta → ≈0° rotation, det +1,
translation ≈ part length — pins the cap-ligation), warn-no-autoscaffold, error-nothing-to-route.
Fixtures build a 6hb bundle then replace staples with interior-only staples to expose bare ends.
Full suite 1949 pass after the change.

## NOT yet verified live (2026-06-10)
Backend fully tested. Frontend is thin wiring + builds clean, but **the live menu click + the seam
POLARITY in the cadnano periodic-boundary view were NOT hand-checked** — needs a user design with
bare scaffold ends loaded. The polarity is the one thing to eyeball (per REFERENCE_DNA_TOPOLOGY,
text-only polarity reasoning is unreliable): the bridging staple should render joining the
far-ssScaffold complement of one copy to the near-ssScaffold complement of the next.
