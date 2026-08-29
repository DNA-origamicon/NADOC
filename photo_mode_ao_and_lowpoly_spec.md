# The ChimeraX "stunning" combination — what it actually is, and what NADOC needs

> ## CURRENT IMPLEMENTATION (2026-08-28)
>
> The multishadow ambient-occlusion experiment described below is **not active**.
> It was removed after origami-scale evaluation showed that its per-direction
> resolution produced a broad wash rather than useful duplex-scale occlusion.
> Shipping photomode has one shadow system: one camera-pinned directional key
> light with one PCF shadow map. Studio Ambient is PMREM image-based illumination
> only; diffuse ambient and fill lights cannot cast shadows. Runtime enforcement
> disables `castShadow` on every non-key light, including lights added after
> photomode activation, and restores their state on exit. Diagnostics expose
> `shadowCastingLights`, environment binding, and outline/depth-cue state so
> post-processing cannot be confused with a second shadow source.
>
> Assembly parity was audited on 2026-08-28. Shared assemblies now use the same
> measured-positioning payload as individual parts; Full-representation bead,
> cone, slab, and slab-connector transform multisets match BigO to five decimals.
> Shared rendering also includes crossover arcs and crossover insertion meshes,
> with live Strand/Cluster/Overhang-only coloring. See the regression tests in
> `frontend/e2e/bigo_assembly_geometry_parity.spec.js` and
> `frontend/e2e/assembly_photomode_shadow.spec.js`.

> ## HISTORICAL STATUS (2026-07-28) — multishadow AO was briefly shipped
>
> The 64-direction port below is live in the Exp. Photomode tab, alongside a
> camera-pinned key light with its own shadow map (§B.4a). It was briefly removed
> and then restored — removing it made the render worse.
>
> **The one number that decides whether any of this works: nm per shadow texel.**
> At 64 directions a 1024 atlas gives each direction only **128 px**, which on a
> 150 nm structure is **2.34 nm/texel** — coarser than a 2.0 nm duplex, so the
> occlusion cannot resolve a single helix and long-range shadowing collapses into
> a wash. ChimeraX's defaults are sized for a ~5 nm protein. Origami needs 4096+.
> The panel prints this live and warns when a texel exceeds a duplex.
>
> **Second rule, learned the hard way:** occlusion multiplies the AMBIENT term, so
> ambient occlusion and "max shadow contrast" (key 2.0 / fill 0 / ambient 0.15)
> are mutually exclusive by construction — at ambient 0.15 the AO is invisible.
>
> **Part A (low-poly geodesic spheres) is untouched and still open.**

**Scope:** the two things named as the priority — (A) low-poly atomistic spheres that hold up at a
distance, and (B) view-independent 64-direction ambient occlusion — plus the lighting/environment
consequences. Everything below about ChimeraX is read from its source, not from the manual.
No code changed.

**Sources read (ChimeraX `develop`):** `src/bundles/graphics/src/opengl.py` (the `Multishadow`
class, L1666–1815), `src/bundles/graphics/src/fragmentShader.txt` (the `USE_MULTISHADOW` block),
`src/bundles/surface/src/shapes.py` (`sphere_geometry`), plus the `lighting` / `graphics` command
docs and the RBVI ambient-occlusion writeup.

---

## Part 0 — The causal chain (why it looks good)

The ChimeraX house look is **not** one feature. It is five things that each hide the weakness of
the next, and removing any one collapses it:

1. **Geodesic spheres with normalized normals** — the *shading* is that of a mathematically perfect
   sphere at any triangle count. Only the silhouette betrays the poly count.
2. **64-direction ambient occlusion** — a low-frequency, cosine-weighted term. It reads as *form*
   and never reveals facets, because it varies over nanometres, not over triangles.
3. **AO drives the ambient term only, and `lighting soft` has nothing else** — so the AO *is* the
   image. No specular highlight to make plastic, no key light to fight it.
4. **Screen-space silhouettes** — a dark contour from the depth buffer, so the outline is smooth
   even where the geometry is faceted. This is what actually covers the low-poly silhouette.
5. **`supersample 3` on export** — 9× the pixels, downsampled. Averages away whatever facet edge
   and contour aliasing survived (4).

NADOC has (4). It has a *screen-space approximation* of (2) that behaves differently. It has none
of (1), (3), or (5).

