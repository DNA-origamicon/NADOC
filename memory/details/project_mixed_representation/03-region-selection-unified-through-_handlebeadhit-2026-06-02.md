# Region selection unified through _handleBeadHit (2026-06-02) — supporting detail

[Topic head](../../project_mixed_representation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Region selection unified through _handleBeadHit (2026-06-02)

> **Terminology note (added 2026-07-30, `/audit-plan`).** This section and the two below it are
> dated work-log entries written *before* the 2026-06-06 selection rewrite. Every `_autoDrill*`,
> `_autoDrillBead`, `_autoDrillCylinder`, `_drillLock` and "manual filters / Tab lock" mentioned
> below was **physically deleted** on 2026-06-06 — zero hits in `frontend/` today. What survives is
> `_handleBeadHit` (`selection_manager.js:2253`), `_repEntryFor` (`:2261`) and the
> `columnRepAt` rep-cap; the drill *ladder* they fed is now the single-`selectionLevel` model in
> `scene/selection_level.js`. Read `.claude/rules/selection.md` for current behavior — the
> rep-aware **cap** semantics described here still hold, only the mechanism name changed.

Goal: cyl/atomistic/surface region picks (incl. linkers/flexible) follow drill/manual/tab rules.
- Extracted `_handleBeadHit(hitEntry, backboneEntries, coneEntries, prevOverhangId)` from the inline
  pointerup bead block — does auto-drill (with `_drillLock`/Tab + rep-aware cap via columnRepAt) when
  `_autoDrill()`, else the MANUAL selectableTypes path (overhang/domain/strand/bead). Replaced
  `_autoDrillCylinder` (removed). Added `_repEntryFor(backboneEntries, strandId, {domainIndex, rep})`.
- All region picks now route through `_handleBeadHit`: atom hit → backbone entry by (helix,bp,dir);
  surface hit → a 'surface'-column repEntry of the strand; cylinder hit → a domain repEntry. So
  atom/surface/cylinder selection now respects auto-drill + manual filters + Tab lock uniformly.
- COVERAGE: works for elements that HAVE beads/atoms (standard strands/domains, regular linker
  strands). LIMITATIONS (arc-rendered geometry has no backbone beads): flexible-segment and
  ss-linker-BRIDGE nucs are skipped from backboneEntries (drawn as arcs) → atom/surface pick on them
  FALLS BACK to strand select (no nucleotide/domain); their per-region cylinder doesn't render
  (linker cylinders are global-LOD controlled, not columnRep) and isn't raycast. Follow-ups: (1)
  control iLinkerBinding/BridgeCylinders visibility from columnRep + add them to the cyl raycast +
  domain mapping; (2) arc-aware picking for flexible/ss-linker so atoms map to the arc nucs.
- Verified (Playwright, removed): selectStrand→strand, Tab lock cluster→Escape→null, vdw overlay
  renders, no console errors (refactor preserved core selection + drill-lock + overlays).
  NOT verified headlessly: real-click manual-mode routing of atom/cyl/surface picks (needs raycast).

## Rep menu: flyout submenu + non-standard elements (2026-06-02)

- The representation options are now ONE "Representation ▸" item with a hover/click FLYOUT
  submenu (Full detail/Cylinders/Surface/VDW/Ball & Stick/Reset). Extracted into a shared
  `createRepresentationMenuItem({apply, dismiss})` in representation_overrides.js (flyout is a
  DOM child of the item so a parent menu's `menu.contains(target)` outside-click dismissal still
  treats it as inside). selection_manager `_appendRepresentationMenu` now just builds the apply
  closure + appends the shared item.
- Coverage of non-standard elements:
  - Linkers: ALREADY covered — linker strands route through `_showColorMenu` which appends the
    rep menu (strandsToSegments).
  - Overhangs: added to `_showOverhangOrientMenu` (main.js) via the shared item +
    `overhangsToSegments(design, overhangIds)` (the overhang's own ss domains → segments).
  - Flexible regions: added to `_showFlexibleSegmentMenu` scoped to the clicked nuc's domain.
  - NOT added: `_showFlexibleConnectionMenu` (right-click on the arc/connection — no clean column
    mapping; the per-segment menu covers the region).
- Verified (Playwright, removed): overhangsToSegments returns only the overhang domain;
  createRepresentationMenuItem builds 6 options, hover opens flyout, click applies+dismisses.
  NOT verified headlessly: the menus appearing on real right-click of overhang/flexible/linker.
- CAVEAT: flexible nucs render as ssDNA arcs (overhang_link_arcs), separate from the columnRep
  bead-hide — a flexible region set to a rep may show the arc AND the new rep; flag if it bites.

## Surface + atomistic as per-region reps (2026-06-02)

Plan: `~/.claude/plans/ok-now-we-would-delegated-galaxy.md`. Extends mixed rep to surface / vdw /
ballstick overrides (base = CG global, focal regions = overlays). Picking works on the actual
geometry: atom click → drill to nucleotide; surface click → cluster→strand.
- Model: `RepresentationOverride.representation` Literal widened to add surface/vdw/ballstick.
  `resolveRepOverrides` passes the value through; helix_renderer `beadVis`/`cylVis` ALREADY hide
  both beads+cylinders for any non-full/non-cylinders column → CG auto-hides (no renderer change).
  `repColumnsByRep(design)` → {vdw,ballstick,surface: Set<"helix:bp">}.
- Overlays (main.js): two `initAtomisticRenderer(scene)` instances (`regionVdwRenderer` /
  `regionBallstickRenderer`) — atomistic renderer holds ONE mode each. `_filterAtomData(colSet)`
  filters the cached `/design/atomistic` atoms by `${helix_id}:${bp_index}`; ballstick bonds are
  serial-pairs so just filter to surviving serials (NO renumber). ALWAYS dispose()-then-update()
  (update doesn't pre-clear). `regionSurfaceRenderer = initSurfaceRenderer(scene)` named
  'dna-surface-region'; backend `POST /design/surface/region` filters `build_atomistic_model`
  atoms to the segments → `compute_surface`. Surface coordinator is DEBOUNCED 400ms + signature-
  cached (compute is slow). 3 subs: override/rebuild change → re-apply (surface forced on geo
  change), selection → highlight. `_ensureAtomData()` shared with global atomistic mode.
- Picking (selection_manager): exclude beads/cones whose `columnRepAt` ∈ {vdw,ballstick,surface}
  (hidden CG keeps full-scale matrices → would win). Atom branch raycasts both overlays
  (`raycastPick`), maps atom→backbone entry → `_autoDrillBead` (cap full→nucleotide). Surface
  branch raycasts the 'dna-surface-region' mesh → `surfaceRenderer.strandIdAt(face)` → cluster→
  strand. `_autoDrillBead` cap now by `columnRepAt`: cylinders→domain, surface→strand,
  full/vdw/ballstick→nucleotide. `columnRepAt`/`isColumnAtomistic`/`isColumnSurface` on
  helix_renderer + design_renderer. Lazy getters `getRegion{Vdw,Ballstick,Surface}Renderer` in
  initSelectionManager opts.
- Menu: Surface / VDW / Ball & Stick items in `_appendRepresentationMenu` (single/multi domain/
  strand/cluster). Master-reset (global rep change) clears overrides → subs dispose overlays.
- Verified: backend 13 override+surface-region tests; full suite 1728 pass (1 pre-existing flaky
  seam fail). Playwright (removed): vdw+ballstick coexist with atoms, 164 CG beads hidden; surface
  region mesh 5715 verts; clear → all overlays disposed + CG restored. No console errors.
- NOT verified headlessly (real raycast clicks): atom→nucleotide drill, surface→strand pick, menu
  DOM, highlight. Need in-app. LIMITATION: region atoms/surface from build_atomistic_model →
  don't follow deform/unfold/mrDNA live positions (same as global atomistic). `__NADOC_DBG__`
  exposes region{Vdw,Ballstick,Surface}Renderer.

## Per-domain cylinder conversion + cylinder-aware selection (2026-06-02)

Plan: `~/.claude/plans/ok-now-we-would-delegated-galaxy.md`. Frontend-only (no backend change;
segments model already supports a single domain). Shipped:
- A) Convert INDIVIDUAL DOMAINS to/from cylinder. `domainsToSegments(design, [{strandId,domainIndex}])`
  in representation_overrides.js. `_appendRepresentationMenu` gained `domainRefs`; single-domain
  right-click threads `_domainRef` into `_showColorMenu` (scopes the Representation submenu to the
  domain); multi-domain lasso right-click → new `_showMultiDomainMenu`.
- B) Cylinder-aware selection + ADDITIVE GLOW (user chose glow over recolor; drill caps at domain):
  - helix_renderer: per-domain cylinder glow = two additive InstancedMeshes `helixCylGlow`/
    `overhangCylGlow` (GEO_UNIT_CYL/GEO_HALF_CYL, inflated ×1.28, renderOrder 1) mirroring the live
    solid-cylinder matrices via `_writeCylGlow`/`_refreshCylGlow` (called at every cyl-matrix
    recompute). `glowCylinderDomains(refs)` filters to ACTUALLY cylinder-rendered domains via
    `_isDomainCyl`. Added `isColumnCylinder(h,bp)` + `isDomainCylinder(s,di)` reusing the effCol
    predicate. Exposed via design_renderer passthrough.
  - selection_manager: `_setSelectionGlow` now SPLITS highlighted entries — bead-rendered domains
    get sphere glow, cylinder-rendered domains get the cylinder glow (no double halo). This one
    central change makes strand/domain/cluster/bead/multi-domain highlights all cylinder-aware.
    `_autoDrillCylinder` (global cyl LOD cylinder hit) drills cluster→strand→domain (no bead),
    honoring `_drillLock`; replaces the old one-shot 'cylinder' strand select; also raycasts the
    overhang cylinder mesh. `_autoDrillBead` caps `_drillSeq` at domain when
    `isColumnCylinder(hit nuc)` (mixed view hits the hidden full-scale bead under a cylinder).
    Post-rebuild subscription now re-applies single `domain`/`cluster` modes (was: fell to else →
    cleared selection, losing glow after a conversion rebuild).
- Verified Playwright (removed): domainsToSegments correct; cylinders-override on domain 0 marks
  exactly its 35 columns; selecting the strand glows exactly 1 cyl-rendered domain (override) / 0
  (full, no override) / all domains (global cyl LOD). 1722 backend pass (frontend-only).
- NOT verified headlessly (need real raycast clicks): the click-drill itself (cylinder-hit
  cluster→strand→domain; mixed-view cap at domain). Needs in-app confirmation.
- LIMITATION: curved/deformed cylinders (`_curvedDomainCylData` lacks domainIndex) → domain glow +
  cylinder-hit drill are straight+overhang only for now.

## PIVOT to column-based resolution (2026-06-02) — fixes two bugs

Symptoms reported: (1) strand-level overrides stopped working after applying crossovers/breaks;
(2) a staple→cylinders override drew the duplex cylinder over the scaffold's still-FULL beads.

Root causes: overrides stored `strand_ids` (reassigned by break/crossover → stale), and a cylinder
is built per STAPLE domain representing the whole duplex (scaffold domains are skipped to avoid
z-fighting — [helix_renderer.js] ~1176), so a staple override never touched the scaffold's beads.

Fix = both share one model change: resolve by DUPLEX COLUMN (helix_id + bp), covering BOTH strands,
stored as position ranges (not strand ids):
- Backend: `RepresentationSegment {helix_id, bp_start, bp_end}` + `RepresentationOverride.segments`
  (replaced strand_ids/cluster_ids). Endpoint validates helix ids (404) + non-empty segments (422).
  8 tests green; full suite 1722 pass (2 pre-existing seam failures only).
- Resolution `resolveRepOverrides(design) -> {columnRep: Map<"helixId:bp", rep>}` (no geometry needed).
- helix_renderer `applyRepOverrides(columnRep)`: beadVis per column (hides staple AND scaffold beads
  at a 'cylinders' column); a domain cylinder shows only if EVERY column it spans is 'cylinders'
  (region boundary cutting a domain falls back to beads, no overdraw).
- UI: `strandsToSegments` / `clustersToSegments` compute the column footprint from the selection;
  `editOverridesForSegments(overrides, segments, rep|null)` does per-helix bp set algebra (add/remove,
  compress to ranges, merge same-rep, drop empties). Right-click menu now stores segments.
- Verified via Playwright (removed): cylinders override on ONE staple hid 82 beads (staple nt=42 →
  scaffold partners hidden too); after nicking that staple (14→15 strands, cyl 1→2) the override's
  segments were unchanged and both strands stayed hidden. No console errors.
- NOTE: position-based = does NOT auto-extend if a strand is later lengthened (baked at creation);
  intended tradeoff for break/crossover stability. Selecting the scaffold → whole-structure region.
