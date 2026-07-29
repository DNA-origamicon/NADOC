# Mixed Representation — per-region representation for a single structure

Status: **SHIPPED — PATH A COMPLETE** (probe-verified 2026-07-28). **Rank: P1** — the core
feature is live end-to-end and in daily use; what's left is a small set of coverage holes
(deformed cylinders, impostors) plus one suspected photo-export bug, all of which bite the
publication-figure use case this feature exists for.

The 2026-06-02 "PATH A IN PROGRESS / UI + photo-mode pending" banner was **stale**. Codebase
probe (2026-07-28) found every backend + frontend + UI anchor EXISTS and WIRED: model +
routes + 13 backend tests, resolution + renderer alpha path, the right-click Representation
menu, the global-rep master reset, and the region atom/surface overlays. See
`plan_audit_ledger.md` for the audit row. Open work is the `## Open items` list below —
everything above it in this file is history.

**CODE LOCATIONS (refreshed 2026-07-28 — the older paths below are pre-carve-up):**

| Thing | Now lives in |
|---|---|
| `RepresentationOverride` / `RepresentationSegment`, `Design.representation_overrides` | `backend/core/models.py:1054`, `:1064`, `:2275` |
| `PUT`/`DELETE /design/representation-overrides` | `backend/api/routes_display_metadata.py:117` / `:142` (registered `backend/api/main.py:55`) — **no longer `crud.py`** |
| `POST /design/surface/region` | `backend/api/routes_display_geometry.py:301` |
| Pure resolution + segment helpers | `frontend/src/scene/representation_overrides.js` — `resolveRepOverrides`, `repColumnsByRep`, `strandsToSegments`/`domainsToSegments`/`overhangsToSegments`/`clustersToSegments`, `editOverridesForSegments`, `createRepresentationMenuItem` |
| Renderer alpha path | `helix_renderer.js` `_installInstanceAlpha:238`, `_ensureRepAlpha:2469`, `_applyRepOverrides:2493`, public `applyRepOverrides:2588` |
| Rebuild + no-rebuild wiring | `design_renderer.js` `_applyRepresentationOverrides:387` (calls `setDetailLevel` first — bug-A fix intact), `getDetailLevel:1167`, `columnRepAt/isColumnAtomistic/isColumnSurface:1185-1187` |
| Right-click menu | `selection_manager.js` `_appendRepresentationMenu:411` (6 call sites) |
| F1–F7 + global-rep master reset | `frontend/src/ui/representation_switcher.js:256` / `:286` — **no longer `main.js`** |
| Region atom/surface overlays | `frontend/src/scene/atom_surface_display.js` (`initAtomSurfaceDisplay`, called `main.js:2442`); segment extraction moved to `surfaceSegments()` in `design_queries.js` |
| Photo export | `frontend/src/scene/photo_mode.js` — **no longer `main.js ~12886`** |

**Stale claims corrected 2026-07-28:** `editOverridesForStrands`/`editOverridesForClusters`
(named as shipped in the 06-02 Progress block) **do not exist** — the column pivot replaced them
with `*ToSegments` + `editOverridesForSegments`. Backend tests are 13, not 9.

## BUG: global-cylinders + region override (2026-06-02) — fixed

Two linked bugs when the GLOBAL rep was cylinders (F2) and a region was overridden to 'full':
- (A) the whole structure reverted to full. Cause: saving an override returns no geometry →
  client `_syncFromDesignResponse` calls `getGeometry()` → a full REBUILD. `_rebuild` builds helix
  meshes at FULL (level 0), and `_lastDetailLevel` is only reset to -1 on NEW-DESIGN load (main.js
  ~4473), so the tick's `if (targetLevel !== _lastDetailLevel)` never re-applies cylinders. So
  `applyRepOverrides` read `baseCyl = (_detailLevel===2)` as FALSE on the fresh helixCtrl → every
  non-overridden column resolved to full. (Also a latent "global cylinders lost on ANY edit" bug.)
  FIX: `design_renderer._applyRepresentationOverrides` now calls `_helixCtrl.setDetailLevel(_detailLevel)`
  first to re-sync the global LOD before resolving overrides. No-op when already in sync.
