---
name: project_hinge_autoscaffold
description: "Hinge scaffold router — route ONE scaffold strand through forced-ligation gap-bridges (hinge primitives). Reframes FLs from \"manual anchor to route around\" to \"mandatory bridge to route through\"."
metadata: 
  node_type: memory
  type: project
  originSessionId: 7cfe31c9-8568-42d1-a022-298315c1bd8f
---

# Hinge autoscaffold (backend/core/hinge_router.py) — shipped 2026-06-26

Hinge primitives (`2x2_single`/`2x4_double`/`2x6_triple_hinge_link` in
`workspace/Primitives/`) are two rigid leaves joined across a physical gap by
**forced ligations** (FLs). The FLs are the structural cross-gap *links*, not
one-off manual anchors.

## The reframe (the load-bearing idea)
Historically a forced ligation = "user hand-joined these ends; autoscaffold must
PRESERVE + route AROUND" — every router bailed/skipped when `design.forced_ligations`
was non-empty (`seamed_router` preserved FL strands + skipped the bridged helices →
each leaf fragmented into sub-4-helix components → silently did nothing, 6 strands).
For a hinge that's exactly wrong: the FL is a **mandatory scaffold bridge the strand
must traverse**. New behavior (user decision 2026-06-25): **route THROUGH every FL**
at its exact recorded `(helix, bp)` (preserves the hinge axis). Genuine one-off
manual FLs still fall back to the old preserve pipeline.

## What does NOT work (proven, don't retry)
- **Route each leaf independently + splice at FLs** — provably fragments. Two leaf
  cycles cut at FL points and reconnected through one reciprocal FL pair close a
  small loop through only the inner gap faces, leaving each leaf's bulk as separate
  loops (2x2 → 3 strands). The reference single strand *co-routes*: it weaves across
  the gap at every FL, which only composes if leaf routing + FL positions are designed
  together. (User had picked this "Option A" first; empirical check killed it.)
- **Generic collapse-and-route** (treat gap rows as lattice-adjacent, run seamed) —
  the primitives' ragged hinge-link faces trip the multi-section guard → fragments
  (5 strands) and places 0 gap bridges.
- A generic Hamiltonian path over the FL-augmented graph uses only SOME FL edges →
  the unused FLs become branches. Must force ALL FL edges onto the path.

## The working algorithm (B-graph: preserve FL positions)
`route_hinge(design) -> (Design, SeamedResult) | None`:
1. **Leaves** = connected components of the *lattice* scaffold-adjacency graph
   (`_build_adj`; the gap means leaf-A/leaf-B helices are never lattice neighbours).
2. **Force every FL edge onto one Hamiltonian helix path** by CONTRACTING each FL
   helix-pair into a super-node, finding a plain backtracking Hamiltonian path over
   the contracted graph, then expanding each super-node oriented to its external
   neighbours. Guarantees each FL is a path edge.
3. **Orient** the global 5'→3' so every FL edge is traversed three_prime-helix-first
   (try path, else reverse; else None).
4. **Parity raster**: one domain per helix over its coverage section; direction =
   helix parity (`_is_forward`), which matches each FL's recorded endpoint directions
   AND alternates cleanly (lattice + FL neighbours always have opposite parity). Each
   consecutive pair turns at a shared face: FL edge → keep the ForcedLigation at its
   recorded bp (no crossover); lattice edge → geometric u-turn crossover (`_turn_bp`
   searches the coverage overlap nearest the hi/lo face), process_id
   `auto_scaffold_seamed:hinge`.
5. Extend helix geometry to the final domains; replace active scaffold strands with
   the one routed strand.

Returns **None** (→ caller falls back to classic preserve pipeline) when: no FLs,
a helix has >1 coverage section, an FL is intra-leaf, FLs aren't a clean pairing
(a helix in >1 FL edge), no Hamiltonian path, or FL polarity can't be made consistent.

## Dispatch
`seamed_router.auto_scaffold_seamed` (the `/design/auto-scaffold-seamed` entry):
`if design.forced_ligations: try route_hinge first; None → fall through`. The
section-router dispatch stays gated on NO forced ligations. **Seamless entry
(`auto_scaffold_seamless`) NOT yet wired** — only the seamed path routes hinges.

## Validation / oracle
`Hinge_route_test.nadoc` (workspace) is the proven target: 2x6 hinge, 1 scaffold
strand, 41 domains, 6 FLs all traversed. Tests `tests/test_hinge_router.py` (parametrized
over all 3 primitives, skip-if-fixture-missing): 1 strand, full coverage, all FLs
preserved-verbatim + traversed, every domain junction backed by FL/crossover,
`validate_design` passes, dispatch via `auto_scaffold_seamed`, intra-leaf-FL + no-FL
fallback. 20 tests green.

## NOT verified live in app
Backend tested + validator-clean, but the live in-app Auto-scaffold (seamed) click on
a placed hinge primitive + visual single-strand trace was NOT hand-checked this session
(headless localhost unreachable under WSL). The reciprocal-pair assumption holds for all
3 shipped primitives; a hinge with an ODD/unpaired gap link would fall back (deferred —
would need a different join). See [[project_primitive_library]] (hinge primitives) and
[[project_forced_ligation]] (the original manual-anchor feature this reframes).