---

## Part A — Low-poly spheres

### A.1 What ChimeraX does

`sphere_geometry(ntri)` in [`shapes.py`](https://github.com/RBVI/ChimeraX/blob/develop/src/bundles/surface/src/shapes.py):

```python
va, ta = icosahedron.icosahedron_geometry()
while 4*len(ta) <= ntri:
    va, ta = subdivide_triangles(va, ta)   # 20 → 80 → 320 → 1280 …
vn = sqrt((va*va).sum(axis=1))
for a in (0,1,2): va[:,a] /= vn            # all vertices onto the unit sphere
return va, va.copy(), ta                   # NORMALS == POSITIONS
```

Three properties, all load-bearing:

- **Icosahedral (geodesic), not UV.** Triangles are uniform over the sphere. A UV sphere spends a
  large fraction of its budget on degenerate slivers at the two poles and under-tessellates the
  equator — exactly the band that forms the silhouette in a typical view.
- **`normals = normalize(position)`.** Exact sphere normals. Diffuse and specular are pixel-correct
  at 20 triangles.
- **Auto triangle budget.** `graphics atomTriangles` is automatic in 10–2000 per atom against a
  `totalAtomTriangles 5000000` cap — LOD scales with how many atoms are on screen, not with a
  fixed constant.

Bonds/cylinders get the same treatment: `cylinder_geometry(nz=2, nc=10)`, `bondSides` auto 24–160.

### A.2 What NADOC does

| | geometry | triangles | vertices |
|---|---|---|---|
| Atoms, interactive | `SphereGeometry(1, 10, 8)` ([geometry_builder.js:28](frontend/src/scene/atomistic_renderer/geometry_builder.js#L28)) | 140 | 99 (indexed) |
| CG beads | `SphereGeometry(BEAD_RADIUS, 10, 8)` ([helix_renderer.js:77](frontend/src/scene/helix_renderer.js#L77)) | 140 | 99 |
| Fluorophores | `SphereGeometry(0.25, 12, 10)` | 216 | 143 |
| Bonds | `CylinderGeometry(1,1,1,6,1)` | 12 + caps | — |
| Export upgrade | `32×24` UV sphere ([main.js `_highDetailGeometries`](frontend/src/main.js)) | 1536 | 825 |

**UV spheres, every one.** A 10-segment UV sphere has a 10-gon equatorial silhouette — ~4.9 % radial
error — and burns ~20 of its 140 triangles on the two pole fans that are almost never visible.

### A.3 The direct fix — geodesic, indexed

```js
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js'
const SPHERE_GEO = mergeVertices(new THREE.IcosahedronGeometry(1, 2))
```

- `IcosahedronGeometry(1, d)` extends `PolyhedronGeometry`, which for `detail > 0` calls
  `normalizeNormals()` — i.e. **normals = normalized position**, identical to ChimeraX. (At
  `detail === 0` it flat-shades; don't use detail 0.) Verified in `node_modules/three@0.172`.
- `PolyhedronGeometry` emits **non-indexed** geometry, so `mergeVertices` is required or the vertex
  count triples. Merging is lossless here: co-located vertices share a normal by construction, and
  none of these materials sample UVs.

| detail | triangles | verts (indexed) | vs current 140 tri / 99 v |
|---|---|---|---|
| 1 | 80 | 42 | **43 % fewer tris, 58 % fewer verts**, rounder silhouette |
| 2 | 320 | 162 | 2.3× tris for a visibly round sphere — the photo-mode default |
| 3 | 1280 | 642 | replaces the 1536 tri / 825 v export upgrade at lower cost |

Detail 1 is a strict win for the interactive path. Detail 2 is the "looks good from a distance"
setting. Detail 3 replaces the export swap. **Cheap, low-risk, self-contained** — three shared
geometry constants and the `_highDetailGeometries` table.

### A.4 The bigger lever NADOC already owns — and a locked decision to revisit

[impostor_material.js](frontend/src/scene/impostor_material.js) already ray-paints spheres from a
2-triangle quad: exact normal `vec3(v_corner, sqrt(1-r²))`, exact `gl_FragDepth`. A **perfect
silhouette and perfect normals at any zoom, from 2 triangles** — strictly better than any low-poly
geometry, and better than what ChimeraX does.

It is not used in photo mode, by explicit decision:

> **"Photo mode keeps REAL spheres."** … *Consequence: the one impostor fidelity caveat (silhouette
> aliasing — MSAA doesn't smooth discard-edges) never reaches a figure.*
> — [project_sphere_impostors.md](memory/project_sphere_impostors.md), locked 2026-05-22

**That reasoning is worth re-opening now, because its premise is fixable.** The objection is
`discard`-edge aliasing, which MSAA cannot resolve. But:

- **Supersampled export (§C.3) resolves it exactly** — SSAA is post-rasterization averaging, so it
  smooths discard edges the same as any other edge. This is precisely how ChimeraX gets away with
  a 20-triangle sphere.
- The screen-space outline already draws over the silhouette.
- And there is a large second-order payoff: **impostors make the 64-direction AO bake ~70× cheaper**
  (§B.5). The two features are strongly synergistic.

Blockers if impostors do enter photo mode — all bounded:

1. They are excluded from the figure pre-pass (`userData.sharedLodImpostor` skip in
   [figure_pass.js](frontend/src/scene/photo_renderer/figure_pass.js)) because they collapse to the
   source origin under `MeshNormalMaterial` override → **no outline, no depth cue on impostors
   today**. Fix: an impostor-aware override material — the fragment shader already computes the
   view-space normal and the corrected depth; it needs to write them instead of Phong colour.
2. They are excluded from shadow casting (`material.userData.impostorRadius != null` skip).
   Same fix: a `customDepthMaterial` that billboards and writes `gl_FragDepth`.
3. They are `MeshPhongMaterial`-patched, so photo mode's `MeshPhysicalMaterial` swap doesn't apply.
   Either patch a physical material the same way, or accept Phong for impostor meshes.

**Recommendation:** do §A.3 unconditionally (it is nearly free and helps every path). Treat the
impostor question as a decision for the user — see §D.

---

## Part B — 64-direction view-independent ambient occlusion

### B.1 What ChimeraX actually does

Verified in `opengl.py` `class Multishadow` and the `USE_MULTISHADOW` block of `fragmentShader.txt`.

**Directions.** `sphere.sphere_points(n)` — uniformly distributed on the sphere. `n` = the
`multishadow` setting: **64** for `soft` and `full`, up to 1024 (hard cap
`GL_MAX_UNIFORM_BLOCK_SIZE / 64`, clamped to 2048).

**Storage — one tiled 2D depth texture, not an array:**

```python
d = int(ceil(sqrt(nl)))     # subtextures per axis
s = size // d               # subtexture size
for l in range(nl):
    x, y = (l % d), (l // d)
    r.set_viewport(x * s, y * s, s, s)
    lvinv, tf = r.shadow._shadow_transforms(light_directions[l], center, radius, bias)
    r.set_view_matrix(lvinv)
    mstf_array[l,:,:] = tf.matrix
    draw_depth(r, sdrawings, opaque_only = not mat.transparent_cast_shadows)
```

For `soft`: `msMapSize 1024`, n = 64 → d = 8 → **each of the 64 shadow maps is 128×128 pixels.**
`gentle` uses `msMapSize 128` → **16×16 each**. This is the surprise: the individual maps are
almost comically coarse. It works because you are averaging 64 of them — per-map noise cancels.
Each is an orthographic depth render covering the scene bounding sphere (`center`, `radius`).

**Matrices.** A `std140` UBO, 3×4 transforms, 64 bytes each:
```glsl
layout(std140) uniform shadow_matrix_block { mat4 shadow_transforms[MAX_SHADOWS]; };
uniform int shadow_count;
uniform float shadow_depth;
uniform sampler2DShadow multishadow_map;
```

**The fragment shader — this is the part that matters:**

```glsl
for (int i = 0 ; i < shadow_count ; ++i) {
    mat4 stf = shadow_transforms[i];
    vec3 shadow_tex_coord = (stf*vec4(v,1)).stp;
    vec3 light_direction = shadow_depth * vec3(stf[0][2], stf[1][2], stf[2][2]);
    float diffuse = max(-dot(N1, light_direction), 0.0);
    mshadow += diffuse * texture(multishadow_map, shadow_tex_coord);
}
mshadow /= 0.25*shadow_count;
...
vec3 Iamb = fcolor.rgb * ambient_color * mshadow;
```

Four details that are the whole trick:

- **`sampler2DShadow`** — hardware depth comparison with free 2×2 PCF. Each of the 64 taps is
  already bilinearly filtered against the depth test.
- **`diffuse = max(-dot(N, lightDir), 0)`** — the sum is **cosine-weighted**, a proper Lambertian
  hemisphere integral, not a binary occlusion average. This is why it reads as real diffuse
  illumination rather than as dirt in the creases.
- **`/= 0.25 * shadow_count`** — normalization; the 0.25 is the average of the cosine weight over
  the sphere, so a fully unoccluded surface lands at ≈1.
- **`Iamb = fcolor * ambient_color * mshadow`** — it modulates **the ambient term only**. Key and
  fill are untouched. Under `lighting soft` (ambient 1.5, directionals off) the AO is 100 % of
  the shading.

**View independence.** `_multishadow_transforms` is computed once and cached; `use_multishadow_map`
early-returns while `len(transforms) == len(directions)`. Each frame, `set_multishadow_view(camera)`
composes the cached transforms with the current camera — a matrix multiply, no re-render.
**Orbiting is free.** It re-bakes only when the lighting parameters change or geometry changes.

### B.2 Why this is categorically better than NADOC's GTAO

[post_processing.js:98](frontend/src/scene/photo_renderer/post_processing.js#L98) uses three.js
`GTAOPass` with `OUTPUT.Default`.

| | ChimeraX multishadow | NADOC GTAO |
|---|---|---|
| Occluders | all scene geometry | only what is on screen and in front of the depth buffer |
| View dependence | none — bake once, orbit free | recomputed every frame; occlusion changes as you orbit |
| Silhouette behaviour | correct | halos and leaks where geometry leaves the frustum |
| What it modulates | ambient only | the whole beauty pass, key light and specular included |
| Radius | true world-space, from the scene bounding sphere | `aoRadius` nm, but sampled in screen space |
| Tiled export | unaffected (world-space bake) | **seams** — a tile can't see occluders outside its frustum |
| Cost | one bake, then ~64 cached texture taps/px | full-res depth+normal reconstruction every frame |

The tiled-export row is worth calling out: NADOC's high-res export splits the image into
`setViewOffset` tiles, so a screen-space AO pass in tile 2 cannot see the helix that occludes it
from tile 1. Multishadow has no such failure mode — the bake is in world space.

### B.3 What it takes in three.js r172 — all primitives exist

1. **Directions** — Fibonacci sphere, 64 points. ~10 lines, pure, testable.
2. **Tiled depth target** —
   ```js
   const rt = new THREE.WebGLRenderTarget(1024, 1024)
   rt.depthTexture = new THREE.DepthTexture(1024, 1024)
   rt.depthTexture.format  = THREE.DepthFormat
   rt.depthTexture.type    = THREE.UnsignedIntType
   rt.depthTexture.compareFunction = THREE.LessEqualCompare   // ← makes it a sampler2DShadow
   ```
   `DepthTexture.compareFunction` exists in r172 (confirmed in `node_modules`). Setting it is what
   makes three.js declare the sampler as `sampler2DShadow` and give you free PCF.
   **Caveat:** the codebase has a documented hazard with `DepthFormat`+`UnsignedIntType` breaking
   `MeshPhysicalMaterial` compilation when transmission is active (see the inscatter gotcha in
   [project_photo_mode.md](memory/project_photo_mode.md)). That failure was for depth attached to
   the *composer's main target*; a pass-owned target is the safe pattern already used twice here.
   Verify early.
3. **The bake** — 64× { `renderer.setViewport(x*s, y*s, s, s)`; set an orthographic camera along
   direction *i* fitted to the scene bounding sphere; render depth-only into the shared target }.
   Note `renderer.setScissor` + `setScissorTest` must be used alongside `setViewport` so clears
   don't wipe neighbouring tiles.
4. **Matrix upload — use a DataTexture, not a uniform array.** 64 `mat4` = 256 vec4 uniforms, which
   is at or over the guaranteed fragment-uniform limit on some drivers. three.js exposes
   `UniformsGroup` (real UBOs), but a `THREE.DataTexture(Float32Array, 4, 64, RGBAFormat, FloatType)`
   read with `texelFetch` is simpler, has no limit, and scales to 256 directions for free.
5. **Consumption — two options:**
   - **(a) Material patch.** `onBeforeCompile` on the photo-mode `MeshPhysicalMaterial`, injecting
     the 64-tap loop into `<lights_fragment_end>` and multiplying `irradiance` (the ambient/IBL
     term) — the faithful equivalent of ChimeraX's `Iamb *= mshadow`. Correct, but touches every
     photo material and interacts with the existing translucency/emissive patches.
   - **(b) A composer pass.** Reconstruct world position + normal from the pass's own depth+normal
     pre-pass — **[figure_pass.js](frontend/src/scene/photo_renderer/figure_pass.js) already renders
     exactly this pre-pass** for the outline and depth cue — then multiply the beauty buffer by the
     occlusion. Far less invasive; can literally share `figure_pass`'s RT. **Recommended for v1.**
     Its one compromise is that, like GTAO, it multiplies the whole beauty pass rather than just
     ambient — mitigate by running the "publication" lighting (ambient-only) where that distinction
     vanishes, and revisit with (a) if the studio styles need it.
6. **Invalidation** — re-bake on: representation change, topology rebuild, simulation frame applied,
   cluster/unfold move, animation frame. Not on camera move. Photo mode already has the hook it
   needs: `_dirty` / `invalidate()` and `resyncMaterials()`.

### B.4 Cost, honestly

**Bake** = 64 depth-only renders of the whole scene.

| scene | tris | bake (≈500 M tri/s depth-only) |
|---|---|---|
| 7 kbp origami, CG `full` | ~2 M | 64 × 2 M = 128 M → **~0.3 s** |
| same, atomistic | ~40 M | 64 × 40 M = 2.6 G → **~5 s** |
| same, atomistic **with impostors** | ~0.6 M | → **~0.1 s** |

One-time, cached, on a user-driven action. 0.3 s is invisible; 5 s needs a progress toast; 0.1 s is
nothing. **This is the strongest argument for putting impostors in photo mode.**

**Per frame** = 64 `sampler2DShadow` taps per pixel from a 1024² texture that is fully cache-resident.
~130 M taps at 1080p; on any real GPU that is low single-digit milliseconds. On WSL software GL it
will be unusable — so this is another feature whose look is a user manual check, not a headless one
(consistent with the rest of photo mode).

**Fallback if the bake is too slow:** bake **per instance** instead of per fragment — one occlusion
scalar per bead/atom into an `InstancedBufferAttribute`. Per-frame cost drops to zero and the bake
gets much cheaper. The RBVI writeup quotes a density-grid variant at 0.007 s for a 100 k-atom
ribosome and 0.18 s for a 2.4 M-atom HIV capsid. Constant-AO-per-sphere is visually wrong at extreme
zoom (QuteMol uses per-patch textures for exactly this reason) but is *right* for the stated goal —
looking good from a distance. Worth keeping in the back pocket, not building first.

### B.4a `lighting full` — the SECOND shadow system (added 2026-07-28)

**Observed:** in ChimeraX `lighting full` the shadows move as you reorient the structure.
Nothing in the multishadow bake can do that — it is view-independent by construction. Traced to
source; there are three separate causes and we have none of them.

**1. `full` turns on a completely separate key-light shadow map.**
`std_commands/src/lighting.py`:

```python
elif preset == 'full':
    lp.shadows = True            # ← a directional shadow map, SEPARATE from multishadow
    lp.multishadow = ms_directions
    lp.key_light_intensity = 0.7
    lp.fill_light_intensity = 0.3
    lp.ambient_light_intensity = 0.8
elif preset == 'soft':
    lp.shadows = False           # ← ambient occlusion is the ONLY shadow
    lp.multishadow = ms_directions
    lp.key_light_intensity = 0
    lp.fill_light_intensity = 0
    lp.ambient_light_intensity = 1.5
```

One 2048² map (`shadow_map_size = 2048`, `shadow_depth_bias = 0.005` — twice as fine as
multishadow's 1024-shared-across-64 at bias 0.01). The two never touch each other in the shader:
multishadow multiplies **ambient only** (`Iamb = fcolor.rgb * ambient_color * mshadow`), the key
shadow multiplies **the key diffuse term only** (`key_light_diffuse_color * key_factor * shadow`).
Static occlusion underneath, dynamic directional shadow on top.

**2. The key light lives in CAMERA coordinates and is re-derived every frame.** This is the
orientation-dependence. `Lighting`'s own docstring: *"Directions are unit vectors in camera
coordinates (x right, y up, z opposite camera view)"*, with `move_lights_with_camera = True` as the
default. Then in `Shadow.use_shadow_map`:

```python
kl = lp.key_light_direction                            # (.577,-.577,-.577), CAMERA space
light_direction = camera.position.transform_vector(kl) # → scene space, every frame
```

The key light is nailed to the viewer's upper-left; ChimeraX's default drag rotates the *model*, so
the structure turns under a fixed light and the shadow sweeps across it.

**3. The invalidation policies are deliberately opposite** — this is the elegant part of the design
and worth copying exactly. In `view.py::check_for_drawing_change`:

```python
if dm.shadows_changed() or cp.changed:            # cp = CLIP PLANES, not the camera
    r.multishadow.multishadow_update_needed = True
```

Multishadow re-bakes on geometry or clip-plane changes and **never on a camera move** (a camera-only
change is tracked separately as `_cam_only_change`). The key shadow map, by contrast, is re-rendered
unconditionally on every draw. Expensive-and-static + cheap-and-dynamic, layered.

**What NADOC needs, in order:**

- **(i) Camera-pinned light rig.** Orient the rig by the camera's world quaternion each frame so the
  key/fill are fixed in screen space. One flag, no new passes, and it alone makes the *shading*
  rotate with the view. Note our fills are scene-fixed today, so even shadow-less orbiting feels
  dead compared with ChimeraX.
- **(ii) A key-light shadow map.** three.js gives this almost free: `DirectionalLight.castShadow`,
  `PCFSoftShadowMap`, ortho shadow camera fitted to the scene bounds. **The shipping photo mode
  already has the machinery** (`_enableRigShadows` / `_fitDirLightShadow` in photo_renderer.js) —
  it is only gated behind a floor being switched on
  ([photo_renderer.js:898](frontend/src/scene/photo_renderer.js#L898)). Ungate it here; self-shadowing
  on the structure is the whole point, and no ground plane is wanted.
  **Caveat:** three drives the shadow pass internally, so it uses each material's built-in depth
  material or `customDepthMaterial`. Impostors and shared-LOD instancing will NOT cast correct
  shadows — the same override-material problem the AO bake dodges with `colorWrite`, which is not
  available here. Those need a `customDepthMaterial` (§A.4 blocker 2).
- **(iii) The `full` mix — and this is where the v1 AO shortcut breaks.** Our AO is a composer pass
  that multiplies the WHOLE composited image (the documented §B.3 option-(b) compromise). Under
  `soft` (ambient-only) that is identical to ChimeraX. Under `full` it is **wrong**: the key light
  would get multiplied by occlusion too, double-darkening exactly where the directional shadow
  already is. Doing `full` properly means moving to §B.3 option (a) — patch `irradiance` in
  `<lights_fragment_end>` so occlusion modulates ambient/IBL only, leaving key and fill alone.

So `full` is not a preset we can add on top of what exists; it is the case that forces the
material-patch consumption path.

### B.5 Suggested parameters for DNA origami

ChimeraX's defaults are tuned for proteins at Å scale; NADOC works in nm.

- `multishadow` 64 (`soft`) — expose 32 / 64 / 128 as Fast / Normal / Fine.
- `msMapSize` 1024 → 128² per direction. For a bundle of 2 nm duplexes that resolves inter-helix
  crevices comfortably. Offer 2048 (256² each) for the export bake.
- `msDepthBias` 0.01 × scene diameter. On a 60 nm object that is 0.6 nm — larger than a bead radius.
  **Expect to retune this**; the origami case has much finer geometry relative to the bounding
  sphere than a globular protein does.
- The bounding sphere must exclude the floor plane and the photo helper groups — `floor.js`
  already maintains exactly that skip-list (`photoFloor`, sprites, line materials, impostors);
  reuse it, minus the impostor exclusion.

---

## Part C — The lighting/environment consequences

Reframing away from figure furniture, toward what actually makes the render:

### C.1 AO must drive ambient, and the style must strip everything else

ChimeraX `soft` is: **ambient 1.5, no key, no fill, no specular, AO on the ambient term.** NADOC's
closest is the `publication2` style (`lighting:'scientific'`, GTAO strong, outline off). Once real
AO lands, add a `soft`-equivalent style: `lighting:'ambient'` or a new ambient-only preset,
`ao:true` at high intensity, `ssao:false`, `bloom:false`, `environment:'off'` or low-intensity IBL,
flat materials. The AO *is* the lighting — that is the whole aesthetic.

### C.2 The missing IBL intensity control

The gap map flagged this; it matters more here. `scene.environment` contributes an uncontrolled
ambient term with no slider, so once AO modulates ambient, IBL and AO fight. **`envMapIntensity` as
one exposed setting** is a prerequisite for the AO work, not a nice-to-have.

### C.3 Supersampled export is now load-bearing, not polish

It was Tier B in the gap map. With low-poly spheres (facet edges) and possible impostor discard
edges, SSAA becomes the thing that makes both acceptable — exactly as it does for ChimeraX's
20-triangle spheres. Render each export tile at 2–3× and box-downsample on the CPU stitch canvas.
The tiling machinery in `renderToBlob` already does CPU-side compositing, so this is a change to
tile size + a downsample step, not new architecture. **It also fixes the outline-thickness scaling
problem** flagged in the gap map (§7), since the outline would be drawn at supersampled resolution
and averaged down.

### C.4 Cheap visual wins in the same area

- **A curated HDRI set.** `environment` is `off` / `room` / user file. Three or four bundled studio
  HDRIs (a soft overhead softbox, a rim-lit dark studio, a neutral grey room) would move the
  "stunning" needle for near-zero engineering. Bundle size is the only question.
- **Camera-pinned lighting** (ChimeraX `lighting moveWithCamera true`). NADOC's rig is scene-fixed,
  so orbiting changes the lighting and the user has to re-tune yaw/pitch per view. One flag.
- **Ungate shadows from the floor** — [photo_renderer.js:898](frontend/src/scene/photo_renderer.js#L898)
  requires `floor !== 'off'` for any shadow at all, so helix-on-helix cast shadow is impossible
  without a visible ground plane. One condition. Pairs with `lighting full` (key shadows *and*
  ambient shadows), which is the most dramatic ChimeraX preset.

---

## Part D — Recommended order, and the decisions needed

**Do first (cheap, unblocks the rest)**
1. Geodesic indexed spheres — §A.3. Small, self-contained, improves every path including interactive.
2. Ungate shadows from the floor — §C.4. One condition.
3. `envMapIntensity` control — §C.2. Prerequisite for AO to behave.

**The main build**
4. **Multishadow AO** — §B.3, as a composer pass sharing `figure_pass`'s depth+normal pre-pass.
   Direction set + tiled bake + DataTexture matrices + 64-tap consumption + invalidation hooks.
   Largest single visual win on this document.
5. **Supersampled export** — §C.3. Now load-bearing for (1) and (4), and fixes the outline-scaling defect.
6. A `soft`-equivalent style preset — §C.1. Trivial once (4) exists; it is what makes (4) legible.

**Conditional**
7. Impostors in photo mode — §A.4. **Blocked on a user decision** (see below). If yes, it makes (4)
   ~70× cheaper on atomistic scenes and unblocks "1000 parts at full detail."

### Decisions needed

1. **Re-open "photo mode keeps real spheres"?** The locked 2026-05-22 rationale was impostor
   discard-edge aliasing. Supersampled export (item 5) removes that objection, and impostors would
   make the AO bake cheap enough to use on atomistic scenes. Cost: an impostor-aware depth/normal
   override material and a `customDepthMaterial`. Worth it?
2. **AO consumption — pass (recommended) or material patch?** The pass is far less invasive and can
   share the existing pre-pass, but multiplies the whole beauty buffer rather than only the ambient
   term. Under ambient-only publication lighting the two are identical; they differ only in the
   studio/PBR styles. Accept the pass for v1?
3. **What is the heaviest scene this has to work on?** The bake cost swings from 0.3 s to 5 s
   between CG and atomistic. If atomistic-at-scale is the target, decision 1 effectively answers
   itself and the per-instance fallback (§B.4) moves up the list.
4. **Bundle HDRIs?** Adds to the frontend payload. Say roughly how much is acceptable.