- (B) pressing F2 then cycled coloring instead of reverting to cylinders. Cause: the F-key handler
  routed an already-`is-checked` rep to `_cycleColoringForRepr`. FIX (main.js F1–F7 handler): when
  `currentDesign.representation_overrides.length > 0`, skip the coloring-cycle and `btn.click()`
  instead (which clears overrides + re-applies the global rep) — the displayed structure diverges
  from the nominal global rep while overrides are active, so the press should reset it.
- Verified via Playwright (removed): global cylinders → staple→full override shows only 82/490 beads
  (region, both strands) with 9/10 cylinders still shown; real F2 keypress → overrides=0, beads hidden,
  cylinders shown. No console errors. Frontend-only change (backend untouched, 1722 still green).

## Overhang + bridge as independent per-region reps (2026-06-02)

- Overhang domains: ALREADY render per-region — overhang cylinders go through `cylVis(_overhangCylData)`
  and surface/atom through the overlays; `overhangsToSegments` scopes to the overhang's ss domain.
- ds-linker BRIDGE cylinder now responds to columnRep (was global-LOD-visibility only):
  `_bridgeCylData[i]` gained `{bp_lo, bp_hi, cylIdx}`; `_ensureRepAlpha` installs instanceAlpha on
  `iLinkerBridgeCylinders`; `_applyRepOverrides` shows the bridge cylinder where ALL its
  bridge-helix columns resolve to 'cylinders' (`bridgeVis`, keyed on `br.bridgeHelixId`), and
  restores alpha=1 when inactive. So a per-region bridge→cylinders now renders the bridge tube.
- Targeting the bridge INDEPENDENTLY: a bridge-cylinder click now selects via a bead ON the bridge
  helix (`backboneEntries.find(strand_id===br.strandId && helix_id===br.bridgeHelixId)`) → drills the
  BRIDGE domain (not the binding domains) → right-click rep scopes to just the bridge.
- Verified: no regression (cylinders override renders, beads hide, selection intact, bridge+overhang
  meshes present, bridge alpha-install no crash). NOT headlessly verified: actual bridge per-region
  RENDER + bridge-domain pick (needs a ds-linker design — overhang examples don't load: old
  crossover format missing half_a/half_b). Overhang per-region render couldn't be e2e'd for the same
  reason; reasoned correct via cylVis/overlay reuse.
- REMAINING gap: linker BINDING cylinders (iLinkerBindingCylinders) still not column-driven (only
  the bridge was requested — "dsDNA only for now").

## Linker bridge cylinder selectable (2026-06-02)

- ds-linker BRIDGE cylinder (`iLinkerBridgeCylinders`, full cylinder per `__lnk__` helix) was not
  in the selection raycast → unclickable in global cylinder LOD. Fix: helix_renderer stores
  `_bridgeCylData[idx] = {bridgeHelixId, strandId: bridgeHelixId+'__a'}` during the bridge build;
  exposes `getLinkerBridgeCylinderMesh()` + `getLinkerBridgeCylinderAt(id)` (+ design_renderer
  passthrough). selection_manager cyl-hit branch now raycasts the bridge mesh too; on a bridge hit
  → linker strand id → route a binding-domain repEntry through `_handleBeadHit` (drill/manual/tab),
  else strand-select (ss linker has no beads). Guarded so a bridge hit doesn't misindex
  getCylinderDomainAt.
- Scope: works in GLOBAL cylinder LOD (where the bridge cylinder renders). PER-REGION linker→
  cylinders still doesn't RENDER the bridge (linker cylinders are global-LOD-visibility controlled,
  not columnRep) — separate rendering follow-up if needed.
- Verified (Playwright, removed): bridge mesh present+instanced, selection intact, no errors.
  NOT verified: actual bridge click-select (needs a design WITH a ds linker + real raycast).

## Region selection unified through _handleBeadHit (2026-06-02)

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

## Progress (2026-06-02)

DONE + tested (backend, `tests/test_representation_overrides_api.py` 9/9; full suite 1723 pass):
- `RepresentationOverride` model + `Design.representation_overrides` list (display-only,
  round-trips, old files → []). [backend/core/models.py]
- `PUT`/`DELETE /design/representation-overrides` (strand/cluster 404, empty-selection 422).
  [backend/api/crud.py]
- Client `saveRepresentationOverrides` / `clearRepresentationOverrides`. [frontend/src/api/client.js]

DONE, syntax-clean, NOT VERIFIED IN APP (frontend rendering):
- Pure resolution `resolveRepOverrides(design, geometry)` → {nucReps, domainReps}.
  [frontend/src/scene/representation_overrides.js]
