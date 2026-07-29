# Photo mode v1 — archived 2026-07-29

Replaced by the ground-up rebuild that started life as the "Exp. Photomode" tab
and is now simply **Photomode** (`src/scene/photo_mode.js` + `src/ui/photo_panel.js`).
Nothing here is imported by the live app. It is kept verbatim because several of
these subsystems were expensive to get right and may be worth mining rather than
rewriting.

## Why it was replaced

v1 grew into a general-purpose 3D render suite: HDRI environments, bloom, a
path tracer, a ground plane with reflections, volumetric mist, a floor-gated
shadow rig, style presets, and an export-representation upgrade. The user's
actual goal was narrower and sharper — *a DNA-origami-native replacement for
ChimeraX*, so that producing a figure never requires exporting PDBs. Measured
against that, most of v1 was surface area that buried the two things that
matter: lighting that reads as a molecular figure, and a real cast shadow.

The decision, in the user's words, was that there were "just too many options",
and to "build from the ground up" instead of continuing to prune.

## What is in here

| File | What it was |
|---|---|
| `photo_renderer.js` | The v1 orchestrator (2033 L): composer, HDRI, bloom, PT, floor, mist, material swap |
| `photo_mode.js` | Tab lifecycle + the export-representation upgrade |
| `photo_panel.js`, `photo_figure_panel.js` | The v1 panels |
| `photo_renderer/floor.js` | Ground plane + `AXIS_NORMALS` (still referenced by a comment in `scene/oxdna_floor_math.js`) |
| `photo_renderer/post_processing.js` | Bloom / SSAO / GTAO / inscatter composer wiring |
| `photo_renderer/style_presets.js` | Named look presets |
| `photo_renderer/volumetric_inscatter_pass.js` | Mist. Its pre-pass design is what `figure_pass.js` still follows |
| `photo_mode.spec.js` | The v1 e2e (panel open/close, presets, export) |

## What SURVIVED into the live app

These stayed in `src/scene/photo_renderer/` because the current photo mode uses
them — do not assume that directory is dead:

`figure_pass.js` (silhouette + depth cue) · `figure_camera.js` · `material_presets.js` ·
`lighting_presets.js` · `shadow_bounds.js` · `mesh_repr.js`

## Deliberately dropped, not ported

- **Ground plane / floor.** A figure of a helix bundle does not want one. The
  camera-clip seam in `main.js` (`_floorReach`) still exists and returns `null`.
- **Export-representation upgrade.** v1 temporarily raised every assembly
  instance to full geometric detail for the duration of a render, then restored
  it — with `getExportRepActive()` gating the save path so the temporary state
  never hit disk. `initFileSave` now takes `() => false`. Reviving this needs
  the assembly rep-upgrade machinery and an `api` dep.
- **HDRI, bloom, path tracer, mist, style presets.** See above.
- **Multishadow AO** was never part of v1 — it was tried in the rebuild and
  retired separately; see `archive/multishadow_ao/README.md`.

## If you revive something

The live modules under `src/scene/photo_renderer/` have moved on (notably
`figure_pass.js` gained the ChimeraX depth-outline behind a `uSilhouette`
uniform). Anything lifted from here must be re-tested against them, not assumed
compatible.

## Also archived here

`export_representation.spec.js` — the e2e for the export-rep upgrade. It drives
`#photo-export-rep`, a v1-only control, so it cannot pass against the current
panel. Note the *persistence* half of what it covered (per-assembly
`export_representation` round-tripping through `.nass`) is backend behaviour and
is still live and still tested on that side; only the render-time upgrade left.
