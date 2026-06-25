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

Phase 3 (DONE): MD CG trajectory. `build_chain_map` (atomistic_to_nadoc.py) emits
`("__xb__", crossover_id, k)` for extra-base P atoms (local `_XB_SENTINEL` constant), making
`p_order` unique; `_build_md_nadoc_ctx` `_p_ref` keys the SAME way (was colliding on the
source tuple) and `rigid_mask` guards `bpi >= 0` with `isinstance(bpi, int)` (extra bases =
flexible, non-rigid). `centroid_offset` skips `__xb__` keys (not in design, no crash). The
md_composite_trajectory `keys`/`frames` now interleave `["__xb__", xo, k]` the frontend
already routes. (Full MD/heavy-rep app exercise needs a real job; backend placement is
pinned in test_oxdna_extra_bases.py.)