- helix_renderer `applyRepOverrides(nucReps, domainReps)` — per-instance ALPHA (not scale, so
  it survives deform/radius matrix recomputes) for beads+slabs+cones+fluoros and straight
  `iHelixCylinders`/`iOverhangCylinders`; multiplies over reference alpha; takes over `.visible`
  when active; re-applied from `setDetailLevel`/`setReferenceHidden`. Added `domainIndex` to
  `_domainCylData`. Lazy `_installInstanceAlpha`.
- design_renderer wiring: `_applyRepresentationOverrides` after the reference block in `_rebuild`,
  AND a no-rebuild path in the store subscription (override edits are a visual-only design field —
  the rebuild is skipped by the existing length-equal early-return, so apply directly).

DONE, syntax-clean, NOT VERIFIED IN APP (UI — right-click context menu, user-chosen surface):
- Pure merge helpers `editOverridesForStrands` / `editOverridesForClusters(overrides, ids, rep|null)`
  in representation_overrides.js — assign moves ids between overrides (one rep per strand/cluster),
  null = reset to global, drops empties, never mutates input.
- Shared `_appendRepresentationMenu(menu, {strandIds, clusterIds})` in selection_manager.js
  ("Representation ▸ Full detail / Cylinders / Reset to global"), wired into `_showColorMenu`
  (single + multi-via-param), `_showMultiMenu`, and `_showClusterMenu`. Reads current overrides
  from store, merges, calls `api.saveRepresentationOverrides`.

BUG FOUND + FIXED (2026-06-02) — overrides broke left-click selection:
- Root cause: selection_manager used `designRenderer.getCylinderMesh()?.visible` as the proxy
  for "in cylinder LOD → don't raycast beads". The mixed-rep ACTIVE branch sets
  `iHelixCylinders.visible = true` to drive per-instance alpha, so at full LOD the proxy went
  true → `selBackbone/beadMeshes = []` → ALL bead/cone left-click selection died (drill too).
  Right-click context menu didn't gate on it, so it kept working — matched the symptom.
- Fix: the real signal is "are the bead meshes actually hidden". Drill site (sel_mgr ~2653)
  now filters bead/cone meshes by `.filter(m => m.visible)` instead of the cylinder-visible
  binary (true cylinder LOD → beads hidden → []→ cylinder-hit fallback; full + mixed-rep →
  beads visible → selectable). Lasso site (~2294) now uses `designRenderer.getDetailLevel()===2`.
  Added `design_renderer.getDetailLevel()`. `getCylinderMesh().visible` is used at 5 sel sites;
  only the two binary-LOD switches needed changing — the other 3 legitimately raycast the cyl mesh.
- Verified via Playwright (scratch spec, since removed): override active → cyl visible + beads
  STILL visible (selectable); clear → cyl hidden; no console errors; programmatic select works.
- LESSON: do not overload a mesh's `.visible` as a mode flag — mixed-rep needs cylinders
  renderable at full LOD without the app reading that as "cylinder LOD".

DONE (2026-06-02) — global rep change is a master reset:
- Choosing a global representation via View → Representation menu OR F1–F7 clears all per-region
  overrides so the new global wins everywhere. Hook is in the menu-button click handler's
  design-mode branch ([main.js] ~14211: `if (currentDesign.representation_overrides?.length)
  await api.clearRepresentationOverrides()` before `_setRepresentation`). F-keys delegate to
  `btn.click()` so they share it. Internal `_setRepresentation` calls (reset-to-full at ~4506,
  hull-prism auto-switch at ~6472) bypass this handler → overrides preserved (intended).
  Edge: F-key pressed on the ALREADY-active rep cycles coloring (`_cycleColoringForRepr`) and does
  NOT clear — only an actual rep switch (or any menu click) clears. Verified via Playwright (removed).

PENDING (as written 2026-06-02 — superseded by `## Open items` at the end of this file).

Verify construction for the figure: keep global rep = full, override the BULK strands→'cylinders'
(focal stays full). Works without needing global-LOD-preserved-across-rebuild.

NOTE: 2 pre-existing test failures at clean HEAD — `test_seamless_router::test_teeth_closing_zig`
and `test_seamed_router::test_advanced_seamed_clears_existing_auto_route_before_teeth_reroute` —
unrelated to this work (proven by stashing all session changes). Don't chase them here.

## Original plan below


## Goal / use case

