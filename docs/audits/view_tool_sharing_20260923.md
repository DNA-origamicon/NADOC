# Standard view tools in shared presentations

Host toggles are mirrored; guests have read-only legends and retain their own camera.
Prepared exports capture length heatmap, sequences, undefined-base highlights,
loops/skips, overhang names, grid and clash state. The guest shows the strand-length
scale, loop/skip key and clash count alongside the exported scene geometry.
Overhang-location ArrowHelpers export as ordinary object hierarchies with their
line/cone geometry. Sequence and overhang text textures remain embedded PNGs.

Native presentations watch view-tool changes after an explicit publication and
replace content on the same invitation, even when camera sharing is off. The
watcher checks document, scene/pane, selected simulation job, active controller
job and visualization mode. It does not publish another private context. Starting
job sharing clears this watcher; successful return to the native model establishes
a new baseline. Pending exports are invalidated across these transitions. Recorded
clips remain frozen; live job sharing uses its existing scene/frame publication path.
View-tool metadata participates in scene fingerprints so count-only legend changes
also reach live-job guests. Older hosts require a restart for `view-tools-v1`.

Validation:
- 123 frontend tests: viewer suite and view-tool buttons.
- 8 hosting, broadcast and live-frame tests.
- Chromium test of real sequence/overhang overlays: embedded textures, guest loading,
  rendering without console errors, and hidden-label exclusion.
- Production build.
