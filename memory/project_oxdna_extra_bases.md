
# Crossover extra bases → oxDNA (single-stranded inserts) — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="crossover-extra-bases--oxdna-single-stranded-inserts"></a>
- [Crossover extra bases → oxDNA (single-stranded inserts)](details/project_oxdna_extra_bases/01-crossover-extra-bases--oxdna-single-stranded-inserts.md#crossover-extra-bases--oxdna-single-stranded-inserts)

<a id="what-it-does"></a>
- [What it does](details/project_oxdna_extra_bases/01-crossover-extra-bases--oxdna-single-stranded-inserts.md#what-it-does)

## CRITICAL gotcha — the phantom FENE bond

`backbone_bond_pairs` (consumed by the relaxation health check `backbone_fene_stretch`
/ `max_backbone_stretch`) pairs consecutive backbone nucleotides. At an extra-base
junction the two flanking real nucleotides are NOT directly bonded — the inserts sit
between them. If `backbone_bond_pairs` still pairs `prev_real → next_real` it measures
ONE phantom bond spanning the widened gap (~2.1 oxDNA units vs the 1.006 FENE cliff),
which reads as a spurious over-stretch → md_relax fails fene-safe → 3 escalating
retries → **the whole relaxation fails** ("1 bond over-stretched, longest 2.121 units").
The real oxDNA sim relaxes fine; only the health check was wrong.

Fix: `backbone_bond_pairs` threads `_XB_SENTINEL` placeholders at extra-base junctions,
so the junction bonds involve a dropped key and are skipped (not measured as one giant
bond). Non-extra-base junctions are untouched. If a future change re-walks the strand
graph for health, remember the inserts.

<a id="production-instability-on-floppy-designs--auto-dt-halving-recovery-2026-06-25"></a>
- [Production instability on floppy designs → auto dt-halving recovery (2026-06-25)](details/project_oxdna_extra_bases/02-production-instability-on-floppy-designs--auto-dt-halving-recover.md#production-instability-on-floppy-designs--auto-dt-halving-recovery-2026-06-25)

<a id="validation"></a>
- [Validation](details/project_oxdna_extra_bases/02-production-instability-on-floppy-designs--auto-dt-halving-recover.md#validation)

<a id="rendering-extra-bases-at-real-simulated-positions-phase-1-done"></a>
- [Rendering extra bases at REAL simulated positions (Phase 1 done)](details/project_oxdna_extra_bases/02-production-instability-on-floppy-designs--auto-dt-halving-recover.md#rendering-extra-bases-at-real-simulated-positions-phase-1-done)

### THE INSERT-ORDERING LAW (fixed 2026-08-01 — was silently swapping inserts)

Beads are laid out along the Bézier from **`half_a` → `half_b`**, so bead 0 is the one
next to `half_a`. Every emitter — NAMD (`atomistic.py:2795-2802`) and oxDNA
(`oxdna_interface.py:394-403`) — instead numbers the run **5′→3′ from `src`**, where
`src` is whichever half sits at a domain **END** (`domain_end_to_strand`, half_a
preferred when both are). Those two agree only when the strand exits from `half_a`.
When it exits from `half_b` the run is drawn **reversed**: every bead lands on a
neighbouring insert's coordinates (~0.6 nm each for a TT — ~2 bp rises) and the
connector cones cross themselves. `forced_ligations` never had the bug: their wrapper
assigns `half_a = 3′ side` by construction.

Fix lives entirely in the renderer (display layer — no topology touched):
`domainEndKeys(design)` + `extraBaseOrderReversed(xo, endKeys)` (pure, mirroring the
backend rule including its tie-break) stamp `simReversed` on each `arcData` at build
time; `simBeadIndex(k, n, reversed)` (self-inverse) is applied at all **three** sites
that map k↔bead: both sim branches in `design_renderer.js` and the `__xb__` scalar
(RMSF) colour lookup — the colours were swapped too. Real regression fixture in
`crossover_connections.test.js` uses the `2hb_2xT` shape (one crossover of each
direction), verified against that run's PSF covalent bonds.

**Slab orientation for simulated inserts** now uses `simSlabQuaternion` — the
helix_renderer basis (`tangential, axis, baseNormal` → long 0.70 axis on the base
normal). It previously fed the base normal into `arcSlabQuaternion`'s **arc-tangent**
slot, leaving the plate 90° off from the real slabs beside it and pinned to the
design's static `avgAx` instead of following the trajectory. `arcSlabQuaternion` is
still correct — and still used — for the un-simulated Bézier arc and by
`overhang_link_arcs.js`, which pass a genuine arc tangent.

Phase 1 (CG beads/slabs, oxDNA display + trajectory) — DONE:
- The oxDNA composite TRAJECTORY already carried `__xb__` keys+positions. The single-
  frame `/display` route now surfaces them too: `read_configuration_full` /
  `configuration_full_from_particles` / `read_configuration_unwrapped` /
  `_relaxed_full_map` gained `include_extra_bases` (default False keeps health/oracle
  clean); the CG `/display` route passes True. `assert_relaxed_geometry_recovered`
  filters `helix_id == "__xb__"`.
- Frontend: `partitionExtraBaseUpdates` (pure, in crossover_connections.js) splits FEM/
  trajectory updates into real vs `__xb__` (key shape `{helix_id:"__xb__",
  bp_index:crossover_id, direction:k}`); `design_renderer.applyFemPositions` routes
  `__xb__` to `setExtraBaseInstanceFromSim` (bead at real pos, slab oriented from a1 —
  through `simBeadIndex`, see the ordering law above),
  marks those arcs sim-driven, and `applyClusterCrossoverUpdate` SKIPS Bézier for them
  (Bézier stays for static design view / revert).
- Verified: pytest (`test_display_route_surfaces_extra_bases`,
  `test_display_readers_surface_extra_bases_on_request`), vitest
  (`crossover_connections.test.js`), and a live Playwright e2e
  (`extra_base_sim_render.spec.js`) that opens `6hb_2xT` and asserts beads move to a
  pushed sim frame then revert to the arc. Note: GET /api/design returns DIFFERENT
  crossover ids than the RENDERED `store.getState().currentDesign` — drive bead lookups
  from the store, not the API. `/api/design/load` alone leaves the welcome screen up;
  open via the library item click to render.

Phase 0 (DONE): `Atom.crossover_id`/`Atom.extra_base_k` (atomistic.py) set ONLY on
extra-base atoms in `_build_extra_base_atoms` (stored helix/bp/direction stay the SOURCE
key, so NAMD/GROMACS topology writers are untouched). Propagated through `merge_models`,
`atomistic_model_from_reference`, `atomistic_to_json`, `AtomisticReferenceAtom`
(models.py).

Phase 2 (DONE): atomistic + surface heavy reps follow the sim. `_frame_atomistic_overrides`
(oxdna_health.py) now returns a 3rd map `xb_pos_override {(crossover_id,k): backbone_site}`
(built from the frame's `__xb__` entries, EXCLUDED from frame3 so deformed_helix_axes
skips them); threaded `build_display_model → build_atomistic_model(xb_pos_override=) →
_build_extra_base_atoms`, where it overrides `origin_pos` per insert. Heavy-rep routes pass
`include_extra_bases=True`. **GOTCHA**: the scipy backbone-bridge minimisation
(`_minimize_{1,2,3}_extra_base`) re-seats the whole insert onto the GEOMETRIC junction arc,
silently discarding the override — so when `xb_pos_override` has the crossover, the
minimisation job is SKIPPED (sim positions are authoritative). Surface follows free (built
from the atoms). `_frame_atomistic_overrides` now returns 3 values — fix any 2-tuple
unpack (test_atomistic_validation did).

Backbone connectors (DONE 2026-06-25): the extra-base beads/slabs rendered but had
NO backbone line threading them — because the two flanking REAL beads sit on different
helices, `helix_renderer` forces their connecting cone to zero radius (`isCrossHelix`),
so inserts floated disconnected. Fix draws arrow cones (helix_renderer style,
`CONN_RADIUS=0.075`) threading `prev_real → eb0 → … → eb_{n-1} → next_real`. New
`xoverExtraConnectors` InstancedMesh built in `crossover_connections.js`
(`setExtraBaseConnectors`/`hideExtraBaseConnectors`, `arcData.connStartIdx`, segCount =
beadCount+1). `design_renderer._syncExtraBaseConnectors()` re-threads them from the LIVE
bead-mesh matrices + `_liveXoverPos` endpoints — mode-agnostic (sim/Bezier/cluster),
single chokepoint called from `flushExtraBaseMeshes` + both xover-visibility fns; color in
`_applyXoverColoring`, LOD-hide in `_applyXoverExtrasLod`, hidden arcs → zero-scale cones.
Pins: `crossover_connections.test.js` (placement/hide). Verified in app on 6hb_2xT via a
throwaway Playwright spec (inner cone midpoint = bead average, end cones bridge to real
endpoints). NOTE: connector color is fixed at build/coloring time, not re-tinted on
selection-highlight (beads have the same limitation).

Connector cones under a SCALAR (flex/RMSF) map (FIXED 2026-07-30): `_applyExtraBaseScalarColors`
recoloured only `_xoverBeadsMesh` + `_xoverSlabsMesh`, so with a flexibility map on, the inserts
went viridis while the `beadCount+1` cones bridging them stayed at the build-time strand colour
(and `_restoreExtraBaseColors` had the mirror hole). Both now cover `_xoverConnMesh`. Colour rule
lives in the pure `extraBaseConnectorScalarColors(arc, lookup)` (`crossover_connections.js`) and
mirrors `helix_renderer`'s bond-cone convention exactly — **a cone takes the colour of the
nucleotide it points AWAY from** (`coneEntries[].fromNuc`): segment 0 from the real endpoint
`nucA` (key `helix:bp:dir`, falling back to `…:0`), segments 1..n from inserts 0..n-1
(`__xb__:<xoId>:<k>`); trailing `nucB` is only ever a segment END so it colours nothing, same as
the last nucleotide of a real strand. Missing key → that cone is left alone. Pins:
4 tests in `crossover_connections.test.js`. Verified in app (6hbx100_1xT + oxDNA job
`012a0fbe2de2`, 60 inserts / 120 cones): 120/120 cones recoloured, 61 distinct colours,
`cone[2a+1] === bead[a]` for 60/60 arcs, and clearScalarColors restored all 120 exactly.

Arc-line removal (DONE 2026-06-25): the thin point-to-point Bezier arc line that
`unfold_view.js` draws for every crossover is REDUNDANT for extra-base crossovers (the
bead+slab+connector cones now show the real backbone), so it's collapsed to zero length.
CRITICAL coupling: the extra-base bead/slab live-updates are driven by the arc loop's
`updateExtraBaseArc()` calls — so you must NOT set `e.hidden=true` (that skips the bead
update and detaches the slabs). Instead: new `e.isExtraBase` flag (set in `_initArcs`
from `xoForArc.extra_bases`; forced-ligation synthetic now carries `extra_bases`) +
`_collapseExtraBaseArcLines()` helper that zeros only the LINE vertices, called at all 3
arc-flush sites (`_updateArcPositions`, `applyFemArcs`, `applyHelixOffsets`) AFTER the
`updateExtraBaseArc` calls. Regular crossover arcs untouched. Verified in app on 6hb_2xT:
24 extra-base arcs collapse (span 0), 6 regular arcs stay visible (span ~2nm), slabs sit
0.45nm (SLAB_OFFSET) from beads after a sim frame. `getArcDebugInfo().arcs[].isExtraBase`
exposes the flag. NOTE: a collapsed arc is also unpickable (same as `e.hidden` arcs) — to
re-edit an extra-base crossover's bases, select via the beads, not the (gone) line.

Phase 3 (DONE): MD CG trajectory. `build_chain_map` (atomistic_to_nadoc.py) emits
`("__xb__", crossover_id, k)` for extra-base P atoms (local `_XB_SENTINEL` constant), making
`p_order` unique; `_build_md_nadoc_ctx` `_p_ref` keys the SAME way (was colliding on the
source tuple) and `rigid_mask` guards `bpi >= 0` with `isinstance(bpi, int)` (extra bases =
flexible, non-rigid). `centroid_offset` skips `__xb__` keys (not in design, no crash). The
md_composite_trajectory `keys`/`frames` now interleave `["__xb__", xo, k]` the frontend
already routes. (Full MD/heavy-rep app exercise needs a real job; backend placement is
pinned in test_oxdna_extra_bases.py.)

**Graphs & Metrics card crash on __xb__ bp_index (fixed 2026-07-04).** The MD "Generate"
button (`md_metric_series` → the card) fed the interleaved `__xb__` positions — whose
`bp_index` is a crossover-id STRING — into two `oxdna_health` helpers that did
`int(p["bp_index"])`: `_filter_to_reference_core` (runs PER FRAME, so it crashed first) and
`base_pairing_spatial_profile` (the unfiltered `mean_positions` path). Both now skip any
entry whose `bp_index` isn't an `int` via the shared `_core_column_key` helper (matches the
`isinstance(bpi, int)` convention above) — the inserts are ssDNA, never a designed dsDNA
core pair, so dropping them is correct. Twist/curvature always used the FILTERED `mean_core`,
which is why only base-pairing appeared to fail. oxDNA's `production_metric_series` is
unaffected (read-back drops `__xb__`). Pins: `test_md_metrics.py`
(`test_md_metric_series_tolerates_extra_base_inserts` — full card path;
`test_filter_to_reference_core_skips_extra_base_inserts`), `test_oxdna_relaxation.py`
(`test_base_pairing_spatial_profile_skips_extra_base_inserts`); all can-go-red (reproduce the
exact `invalid literal for int()` on the crossover uuid).

2026-10-28: **forced-ligation inserts are included too.** Gerling reconstruction
exposed missing TT bases after junctions were classified as forced ligations.
`crossover_extra_base_junctions` now matches each forced ligation's complete,
directed pair of endpoints against an actual consecutive-domain transition.
Same-helix and unequal-BP connections work; reversed polarity/wrong endpoint
does not acquire an insert. Existing crossover ownership logic is unchanged.
All consumers of the canonical walk share the corrected particle order/count.
No placement formula or phase constant changed. Six new regression cases in
`tests/test_oxdna_forced_ligation_inserts.py`; all six pass (three failed before
the fix). Existing extra-base and extension checks:48 passed,6 skipped.