Publication-figure capability: render one structure with **different representations in
different regions** — e.g. the bulk bundle as plain **cylinders** for context, one focal
duplex/junction popped out at **full bead-and-base** detail. Canonical Dietz-lab cover-art
figure (white cylinder bundle + colored focal duplex). Display layer only.

Two phases, develop in order:
- **Path A (this plan)** — assign a rep to a *topological selection* (strands / clusters).
- **Path B (later)** — assign a rep to a *spatial volume* (draggable box/sphere) that may cut
  mid-helix. NOT built here, but A is architected so B is **additive, not a refactor**.

## Decisions locked (2026-06-02, with user)

- A selectors: **strand(s)** and **cluster(s)**. (Not helix/domain in first cut.)
- Override rep palette: **cylinders** and **full beads+slabs** only. (No hull/atomistic/surface
  in overrides yet — those stay global-only for now.)
- Base layer = the existing global representation. Overrides sit on top.
- A before B, but **the keystone below is mandatory in A** so B drops in.

## Today's constraint (why this is new capability)

Single-structure rep is **strictly global** — whole design is cylinders OR beads OR hull, one
at a time. `_setRepresentation` ([main.js] ~14127) flips everything; geometry is one
monolithic `_helixCtrl` whose `setDetailLevel` ([design_renderer.js] ~648) hits all of it.
No per-strand/cluster/region rep exists in the single-design view. (The *assembly* renderer
has per-part rep + per-instance visibility texture + shader discard — prior art, but
whole-part granularity only.) Hull is the one already-subdivided seam: one mesh per cluster
([joint_renderer.js] ~2892), toggled by a single global boolean `setHullRepr`.
*(Line numbers approximate — verify at implementation time.)*

## KEYSTONE (the decision that makes B free)

Do **not** model representation as a property of a helix/strand. A spatial volume (B) cuts
through a helix, so per-helix rep can't express "nucs 1–20 detailed, 21–40 cylinders."

Model it as: **resolve representation per nucleotide, then draw as contiguous runs.**

A and B differ ONLY in how a layer's nucleotide set is produced:
- A: "nucs of selected strands / cluster" → whole-helix runs.
- B: "nucs whose 3D position ∈ volume" → possibly mid-helix runs.
Everything downstream (resolve map → segment into runs → build per-segment geometry) is
identical. B = one new selector branch + a gizmo. B's first version snaps the volume boundary
to the nearest bp (nuc in/out by center) and reuses A's pipeline wholesale; smooth
per-fragment edge clipping is an optional later refinement.

## Architecture

### 1. Data model (saved display state, never mutates topology)
Ordered list of overrides on the Design: `[{ selector, rep }, ...]`.
- `selector` = tagged union:
  - `{type:'strand', ids:[...]}`
  - `{type:'cluster', id}`
  - (future) `{type:'volume', shape, transform, halfExtents}`
- `rep` ∈ `'cylinders' | 'full'`.
- Store the **selector**, not a baked nuc list → override follows structure across edits; drop
  selector entries whose referenced strand/cluster no longer exists.
- Lives with global-rep state in [store.js] (~265 area). Round-trips in `.nadoc`.
- Three-Layer Law: this is display metadata derived over topology. Never written back.
  A's resolution reads only topology ids; B's reads geometric nuc positions (read-only).

### 2. Resolution (pure function, the reusable core)
`resolveRepMap(design, overrides) -> Map<nucId, rep>`:
- init every nuc to global rep
- apply overrides in order, later wins
- strand selector → nucs of those strands; cluster selector → nucs of that cluster

### 3. Segmentation
Per helix, walk nucs in index order, cut into contiguous same-rep runs →
`[{helixId, startIdx, endIdx, rep}, ...]`. For A these are whole-helix runs; B yields
mid-helix runs. **This is the B seam.**

### 4. Rendering
Generalize the monolithic `_helixCtrl` build to build **per run-segment**, each in its own
rep (cylinder tube over the run, or beads+slabs over the run). Disjoint nuc sets → coexist in
one scene, no overlap/z-fight. Reuse the per-cluster-hull coexistence pattern
([joint_renderer.js] ~2892), generalized "cluster" → "segment".
- Junction cosmetic: where a cylinder run meets a bead run in the same helix, decide how the
  cylinder caps at the last bp before detail begins. Eyeball on a real design.

