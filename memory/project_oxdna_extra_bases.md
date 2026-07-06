# Crossover extra bases → oxDNA (single-stranded inserts)

`Crossover.extra_bases` (e.g. "TT" — single-stranded thymines that relieve junction
strain) are now materialized as real ssDNA nucleotides in the oxDNA topology +
configuration. Before this work they reached only the atomistic/GROMACS path
(`atomistic.py` `_build_extra_base_atoms`); the oxDNA writer ignored them, so a CG
relaxation of a design with extra bases was byte-identical to one without.

## What it does

All wiring is in `backend/physics/oxdna_interface.py`:

- `_walk_strand_nucleotides(design)` — the single source of truth for the
  strand→domain→bp nucleotide walk, shared by `_strand_nucleotide_order`,
  `topology_rows`, `count_undefined_bases`, `_strand_nucleotide_provenance`. Yields a
  `_NucStep` per emitted nucleotide INCLUDING extra-base inserts. Centralizing this
  was necessary because those consumers + the geometry resolver must agree on the
  particle order or anchors/positions silently shift.
- `crossover_extra_base_junctions(design)` — mirrors the atomistic `extra_base_xover_src`
  rule: an extra-base crossover inserts on the **owning strand** at the domain→domain
  transition (`prev.helix_id != next.helix_id and prev.end_bp == next.start_bp`).
  Keyed strand-scoped `(strand_id, prev_domain_index)`. Crossover-only (forced
  ligations out of scope). Base identity comes from the `extra_bases` chars, NOT from
  `strand.sequence` (which excludes them — so inserts do not consume `seq_idx`).
  **Owning-strand selection (reciprocal-crossover bug, fixed 2026-06-25):** register
  each crossover at ONLY its owning (src) half — the half sitting at a domain 3′ end,
  picked exactly like atomistic's `domain_end_to_strand` (half_a preferred when both
  halves are domain ends). Registering BOTH halves double-fired the strand walk on a
  *reciprocal* crossover (two strands swap helices at the SAME junction position →
  both strands match), so two strands emitted the SAME `(_XB_SENTINEL, xo_id, k)`
  insert key. That key collision corrupts `topology_rows`' `index_map`/threading:
  duplicate physical rows collapse to one index, the first occurrence is orphaned
  (`-1/-1` bonds, wrong strand id from last-write-wins), and the surviving n3/n5
  point cross-strand → oxDNA aborts at init with `Topology inconsistency detected:
  particle X's n3 points to Y, but that particle's n5 does not point back`.
  VoltronCore (TT on all 577 crossovers) had 3 reciprocal cases; 6hb/18hb had none
  (why earlier validation missed it). Pin:
  `test_reciprocal_crossover_owns_insert_on_one_strand` (can-go-red) +
  `test_all_crossovers_insert_keys_unique_and_topology_consistent`.
- Insert key = `("__xb__", crossover_id, k)` (`_XB_SENTINEL`), threaded in-chain so
  n3/n5 connect `prev_real → eb0 → … → next_real` automatically.
- `_resolve_extra_base_geometry` — position = lerp along the chord between the two
  flanking real nucleotides at `t=(k+1)/(n+1)`; a3 = chord (5′→3′), a1 ⟂ a3. Even
  spacing keeps backbone bonds ≈ chord/(n+1) (~0.66 nm), inside the FENE range.

Read-back (`read_configuration`, `read_configuration_full`,
`configuration_full_from_particles`) DROPS `__xb__` keys: inserts occupy a particle
slot (so real-nucleotide indices stay aligned) but are absent from the design-keyed
position map, so the CG `/display` route and `assert_relaxed_geometry_recovered` stay
keyed to real nucleotides. v1 limitation: extra bases are simulated but not rendered
in the relaxed CG view.

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

## Production instability on floppy designs → auto dt-halving recovery (2026-06-25)

Putting extra bases at EVERY crossover (e.g. VoltronCore: "TT" on all 577) globally
softens the structure — each crossover becomes a 2-nt ssDNA gap instead of a rigid
junction. Such a design can relax fine (healthy 93% bp) yet go numerically unstable
LATE in production: it sampled stably for ~24M/50M steps, then a region nucleated
melting (potential energy climbed −1.388 → −1.26 while temperature held), and a single
scaffold particle's coordinates exploded to ~1e17. oxDNA aborts: "A cell contains more
than _max_n_per_cell (114) particles … particles with very large coordinates …".
Root cause = the production timestep `dt=0.005` (`build_production_stage` /
`build_field_stage` / `build_run_stage` in oxdna_protocol.py; relax stages use 0.002/
0.003) is too aggressive for a large floppy structure under mixed-precision CUDA.

