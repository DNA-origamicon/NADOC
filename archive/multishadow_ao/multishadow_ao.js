/**
 * Multishadow ambient occlusion — view-independent geometric occlusion from N
 * directions, ported from ChimeraX's `lighting soft` / `full` ambient shadows.
 *
 * WHY NOT SSAO/GTAO. Screen-space AO can only be occluded by what is currently
 * on screen and in front of the depth buffer, so occlusion changes as you orbit,
 * haloes at silhouettes, and breaks across the tiles of a high-resolution export
 * — a tile cannot see an occluder outside its own frustum. Multishadow bakes
 * occlusion in WORLD space, once, and has none of those failure modes.
 *
 * THE ALGORITHM (from ChimeraX `graphics/opengl.py::Multishadow` + the
 * USE_MULTISHADOW block of its fragmentShader.txt):
 *
 *   1. N uniformly distributed directions on the sphere (64 default).
 *   2. An orthographic DEPTH-ONLY render along each, all into ONE tiled depth
 *      texture — a ceil(sqrt(N))² grid.
 *   3. Keep the N world→shadow matrices. They do not depend on the camera, so
 *      the bake is reused every frame — ORBITING IS FREE. Re-run only when the
 *      geometry changes.
 *   4. Per pixel, accumulate COSINE-WEIGHTED visibility `max(dot(N,-L),0) * lit`
 *      over all directions, normalised by `0.25 * count` (0.25 = the mean of the
 *      cosine weight over the sphere, so unoccluded lands at 1.0).
 *
 * The cosine weight is what makes this read as diffuse illumination rather than
 * dirt in the creases — it is a Lambertian hemisphere integral.
 *
 * WORKS FOR EVERY REPRESENTATION — the load-bearing design choice. The bake
 * renders each mesh with its OWN material, NOT through `scene.overrideMaterial`.
 * An override is what breaks sphere impostors and shared-renderer LOD instancing
 * (both compose their instance transform in a custom vertex shader the override
 * lacks, so they collapse to the source origin — see the exclusion list in
 * figure_pass.js). Letting every mesh run its own vertex shader means beads,
 * slabs, cones, cylinders, atoms, bonds, the marching-cubes surface, hull prisms
 * and impostors all write correct depth with no per-representation casing. Same
 * for the screen pre-pass, whose normals are therefore derived from depth.
 *
 * SCALE CAVEAT — read before tuning. ChimeraX's map-size defaults are sized for
 * a ~5 nm protein. At 64 directions a 1024 atlas gives each direction only
 * 128 px, which on a 150 nm origami is ~2.3 nm/texel — coarser than a 2.0 nm
 * duplex, so the occlusion cannot resolve one helix and long-range shadowing
 * degenerates into a wash. Origami wants 4096+. See
 * photo_mode_ao_and_lowpoly_spec.md.
 */

import * as THREE from 'three'
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js'
import { computeShadowBounds, isShadowExcluded, rejectedObjects, sceneSignature }
  from './shadow_bounds.js'

/** Compile-time ceiling on the shader's direction loop (GLSL ES 1.00 needs a
 *  constant bound; the runtime count breaks out early). */
export const MAX_DIRECTIONS = 256

/** Raw depth at or above this is the far plane → background, not geometry. */
const BACKGROUND_DEPTH = 0.999999

/** Ortho box margin so no scene point lands exactly on a tile edge. */
const FRUSTUM_MARGIN = 1.02

/** How often (in rendered frames) to re-fingerprint the scene. ~0.5 s at 60 fps. */
const SIGNATURE_CHECK_FRAMES = 30

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/**
 * `n` roughly-uniformly distributed unit vectors on the sphere (Fibonacci
 * lattice). Any low-discrepancy spherical set works — what matters is that no
 * hemisphere is over-sampled, because a biased set tilts the occlusion like a
 * directional light.
 */