### 5. UI
- Select strand(s) / cluster → context-menu or sidebar: "Set representation → Cylinders /
  Full Detail"; "Clear" reverts to global.
- Small overrides-list panel (add/remove) for the figure-making workflow.
- Cluster multi-select picker already exists (deformation cluster work) — reuse.

## Required touch point — photo mode
Photo mode is the export path for these figures and **currently forces one global export rep
onto everything** ([main.js] ~12886, `_applyRepAndAwaitRebuild` over all). It MUST honor
per-segment overrides instead of flattening them — otherwise the mixed view exports as a
single rep. Non-optional in A.

## Suggested implementation order
1. Data model + store state + `.nadoc` round-trip (+ edit-survival: drop dead selectors).
2. `resolveRepMap` + segmentation — pure, unit-testable, no rendering.
3. Per-segment build in design_renderer/helix_renderer (the real work). Verify two reps
   coexist on a loaded design.
4. Selection → set/clear override UI + overrides panel.
5. Photo-mode: honor overrides in export.
6. (Later, Path B) volume gizmo + `{type:'volume'}` selector branch; optional edge clipping.

## Test points
- Unit: `resolveRepMap` precedence (later override wins), strand vs cluster resolution,
  contiguous-run segmentation including a helix that spans two reps.
- Round-trip: save/load a design with overrides; delete a referenced strand → override drops.
- Visual: load a representative `.nadoc`, set a cluster to full while base is cylinders;
  confirm coexistence + junction look. Then export via photo mode and confirm the mix survives.

## Open questions / gotchas
- Junction appearance (cylinder cap → first detailed bp).
- Persistence schema version bump for `.nadoc` if needed.
- Confirm cylinders is a real detail level in helix_renderer (LOD 2) for the single-design path.
- Selection plumbing: strand selection exists; confirm cluster-selection → override wiring.
- Whether base rep being `hull` interacts oddly with `full`/`cylinder` overrides (A palette is
  cylinders+full, but base could still be hull globally) — decide if hull base is allowed.

## Related
- [[project_photo_mode]] — export path that must honor overrides
- [[project_hull_prism]] — per-cluster mesh coexistence pattern + LOD reps
- [[project_path_to_thousands]] — assembly renderer's per-instance vis-texture + shader-discard
  (prior art for per-piece rendering; whole-part granularity)

## Per-region AXIS LINES + CROSSOVER ARCS follow the rep (shipped 2026-06-02)

Two bugs after global cylinder LOD + a per-region `full` override (repro: `workspace/Ultimate Polymer Hinge2.nadoc`):

1. **Axis lines showed for ALL helices** instead of only full/beads-rendered columns.
   Root cause: axis-mesh visibility is written in THREE places, only one of which was rep-aware:
   `_applyShaftModeVisibility` (mode-only), `setDetailLevel`'s coarse-hide, AND
   `applyDeformLerp` (single curved shaft, line ~1883 — set `.visible=!useStraight` directly).
   On a deformed design the deform lerp/`setAxisShaftMode` re-asserts shaft visibility and
   was overriding the LOD hide. Fix in [helix_renderer.js]: module-level `_axisColRep`/`_axisSegOn`
   gate (column rep === 'full' → axis shown), applied in `_applyShaftModeVisibility` AND
   `applyDeformLerp`. Added `bp_lo`/`bp_hi` to each `axisArrows` entry for the shaft gate.
   Active-override branch re-calls `_applyShaftModeVisibility`. Axis meshes now named `'axisLine'`.

2. **Crossovers (arc lines) didn't show for a strand set to full.** Arc lines live in
   unfold_view `_arcMeta` (merged scaffold/staple LineSegments, shown in 3D too) and were
   globally hidden at LOD≥2 via `setArcsVisible(lvl<2)`. Fix: added `_arcRepHidden(e)` to
   `_reapplyArcHidden` — an arc hides when BOTH endpoints are non-`full` columns
   (`designRenderer.columnRepAt`). So global cylinders → all arcs collapse; a full region →
   its arcs reappear. Decoupled the group from LOD: 4 `setArcsVisible(... && _lastDetailLevel<2)`
   callers in [main.js] now pass only design-visibility; LOD/override changes call the new
   `unfoldView.refreshArcVisibility()` (re-runs `_reapplyArcHidden` + `_updateArcPositions`).
   The override-save rebuild re-gates automatically via the existing rebuild subscription.

