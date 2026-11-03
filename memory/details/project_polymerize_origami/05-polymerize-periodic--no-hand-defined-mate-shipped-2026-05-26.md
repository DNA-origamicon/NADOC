# Polymerize (Periodic) — no hand-defined mate (shipped 2026-05-26) — supporting detail

[Topic head](../../project_polymerize_origami.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Polymerize (Periodic) — no hand-defined mate (shipped 2026-05-26)

Sibling feature: grow a chain from a SINGLE periodic part instance, deriving the repeat transform from the part's `is_periodic_seam` forced ligations (the end-to-end seam marked in the cadnano editor's periodic-boundary view, see [[periodic-boundary]]). No mate picker needed.

- **Math**: new `backend/core/periodic_polymer.py` — `derive_periodic_delta(design)` rigidly registers (Kabsch, reflection-guarded) the part's NEAR-end seam cross-sections onto the FAR-end ones. CRITICAL conventions (empirically pinned, NOT reasoned): (1) register AXIS GEOMETRY ONLY — origin (true helix axis point) + axis-tangent (z) tip, via `_axis_points`; do NOT register the radial x/y (that leaked the incommensurate per-period twist into a spurious BEND → spiral; see LESSONS A5, fixed 2026-05-26). The axis point is still recovered direction-independently by undoing the minor-groove offset (z=axis_tangent identical fwd/rev). (2) near=lower-bp endpoint, far=higher-bp (a reverse strand presents its 3' at the near side, so key off bp not the 3'/5' role); (3) the far frame is advanced ONE BP (junction bond ≈ one rise, `_bp_step_screw`) so the period is L bp not L−1. Validated: straight bundle (commensurate AND incommensurate L) → pure axial translation, 0° rotation, det(R)=+1; teeth.nadoc (251 bp) → pure 84.168 nm translation. A genuinely curved part still bends (curvature lives in the axis-tangent direction). Twist is left to topology (groove phase may jump at incommensurate junctions; fibre stays straight). `extra_bases` junctions NOT yet modelled.
- **Route**: `POST /assembly/polymerize-periodic` {instance_id, count, direction} ([backend/api/assembly.py](../../../backend/api/assembly.py), after `polymerize_assembly`). Places copy k at `T_seed @ delta^k` (delta is part-LOCAL → left-multiply seed world transform). Synthesizes `seam0:5p`/`seam0:3p` connectors on seed+clones + rigid joints between consecutive copies, capturing ONE `mate_relative_transform = inv(F_a^3p)@F_b^5p` reused on every junction (same pattern as `polymerize_assembly`). op_kind `assembly-polymerize-periodic` (in SnapshotOpKind + _EDITABLE/_REPLAYABLE + replay branch delegates to the route). 422 on non-periodic, 400 on count<2. Tests: `tests/test_periodic_polymer.py` (16). Verified live: 1 POST count=4 → 4 instances + 3 rigid mates, undo→1.
- **Frontend (UNIFIED into the regular Polymerize Origami panel, 2026-05-26)**: periodic parts appear as synthetic entries in the panel's Mate dropdown — `<instance> — via periodic boundary` (option value `periodic:<instanceId>`). Selecting one switches the panel to periodic mode: hides the "to pattern" section (`#poly-pattern-section`), shows periodic eligibility, and the Polymerize button calls `polymerizePeriodicAssembly({instance_id,count,direction})` instead of `polymerizeAssembly`. `initPolymerizePanel(store, { isInstancePeriodic })` ([polymerize_panel.js](../../../frontend/src/ui/polymerize_panel.js)); the panel detects periodicity from `inst.source.design.forced_ligations` (inline sources embed the design) with the injected renderer-cache check as fallback (file sources). Right-clicking a periodic part → "Polymerize…" opens the panel pre-selecting its periodic entry (`open({periodicInstanceId})`). NO separate menu item / context item / panel (the earlier `initPeriodicPolymerizePanel` + `#menu-assembly-polymerize-periodic` were removed in the unification).
- **Gotcha during verification**: the app auto-saves the assembly back to the opened `.nass`, so repeated Playwright runs on the same fixture ACCUMULATE chains (1→4→7→…). Regenerate the fixture between runs; verify via the POST response body, not the persisted file.