export function fibonacciSphereDirections(n) {
  const count = Math.max(1, Math.floor(n))
  const out = []
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i++) {
    const y = 1 - (2 * i + 1) / count          // in (-1, 1), never exactly ±1
    const r = Math.sqrt(Math.max(0, 1 - y * y))
    const t = golden * i
    out.push([Math.cos(t) * r, y, Math.sin(t) * r])
  }
  return out
}

/**
 * How `count` shadow maps tile one square texture. `size` is `grid * tile`,
 * which can sit slightly below `mapSize` so there is never a partial tile.
 */
export function tileLayout(count, mapSize) {
  const n    = Math.max(1, Math.floor(count))
  const grid = Math.ceil(Math.sqrt(n))
  const tile = Math.max(8, Math.floor(mapSize / grid))
  return { grid, tile, size: grid * tile }
}

/**
 * Point the shadow camera along `dir` at the scene bounding sphere and return
 * the world→shadow matrix (bias × projection × view), mapping any point inside
 * the sphere into [0,1]³. `dir` is the direction light TRAVELS.
 */
export function configureShadowCamera(camera, dir, center, radius) {
  const r = Math.max(radius, 1e-6) * FRUSTUM_MARGIN
  camera.left = -r; camera.right = r
  camera.top  =  r; camera.bottom = -r
  camera.near = 0;  camera.far    = 2 * r

  camera.position.set(
    center.x - dir[0] * r,
    center.y - dir[1] * r,
    center.z - dir[2] * r,
  )
  // `up` must not be parallel to the view direction or lookAt degenerates.
  if (Math.abs(dir[1]) > 0.99) camera.up.set(0, 0, 1)
  else                         camera.up.set(0, 1, 0)
  camera.lookAt(center)
  camera.updateMatrixWorld(true)
  camera.updateProjectionMatrix()

  const bias = new THREE.Matrix4().set(   // NDC [-1,1] → texture [0,1]
    0.5, 0,   0,   0.5,
    0,   0.5, 0,   0.5,
    0,   0,   0.5, 0.5,
    0,   0,   0,   1,
  )
  return new THREE.Matrix4()
    .multiplyMatrices(bias, camera.projectionMatrix)
    .multiply(camera.matrixWorldInverse)
}

/**
 * Skip shadow-map rendering for the duration of an internal scene render,
 * WITHOUT touching `renderer.shadowMap.enabled`. Returns a restore function.
 *
 * DO NOT "simplify" this to `shadowMap.enabled = false` — that is a silent,
 * total break of the key-light shadow, and no headless test can see it:
 *
 *   • `shadowMapEnabled: renderer.shadowMap.enabled && shadows.length > 0` is a
 *     PROGRAM PARAMETER (WebGLPrograms.js) — it compiles `USE_SHADOWMAP` in.
 *   • `WebGLRenderer.setProgram`'s recompile checks cover colorSpace, batching,
 *     instancing, skinning, envMap … but NOT `shadowMap.enabled`.
 *
 * A bake that flips the flag off renders the whole scene — where every material
 * first compiles — into programs with no shadow sampling. Restoring the flag
 * afterwards recompiles nothing, so the beauty pass reuses shadow-less programs
 * for the rest of the session. `WebGLShadowMap.render()` early-returns on
 * `autoUpdate === false && needsUpdate === false` without consulting `enabled`.
 */
function _suspendShadowMapUpdates(renderer) {
  const sm = renderer?.shadowMap
  if (!sm) return () => {}
  const prevAuto  = sm.autoUpdate
  const prevNeeds = sm.needsUpdate
  sm.autoUpdate  = false
  sm.needsUpdate = false
  return () => { sm.autoUpdate = prevAuto; sm.needsUpdate = prevNeeds }
}

// ── Material-side consumption (the `lighting full` path) ─────────────────────

