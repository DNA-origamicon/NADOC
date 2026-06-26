---
name: sphere-impostors
description: "Replace real sphere meshes (backbone beads + atomistic atoms) with 2-triangle camera-facing impostor quads that ray-paint a lit sphere with correct gl_FragDepth. ~70x triangle cut for full/atomistic reps at scale. Phased: design view -> assembly shared path -> atomistic. Started 2026-05-22."
metadata: 
  node_type: memory
  type: project
  originSessionId: c2052b9a-98cc-4f45-9fbb-931f128384e6
---

# Sphere Impostors — vertex-load reduction for beads & atoms

**Why:** at `full` / atomistic representation the assembly view is *vertex/triangle-bound*, not
fill-bound (see [[path-to-thousands]]). One 7000-bp origami ≈ 2 M tris at full CG, ≈ 40 M at
atomistic; instancing cut draw-calls/CPU but not vertex throughput, so "1000 at full" stays
infeasible. The only lever that raises that ceiling is fewer triangles. Impostors turn each
~140-tri sphere (`SphereGeometry(r,10,8)`) into a 2-tri camera-facing quad whose fragment shader
ray-paints a perfectly round, correctly-lit sphere and writes `gl_FragDepth` for exact occlusion.
~20× (CG beads) to ~70× (atoms) triangle reduction. Cost moves vertex→fragment, which makes the
deferred dynamic-resolution idea directly effective afterward (synergy).