### 3D rendering of the seam connector + View toggle (2026-05-27)
A periodic seam (forced ligation merging far-3'→near-5' on the SAME helix) makes the merged strand's two termini CONSECUTIVE but ~a-whole-part apart, so `buildHelixObjects` ([helix_renderer.js](../../../frontend/src/scene/helix_renderer.js)) draws it as one giant full-radius backbone CONE spanning the structure (it's not cross-helix, so `getCrossHelixConnections` would otherwise skip it). Fix/feature: in the cone loop we detect periodic-seam pairs (`design.forced_ligations` where `is_periodic_seam`, keyed `helix:bp:DIRECTION`) and **treat them AS cross-helix** → the fat cone is suppressed (radius 0 at every site keyed off `isCrossHelix`) and the connector flows into the ARC pipeline tagged `isPeriodicSeam`. View menu → **"End-to-End Crossovers"** (`#menu-view-periodic-seam-arcs`, store `showPeriodicSeamArcs`, **default false**) shows/hides those arcs: single-design via `unfold_view._reapplyArcHidden` (mirrors the `showReferenceGeometry` per-arc `hidden` collapse + a store subscriber); assembly via a segregated `periodic` line in `_buildInstanceCrossoverArcs` toggled by a subscriber over `_cache.values()`. Zero impact on designs without periodic seams (empty seam-map short-circuits). Frontend-only.

## Periodic chains re-dock on part feature changes — LIVE seam connectors (2026-05-26)

Editing a feature of a periodic-polymerized part (e.g. a twist/bend on the source) did NOT
update the chain — copies stayed frozen at the polymerize-time pose. Two gaps, both fixed in
[backend/api/assembly.py](../../../backend/api/assembly.py):