/**
 * Apply the baked occlusion INSIDE the material, to the indirect (ambient/IBL)
 * term only — leaving key and fill light untouched.
 *
 * WHY A SECOND CONSUMPTION PATH. The composer pass multiplies the finished
 * image, darkening direct light too. Under an ambient-only rig those are
 * identical (there IS no direct light). Under `full` they are not: the key light
 * would be multiplied by occlusion as well as being shadowed by its own shadow
 * map, double-darkening exactly where the directional shadow already falls.
 * ChimeraX keeps them strictly separate — `Iamb = fcolor * ambient * mshadow`
 * for occlusion, `key_light_diffuse_color * key_factor * shadow` for the key.
 *
 * Injection point is three's own `<aomap_fragment>`, which sits after
 * `<lights_fragment_end>` and already does the right thing:
 * `reflectedLight.indirectDiffuse *= ambientOcclusion`. We keep its body and
 * only change where `ambientOcclusion` comes from.
 *
 * TRADE-OFF vs the pass: only patched materials get occluded, so sphere
 * impostors and shared LOD impostors are NOT occluded on this path (the pass
 * covered them, working in screen space on any pixel).
 */
export function createMaterialOcclusion(pass) {
  const p = pass.uniforms
  // Bake-side uniforms are SHARED BY REFERENCE with the pass, so a re-bake
  // reaches every patched material with no per-material bookkeeping.
  const uniforms = {
    tShadow:    p.tShadow,
    tMatrices:  p.tMatrices,
    uCount:     p.uCount,
    uRows:      p.uRows,
    uGrid:      p.uGrid,
    uTileUV:    p.uTileUV,
    uTileInset: p.uTileInset,
    uBias:      p.uBias,
    // Owned here: the pass's own uIntensity gates its screen composite, which
    // must stay off while this path drives.
    uMSIntensity:   { value: 1.0 },
    // View→world rotation, so the fragment's view-space `geometryNormal` can be
    // taken into the world space the shadow matrices live in.
    uMSViewToWorld: { value: new THREE.Matrix3() },
  }

  const VERT_DECL = /* glsl */`
    varying vec3 vMSWorldPos;
  `

  // Mirrors three's <worldpos_vertex>, but unconditional: that chunk only
  // defines `worldPosition` when an env map / shadow map / transmission is in
  // play, and we must not depend on whether the key shadow happens to be on.
  const VERT_BODY = /* glsl */`
    #include <worldpos_vertex>
    vec4 _msWorld = vec4( transformed, 1.0 );
    #ifdef USE_BATCHING
      _msWorld = batchingMatrix * _msWorld;
    #endif
    #ifdef USE_INSTANCING
      _msWorld = instanceMatrix * _msWorld;
    #endif
    vMSWorldPos = ( modelMatrix * _msWorld ).xyz;
  `

  const FRAG_DECL = /* glsl */`
    uniform sampler2D tShadow;
    uniform sampler2D tMatrices;
    uniform int   uCount;
    uniform float uRows;
    uniform float uGrid;
    uniform float uTileUV;
    uniform float uTileInset;
    uniform float uBias;
    uniform float uMSIntensity;
    uniform mat3  uMSViewToWorld;
    varying vec3  vMSWorldPos;

    vec4 msFetch(float col, float row) {
      return texture2D(tMatrices, vec2((col + 0.5) / 5.0, (row + 0.5) / uRows));
    }

    float msOcclusion(vec3 Pw, vec3 Nw) {
      float sum = 0.0;
      for (int i = 0; i < ${MAX_DIRECTIONS}; i++) {
        if (i >= uCount) break;
        float row = float(i);
        vec3 L = msFetch(4.0, row).xyz;
        float w = max(dot(Nw, -L), 0.0);
        if (w <= 0.0) continue;
        mat4 M = mat4(
          msFetch(0.0, row), msFetch(1.0, row),
          msFetch(2.0, row), msFetch(3.0, row)
        );
        vec4 sc = M * vec4(Pw, 1.0);
        vec3 s  = sc.xyz / sc.w;
        vec2 cell = vec2(mod(row, uGrid), floor(row / uGrid));
        vec2 uvT  = (cell + clamp(s.xy, uTileInset, 1.0 - uTileInset)) * uTileUV;
        sum += w * step(s.z - uBias, texture2D(tShadow, uvT).x);
      }
      return clamp(sum / (0.25 * float(uCount)), 0.0, 1.0);
    }
  `

  // Replaces <aomap_fragment>. Body kept verbatim from three r172 so clearcoat,
  // sheen and specular occlusion keep behaving; only the source of
  // `ambientOcclusion` differs.
  const FRAG_BODY = /* glsl */`
    float ambientOcclusion = mix(
      1.0,
      msOcclusion( vMSWorldPos, normalize( uMSViewToWorld * geometryNormal ) ),
      uMSIntensity
    );

    reflectedLight.indirectDiffuse *= ambientOcclusion;

    #if defined( USE_CLEARCOAT )
      clearcoatSpecularIndirect *= ambientOcclusion;
    #endif

    #if defined( USE_SHEEN )
      sheenSpecularIndirect *= ambientOcclusion;
    #endif

    #if defined( USE_ENVMAP ) && defined( STANDARD )
      float dotNV = saturate( dot( geometryNormal, geometryViewDir ) );
      reflectedLight.indirectSpecular *= computeSpecularOcclusion( dotNV, ambientOcclusion, material.roughness );
    #endif
  `

  function apply(material) {
    if (!material || material.userData?.msOcclusionApplied) return material
    const prior = material.onBeforeCompile
    material.onBeforeCompile = (shader, renderer) => {
      prior?.(shader, renderer)
      Object.assign(shader.uniforms, uniforms)
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>\n${VERT_DECL}`)
        .replace('#include <worldpos_vertex>', VERT_BODY)
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>\n${FRAG_DECL}`)
        .replace('#include <aomap_fragment>', FRAG_BODY)
    }
    // Without a distinct key three would hand this material a cached program
    // compiled from the UNPATCHED source when the parameters happen to match.
    material.customProgramCacheKey = () => 'multishadowAO'
    material.userData.msOcclusionApplied = true
    material.needsUpdate = true
    return material
  }

  return {
    uniforms,
    apply,
    setIntensity(v) { uniforms.uMSIntensity.value = Math.max(0, Math.min(2, v)) },
    /** Refresh the view→world rotation. Cheap; call once per frame. */
    syncCamera(camera) {
      camera.updateMatrixWorld()
      uniforms.uMSViewToWorld.value.setFromMatrix4(camera.matrixWorld)
    },
  }
}