**Extra-base beads NOT yet per-region**: `_applyXoverExtrasLod` still hides ALL extra-base
beads/slabs (the inserted-base markers) at LOD≥2 — restoring collapsed instances on LOD
toggle is fiddly and fights the other xover-visibility passes. Only crossovers WITH inserted
bases are affected; standard crossovers (the arc) are fully covered. Follow-up if needed.

Verified via Playwright on the hinge: global cylinders → 0 axis lines / 0 arcs; pin one
staple to full → only that region's axis + arcs reappear. NOT visually confirmed in the app.
Debug handles added: `__NADOC_DBG__.designRenderer`, `__NADOC_DBG__.unfoldView` (getter).

---

## Open items (rewritten 2026-07-28 against a codebase probe — this is the live list)

**Rank: P1.** Feature ships; these are the holes. Ordered worst-first.

1. **SUSPECTED BUG — photo export may blank all beads once an override has been used.**
   `_installInstanceAlpha` permanently patches the shared bead/fluoro material with
   `diffuseColor.a *= vInstanceAlpha; if (a < 0.02) discard` and puts the `instanceAlpha`
   attribute on a **cloned per-mesh geometry** [helix_renderer.js:238-260]. On every export
   (assembly or not) `_withHighDetailGeometry` swaps `backboneSpheres`/`extensionFluorophores`
   to `hd.bead`/`hd.fluoro` [photo_mode.js:126-128], which carry **no** `instanceAlpha` → the
   attribute reads 0 → every bead and fluorophore should `discard`. **Not yet confirmed in
   app.** Repro to try: apply any per-region override, then photo-export a design with beads
   visible. Fix if real: copy the `instanceAlpha` attribute onto the HD geometry in the swap
   (or skip the swap while overrides are active).
2. **Photo mode does not read `representation_overrides` at all** (zero hits across
   photo_mode / photo_exp_mode / photo_renderer / photo_panel / photo_exp_panel /
   photo_figure_panel). The old fear — that export force-flattens to one global rep — turns out
   to be **assembly-gated only** (`inAssembly && exportRep !== 'working'`, photo_mode.js:31-37),
   so in single-design mode overrides survive the export by accident, not by design. Worth an
   explicit guard + a note, since the publication-figure use case is exactly this path.
3. **Deformed/curved cylinders are not covered.** `_applyRepOverrides` touches only
   `_domainCylData` / `_overhangCylData` / `_bridgeCylData`; `_curvedCylGroup` visibility is
   still pure global-LOD [helix_renderer.js:2489, 3531], and `_curvedDomainCylData` entries
   still lack `domainIndex` [:1458]. So on a **deformed** design a per-region cylinder override
   silently does nothing, and per-domain glow / cylinder-hit drill stay straight+overhang only.
   This is the biggest real-usage hole — most interesting figures are of deformed structures.
4. **Impostor beads bypass the alpha path.** `_installInstanceAlpha` is explicitly skipped when
   `_useImpostors` [:2420-2422, :2471-2474], so with `?impostors=1` bead alpha-hiding is a
   silent no-op.
5. **`iLinkerBindingCylinders` still global-LOD only** — no `_installInstanceAlpha`, no alpha
   write in `_applyRepOverrides`, only `.visible = coarse` [:2491, 3535]. (Bridge cylinders ARE
   column-driven; only the binding cylinders were deferred — "dsDNA only for now".)
6. **Extra-base beads not per-region** — `_applyXoverExtrasLod` hides ALL inserted-base markers
   at LOD≥2 (see the section above). Only crossovers *with* inserted bases affected.
7. **Test gap: no `representation_overrides.test.js`.** The pure helpers (`resolveRepOverrides`,
   `*ToSegments`, `editOverridesForSegments`) have no direct vitest; they're only exercised
   indirectly by `ui/overhang_orientation_menu.test.js` and mocked out in
   `atom_surface_display.test.js`. These are pure input→output functions — cheap to pin.
8. **Never verified by a real mouse click in-app** (headless raycast can't hit). Suggested test
   design: **6hb_test** (6 helices, 1 cluster, undeformed); `Examples/teeth.nadoc` does not exist.

**Not superseded by anything.** Probe found no competing per-region rep mechanism —
`_ALL_REPRS` in `representation_switcher.js` is the *global* rep list, `animation_player.js`
has no representation state, and ssDNA ball-joint code has none. `unfold_view.js:308` *consumes*
`columnRepAt` rather than duplicating it.