1. **Static seam connectors.** `polymerize_periodic_assembly` bakes `seam0:5p`/`seam0:3p` as
   STATIC `ip.position` snapshots. In `resolve_assembly`, connector frames are recomputed live
   from geometry ONLY for `blunt:helix:bp` labels (`_resolve_blunt_label_local` → `deformed_helix_axes`
   / `deformed_nucleotide_positions`); every other label (manual connectors AND the seam labels)
   fell back to the stale stored position. So the rigid seam joints snapped to old frames →
   chain never re-docked. Demonstrated on `workspace/Spiral.nass` (built from `teeth.nadoc`): the
   stored `seam0:3p` (17.0,−48.4,49.8) was already stale vs the live (1.9,−50.5,49.8); a twist
   moved the live anchor 43 nm while the static value used by resolve ignored it.
   **Fix:** new `_resolve_seam_label_local(design, "seam0:5p|3p")` recomputes the anchor from
   `principal_seam_connectors(design)` (live), and a dispatcher `_resolve_live_connector_local`
   (blunt-first, then seam) replaces the 3 `_resolve_blunt_label_local` call sites
   (`_local_frame_for_label`, `_get_connector_world_frame`, `_get_connector_world`). At original
   geometry live==stored → resolve stays a no-op (`test_periodic_resolve_is_stable_noop`). The
   captured `mate_relative_transform` M stays valid: it's a near-identity junction residual
   (the connector-coincidence holds), and it was captured via the same `_build_frame_from_normal`
   the live path uses, so the chain re-derives its effective delta from the live seam frames at
   each junction. Frame builder uses roll-from-normal only (no radial), so a straight part stays
   straight (no spiral — consistent with `derive_periodic_delta`'s axis-only fit, LESSONS A5).

2. **Resolve trigger too narrow.** `seek_instance_features` only auto-ran `resolve_assembly` when
   `_cluster_transforms_signature` changed — its docstring wrongly claimed "deformations don't
   move mate connectors." But connector frames ARE pulled from deformed geometry, so a twist/bend
   edit moves them. **Fix:** new `_part_geometry_signature(design)` = cluster_transforms +
   deformations + per-helix loop_skips; the seek gate compares it instead. (Manual `POST
   /assembly/resolve` always re-docks regardless of trigger.)

Tests: `tests/test_periodic_polymer.py::test_periodic_chain_re_docks_after_part_geometry_change`
(bend added to the shared part → resolve moves clones >1 nm + seam connectors still coincide under
new geometry), `tests/test_assembly_api.py::test_part_geometry_signature_detects_deformation_changes`.
Backend-only — the frontend already applies the resolve response (`solve_status`, geometry).
Scope note: covers the part-context SEEK path + manual Resolve.

### Part-editor save path now auto-resolves + faster cross-tab sync (2026-05-27)

Follow-up: editing the part via the PART EDITOR (separate `?part=&assemblyDoc=` tab → debounced
`_savePartToAssembly` → `patchInstanceDesign(docId=assemblyDoc)`) still left the polymerized chain
frozen, and the sync fired several redundant calls. Two fixes:
- **Backend** `patch_instance_design` ([backend/api/assembly.py](../../../backend/api/assembly.py)) now
  auto-resolves exactly like `seek_instance_features`: compute `_part_geometry_signature` of the
  OLD source design vs the new `body.content`; if it changed AND the assembly has joints, call
  `resolve_assembly()` and return the re-docked assembly. Was the gap — the part-editor save path
  skipped resolve entirely, so the chain transforms never recomputed. Test:
  `tests/test_periodic_polymer.py::test_patch_instance_design_auto_resolves_periodic_chain`
  (file-backed periodic seed → polymerize → PATCH a bent design → chain moves >1 nm, no manual Resolve).
- **Frontend** `_refreshAssemblyPartInstance` ([frontend/src/main.js](../../../frontend/src/main.js), the
  `part-design-updated` BroadcastChannel handler): (1) it invalidated ONLY the one instance whose id
  came through — now invalidates ALL instances sharing that source file, so every chain copy's
  GEOMETRY (shape) refetches, not just the seed's (positions came from getAssembly, but the clones
  kept stale shape); (2) marks the source path in `_selfSavedPaths` so the watchdog SSE `file-changed`
  echo (which would run a SECOND full rebuild + 4× `getInstanceDesign`) is skipped by
  `_handleLibraryEvent`; (3) the cluster-panel `getInstanceDesign` is fetched once and applied to all
  affected instances. Net: one rebuild + ~3 calls (getAssembly + getAssemblyGeometry + 1
  getInstanceDesign) instead of two rebuilds + ~6 calls. Frontend NOT click-verified (local :8000
  backend was hung); `npx vite build` passes.

The file-watchdog reload path for a part edited in plain design mode (no `_partEditContext`) still
goes through `_handleLibraryEvent` (which rebuilds but does not itself resolve — it relies on the
backend assembly_state already being resolved by whatever wrote the file; an external editor that
writes the file without hitting `patch_instance_design` would NOT auto-resolve — manual Resolve then).

### Part-edit sync FLOOD (40× rebuild) + hull/cylinder overlay — fixed 2026-05-27

User repro: editing a part in a part-editor tab and returning to the assembly produced a huge flood
in the assembly tab's console — dozens of `GET /assembly/geometry` (each a full rebuild of all N
instances) + one `GET /assembly/instances/{id}/design` PER instance, all concurrent, 20-30 s
responses (backend saturated). The hull-prism+cylinder LOD overlay only appeared after this, and was
a RACE during the 40-way concurrent rebuild (one rebuild's `dispose()` racing another's build → a
stale `sharedLodCurvedCyl` left drawing under the new `sharedLodHull`). The two issues were the same
root cause.

**Root cause:** the SHARED renderer's `invalidateInstance(id)` ([assembly_renderer.js](../../../frontend/src/scene/assembly_renderer.js) ~5437)
IGNORES the id and does a full `rebuild(assembly)` (fire-and-forget). A prior fix had
`_refreshAssemblyPartInstance` ([main.js](../../../frontend/src/main.js)) invalidate EVERY instance sharing the
edited source (to update clones) → for an N-copy chain that fired N full rebuilds → N×
`getAssemblyGeometry`. Plus the broadcast (`part-design-updated`) AND the watchdog SSE
(`file-changed`) BOTH ran a full `_refreshAssemblyPartInstance`, and the SSE handler additionally did
one `getInstanceDesign` per instance.

