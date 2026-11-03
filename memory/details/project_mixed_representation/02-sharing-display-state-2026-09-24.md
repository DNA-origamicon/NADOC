# Sharing display state (2026-09-24) — supporting detail

[Topic head](../../project_mixed_representation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Sharing display state (2026-09-24)

Native sharing also watches design/geometry identities. After an edit, it waits
for a stable document and scene structure across polling ticks, then replaces the
existing invitation's scene. GPU upload-counter churn does not block publication;
superseding edits invalidate in-flight exports. Guests retain their camera.
Active multi-overlay layers refresh from updated design geometry, serialize their
rebuilds, and preserve the presenter camera. Small-design browser coverage includes
overhang extrusion, free-end resize, and bundle extrusion, including active overlay.
See `docs/audits/shared_design_edits_20260924.md`.

Shared snapshots include visible volume outlines and representation geometry, with
per-instance alpha preserved. After explicit publication, native sharing watches
scene display changes, so representation switches and volume edits update the same
link without requiring camera sharing. Multi-overlay uses separate guest render
passes for each frozen layer, retaining opacity, separation, lighting, and
camera-dependent draw order. Guests orbit the result; volume editing remains in
the editor. See `docs/audits/representation_sharing_20260924.md` for validation.

## Spatial View Volumes (Path B, shipped 2026-09-01)

The Visualization sidebar now owns a `View Volumes` card. Each persisted
`Design.view_volumes` record stores an axis-aligned world-space box, name,
representation, and opacity. The plus action builds a volume around the current
part; selecting it exposes eight raycastable corner handles, and dragging a handle
resizes against the opposite corner. Spatial membership is resolved from live
rendered nucleotide positions. Overlaps remain independent overlay layers (for
example surface + stick), while the coarse-grained visibility channel yields to
the selected heavy representations. The controller exposes
`window.__NADOC_VIEW_VOLUMES__` for deterministic building/validation. Persistence:
`PUT /design/view-volumes`; implementation/tests live in
`frontend/src/scene/view_volumes.js`, `view_volumes.test.js`,
`frontend/e2e/view_volumes.spec.js`, and `tests/test_view_volumes_api.py`.

**Interaction/performance revision (2026-09-01):** box manipulation now uses
Three.js `TransformControls` with explicit Move (translation, shape preserved) and
Resize (scale about center) modes. Pointer motion changes only the scene-local box;
spatial membership is latest-frame coalesced and representation application is a
120 ms trailing-edge job. Surface requests are abortable and revision-checked;
atom overlays reject stale async completions. Pointer-up persists once through a
small metadata-only response—the old endpoint revalidated and returned the entire
82 MB VoltronCoreArm design. `window.__NADOC_VIEW_VOLUMES__` exposes scripted
begin/translatePreview/scalePreview/commit, cancellation, event timing, counters,
and current bounds. `view_volumes_voltron_performance.spec.js` validates 24
frame-paced move/resize previews on real VoltronCoreArm, one commit, coalescing,
and <50 ms membership passes (the fixture itself takes ~9 minutes to load/build in
the isolated Playwright server).

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
| Renderer alpha path | `helix_renderer.js` `_installInstanceAlpha`, `_ensureAlphaInstalled` (was `_ensureRepAlpha`), `_applyRepOverrides`, public `applyRepOverrides` — **re-grep, these moved 2026-08-01** |
| The shader patch itself | `frontend/src/scene/instance_alpha.js` — `instanceAlphaOnBeforeCompile` + `applyInstanceAlphaMaterial`. Extracted 2026-08-01 so photo mode can re-install it after its material swap (see item 1 below) |
| Rebuild + no-rebuild wiring | `design_renderer.js` `_applyRepresentationOverrides:387` (calls `setDetailLevel` first — bug-A fix intact), `getDetailLevel:1167`, `columnRepAt/isColumnAtomistic/isColumnSurface:1185-1187` |
| Right-click menu | `selection_manager.js` `_appendRepresentationMenu:411` (6 call sites) |
| F1–F8 + global-rep master reset | `frontend/src/ui/representation_switcher.js` (F8 is Stick) — **no longer `main.js`** |
| Region atom/surface overlays | `frontend/src/scene/atom_surface_display.js` (`initAtomSurfaceDisplay`, called `main.js:2461`); segment extraction moved to `surfaceSegments()` in `design_queries.js` |
| Photo export | `frontend/src/scene/photo_mode.js` — **no longer `main.js ~12886`** |

**Stick representation (2026-08-11):** `stick` is a first-class atomistic representation for
global design view, per-region overrides, saved assemblies, MD/oxDNA displays, coloring, and photo
mode. It reuses ball-and-stick bonds/materials while omitting `atomSpheres`, and is bound to F8.

**The master reset is exempt from the no-op guard (2026-08-01).** Re-picking the representation
already on screen now returns before `_setRepresentation` (`representation_switcher.js:279`),
because dispatching `nadoc:representation-change` fans out to six listeners and several do real
network work. **A click that clears overrides is NOT a no-op** even when the name matches — the
displayed structure genuinely diverged from the nominal global rep — so the guard is
`if (!hadOverrides && repr === _appliedRepr) return`, evaluated *after* the clear. Same idea as
the F-key handler's existing `_hasRepOverrides` branch (`:307`), which already routed an
already-checked rep to a real re-apply instead of a coloring cycle. Pinned by
`representation_switcher.test.js` → `no-op re-pick` (4 tests, incl. the overrides exemption).

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