// ── Shader ───────────────────────────────────────────────────────────────────

export const MultishadowShader = {
  uniforms: {
    tDiffuse:   { value: null },
    tDepth:     { value: null },   // this pass's own scene-depth pre-pass
    tShadow:    { value: null },   // the tiled bake
    tMatrices:  { value: null },   // 5 × N float texture: 4 matrix columns + direction
    resolution: { value: new THREE.Vector2(1, 1) },
    uInvProjection: { value: new THREE.Matrix4() },
    uCameraWorld:   { value: new THREE.Matrix4() },
    uCount:     { value: 64 },
    uRows:      { value: 64 },
    uGrid:      { value: 8 },
    uTileUV:    { value: 1 / 8 },
    uTileInset: { value: 1 / 128 },
    uBias:      { value: 0.01 },   // fraction of scene diameter
    uIntensity: { value: 1.0 },
  },

  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,

  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform sampler2D tDepth;
    uniform sampler2D tShadow;
    uniform sampler2D tMatrices;
    uniform vec2  resolution;
    uniform mat4  uInvProjection;
    uniform mat4  uCameraWorld;
    uniform int   uCount;
    uniform float uRows;
    uniform float uGrid;
    uniform float uTileUV;
    uniform float uTileInset;
    uniform float uBias;
    uniform float uIntensity;

    varying vec2 vUv;

    const float BACKGROUND_DEPTH = ${BACKGROUND_DEPTH};

    vec3 viewPosAt(vec2 uv, float d) {
      vec4 ndc = vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
      vec4 vp  = uInvProjection * ndc;
      return vp.xyz / vp.w;
    }

    vec4 fetchM(float col, float row) {
      return texture2D(tMatrices, vec2((col + 0.5) / 5.0, (row + 0.5) / uRows));
    }

    void main() {
      vec4 base = texture2D(tDiffuse, vUv);
      // Intensity 0 is the pass-through path (also how the pass blits when the
      // bake is unavailable) — return before touching tDepth, which may be unset.
      if (uIntensity <= 0.0) { gl_FragColor = base; return; }

      float d = texture2D(tDepth, vUv).x;
      // Background left exactly as it came in, so a transparent background stays
      // transparent.
      if (d >= BACKGROUND_DEPTH) { gl_FragColor = base; return; }

      vec2 texel = 1.0 / resolution;
      vec3 P = viewPosAt(vUv, d);

      // View normal from depth. Derived rather than read from a normal pre-pass
      // so impostors and custom-instancing meshes (which no override material
      // can reproduce) get correct normals too. Picking the CLOSER of each
      // neighbour pair keeps the normal sane across silhouettes, where a plain
      // dFdx/dFdy would straddle a depth discontinuity.
      float dl = texture2D(tDepth, vUv - vec2(texel.x, 0.0)).x;
      float dr = texture2D(tDepth, vUv + vec2(texel.x, 0.0)).x;
      float dd = texture2D(tDepth, vUv - vec2(0.0, texel.y)).x;
      float du = texture2D(tDepth, vUv + vec2(0.0, texel.y)).x;

      vec3 Px = (abs(dr - d) < abs(d - dl))
        ? viewPosAt(vUv + vec2(texel.x, 0.0), dr) - P
        : P - viewPosAt(vUv - vec2(texel.x, 0.0), dl);
      vec3 Py = (abs(du - d) < abs(d - dd))
        ? viewPosAt(vUv + vec2(0.0, texel.y), du) - P
        : P - viewPosAt(vUv - vec2(0.0, texel.y), dd);

      vec3 Nv = cross(Px, Py);
      float nl = length(Nv);
      if (nl < 1e-12) { gl_FragColor = base; return; }
      Nv /= nl;
      if (Nv.z < 0.0) Nv = -Nv;              // always face the camera

      vec3 Pw = (uCameraWorld * vec4(P, 1.0)).xyz;
      vec3 Nw = normalize(mat3(uCameraWorld) * Nv);

      float sum = 0.0;
      for (int i = 0; i < ${MAX_DIRECTIONS}; i++) {
        if (i >= uCount) break;
        float row = float(i);

        vec3 L = fetchM(4.0, row).xyz;         // direction the light travels
        float w = max(dot(Nw, -L), 0.0);       // Lambertian weight
        if (w <= 0.0) continue;                // back-facing: contributes nothing

        mat4 M = mat4(
          fetchM(0.0, row), fetchM(1.0, row),
          fetchM(2.0, row), fetchM(3.0, row)
        );
        vec4 sc = M * vec4(Pw, 1.0);
        vec3 s  = sc.xyz / sc.w;               // [0,1]³ inside the shadow frustum

        vec2 cell = vec2(mod(row, uGrid), floor(row / uGrid));
        vec2 uvT  = (cell + clamp(s.xy, uTileInset, 1.0 - uTileInset)) * uTileUV;

        float nearest = texture2D(tShadow, uvT).x;
        sum += w * step(s.z - uBias, nearest);  // 1 when nothing is in front
      }

      // 0.25 is the mean of max(dot(N,-L),0) over uniformly distributed L, so a
      // fully unoccluded surface normalises to 1.0.
      float vis = clamp(sum / (0.25 * float(uCount)), 0.0, 1.0);
      gl_FragColor = vec4(base.rgb * mix(1.0, vis, uIntensity), base.a);
    }
  `,
}

// ── The pass ─────────────────────────────────────────────────────────────────

export class MultishadowAOPass extends Pass {
  constructor(scene, camera, opts = {}) {
    super()
    this.scene  = scene
    this.camera = camera
    this.needsSwap = true

    this._count     = opts.directions ?? 64
    this._mapSize   = opts.mapSize    ?? 4096
    this._intensity = opts.intensity  ?? 1.0
    this._bias      = opts.bias       ?? 0.01

    this._stale     = true
    this._ready     = false
    this._bakeRT    = null
    this._matrixTex = null
    this._shadowCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2)
    this._lastBake  = { count: 0, ms: 0, radius: 0 }
    this._signature = null       // scene fingerprint the current bake describes
    this._sigFrame  = 0
    this._rejected  = new Set()  // objects too large to belong to the structure

    // Scene-depth pre-pass. DepthStencilFormat + UnsignedInt248Type is the
    // driver-safe combination this codebase settled on; a pass-OWNED target is
    // the safe pattern (never attach depth to the composer's main target).
    this._prepassRT = new THREE.WebGLRenderTarget(1, 1, {
      minFilter: THREE.NearestFilter,
      magFilter: THREE.NearestFilter,
      type: THREE.UnsignedByteType,
    })
    this._prepassRT.depthTexture = new THREE.DepthTexture(1, 1)
    this._prepassRT.depthTexture.format = THREE.DepthStencilFormat
    this._prepassRT.depthTexture.type   = THREE.UnsignedInt248Type

    this._material = new THREE.ShaderMaterial({
      uniforms:       THREE.UniformsUtils.clone(MultishadowShader.uniforms),
      vertexShader:   MultishadowShader.vertexShader,
      fragmentShader: MultishadowShader.fragmentShader,
    })
    this._fsQuad = new FullScreenQuad(this._material)

    this._hidden = []
    this._applyUniforms()
  }

  get uniforms() { return this._material.uniforms }

  // ── Settings ───────────────────────────────────────────────────────────────

  setDirections(n) {
    const v = Math.max(1, Math.min(MAX_DIRECTIONS, Math.floor(n)))
    if (v === this._count) return
    this._count = v
    this._stale = true
  }

  setMapSize(px) {
    const v = Math.max(64, Math.floor(px))
    if (v === this._mapSize) return
    this._mapSize = v
    this._stale = true
  }

  setIntensity(v) {
    this._intensity = Math.max(0, Math.min(2, v))
    this._material.uniforms.uIntensity.value = this._intensity
  }

  /** Depth bias as a fraction of the scene DIAMETER (ChimeraX msDepthBias). */
  setBias(v) {
    this._bias = Math.max(0, v)
    this._material.uniforms.uBias.value = this._bias
  }

  /** Mark the bake stale. NOT needed on camera moves — the whole point of this
   *  technique is that the bake is view-independent. Mesh replacement is caught
   *  automatically by the scene fingerprint. */
  invalidate() { this._stale = true }

  isStale()  { return this._stale }
  isReady()  { return this._ready }
  lastBake() { return { ...this._lastBake } }

  getSettings() {
    return {
      directions: this._count,
      mapSize:    this._mapSize,
      intensity:  this._intensity,
      bias:       this._bias,
    }
  }

  _applyUniforms() {
    const u = this._material.uniforms
    u.uIntensity.value = this._intensity
    u.uBias.value      = this._bias
    u.uCount.value     = this._count
  }

  // ── Bake ───────────────────────────────────────────────────────────────────

  /** Safe to call every frame — returns immediately unless stale. Periodically
   *  re-fingerprints the scene so a geometry change nobody announced (a
   *  representation switch) still invalidates. */
  ensureBaked(renderer) {
    if (!this._stale && ++this._sigFrame >= SIGNATURE_CHECK_FRAMES) {
      this._sigFrame = 0
      if (sceneSignature(this.scene) !== this._signature) this._stale = true
    }
    if (!this._stale) return this._ready
    this.bake(renderer)
    return this._ready
  }

  bake(renderer) {
    const t0 = (typeof performance !== 'undefined' ? performance.now() : 0)
    this._stale = false
    this._sigFrame = 0
    this._signature = sceneSignature(this.scene)

    const bounds = computeShadowBounds(this.scene)
    if (!bounds) { this._ready = false; return }
    // Anything the bounds rejected must not be drawn into the maps either — a
    // 100 µm plane fitted OUT of the frustum would still occlude from below.
    this._rejected = rejectedObjects(bounds)

    const { grid, tile, size } = tileLayout(this._count, this._mapSize)
    this._ensureBakeTargets(size)

    const dirs = fibonacciSphereDirections(this._count)
    const data = this._matrixTex.image.data

    const prevRT        = renderer.getRenderTarget()
    const prevAutoClear = renderer.autoClear
    const prevBg        = this.scene.background
    const prevOverride  = this.scene.overrideMaterial

    this._hideExcluded()
    this.scene.background       = null
    this.scene.overrideMaterial = null   // all-reps rule, see module header
    const restoreShadowUpdate   = _suspendShadowMapUpdates(renderer)

    try {
      // One full clear (depth → 1) up front; each tile then renders into its own
      // scissored region, so no per-tile clear is needed.
      const rt = this._bakeRT
      rt.scissorTest = false
      rt.viewport.set(0, 0, size, size)
      rt.scissor.set(0, 0, size, size)
      renderer.setRenderTarget(rt)
      renderer.clear(true, true, false)
      renderer.autoClear = false

      for (let i = 0; i < this._count; i++) {
        const m = configureShadowCamera(this._shadowCam, dirs[i], bounds.center, bounds.radius)

        const x = (i % grid) * tile
        const y = Math.floor(i / grid) * tile
        // Drive the viewport through the render target, NOT renderer.setViewport
        // — the latter multiplies by devicePixelRatio, which would scale the tile
        // off its cell on a HiDPI display.
        rt.viewport.set(x, y, tile, tile)
        rt.scissor.set(x, y, tile, tile)
        rt.scissorTest = true
        renderer.setRenderTarget(rt)
        renderer.render(this.scene, this._shadowCam)

        const o = i * 20
        for (let k = 0; k < 16; k++) data[o + k] = m.elements[k]
        data[o + 16] = dirs[i][0]
        data[o + 17] = dirs[i][1]
        data[o + 18] = dirs[i][2]
        data[o + 19] = 0
      }
      this._matrixTex.needsUpdate = true
      this._ready = true
    } finally {
      renderer.autoClear = prevAutoClear
      restoreShadowUpdate()
      this.scene.background = prevBg
      this.scene.overrideMaterial = prevOverride
      this._restoreHidden()
      this._bakeRT.scissorTest = false
      this._bakeRT.viewport.set(0, 0, size, size)
      this._bakeRT.scissor.set(0, 0, size, size)
      renderer.setRenderTarget(prevRT)
    }

    const u = this._material.uniforms
    u.tShadow.value    = this._bakeRT.depthTexture
    u.tMatrices.value  = this._matrixTex
    u.uCount.value     = this._count
    u.uRows.value      = this._count
    u.uGrid.value      = grid
    u.uTileUV.value    = 1 / grid
    u.uTileInset.value = 1 / tile

    this._lastBake = {
      count:  this._count,
      ms:     Math.round(((typeof performance !== 'undefined' ? performance.now() : 0) - t0) * 10) / 10,
      radius: bounds.radius,
    }
  }

  _ensureBakeTargets(size) {
    if (!this._bakeRT || this._bakeRT.width !== size) {
      this._bakeRT?.depthTexture?.dispose()
      this._bakeRT?.dispose()
      this._bakeRT = new THREE.WebGLRenderTarget(size, size, {
        minFilter: THREE.NearestFilter,
        magFilter: THREE.NearestFilter,
        type: THREE.UnsignedByteType,
        depthBuffer: true,
      })
      this._bakeRT.depthTexture = new THREE.DepthTexture(size, size)
      this._bakeRT.depthTexture.format    = THREE.DepthStencilFormat
      this._bakeRT.depthTexture.type      = THREE.UnsignedInt248Type
      this._bakeRT.depthTexture.minFilter = THREE.NearestFilter
      this._bakeRT.depthTexture.magFilter = THREE.NearestFilter
    }
    // 5 texels per direction: 4 matrix columns + the light direction.
    if (!this._matrixTex || this._matrixTex.image.height !== this._count) {
      this._matrixTex?.dispose()
      const tex = new THREE.DataTexture(
        new Float32Array(this._count * 5 * 4), 5, this._count,
        THREE.RGBAFormat, THREE.FloatType,
      )
      tex.minFilter = THREE.NearestFilter
      tex.magFilter = THREE.NearestFilter
      tex.generateMipmaps = false
      tex.needsUpdate = true
      this._matrixTex = tex
    }
  }

  _hideExcluded() {
    this._hidden.length = 0
    this.scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh && !obj.isSprite) || !obj.visible) return
      if (!isShadowExcluded(obj) && !this._rejected?.has(obj)) return
      obj.visible = false
      this._hidden.push(obj)
    })
  }

  _restoreHidden() {
    for (const obj of this._hidden) obj.visible = true
    this._hidden.length = 0
  }

  // ── Composite ──────────────────────────────────────────────────────────────

  render(renderer, writeBuffer, readBuffer /* , deltaTime, maskActive */) {
    this.ensureBaked(renderer)

    if (!this._ready || this._intensity <= 0) {
      this._blit(renderer, writeBuffer, readBuffer)
      return
    }

    const prevRT       = renderer.getRenderTarget()
    const prevBg       = this.scene.background
    const prevOverride = this.scene.overrideMaterial

    this._hideExcluded()
    this.scene.background       = null
    this.scene.overrideMaterial = null
    const restoreShadowUpdate   = _suspendShadowMapUpdates(renderer)
    try {
      renderer.setRenderTarget(this._prepassRT)
      renderer.clear(true, true, false)
      renderer.render(this.scene, this.camera)
    } finally {
      restoreShadowUpdate()
      this.scene.background       = prevBg
      this.scene.overrideMaterial = prevOverride
      this._restoreHidden()
      renderer.setRenderTarget(prevRT)
    }

    const u = this._material.uniforms
    u.tDiffuse.value = readBuffer.texture
    u.tDepth.value   = this._prepassRT.depthTexture
    this.camera.updateMatrixWorld()
    // Invert here rather than reading `camera.projectionMatrixInverse`: that
    // cache is only refreshed by updateProjectionMatrix(), and main.js rewrites
    // near/far per frame — a stale inverse would smear the occlusion.
    u.uInvProjection.value.copy(this.camera.projectionMatrix).invert()
    u.uCameraWorld.value.copy(this.camera.matrixWorld)

    if (this.renderToScreen) {
      renderer.setRenderTarget(null)
    } else {
      renderer.setRenderTarget(writeBuffer)
      if (this.clear) renderer.clear()
    }
    this._fsQuad.render(renderer)
  }

  /** Copy read→write unchanged (used when there is nothing to occlude). */
  _blit(renderer, writeBuffer, readBuffer) {
    const u = this._material.uniforms
    u.tDiffuse.value   = readBuffer.texture
    const prevInt      = u.uIntensity.value
    u.uIntensity.value = 0
    if (this.renderToScreen) {
      renderer.setRenderTarget(null)
    } else {
      renderer.setRenderTarget(writeBuffer)
      if (this.clear) renderer.clear()
    }
    this._fsQuad.render(renderer)
    u.uIntensity.value = prevInt
  }

  setSize(width, height) {
    this._prepassRT.setSize(width, height)
    this._material.uniforms.resolution.value.set(width, height)
  }

  dispose() {
    this._prepassRT.depthTexture?.dispose()
    this._prepassRT.dispose()
    this._bakeRT?.depthTexture?.dispose()
    this._bakeRT?.dispose()
    this._matrixTex?.dispose()
    this._material.dispose()
    this._fsQuad.dispose()
  }
}
