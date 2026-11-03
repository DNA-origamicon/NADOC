# Open items (rewritten 2026-07-28 against a codebase probe — this is the live list) — supporting detail

[Topic head](../../project_mixed_representation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

1. ~~**SUSPECTED BUG — photo export may blank all beads once an override has been used.**~~
   **WITHDRAWN 2026-07-30** (`/audit-plan` rendering probe). The mechanism does not exist:
   `_withHighDetailGeometry`, `hd.bead` and `hd.fluoro` have **zero hits anywhere in
   `frontend/src`**, and `photo_mode.js:126-128` is an export-dimensions config block
   (`exportWidth: 4200` …), not a geometry swap. Photo mode was rewritten into
   `scene/photo_renderer/*` (v2); the closest surviving thing is the static rep table
   `photo_renderer/mesh_repr.js:18,22` (`backboneSpheres: 'full'`, `extensionFluorophores:
   'full'`), which never touches geometry or attributes. `instanceAlpha` appears **only** in
   `helix_renderer.js` — nothing outside it clones, swaps, or drops the attribute.
   *The open sub-question — "does photo export honour per-instance alpha at all?" — was
   **ANSWERED NO and FIXED 2026-08-01** while adding per-cluster opacity.* It did not, and the
   mechanism was one line up from where this item was looking: `swapToFlatMaterials`
   ([photo_mode.js:209](../../../frontend/src/scene/photo_mode.js#L209)) REPLACES every mesh material
   with a fresh one from `makeMaterial` and copies `side`/`depthWrite`/`depthTest`/`vertexColors`/
   `color`/conditional-opacity across — but **not `onBeforeCompile`**. The alpha patch lives
   entirely in that callback, so in photo mode (viewport *and* tiled export, which reuses the same
   swapped materials) every ghosted reference strand and every alpha-hidden override region
   rendered **fully opaque**. The geometry attribute always survived; only the material half was
   lost. FIX: the patch moved to `scene/instance_alpha.js` as a module-level named function plus
   `applyInstanceAlphaMaterial(mat)`, which stamps `userData.instanceAlphaPatch`; the swap
   re-installs it when it sees that marker. Setting `transparent` there is **not optional** —
   `makeMaterial` forces `transparent:false` for non-surface reps, and the swap's opacity
   carry-over is gated on `src.opacity < 1`, which is false when the fade lives in the attribute.
   Pinned by 4 tests in `photo_mode.test.js` + `instance_alpha.test.js`. So mixed-representation
   ghosting now survives export too, for free.
2. **Photo mode does not read `representation_overrides` at all** (zero hits across
   photo_mode / photo_panel / photo_renderer/* (v1's photo_renderer.js is archived) /
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

## View volume interaction contract (2026-09-01)

View volumes are oriented boxes persisted as local min/max bounds plus a normalized
`[x, y, z, w]` quaternion. `TransformControls` owns Move, Resize, and Rotate; Tab cycles
those modes while a volume is selected. Selection comes from the transparent raycast box or
the volume's list row, and Escape/canvas background/list-row toggle clears it. Corner handles
and the transform gizmo exist visually only for the selected volume. Rotation participates in
membership by inverse-transforming each world point into the box's local frame.

All three transforms share the latest-frame preview and trailing representation scheduler.
Interactive `objectChange` events update the local box immediately, supersede pending
membership work, and never persist/rebuild the design; `mouseUp` commits exactly once. Debug
hooks expose mode, selection, gizmo visibility, centers, rotate previews, revisions, and stage
timings. The Chromium E2E flow covers Tab/Escape/list/background behavior and persisted
rotation; the large VoltronCoreArm performance flow covers the shared scheduling path.

View-volume PUTs use `state.mutate_display_metadata`: an atomic no-validation mutation that
still advances the document revision. The lightweight response returns only volumes + revision;
the API client advances its stale-response watermark, and the controller reasserts only the
newest acknowledged snapshot. This prevents an older in-flight rebuild response from removing
a just-created or just-moved volume without putting the 82 MB design back on the wire. The
Playwright race test deliberately removes the optimistic volume while a move PUT is gated, then
verifies the acknowledgement restores it and the backend retains its moved bounds.

The browser debug API also exposes `backboneTargets(limit)`, `moveToBackbone(keyOrIndex)`, and
`selectedMembership(targetKey)`. The VoltronCoreArm regression uses actual live renderer entries,
moves the selected box centre onto a chosen nucleotide, and checks non-empty membership, exact
target inclusion, the retained card row, and matching persisted volume ID. Persistence inspection
uses lightweight `GET /api/design/view-volumes` rather than downloading the entire ~82 MB design.
Two live Voltron runs reached and passed every base/card/backend assertion; their only timeout was
the subsequently removed legacy 24-rAF synthetic performance loop, which can suspend indefinitely
in headless Chromium once a large occupied layer is active.

Voltron Volume 1 representation changes exposed two independent cascade sources. First,
`atom_surface_display` treated every new `currentDesign` identity—including optimistic and
acknowledged view-volume metadata—as structural, invalidated the full atom cache, and applied the
OLD spatial layer before the authoritative layer event. `isViewVolumeOnlyDesignChange` now makes
the layer event the sole heavy-overlay trigger and retains caches for card-only saves. Second, the
generic 1.5 s workspace autosave started serializing the ~82 MB portable design between dropdown
changes, blocking the next tiny metadata PUT. View-volume-only changes now retain immediate server
persistence but debounce the portable-file flush until 10 s of card inactivity. The saved-pose
Playwright test passes Beads→Stick→Beads with exactly one atom request total, two completed metadata
saves, no move commits, retained occupied membership/card count, and final Beads persistence.

The View Volumes header owns a hidden `.nadoc-spinner` driven by real heavy-overlay lifecycle
events, not by the selected dropdown value. Atomistic and surface coordinators emit scheduled,
applied, cleared, failed, and abort stages tagged `viewVolume:true`; the card tracks atom and
surface independently so overlapping work keeps it visible until both settle. Switching to a
light representation, a no-data response, cancellation, and failure all clear ownership, avoiding
the classic endless-spinner failure. `representationBusy()` exposes the state to Playwright.
