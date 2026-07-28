# Photo mode → ChimeraX-replacement gap map

**Goal being measured against:** photo mode should be a *DNA-origami-native* replacement for ChimeraX
for figure work — the user never exports a PDB (or five) just to get a publishable image.
**Status:** audit only, 2026-07-27. No code changed.

> **Priority correction (user, 2026-07-27).** The target is the **visually stunning lighting and
> environment**, not figure furniture. Labels, scale bars, colour keys, and annotation are *not* the
> priority — §5 and most of §2/§6 below are demoted accordingly; see the re-ranked §11. The two named
> must-haves are **low-poly atomistic spheres that hold up at a distance** and **view-independent
> 64-direction geometric occlusion**. Those are specified in depth in
> **[photo_mode_ao_and_lowpoly_spec.md](photo_mode_ao_and_lowpoly_spec.md)** — read that first; this
> file is the surrounding inventory.

**What was read.** NADOC side: [photo_renderer.js](frontend/src/scene/photo_renderer.js) (2052 L,
~60 setters), [photo_renderer/](frontend/src/scene/photo_renderer/) (figure_pass, style_presets,
material_presets, lighting_presets, post_processing, floor, figure_camera, volumetric_inscatter_pass),
[photo_panel.js](frontend/src/ui/photo_panel.js) + [photo_figure_panel.js](frontend/src/ui/photo_figure_panel.js),
the `#tab-content-photo` markup in [index.html](frontend/index.html#L5882), and
[memory/project_photo_mode.md](memory/project_photo_mode.md). ChimeraX side: the user-guide command
pages for `lighting`, `graphics`, `camera`, `material`, `nucleotides`, `save` (image), `clip`,
`surface`, `color`, `transparency`, `label`, `2dlabels`, `key`, `view`, `scenes`, `shape`, `size`,
`movie`, `hbonds` — plus the UCSF publication-image guidance and a practitioner workflow writeup.

---

## 0. The one-paragraph verdict

Photo mode has **more renderer than ChimeraX** (PBR, HDRI/IBL, filmic tone mapping, path tracing,
volumetrics, SSS, emissive fluorophores, a floor rig) and **less figure tool than ChimeraX** by a
wide margin. Everything in ChimeraX that turns a render into a *figure* — labels, a scale bar, a
colour key, clipping planes, named views, arbitrary show/hide, attribute→colour mapping — is absent.
The gap is not in the pixels; it is in everything that goes *on top of* and *around* the pixels, plus
two shading primitives (real ambient-occlusion shadowing, true orthographic projection) that carry
the ChimeraX house style. A DNA-specific advantage exists and is currently unexploited: NADOC knows
strand/domain/crossover/scaffold-vs-staple identity natively, which ChimeraX can only recover from a
PDB by heuristics.

---

## 1. Shading & lighting model

| ChimeraX | NADOC photo mode | Gap |
|---|---|---|
| `lighting soft` / `full` — **ambient occlusion by multi-directional shadow mapping**, 64 directions default (`multiShadow 64`, `msMapSize 1024`, `msDepthBias 0.01`) | **Screen-space** GTAO (`ao`, `aoRadius` nm, `aoIntensity`) + a separate SSAO garnish | **P0.** Different physics. Screen-space AO only occludes from what is *on screen and in front*; ChimeraX's ambient shadows are real geometric occlusion, view-independent, and don't halo or leak at silhouettes. This is the single biggest reason a ChimeraX `lighting soft` render of a bundle reads as solid and a GTAO render reads as smudged. `publication2` already tries to imitate it with `aoRadius 2.5, aoIntensity 1.5`. |
| `lighting shadows true` — key-light cast shadow, **no ground plane needed**; molecules self-shadow | Shadows exist but are **gated on a floor being on** — [`_rebuildFloor`](frontend/src/scene/photo_renderer.js#L895): `wantShadows = (floor !== 'off') && floorShadows` | **P0.** You cannot get helix-on-helix cast shadow without switching on a visible ground plane, which is exactly what a journal figure must not have. Ungating this is small. |
| `lighting flat` — ambient only + silhouettes auto-on (`ambientIntensity 1.45`) | `lighting: 'flat'` preset + independent `outline` | Parity. |
| `material` presets: `default` / `shiny` / `dull` / `chimera`; scalar `reflectivity 0.8`, `specularReflectivity 0.3`, `exponent 30`, `ambientReflectivity 0.8` | 4 material presets per representation, PBR (`roughness`/`metalness`/`clearcoat`/`transmission`) | NADOC ahead, but no numeric escape hatch — a user can't dial specular to 0.05; they pick `flat`/`matte`/`glossy`/`metallic`. **P2:** expose roughness/metalness sliders. |
| `transparentCastShadows`, `meshesCastShadows` | absent | P2. |
| depth cue with explicit `depthCueStart 0.5` / `depthCueEnd 1.0` / `depthCueColor` | `depthCue` + `depthCueColor` + `depthCueStrength`; window auto-derived from the bbox diagonal | Roughly parity, arguably better (the auto-window was hard-won — see the topic file). **P2:** no manual start/end override. |
| `lighting moveWithCamera true` (rig pinned to camera) | rig is scene-fixed; `lightingYaw`/`lightingPitch` rotate it | **P1.** Camera-pinned lighting means the key light never swings behind the object as you orbit — it's what makes ChimeraX renders consistent across viewpoints. NADOC's rig stays put, so orbiting changes the lighting. |

## 2. Camera & projection

| ChimeraX | NADOC | Gap |
|---|---|---|
| `camera ortho` — **true orthographic** | `parallel: true` = 8° long lens + dolly ([figure_camera.js](frontend/src/scene/photo_renderer/figure_camera.js)) | **P1.** Deliberate, documented trade (a real `OrthographicCamera` swap breaks SSAO/GTAO shader defines, the inscatter ray march, the path tracer, OrbitControls, and main.js's per-frame near/far). Residual convergence is sub-pixel at print res on a 60 nm object — but it is *not* sub-pixel on a 1 µm assembly, and ortho is what makes repeat units in a lattice measurably equal. Re-open only with a plan for the five consumers. |
| `view name` / `view <name> frames N` — **named views with interpolated transitions**; `scenes save/restore` capturing colours, display state, camera, clipping | none | **P0.** No way to save "the figure viewpoint", return to it, or produce a matched pair of panels from two angles. This is a daily-use ChimeraX feature. |
| `view orient` (snap to standard XYZ axes), `view zalign` | none | **P1.** No "look down the helix axis" / "align this bundle to screen Z" command. For origami this is *more* useful than in ChimeraX — end-on views of a bundle are a standard figure. |
| `clip near/far/front/back`, `slab`, arbitrary plane `axis`, per-model, `surface cap` on the cut | none | **P0.** No cross-sections. Cannot show the interior of a multilayer block, cannot cut a slab through a bundle to show the lattice. Capped clipping of the molecular surface is a signature ChimeraX figure. |
| `camera 360/dome/stereo` | none | Non-goal. |

## 3. Representations — the DNA-specific axis

| ChimeraX `nucleotides` | NADOC | Gap |
|---|---|---|
| `tube/slab` — ribose as tube, base as **box / muffler / ellipsoid** slab, `thickness`, `glycosidic`, `showOrientation` bumps | `full` = backbone spheres + base slabs; `cylinders`; `vdw`; `ballstick`; `beads`; `hull-prism`; `surface` (`_VALID_REPRESENTATIONS`, [assembly.py:390](backend/api/assembly.py#L390)) | **P2.** NADOC's slab rep is close to `slab`/`tube-slab`. Missing: base-shape choice, slab thickness control, orientation bumps. Matters for zoom-in inset panels, not for whole-object views. |
| `ladder` (paired rungs, `radius 0.45`, `showStubs`), `stubs` | none | **P2.** A ladder rep is a genuinely good origami idiom (rungs = base pairs, shows helical phase at a glance). Cheap to add on top of the existing bead/slab instancing. |
| `size stickRadius/ballScale/atomRadius`, `style sphere/ball/stick` | fixed radii per rep (`BEAD_RADIUS`, atom sphere geo) | **P1.** No user control of bead/stick/atom radius. ChimeraX figures routinely use a thinned stick or a fattened ball to make a panel read. |
| `surface resolution N` (Gaussian low-res), `probeRadius`, `gridSpacing`, `sharpBoundaries`, `visiblePatches`, `surface dust`, `surface style mesh/dot` | one marching-cubes surface, strand or uniform colour | **P1.** No resolution/probe control → can't make the smooth blobby low-res surface that origami papers use for the "overall shape" panel. No mesh/dot style. |
| `hbonds` / `distance` — drawable, labelled pseudobonds | [measurement_tool.js](frontend/src/scene/measurement_tool.js) exists but is not a photo-mode-visible annotation | **P1.** No way to put a labelled distance/crossover marker in a figure. |
| `shape sphere/cylinder/cone/arrow/box/rectangle` as annotation geometry | none | **P1.** No 3D arrows, no marker spheres, no highlight boxes. |

## 4. Colour & data mapping

| ChimeraX | NADOC | Gap |
|---|---|---|
| `color byattribute <attr> palette <p> range lo,hi` — map **any** numeric per-atom/residue attribute to a colormap | fixed categorical modes: strand / base / cluster / cpk / source / overhang-only (`menu-view-coloring-*`) + a bespoke oxDNA strain map (`f784ff7`) | **P0.** No general value→colour machinery. Every new scalar (strain, local twist, RMSF, per-nt occupancy, B-factor-analogue from a sim) needs bespoke code instead of `colorByAttribute('strain', 'viridis', [0, 0.4])`. The strain map proves the demand and the one-off cost. |
| Palettes: rainbow, redblue, grayscale, ColorBrewer, custom colon lists | ad-hoc per feature | **P1.** No shared palette registry. |
| `key` — **colour key / legend** as a model: size, position, blended vs distinct, tick marks, numeric labels, font | none | **P0.** A false-colour panel without a legend is not publishable. This is the direct partner of the item above. |
| `color zone`, `surface zone`, `color sequential`, `rainbow` by chain/residue | strand colouring covers most of it | Parity for origami purposes. |
| `transparency <pct> target a/b/c/s/p/f` — per-target opacity | global `translucency` (full + cylinders), surface opacity slider | **P1.** Cannot make *the staples* 70% transparent while the scaffold stays opaque — the standard "show the scaffold path through the block" figure. Selection-scoped transparency is the ask. |

## 5. Figure composition & annotation

| ChimeraX | NADOC | Gap |
|---|---|---|
| `label` — 3D labels on atoms/residues/models, attribute substitution `{0.name}`, height in scene or fixed px, `bgColor`, `offset`, `onTop`, faces camera | none | **P0.** No way to label helix 7, strand `st-14`, a seam, a domain. |
| `2dlabels` — screen-space text: `xpos/ypos`, size, font, bold/italic, colour, `bgColor`, `margin`, `outline`; Unicode | none | **P0.** No panel letters (A, B, C), no captions burned into the image. |
| `2dlabels arrow` — screen-space arrows, `start`/`end`, `weight`, `headStyle` | none | **P0.** No pointing at things. |
| **Scale bar** | none | **P0.** Every origami figure needs "20 nm ——". NADOC knows the scale exactly (scene units *are* nm), so this is nearly free and strictly better than ChimeraX, which has no built-in scale bar either (users fake it with `shape cylinder`). **Cheapest high-value item on this map.** |
| `save session` for reproducible figure state | localStorage profiles (`nadoc.photoProfiles.v1`) — renderer settings only, **not** camera / visibility / colours | **P1.** A profile doesn't reproduce a figure, only its lighting. |
| Command log → a figure is a reproducible script | no command layer; setters on `window.__photoRenderer` | **P1.** Cross-cutting; see §8. |

## 6. Visibility control

| ChimeraX | NADOC | Gap |
|---|---|---|
| `hide`/`show` with arbitrary atom-spec (`#1/A:10-40@CA`), per-model, per-representation targets | `isolatedStrandId` (isolate **one** staple) + `staplesHidden` (all-or-nothing), per-instance representation in assemblies | **P0.** Cannot build the visibility set a figure needs — "show the scaffold and these three staples", "hide layer 2", "show only helices 0–5". This plus §4-transparency is the "explode the design for the reader" workflow. |
| `select` + `hide sel`, spec algebra | click selection exists; no spec language | P1 (see §8). |
| `sym` — symmetry copies | n/a | Non-goal. |

## 7. Export & output

| ChimeraX | NADOC | Gap |
|---|---|---|
| `save img.png supersample 3` — **true SSAA**, render 3× then downsample; default 3, guides recommend 3–8 for publication | SMAA post-pass + `antialias:true` MSAA on the offscreen renderer; tiled `setViewOffset` render | **P1.** SMAA is a morphological edge filter, not supersampling: it cannot recover sub-pixel detail on a 1-px silhouette or a thin outline. This is a named, specific reason ChimeraX exports look cleaner. |
| silhouette `width` applied at final image scale | outline offset is **`uOutlineThickness / resolution`** in *tile pixels* ([figure_pass.js:149](frontend/src/scene/photo_renderer/figure_pass.js#L149)) | **P0 (likely defect — verify).** The outline is a fixed pixel width. At 600 DPI (8400×5940, tiles ≤4096 px) the contour is roughly the same pixel width as in a ~1000-px preview → visually ~4–8× thinner in the export than in the preview. The Publication style's headline effect probably does not survive its own export. Needs a real 600-DPI export compared against the preview. |
| — | screen-space passes (GTAO, SSAO, outline) run **per tile**; geometry outside a tile's frustum can't occlude inside it | **P1.** Same class as the documented bloom tile-seam. Expect AO/outline discontinuities at tile joins in multi-tile exports. Fix is overlap-and-crop. |
| `pixelSize` (Å/pixel at mid-depth) — sets image scale physically | DPI presets (Screen / 2× / 600 DPI / custom W×H) | NADOC ahead for print; ChimeraX ahead for "make two panels at identical nm/pixel". **P2:** add an nm/pixel mode so panels can be size-matched. |
| `transparentBackground true` | `bgType: 'transparent'` (default) | Parity. |
| `movie record ... encode` — h264/mp4, webm, gif, apng; `framerate`, `bitrate`/`quality`, `crossfade`, supersample per frame | [export_video.js](frontend/src/scene/export_video.js), animation-driven, GIF + others | Near parity; no crossfade, no bitrate control. P2. |

## 8. Reproducibility & the missing abstraction

ChimeraX's real superpower is not any single command — it is that **every figure is a text script**.
`lighting soft; camera ortho; graphics silhouettes true; color /A #b188a7; view myview; save fig.png
supersample 3` is a figure you can re-run, diff, email, and paste into a methods section.

NADOC has ~60 setters on `window.__photoRenderer`, no selection-spec language, and no command
surface. This shows up as three separate gaps above (§4 attribute colouring, §5 reproducible figure
state, §6 visibility sets) because they all need the same missing thing: **a way to name a subset of
the design and apply a property to it**. Something like `strand:staple & helix:0-5` → hide / colour /
transparency. Design that once and §4/§5/§6 collapse into one feature.

**P1, but it is the keystone.** Note the honest constraint from
[photo_mode_audit_plan.md](photo_mode_audit_plan.md): photo mode is frontend-only, has no REST route,
and its "automation API" is the JS controller. A spec language would live in the same place.

---

## 9. Where NADOC already beats ChimeraX (don't regress these)

- **Native origami semantics** — strands, domains, crossovers, scaffold vs staple, clusters, overhangs,
  helix indices. ChimeraX sees a PDB and guesses. This is the whole reason to build the replacement.
- **Simulation frames render directly** — oxDNA / NAMD / mrDNA / CanDo / SNUPI overlays survive into
  photo mode via the shared bead overlay + [display_tab_policy.js](frontend/src/ui/display_tab_policy.js).
  No trajectory→PDB→ChimeraX round trip.
- **Multi-resolution at assembly scale** — beads / cylinders / hull-prism / LOD impostors, plus the
  export-only detail upgrade (preview in cylinders, export in full).
- **Path tracing**, **HDRI/IBL**, **volumetric mist**, **SSS surface presets**, **emissive fluorophores
  as real light sources**, **floor + shadow-catcher/mirror** — ChimeraX has none of this. It is the
  wrong aesthetic for a journal figure and the right one for a cover image, a talk, or a grant.
- **Filmic tone mapping + exposure** — ChimeraX hard-clips.
- **DPI-anchored print export** with tiling past `MAX_TEXTURE_SIZE`.

## 10. Non-goals

Stereo/360/dome cameras; volume/density map rendering and `fitmap` (unless cryo-EM overlay becomes a
goal, in which case it is a large separate project); sequence-alignment-driven colouring; symmetry
copies; ChimeraX's `presets` machinery (NADOC's style presets already cover it).

---

## 11. Priority stack — re-ranked for the visual goal

Detail for items 1–6 lives in [photo_mode_ao_and_lowpoly_spec.md](photo_mode_ao_and_lowpoly_spec.md).

**Tier A — the look**
1. **Geodesic indexed spheres** (§3) — replace every UV `SphereGeometry`. Cheap, helps every path.
2. **Ungate shadows from the floor** (§1) — one condition; unblocks `lighting full`-style key shadows.
3. **`envMapIntensity` control** (§1) — prerequisite so IBL and AO don't fight.
4. **View-independent 64-direction ambient occlusion** (§1) — the `lighting soft` look. **The headline item.**
5. **Supersampled export** (§7) — load-bearing for 1 and 4, and fixes the outline-thickness defect (§7).
6. **A `soft`-equivalent ambient-only style preset** (§1) — what makes 4 legible.
7. **Camera-pinned lighting** (§1) — rig follows the camera, so orbiting doesn't re-light the scene.
8. **Curated HDRI set** (§1) — three or four bundled studio environments; near-zero engineering.
9. **Conditional: impostors in photo mode** (§3) — needs a user decision; makes 4 ~70× cheaper on
   atomistic scenes.

**Tier B — visual parity polish**
10. Radius/thickness controls per representation (§3); numeric roughness/metalness sliders (§1);
    surface resolution + probe radius + mesh/dot style (§3); depth-cue manual window (§1);
    tile-overlap fix for any remaining screen-space passes (§7); `view orient` / `zalign` (§2).

**Tier C — figure furniture (explicitly deprioritized by the user)**
11. Scale bar; 2D labels and panel letters; screen arrows; 3D labels; colour key; attribute→colour;
    clipping planes; named views/scenes; arbitrary visibility sets; selection-scoped transparency;
    the selection-spec + command layer (§8).

Tier C is not wrong — it is what a *figure* eventually needs — but none of it changes how a render
looks, which is the current goal.

---

## 12. Open questions for the user

1. **Ortho:** is the 8° approximation actually failing on real figures (large assemblies, lattice
   repeat units), or is it fine? Determines whether item 10's sibling — a real `OrthographicCamera` —
   is worth re-opening against its five documented consumers.
2. **Which figure did you last make in ChimeraX that you couldn't make here?** That single example
   would re-rank Tier A faster than this whole document.
3. **Cryo-EM density overlay** — in scope ever? It is the one large ChimeraX capability deliberately
   excluded above.
4. **Scriptability:** do you want figures to be reproducible text (a `.figure` script / recorded
   commands), or is a richer saved-profile that captures camera + visibility + colours enough?

## Sources

- [ChimeraX `lighting`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/lighting.html) ·
  [`graphics`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/graphics.html) ·
  [`material`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/material.html) ·
  [`camera`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/camera.html) ·
  [`clip`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/clip.html)
- [`nucleotides`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/nucleotides.html) ·
  [`surface`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/surface.html) ·
  [`size`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/size.html) ·
  [`shape`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/shape.html) ·
  [`hbonds`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/hbonds.html)
- [`color`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/color.html) ·
  [`transparency`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/transparency.html) ·
  [`key`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/key.html) ·
  [`label`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/label.html) ·
  [`2dlabels`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/2dlabels.html)
- [`view`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/view.html) ·
  [`scenes`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/scenes.html) ·
  [`save` (image)](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/save.html) ·
  [`movie`](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/movie.html)
- [UCSF publication-image guidance](https://www.cgl.ucsf.edu/chimera/data/downloads/1.2540/docs/UsersGuide/tutorials/images.html) ·
  [Making figures for the manuscript with ChimeraX](https://www.dzyla.com/science/making-figures-manuscript-chimerax/)