**Fix (frontend):**
- `_refreshAssemblyPartInstance` no longer invalidates per-instance. The shared `rebuild()` ALWAYS
  `dispose()`s every source and refetches the batch `getAssemblyGeometry` once (the part-edit cleared
  the backend geo cache), so a SINGLE rebuild updates every copy's geometry. Removing the loop turns
  N rebuilds into 1.
- New coalesced scheduler `_scheduleAssemblyPartRefresh(instanceId, reason)` (debounce 250 ms +
  drop-while-in-flight + one trailing). Both the `part-design-updated` broadcast handler AND
  `_handleLibraryEvent`'s assembly branch route through it, so a burst of edits (slider drag) + the
  broadcast + the SSE collapse into ONE refresh. The SSE branch no longer does its own rebuild /
  per-instance `getInstanceDesign`.
- Verified (Playwright, throwaway spec): a burst of 6 `part-design-updated` broadcasts → `getAssembly`
  ×1, `getAssembly/geometry` ×0-1 (was ×40), `getInstanceDesign` ×2 (was ×40). Single-tab rep
  switching (cylinders↔hull, incl. revert) was already clean; the overlay was flood-induced, so it's
  resolved by removing the flood.
- KEY GOTCHA for future work: on the shared renderer, `invalidateInstance` == full rebuild. NEVER
  call it in a loop. One call (or one `rebuild()`) refreshes the whole assembly.

### Blank scene + /library/files flood on part-edit refresh — fixed 2026-05-27
After the per-instance-rebuild fix, a part edit still showed: (a) the assembly going BLANK for the
whole refresh ("looks hung"), and (b) a `GET /library/files` flood (rising 384→3088 ms = backend
queuing). Three fixes:
- **No blank** — the shared `rebuild()` ([assembly_renderer.js](../../../frontend/src/scene/assembly_renderer.js))
  called `dispose()` BEFORE the slow `getAssemblyGeometry()` fetch, blanking the viewport for the
  entire (seconds-long) fetch. Now it fetches FIRST and disposes only once the data is in hand, so
  the old chain stays on screen during the fetch (and stays on a fetch error instead of blanking).
- **Library flood** — `_handleLibraryEvent` ([main.js](../../../frontend/src/main.js)) ran
  `libraryPanel.refresh()` (→ `GET /library/files`) on EVERY SSE incl. self-saved echoes, undebounced.
  Now the self-saved skip runs FIRST and the refresh is debounced (`_scheduleLibraryRefresh`, 400 ms).
- **Assembly autosave echo** — a part-edit refresh updates `currentAssembly` → the assembly autosave
  subscriber writes Spiral.nass → `file-changed assembly` SSE → another library refresh. The autosave
  now marks the assembly path (and the resolved `r.path`) in `_selfSavedPaths` so its own echo is
  skipped.
- Build passes; NOT cleanly verified in-app (see hazard below). All three are inspection-sound,
  low-risk reorder/debounce/skip changes.

⚠️ FIXTURE HAZARD (bit me hard this session): the app AUTO-SAVES the open assembly back to its `.nass`
on every change, so repeated Playwright runs against `workspace/Spiral.nass` MUTATE it (4→40 via the
polymerize-accumulate gotcha, then a part-editor-init `importAssembly(cached)` into the shared doc
reset it to 1 instance). ALWAYS use a throwaway copy of a `.nass` for assembly E2E, never the real
fixture, and verify via the response body not the persisted file. (Re-states the polymerize gotcha.)

## Related
- [[assembly-overhang-bindings]] — cross-part bindings + linkers; the polymerize feature does NOT replicate these.
- [[periodic-boundary]] — the cadnano-editor seam-marking feature that makes a part "periodic" (`is_periodic_seam` forced ligations).
- `AssemblyJoint` is the "mate" data class — see [backend/core/models.py:1767](../../../backend/core/models.py#L1767). Both `Define Joint` and `Define Mate` menu items create one.
