# Simulation visualization persistence audit — 2026-09-11

Scope: existing simulation visualization → Animations tab → preview and GIF/WebM export. “Web export” is interpreted as the WebM option in the animation exporter. This is an assessment, not a production fix.

## Result

Tab navigation generally retains a painted simulation display. That does **not** establish that playback, saved animations, or export preserve it. Ordinary camera/spin keyframes can overwrite simulation positions with authored geometry. Trajectory keyframes provide explicit support for oxDNA and NAMD, but there is no general visualization snapshot in an animation.

| State | Enter Animations | Playback / GIF / WebM |
| --- | --- | --- |
| Painted oxDNA/NAMD frame or metric map | Preserved by display policy | Ordinary keyframes can overwrite positions; trajectory keyframes take over the controller |
| CanDo, SNUPI, mrDNA, BLADE painted display | Currently survives normal tab events | No general state capture; shared geometry may be overwritten; standalone meshes may remain independently |
| Live oxDNA/NAMD stream | Stopped by live-session policy | Not captured as an animation source |
| Authored oxDNA/NAMD trajectory range | Supported | Player seeks frames; exporters await settling before rendering |
| NAMD trajectory ions / periodic box | Explicit keyframe flags | Driven as trajectory companions; not a snapshot of every Dynamics toggle |
| Metric legend / other DOM visualization UI | May remain visible in workspace | Not composited into the canvas export |
| Saved visualization job, mode, alignment, color scale, overlays | No general animation field | Cannot reliably reproduce after reopening or changing the live view |

## Gaps and evidence

1. **Camera-only playback is not geometry-neutral.** `animation_player.js:_bakeStates` always includes the live feature-log index and fetches authored geometry. `_applyFrame` calls `applyPositionLerp` for non-trajectory segments even when no feature-log index was selected. A relaxed shape displayed through shared bead coordinates can therefore snap to authored coordinates when starting a spin or camera move. The added characterization test verifies that a camera-only keyframe writes backend design coordinates. Standalone cylinder/bead overlays have different ownership and require separate visual verification.

2. **Visualization state is not persisted with animations.** `backend/core/models.py:AnimationKeyframe` stores camera, design/configuration, motion, trajectory range/resolution, ions/box and text fields. It has no general simulation visualization specification (source job, display mode, scalar coloring/range, alignment, overlay settings, etc.). `DesignAnimation` has no such snapshot either. Rendering depends on ambient scene state. Only `oxdna` and `namd` are accepted trajectory engines, matching controller routing in `main.js`; CanDo/SNUPI/mrDNA/BLADE are not timeline sources.

3. **Stop/export cleanup does not fully restore the incoming view.** `trajectory_keyframes.js:release` restores a previous trajectory frame only when the controller still has the same job. A replaced job or a prior non-trajectory mode calls `stopAndRestore`, explicitly leaving the plain design. NAMD trajectory companions are disabled on release rather than restored from a complete prior snapshot. `animation_player.js:stop` subsequently restores baked base geometry too, so controller-level restoration alone is not proof of final on-screen preservation. Both exporters call `player.stop` on normal cleanup.

4. **Tab handling is inconsistent across engines.** `display_tab_policy.js` explicitly preserves `scene`, `photo`, and `plates`; live sessions exclude `scene`. oxDNA uses that policy. CanDo, SNUPI, mrDNA and BLADE instead test `e.detail.from === 'dynamics'`, while `left_sidebar.js` emits only `{ activeTab, collapsed }`. Their stop handlers do not run for normal tab events. Their apparent persistence is therefore not a reliable shared lifecycle contract. In particular SNUPI/BLADE trajectory playback has its own requestAnimationFrame clock, which the animation exporter does not seek or settle. Such playback can race shared geometry and produce timing-dependent exports.

5. **Export captures the rendered scene, not all visible UI.** Both raw GIF and WebM loops call `seekTo`, await `settleFrame`, render the Three.js scene, copy the canvas, and add animation text. They do not composite the DOM-based `flex_scale.js` legend. Visible scene meshes/colors can be captured if playback leaves them intact, but export does not snapshot or reapply arbitrary visualization settings. Photo export similarly drives the player and composites animation text through its separate rendering session; full overlay compatibility needs pixel-level validation.

## Work needed

1. Define a saved visualization specification and capture/reapply it for animation playback, including a stable job reference and the relevant rendering settings.
2. Make camera-only segments preserve simulation geometry; define explicit ownership when mixing simulation displays with feature-log, cluster, binding, and trajectory motion.
3. Snapshot and restore incoming controllers, frame, coloring, visibility and companions on stop, completion, cancellation and failure.
4. Unify engine tab policy and pause independent display clocks while exporting. Add timeline adapters for additional engines if their motion must be animated.
5. Add optional legend compositing and browser tests that compare decoded GIF/WebM frames with the intended visualization, including reopening a saved animation and post-export restoration.

## Validation and limits

Focused Vitest suites: display tab policy, sidebar transitions, trajectory controller lifecycle, export lifecycle, and animation player geometry. Added a camera-only geometry-write characterization in `frontend/src/scene/animation_player.arcs.test.js`.

These tests use fake renderers/controllers and mocked GIF encoding. They validate control flow and geometry inputs, not actual GPU pixels or decoded GIF/WebM output. No real simulation was run, no workspace design was changed, and no production behavior was modified. The existing graphene ions browser test only checks for a download and visible ion objects; it does not establish metric-map, legend, or general visualization fidelity.