Fix (oxdna_runner.py `run_job` crash handler): on an unbiased MD stage (`kind` in
`_DT_HALVE_KINDS` = production/field/run) crashing with rc≠0 AND a blow-up signature in
the log (`_log_indicates_explosion`: `_max_n_per_cell` / "very large coordinates" /
`nan`), the runner re-runs THAT stage from the clean relaxed seed at HALF the dt
(`_halve_dt_and_restart`: `replace(spec, dt=dt/2)` + `_reset_stage_outputs` so
`_starting_conf` falls back to the relaxed conf, NOT the exploded checkpoint), up to
`max_production_retries` (default 2 → 0.005→0.0025→0.00125). Keeps the fast dt the
default; only floppy/large designs pay the finer timestep. Takes precedence over the
relax-escalation branch (relax was healthy — wrong lever). Exhausted budget → a
plain-language failure telling the user the design is too floppy/strained (relax longer
or use fewer/shorter extra bases). Job model gained `production_retries` /
`max_production_retries` (oxdna_job.py, with `load` setdefaults). Pins in
test_oxdna_relaxation.py: `_log_indicates_explosion` (blow-up vs setup error vs clean),
`_halve_dt_and_restart` transform, field roundtrip, and an e2e `run_job` explode-then-
recover with a mock binary. NOTE: halving dt at fixed step count means the recovered
run samples LESS simulated time; a future improvement could resume from the last GOOD
trajectory frame instead of restarting, and/or double-precision as a final fallback.

## Validation

- `tests/test_oxdna_extra_bases.py` — fast pins: order/topology grows by N, bases on
  the owning strand, n3/n5 thread in-chain, config bond lengths FENE-safe + orthonormal
  frames, read-back drops inserts + off-by-N alignment guard, the phantom-bond pin, and
  the `assert_extra_bases_in_oxdna` harness oracle (can-go-red).
- `tests/test_oxdna_extra_base_production.py` — real CUDA engine, `@pytest.mark.slow`,
  opt-in `NADOC_RUN_OXDNA_SLOW=1`. Parametrized over design (6hb ~1058 nt / 18hb
  ~3210 nt, both seamless-autoscaffolded + autostapled + sequenced) × mode (precise:
  "TT" at one crossover; bulk: "T" at every crossover — 53 on 6hb, 185 on 18hb), then
  relax + 5M-step production at code defaults. ALL FOUR reach `completed` with geometry
  recovered and the duplex re-annealed (retention ≥ 0.85): 6hb ~5 min, 18hb ~7 min each
  on the RTX 3080 Ti. So the wiring is design-agnostic, not 6hb-specific.

Race fix (found via 18hb): `wait_for_terminal` returns the moment the on-disk job is
terminal, but the runner thread writes that status JUST BEFORE it deregisters from the
in-memory `_RUNNING` set — so a programmatic relax→`append_production`/`append_field`
chain could hit the route's `is_running` guard and 400 ("Production requires a completed
relaxation job"). Fixed by having `wait_for_terminal` also wait out the teardown window
(bounded by its timeout) before returning. Benefits all headless automation, not just
the test.

Three-Layer Law: read-only of topology metadata, physical-layer file output only — no
strand-graph mutation. See also [[project_oxdna_benchmarks]] and
[[project_oxpy_binding_patch]].

## Rendering extra bases at REAL simulated positions (Phase 1 done)

Extra-base beads/slabs ALWAYS render (built by `crossover_connections.js`
`buildCrossoverConnections`, present in every mode as children of `_helixCtrl.root`),
but were positioned by a geometric **Bézier arc** between the crossover endpoints
(`updateExtraBaseInstances`, re-interpolated each frame via
`design_renderer.applyClusterCrossoverUpdate`). They never reflected the real ssDNA
conformation. `_xoverArcDataMap.get(crossover_id) → {beadStartIdx, beadCount}` maps
`(crossover_id, k)` → bead instance `beadStartIdx + k`.

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
  `__xb__` to `setExtraBaseInstanceFromSim` (bead at real pos, slab oriented from a1),
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