## Locked decisions (from user, 2026-05-22)
- **Photo mode keeps REAL spheres.** Impostors are an interactive-editing optimization only; photo
  mode reverts these meshes to true `GEO_SPHERE` + PBR material. Consequence: the one impostor
  fidelity caveat (silhouette aliasing — MSAA doesn't smooth discard-edges) never reaches a figure.
- **Phased rollout:** Phase A design/part editor → Phase B assembly shared path → Phase C atomistic.
  Each independently verifiable. Behind a runtime flag (`localStorage.NADOC_IMPOSTORS` / `?impostors=1`)
  until all three validate, then flip default; remove real-sphere bead path as later cleanup.
- **Write `gl_FragDepth`** (correct occlusion vs slabs/cylinders/arcs) — accept early-z loss. No
  log-depth buffer and no shadow maps in the interactive view (confirmed), so depth write is the
  textbook formula and no customDepthMaterial is needed.

## Shared building block — `makeImpostorMaterial()`
Patch a stock `MeshPhongMaterial` via `onBeforeCompile` (NOT a from-scratch ShaderMaterial) so
Three.js Phong lighting + fog + per-instance `instanceColor` all keep matching the rest of the scene.
Inject only:
- **Vertex:** center = `modelViewMatrix * instanceMatrix * vec4(0,0,0,1)`; billboard the quad corner
  (`position.xy` ∈ [-1,1]) in VIEW space by `u_impostorRadius`; pass `v_corner`, `v_centerView`.
- **Fragment:** `r2 = dot(v_corner,v_corner); if (r2>1.0) discard;`
  `normal = vec3(v_corner, sqrt(1.0-r2))` (view space, +z toward camera) → override
  `<normal_fragment_begin>` so Phong lights the painted sphere. Depth:
  `viewZ = v_centerView.z + normal.z*radius; clip = projectionMatrix*vec4(0,0,viewZ,1);
   gl_FragDepth = 0.5 + 0.5*clip.z/clip.w;` (declare `uniform mat4 projectionMatrix;` in the
  fragment — separate compilation unit, renderer populates it; safe).
Geometry: a unit quad spanning ±1 (`PlaneGeometry(2,2)`), 2 tris. The InstancedMesh's per-instance
matrix supplies only the CENTER (translation); radius is a uniform.

Mirrors the existing shared-renderer onBeforeCompile idiom at `assembly_renderer.js:2980-3036`
(injects transform composition at `<begin_vertex>` + discard/color at fragment chunks).

## Why the control surfaces survive (key insight)
Bead CENTER lives in the instance matrix translation; mrDNA relax / deform-lerp / unfold all move
beads by rewriting that matrix (`helix_renderer.js:~165` `setMatrixAt`). The impostor reads its
center from the same place → `applyFemPositions` (mrDNA relax overlay), `applyDeformLerp`,
`applyUnfoldOffsets`, and strand color all flow through UNCHANGED. The ONE thing that breaks:
picking (see Phase A). (NOTE: the XPBD/oxDNA physics overlay + FEM RMSF heatmap were deleted
2026-05-22 as dead code — see [[LESSONS]] / git; don't reintroduce them as smoke-test targets.)

## Phase map (status: TODO / IN_PROGRESS / DONE:<commit>)

### Phase A — Part/design editor (`helix_renderer.js`)        [CODE DONE; manual smoke pending]
- A1. **DONE** — `frontend/src/scene/impostor_material.js`: `impostorsEnabled()` flag reader,
  shared `IMPOSTOR_QUAD` (PlaneGeometry(2,2)), `makeImpostorPhongMaterial({radius})`
  (onBeforeCompile patch), `installSphereImpostorRaycast(mesh, radius)`.
- A2. **DONE** — `iSpheres` (`helix_renderer.js:~611`) + `iFluoros` (`:~660`) branch on
  `impostorsEnabled()` → quad + impostor material (radius 0.10 / 0.25). `setMatrixAt`/`setColorAt`
  unchanged. 5′ cubes / cones / slabs left as real geometry.
- A3. **DONE** — `installSphereImpostorRaycast` overrides `mesh.raycast` with ray-vs-sphere against
  per-instance centers; selection_manager unchanged. (Automated check: override is installed; actual
  click-pick behaviour is in the manual smoke list.)
- A4. **Automated render verification DONE** — `frontend/e2e/impostor_beads.spec.js` (2/2 pass):
  flag-on builds impostor mesh (quad geom, 4 verts, count>50, isImpostor, custom raycast), **no
  shader-compile errors**, screenshots (`e2e/screenshots/impostor_beads{,_closeup}.png`) show round
  lit blue beads matching the non-impostor look; flag-off keeps real SphereGeometry. **Real-design
  check DONE 2026-05-22** — third test loads `workspace/teeth.nadoc` (New Part → `/design/load` →
  broadcast → poll) and asserts impostor mesh + count>500 + no shader errors (`impostor_teeth.png`).
  **Manual smoke still pending** (USER TODO): click-pick a bead, bend deform, unfold, strand color,
  mrDNA relax overlay — should work by construction (center rides the instance matrix), not auto-tested.
  **Test-hygiene note:** the build flow needs a POLL for `backboneSpheres.count>0` after the
  `nadoc-design` broadcast (fixed waits were flaky); and repeated New-Part E2E cycles wedge the shared
  `--reload` dev backend (see [[LESSONS]] C4) — restart it if `/design/load` starts hanging.

> **GOTCHA (cost one iteration):** the first `<normal_fragment_begin>` replacement also declared
> `vec3 geometryNormal = normal;` → `ERROR: 0:895: 'geometryNormal' : redefinition`. In this Three.js
> version `geometryNormal` is declared by `<lights_fragment_begin>`, NOT `<normal_fragment_begin>`.
> The stock `<normal_fragment_begin>` defines only `normal` + `nonPerturbedNormal`; match that
> exactly. See [[LESSONS]] D5. Phase B/C will hit the same chunk-name versioning if they hand-write
> normal injection.

> **Flag:** opt-IN via `?impostors=1` / `localStorage.NADOC_IMPOSTORS='true'` / `window.NADOC_IMPOSTORS=true`.

### Phase B — Assembly shared-instancing path (`assembly_renderer.js`)   [DONE 2026-05-22]
The shared path reuses `buildHelixObjects` (1853/3394), so Phase A's quad+impostor material flows
through automatically — BUT `_attachInstanceShader` (the per-source transform-composition patch)
collides with the impostor material's own `<project_vertex>` (which billboards around `instanceMatrix`,
collapsed to identity on the shared path; the center actually lives in the instance×bp textures). So
a COMBINED injection was needed, NOT just letting both patches run.
- **A1 (impostor_material.js):** exported composable GLSL snippets — `IMPOSTOR_VERT_UNIFORMS`,
  `IMPOSTOR_FRAG_UNIFORMS`, `IMPOSTOR_FRAG_SPHERE_BODY`, `IMPOSTOR_FRAG_NORMAL` (bodies only, no
  chunk `#include`). `makeImpostorPhongMaterial` recomposed from them (Phase A unchanged, re-verified).
- **B (assembly_renderer.js `_attachInstanceShader`):** added an `_isImpostor` branch
  (`material.userData.isImpostor`). For impostor meshes: SKIP `_priorOnBeforeCompile` (don't run the
  material's own design-view billboard); set `u_impostorRadius`; vertex `<begin_vertex>` sets
  `transformed = (instTransform*bpMat*vec4(0,0,0,1)).xyz` (the bead CENTER, not the vertex); a new
  `<project_vertex>` replace billboards the quad corner in view space + sets v_corner/v_centerView/v_impR;
  fragment reuses the exported sphere-paint (`<clipping_planes_fragment>`) + normal
  (`<normal_fragment_begin>`) snippets, on top of the existing shared visibility/bp-color/active-highlight
  `<dithering_fragment>`. Non-impostor meshes (cubes/cones/slabs/mid-cyl/hull) unchanged.
- **Verified** (`frontend/e2e/impostor_assembly.spec.js`, passes): `poly_hin.nass` (full rep, shared
  path, `?impostors=1`) — `renderer.compile()` links the combined shader with **zero shader errors**;
  the shared bead InstancedMesh is a quad (4 verts) + isImpostor and renders (count>0). Screenshot
  (`impostor_teeth`-style, `e2e/screenshots/impostor_assembly.png`) shows beads correctly DISTRIBUTED
  across both hinge instances (rules out collapse-to-origin), correctly bp-colored. Materialized active
  instance (Phase 7c) inherits Phase A automatically.
  - **Test gotcha:** can't frame the camera from `getBoundingBox()` or the impostor mesh bbox (geometry
    sits at origin; positions are GPU/texture-composed — LESSONS D4). Frame from the store's instance
    `transform.values` (row-major; translation at `[3],[7],[11]`) instead. Hide the busy overlay
    (`#op-progress`) before screenshotting.

> **Remaining:** Phase C (atomistic atoms) + the photo-mode real-sphere revert path (still TODO).
- Verify on a large `.nass`; `traceFrame()` before/after for triangle drop.

### Phase C — Atomistic atoms (`atomistic_renderer/`)              [TODO]
- Per-element atom InstancedMesh (`atomistic_renderer.js:106`) → quad + impostor material, radius as
  per-mesh uniform (radius is per-element). Per-instance CPK color already present. Ball-stick BONDS
  stay real cylinders for v1. NOTE: this impostors the per-instance/per-part atomistic renderer
  (design view + part context = immediate win). Atomistic AT ASSEMBLY SCALE additionally needs
  atomistic on the shared path (today vdw/ballstick → grey hull box, `assembly_renderer.js:332`) —
  separate effort where the "drop base atoms" idea (~1.8×) plugs in.

### Photo-mode revert path                                        [TODO]
- On photo-mode enter, rebuild impostor meshes with real `GEO_SPHERE` + PBR material (reuse the
  material-swap rebuild + Phase-7d `applySharedInstancing` re-apply hook); revert on exit. Figures
  stay bit-for-bit identical to today.
- **NOTE (2026-05-22):** a SEPARATE concern — that the real (non-impostor) sphere/cylinder geometry
  is low-poly (10×8) and exported faceted — was fixed independently via an export-only high-detail
  geometry swap (`_withHighDetailGeometry`, see [[photo-mode]]). That handles the *default* (impostors
  off) figure-quality problem. This revert path is still needed only for when the **impostors flag is
  ON** at export time (beads = quads → export should use real high-detail spheres instead).

## Risks / caveats
- **Silhouette aliasing** — MSAA (`scene.js:38` `antialias:true`) smooths geometry edges but not
  discard-edges, so sphere outlines can look slightly jagged in interactive view. Neutralized for
  figures by the photo-mode-real-spheres decision; soft disc-edge fade mitigates if it bothers.
- **Depth-write fragment cost** — disables early-z; correct tradeoff for a vertex-bound scene.
- **Picking override scoped to design view** — assembly per-bead picking already deferred/by-instance
  (Phase 7), so no new picking work on the shared path.

## Verification
- `__NADOC_DBG__.traceFrame()` (`main.js:233`) prints draw calls + triangle count — use before/after
  each phase to confirm the triangle drop and FPS gain are real, not estimated.
- Verification design: **`workspace/teeth.nadoc`** (user-specified 2026-05-22) for part-view checks.
