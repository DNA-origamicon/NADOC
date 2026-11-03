# Unified scaffold context menu (2026-07-01) — supporting detail

[Topic head](../../project_ssdna_ball_joints.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Unified scaffold context menu (2026-07-01)

The three previously-conflicting scaffold right-click menus were collapsed into ONE
standard-format menu. Before: a scaffold strand gave a *different* menu per pixel — the
raw-HTML `#scaffold-split-ctx-menu` (Nick/Assign-seq/Delete) on a terminus cone, the
styled `_showFlexibleSegmentMenu` on an unpaired bead, and `_showLoopSkipMenu` on a paired
bead in bead-mode. Now **`_showScaffoldMenu(x,y,{strandId,nuc},cbs)`** in
`selection_manager.js` fires for ANY right-click that resolves to a scaffold strand (cone
`fromNuc` OR frontmost bead — both are full nucleotides, same shape) via new
`_resolveScaffoldCtx(design,hitBead,hitCone,beadFrontmost)`. Sections: Nick · Assign
sequence… · flexible (mark/unmark + relax sub-items + clear) · loop/skip · Representation ·
Delete strand. Dispatch intercept sits right after the cluster branch (before the
unpaired-bead flexible branch + bead-mode loop/skip). Overhang tips on the scaffold still
divert to the overhang menu first.
- User decisions: flexible "Mark" **always shown, greyed** on paired (dsDNA) regions
  (`disabled:!nuc.is_unpaired` + tooltip); relax kept as sub-items (only when marked);
  loop/skip kept as a 6th section.
- `_showFlexibleSegmentMenu` / `_showFlexibleConnectionMenu` **still live** — the former for
  NON-scaffold unpaired beads (ssDNA staple runs), the latter for the bowed flexible ARC.
- main.js: `onScaffoldRightClick` opt REPLACED by `onScaffoldAssignSequence(strandId)` →
  `_scaffoldModal.openModal`. Old HTML menu + `_showScaffoldSplitCtx`/`_hideScaffoldSplitCtx`
  + 3 button listeners DELETED; `#scaffold-split-ctx-menu` removed from index.html. `onNick`
  now also calls `_clearScaffoldChecks()` (scaffold Nick used to clear the scaffold-ends
  routing indicator; general onNick didn't).
- Verified: build + 1921 vitest pass; smoke render+teardown gates green. **NOT eyeballed in
  browser** — the 3D right-click menu is a WebGL-canvas gesture (LESSONS H7). MV pending.

## oxDNA seed + display of flexible runs (2026-07-02)

Two fixes so the flexible-region representation and the oxDNA sim AGREE (the whole
point of marking ssDNA flexible was to cut relaxation time on conformationally-naïve
segments). Before: the oxDNA writer never consulted `flexible_connections` (`grep
flexible backend/physics/` = nothing) — a marked run was seeded as a rigid B-DNA
half-helix rooted on whichever cluster owns its helix (jutting out of one anchor,
ignoring the other), and the display arc kept floating over the sim.

- **Fix #1 — backend contour-length arc SEED** (`oxdna_interface.py`). New pass 3 in
  `resolved_nuc_map` (after the extra-base pass, unconditional — same philosophy as
  the extra-base chord interp): `_apply_flexible_segment_arc(design, resolved_map)`
  re-seats each connection's `segment_bead_keys` onto a contour-length circular arc
  between the two ALREADY-POSED anchors (anchors are posed because the seed geometry
  = `_geometry_for_design` = deformed+clustered snapshot). Bond spacing ≈
  contour/(n+1) ≈ ssDNA rise → FENE-safe, near-relaxed start. Helpers:
  `_flexible_arc_points` (port of `flexible_arcs.js _arcPoints` BUT rewritten to a
  direct ψ∈[-θ,+θ] parametrization — the JS `acos`-sweep silently COLLAPSES slack
  arcs that exceed 180°; the JS has this latent bug, harmless for its visual),
  `_perp_bow` (deterministic ⟂-chord bow; direction is physically irrelevant for a
  seed, so NO obstacle-repulsion like the frontend), `flexible_segment_geo_keys`
  (FlexibleAnchor {strand,domain,bp,dir} → oxDNA geo key (helix,bp,dir)).
  nuc_conf_line negates the stored tangent for REVERSE beads, so a3 is stored
  pre-flipped to track the arc tangent either way. Physical-layer only (topology
  untouched — pinned). Tests: `tests/test_oxdna_flexible_seed.py` (6): arc taut→lerp
  / slack→even FENE-safe bonds, geo-key resolve, resolved-map re-seat (beads moved,
  bonds 0.2–0.75 nm, within contour of both anchors, unit ⟂ a1/a3), read-only guard,
  no-connections identity.
- **Fix #2 — display beads follow the oxDNA/MD frame** (was: stale geometric arc).
  Flexible run beads are excluded from the rigid mesh, so `applyFemPositions` never
  moved them. `flexible_arcs.js` gains `applySimPositions(updates|null)`: stores a
  `"helix:bp:dir"→{pos,a1}` map; `_render` then draws each run at its SIMULATED
  positions (tube+beads+slabs, slab oriented from the sim a1 ⟂ tangent), anchors from
  the sim-repositioned rigid mesh; missing bead → per-connection fallback to the
  geometric arc; null → revert. `oxdna_display.js` routes ALL 7 `applyFemPositions`
  sites through one `_applyFem(updates)` chokepoint that also calls a new `onFrame`
  dep (null on stopAndRestore). `main.js` wires `onFrame: u =>
  flexibleArcs.applySimPositions(u)` into BOTH `initOxdnaDisplay` calls (oxdnaDisplay
  + mdViz) — thin factory-dep wiring, main.js LOC +~6 (pure wiring, no cohesive
  block). Tests: `flexible_arcs.test.js` (4), `oxdna_display.test.js` (+1 onFrame).
  **NOT hand-verified in app** (needs a flexible design + a real GPU relax) →
  `manual_validation_debt.md` **MV-FLEXSIM**.

Verified: backend `just test` 3639 passed / 0 failed; frontend vitest 1926 passed;
build clean. Lint: 14 pre-existing ruff errors in untouched files (no_bulk_reformat),
none in changed files.
