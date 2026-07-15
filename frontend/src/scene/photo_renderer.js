/**
 * Photo mode — core rendering engine.
 *
 * Responsibilities:
 *  - Swap all scene materials to MeshPhysicalMaterial on entry
 *  - Install a photo-mode lighting rig (saving and hiding original lights)
 *  - Build an EffectComposer (RenderPass → SSAO → SMAA → Bloom → Output)
 *  - Override the main render function via sceneCtx.setRenderFn
 *  - Optional: progressive path tracing via three-gpu-pathtracer
 *  - High-res PNG export via a dedicated offscreen renderer
 *  - Clean restore of all state on deactivate()
 *
 * Material-swap contract:
 *  InstancedMesh instance colours (instanceColor) work with any Three.js
 *  material — the per-instance colour multiplies with material.color.
 *  All photo materials set color=0xffffff so instance colours are preserved.
 *  Per-vertex colour attributes on the surface mesh are preserved via
 *  vertexColors:true, which is copied from the original material.
 *
 * Usage:
 *  const pr = createPhotoRenderer(sceneCtx)
 *  pr.activate(settings)
 *  pr.setLighting('studio')
 *  pr.setMaterialPreset('surface', 'gummy')
 *  const blob = await pr.renderToBlob(4200, 2970)
 *  pr.deactivate()
 */

import * as THREE from 'three'
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js'

import { PRESETS, makeMaterial, makeFluorophoreEmissive } from './photo_renderer/material_presets.js'
import { LIGHTING_PRESETS, applyLighting } from './photo_renderer/lighting_presets.js'
import { createComposer }                  from './photo_renderer/post_processing.js'
import { createFloor }                     from './photo_renderer/floor.js'
import { dollyDistanceForFov, PARALLEL_FOV, PERSPECTIVE_FOV } from './photo_renderer/figure_camera.js'
import { showToast }                       from '../ui/toast.js'
import { RoomEnvironment }                 from 'three/addons/environments/RoomEnvironment.js'
import { RGBELoader }                      from 'three/addons/loaders/RGBELoader.js'

const FLUORO_MESH_NAME = 'extensionFluorophores'

// ── Mesh name → representation mapping ───────────────────────────────────────

const MESH_NAME_TO_REPR = {
  backboneSpheres:           'full',
  backboneCubes:             'full',
  strandCones:               'full',
  baseSlabs:                 'full',
  extensionFluorophores:     'full',
  helixCylinders:            'cylinders',
  overhangCylinders:         'cylinders',
  overhangFullCylinders:     'cylinders',
  curvedHelixCylindersProxy: 'cylinders',
  curvedOverhangFullCylindersProxy: 'cylinders',
  curvedOvhgGroup:           'cylinders',
  'dna-surface':             'surface',
}

// Detect surface mesh by DoubleSide material when name doesn't match
function _inferRepr(obj) {
  if (obj.material?.side === THREE.DoubleSide) return 'surface'
  if (obj.material instanceof THREE.MeshStandardMaterial) return 'atomistic'
  return 'full'
}

// ── Factory-default settings ─────────────────────────────────────────────────
// The single source of truth for "what photo mode looks like out of the box".
// Each renderer instance starts from a copy (`_settings` below); the photo
// panel's Reset button applies this same object through the profile-apply path,
// so a reset lands exactly where a fresh install does.
export const DEFAULT_PHOTO_SETTINGS = Object.freeze({
  lighting:  'studio',
  lightingYaw:   0,    // deg; rotates the photo light rig around scene Y
  lightingPitch: 0,    // deg; tilts the rig around scene X (after yaw)
  full:      'matte',
  cylinders: 'matte',
  surface:   'gummy',
  atomistic: 'cpk-matte',
  bgType:    'transparent',
  bgColor:   '#ffffff',
  ssao:      true,
  bloom:     false,
  bloomStrength: 0.5,
  bloomRadius:   0.4,
  bloomThreshold: 0.85,
  exposure:   1.0,    // filmic tone-mapping exposure (renderer.toneMappingExposure)
  fov:        null,   // null = keep current
  pathTracing: false,

  // ── Figure controls (the "publication" look — see photo_renderer/figure_pass.js
  // and photo_renderer/style_presets.js). Each is INDEPENDENT; the Publication
  // style preset is just a bundle that switches the right ones on.

  // Silhouette outline — the single biggest publication-look lever. A dark
  // contour at depth/normal discontinuities, so overlapping helices separate
  // without lighting having to do it.
  outline:                  false,
  outlineColor:             '#1b1f24',
  outlineStrength:          1.0,    // 0..1 contour opacity
  outlineThickness:         1.4,    // px
  outlineDepthSensitivity:  0.35,   // silhouettes (lower = more contours)
  outlineCreaseSensitivity: 0.85,   // creases within one surface

  // Depth cue — distance fade toward a flat colour so the back of a thick
  // bundle recedes. The fade window tracks the scene bbox, not the camera
  // distance, so it behaves identically at any FOV.
  depthCue:         false,
  depthCueColor:    '#ffffff',
  depthCueStrength: 0.35,   // 0..1 fade at the far edge of the structure

  // Occlusion shading (GTAO) — proper ambient occlusion, strong enough to be
  // the PRIMARY shading cue under the flat/ambient figure rig. Distinct from
  // the `ssao` garnish, which stays as-is for the photoreal styles.
  ao:          false,
  aoRadius:    2.0,   // nm — reaches between neighbouring helices in a bundle
  aoIntensity: 1.0,

  // Near-parallel ("long lens") projection — kills the vanishing point without
  // swapping in a real OrthographicCamera. See photo_renderer/figure_camera.js
  // for why that trade was made.
  parallel: false,
  fluorophoreEmissive:  false,
  fluorophoreIntensity: 5.0,
  environment:           'room',  // 'off' | 'room' | 'file' — default to a neutral
                                   // studio so metallic/glossy PBR presets actually
                                   // reflect (metalness=1 with no env renders dark).
                                   // Reflections only; background follows bgType.
  environmentName:       'Room Studio',  // human-readable identifier
  environmentBackground: false,
  translucency:          0.0,     // 0..1, applied to full + cylinders reps
  envEffect:             'none',  // 'none' | 'mist'
  mistDensity:           0.05,    // scattering coefficient per scene unit (nm⁻¹)
  mistColor:             '#cad3e0',// tint applied to inscatter
  mistHaloIntensity:     1.0,     // overall scatter multiplier (drives uScatter uniform)
  mistNoiseContrast:     0.0,     // 0 = uniform mist; 1 = density swings 0..2× the base
  mistNoiseScale:        0.05,    // noise frequency in 1/nm; lower = bigger wisps (~20 nm at 0.05)
  mistNoiseSpeed:        0.0,     // drift speed; 0 = static noise

  // Sun — independent directional light steered by polar coords relative to
  // the chosen floor's normal (or world +Y if no floor). Lets the user place
  // a shadow exactly where they want; preset rig keeps providing fill/rim.
  sun:           false,           // sun enabled (off by default to preserve existing profiles)
  sunAzimuth:    135,             // deg, around the floor normal (0 = world +X projected onto floor)
  sunElevation:  35,              // deg, above the floor plane (0 = grazing; 90 = straight down toward floor)
  sunStrength:   1.5,
  sunColor:      '#ffffff',

  // Floor (resting surface) — off by default. See photo_renderer/floor.js.
  floor:           'off',         // 'off' | '-y' | '+y' | '-x' | '+x' | '-z' | '+z'
  floorMaterial:   'matte',       // 'matte' | 'glossy' | 'metallic' | 'mirror' | 'shadow-catcher'
  floorColor:      '#888888',
  floorOpacity:    1.0,
  floorSize:       2.0,           // (deprecated) plane is now effectively infinite; kept for old profiles
  floorOffset:     0.0,           // additional offset along outward normal (nm)
  floorShadows:    true,          // cast rig shadows onto the floor
  floorGrid:       false,         // overlay a GridHelper on the floor
  floorGridDensity: 10,           // grid cells per bbox diameter (higher = finer)
  floorGridNeon:   false,         // 80s-vaporwave neon style for the grid
  floorGridColor:  '#ff00ff',     // neon colour (magenta default)
  floorGridGlow:   3.0,           // HDR multiplier on neon grid colour (drives Bloom)
  floorGridFade:   1.5,           // grid fade reach (× the base camera-height window; higher = grid extends farther before dissolving)
})

// ── Photo renderer factory ────────────────────────────────────────────────────

export function createPhotoRenderer(sceneCtx) {
  const { scene, camera, renderer, controls, setRenderFn, resetRenderFn } = sceneCtx

  let _active          = false
  let _composerHandle  = null   // { composer, ssaoPass, bloomPass, setSize, dispose }
  let _savedMaterials  = new Map()  // mesh → original material
  let _savedLightState = []         // { light, visible } for original lights
  let _photoGroup      = null       // THREE.Group holding photo-mode lights (rotated by yaw/pitch)
  let _fluoroLightGroup = null      // THREE.Group holding fluorophore PointLights (not rotated)
  let _fluoroLights    = []         // PointLight[] mirroring the fluorophore InstancedMesh
  let _savedBgColor    = new THREE.Color()
  let _savedBgAlpha    = 0

  // Reusable scratch objects for per-frame inscatter light gathering (no per-frame alloc).
  const _scratchPoints      = []
  const _scratchAmbientColor = new THREE.Color()
  const _scratchVec3         = new THREE.Vector3()
  const _scratchColor        = new THREE.Color()

  // Multiplier applied to the fluorophore-intensity slider when driving PointLight.intensity.
  // Slider range is 0.5..30; we want PointLight intensity in the tens-to-hundreds with decay=2
  // so metals pick up reflections from a few units away.
  const _FLUORO_LIGHT_GAIN = 12.0

  // ── Current settings (persisted across activate/deactivate for UI binding) ──
  // Starts as a mutable copy of the module-level factory defaults.
  const _settings = { ...DEFAULT_PHOTO_SETTINGS }

  // Environment state — kept separately so we can restore on deactivate and
  // re-bake against the offscreen renderer during export.
  let _envSourceType   = 'room'     // 'off' | 'room' | 'file' (default: studio reflections)
  let _envSourceHDR    = null       // DataTexture loaded by RGBELoader (raster source)
  let _envTexture      = null       // PMREM-baked texture currently in scene.environment
  let _savedSceneEnv   = undefined  // pre-photo-mode scene.environment

  // Tone-mapping state — saved on activate, restored on deactivate. The live
  // editor renders with NoToneMapping; photo mode switches the shared renderer
  // to filmic tone mapping so HDR highlights (metallic env reflections, emissive
  // fluorophores) roll off gracefully instead of hard-clipping and smearing
  // saturated colour through Bloom. OutputPass reads renderer.toneMapping +
  // toneMappingExposure, so no per-material change is needed.
  let _savedToneMapping = null
  let _savedExposure    = 1.0

  // ── Sun light (independent of preset rig) ────────────────────────────────
  let _sunGroup = null   // THREE.Group at scene root; holds the sun DirectionalLight
  let _sunLight = null

  // ── Floor (resting surface) ───────────────────────────────────────────────
  const _floor = createFloor({ scene })
  // Saved pre-photo-mode renderer/mesh shadow state so deactivate() restores
  // exactly. We don't touch anything until the user enables a floor + shadows.
  let _savedShadowMapEnabled = false
  let _savedShadowMapType    = null
  const _savedCastShadow     = new Map()   // mesh → original castShadow
  let _shadowRigApplied      = false       // tracks whether rig changes are live

  // ── Figure state (outline / depth cue / occlusion / parallel) ─────────────
  // The eight corners of the drawable scene's bounding box, refreshed on
  // activate + whenever the meshes are rebuilt. Each frame they are projected
  // onto the camera's forward axis to get the depth-cue window (_pushCueRangeTo):
  // the fade then spans exactly the STRUCTURE's extent along the view direction.
  //
  // Why the corners and not a bounding sphere (which is what this was first
  // written with): a sphere is orientation-blind, so for a long thin bundle
  // viewed side-on it reports the ROD'S LENGTH as the depth extent when the
  // actual depth is the rod's diameter — an order of magnitude too wide. The
  // fade window then started at the camera and washed the whole structure out.
  // Projecting the box is exact for any view, and it costs 8 dot products.
  //
  // Anchoring to the structure (rather than to a fraction of the camera
  // distance) is also what lets the cue survive the near-parallel projection,
  // where camera distance balloons ~7× but the structure's own depth doesn't.
  let _cueCorners  = null   // Vector3[8] | null
  let _cueDiagonal = 0      // nm — the design's bbox diagonal (the cue window LENGTH)
  const _camScratch     = new THREE.Vector3()
  const _camForward     = new THREE.Vector3()
  const _cueVecScratch  = new THREE.Vector3()
  // Camera FOV on entry, so exiting photo mode restores the editor's projection
  // (the parallel toggle drives FOV down to 8° and dollies out to match).
  let _savedFov = null

  // ── Path tracing state ────────────────────────────────────────────────────
  let _ptRenderer    = null
  let _ptFsQuad      = null   // FullScreenQuad for blitting PT result
  let _ptSamples     = 0
  let _ptBuilding    = false
  let _ptEnabled     = false
  let _onSamplesUpdate = null  // callback(count) from panel

  // ── Render-loop throttle (raster path only) ───────────────────────────────
  // The photo composer re-rasterises the whole (heavy) scene 4-6× per frame
  // (SSAO + GTAO + outline + inscatter + bloom).  Running that every animation
  // frame — even parked on a static structure — is what made switching to an
  // atomistic/surface rep in photo mode feel frozen.  So:
  //   • _dirty gate — skip the composite entirely when nothing changed (the last
  //     frame persists on the canvas); a low-rate keepalive still redraws so a
  //     scene change we weren't told about (e.g. a live-sim frame applied while
  //     the camera is parked) still appears within a fraction of a second.
  //   • preview quality — while the camera is moving, draw ONE plain raster (no
  //     post chain) instead of the full composite, then snap back to full quality
  //     a few still frames after motion stops.
  const _lastCam = new THREE.Matrix4()
  let _camPrimed  = false
  let _dirty      = true   // a full-quality frame is owed
  let _previewing = false  // currently drawing cheap interactive previews
  let _idleFrames = 0      // consecutive frames with no camera motion
  const _PREVIEW_SETTLE_FRAMES = 3     // still frames before we redraw at full quality
  const _IDLE_KEEPALIVE_FRAMES = 20    // force a redraw at least this often when idle (~3 Hz)

  /** True if the camera moved since the last check; refreshes the snapshot. */
  function _cameraMoved() {
    camera.updateMatrixWorld()
    if (_camPrimed && _lastCam.equals(camera.matrixWorld)) return false
    _lastCam.copy(camera.matrixWorld)
    _camPrimed = true
    return true
  }

  /** Mark the scene dirty so the next frame redraws at full quality (and restart
   *  path-trace accumulation when it's on). Replaces the old scattered
   *  `_invalidate()`. */
  function _invalidate() {
    _dirty = true
    if (_ptEnabled && _ptRenderer) { _ptRenderer.reset(); _ptSamples = 0 }
  }

  // ── Background helpers ────────────────────────────────────────────────────

  function _bgClearParams() {
    if (_settings.bgType === 'transparent') return { color: 0x000000, alpha: 0 }
    if (_settings.bgType === 'black')       return { color: 0x000000, alpha: 1 }
    if (_settings.bgType === 'white')       return { color: 0xffffff, alpha: 1 }
    // custom
    const hex = parseInt(_settings.bgColor.replace('#', ''), 16)
    return { color: hex, alpha: 1 }
  }

  function _applyBackground() {
    // HDRI background takes priority when enabled.
    if (_settings.environmentBackground && _envTexture) {
      scene.background = _envTexture
      renderer.setClearColor(0x000000, 0)
      return
    }
    const { color, alpha } = _bgClearParams()
    renderer.setClearColor(color, alpha)
    scene.background = alpha === 0 ? null : new THREE.Color(color)
  }

  // ── Light management ─────────────────────────────────────────────────────

  function _hideOriginalLights() {
    _savedLightState = []
    scene.traverse(obj => {
      if (obj.isLight) {
        _savedLightState.push({ light: obj, visible: obj.visible })
        obj.visible = false
      }
    })
  }

  function _restoreOriginalLights() {
    for (const { light, visible } of _savedLightState) {
      light.visible = visible
    }
    _savedLightState = []
  }

  // ── Material swap ─────────────────────────────────────────────────────────

  // Phase 7d: shared-instancing InstancedMeshes (path-to-thousands renderer)
  // compose per-instance world transforms in a custom vertex patch. Swapping
  // in a stock MeshPhysicalMaterial drops that patch → every instance collapses
  // to the source origin. The shared renderer stashes a re-apply closure on the
  // mesh (`userData.applySharedInstancing`); call it after every material swap.
  function _reapplyShared(obj) {
    obj.userData?.applySharedInstancing?.(obj.material)
  }

  function _swapMaterials() {
    _savedMaterials.clear()
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      // Don't touch the axis line meshes (they use LineBasicMaterial)
      if (obj.material.isLineBasicMaterial || obj.material.isLineDashedMaterial) return
      // Skip helpers and glow layers (additive blending sprites)
      if (obj.material.blending === THREE.AdditiveBlending) return
      // Phase 7d: shared-renderer mid/far LOD impostors carry custom shaders
      // that compose instance transforms — swapping them in would collapse
      // them to the source origin. Leave them as-is (they don't need PBR).
      if (obj.userData.sharedLodImpostor) return
      // The resting-surface floor owns its own material (PBR / Reflector /
      // ShadowMaterial); don't let the rep-driven swap stomp on it.
      if (obj.userData.photoFloor) return

      const vc = Boolean(obj.material.vertexColors)
      const op = obj.material.opacity ?? 1.0
      _savedMaterials.set(obj, obj.material)

      if (obj.name === FLUORO_MESH_NAME && _settings.fluorophoreEmissive) {
        obj.material = makeFluorophoreEmissive(_settings.fluorophoreIntensity, vc)
        _reapplyShared(obj)
        return
      }
      const repr = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      const presetName = _settings[repr] ?? 'matte'
      obj.material = makeMaterial(repr, presetName, vc, op)
      _applyTranslucencyOverride(obj.material, repr)
      _reapplyShared(obj)
    })
  }

  function _restoreMaterials() {
    for (const [obj, mat] of _savedMaterials) {
      obj.material = mat
    }
    _savedMaterials.clear()
  }

  // Re-apply the PBR material swap after the scene's meshes were rebuilt while
  // photo mode is active (e.g. the export-representation upgrade replaces every
  // assembly mesh). `_swapMaterials()` clears the now-stale `_savedMaterials`
  // (the old meshes were disposed) and re-keys the fresh meshes by name → PBR
  // preset + re-applies the shared-instancing patch. Fluorophore lights point
  // at the disposed InstancedMesh, so re-spawn them from the new one. The HDRI
  // env texture + lighting rig (`_photoGroup`) survive a rebuild — no re-bake.
  function resyncMaterials() {
    if (!_active) return
    _swapMaterials()
    if (_settings.fluorophoreEmissive) _spawnFluoroLights()
    // A mid-photo-mode rebuild produced fresh meshes with castShadow=false.
    // Rebuild the floor (recomputes bbox + refits shadow cameras to the new
    // geometry) and re-flag every mesh if shadows are live.
    if (_settings.floor !== 'off') _rebuildFloor()
    // New meshes → new bounds → the depth-cue window has to be re-measured
    // (e.g. the export-representation upgrade replaces every assembly mesh).
    _refreshCueBox()
  }

  // ── Environment (HDRI) ────────────────────────────────────────────────────

  // Bake an equirectangular HDR or RoomEnvironment to a PMREM texture using the
  // given renderer's GL context. Each WebGLRenderer needs its own PMREM-baked
  // texture; sharing across contexts gives a black env. Returns the texture.
  function _bakeEnvFor(targetRenderer) {
    if (_envSourceType === 'off') return null
    const pmrem = new THREE.PMREMGenerator(targetRenderer)
    pmrem.compileEquirectangularShader()
    let tex = null
    try {
      if (_envSourceType === 'room') {
        const room = new RoomEnvironment()
        tex = pmrem.fromScene(room, 0.04).texture
        room.dispose?.()
      } else if (_envSourceType === 'file' && _envSourceHDR) {
        tex = pmrem.fromEquirectangular(_envSourceHDR).texture
      }
    } finally {
      pmrem.dispose()
    }
    return tex
  }

  function _disposeEnvTexture() {
    if (_envTexture) {
      _envTexture.dispose()
      _envTexture = null
    }
  }

  function _applyEnvToScene() {
    // Sun = sole light source: when the Sun is on, image-based lighting must not
    // contribute, so the scene's environment map is dropped (the HDRI may still
    // show as a *background* via _applyBackground — that's a backdrop, not a
    // light on the geometry). Sun off → environment reflections resume.
    scene.environment = _settings.sun ? null : _envTexture
    _applyBackground()
  }

  async function setEnvironment(mode, fileBlob = null) {
    _settings.environment = mode
    if (mode === 'off') {
      _envSourceType = 'off'
      _envSourceHDR?.dispose?.()
      _envSourceHDR = null
      _settings.environmentName = ''
    } else if (mode === 'room') {
      _envSourceType = 'room'
      _envSourceHDR?.dispose?.()
      _envSourceHDR = null
      _settings.environmentName = 'Room Studio'
    } else if (mode === 'file') {
      if (!fileBlob) {
        console.warn('[photo] setEnvironment(file) needs a File/Blob; ignoring')
        return
      }
      const url = URL.createObjectURL(fileBlob)
      try {
        _envSourceHDR?.dispose?.()
        _envSourceHDR = await new RGBELoader().loadAsync(url)
        _envSourceType = 'file'
        _settings.environmentName = fileBlob.name ?? 'custom.hdr'
      } catch (err) {
        console.error('[photo] HDR load failed:', err)
        showToast(`HDR load failed: ${err.message ?? err}`, 3000)
        return
      } finally {
        URL.revokeObjectURL(url)
      }
    }

    if (!_active) return
    _disposeEnvTexture()
    _envTexture = _bakeEnvFor(renderer)
    // PMREMGenerator churns the renderer's GL state (its own render targets +
    // texture-unit bindings). The composer was built at activate time and is NOT
    // rebuilt here — rebuilding would construct a composer AFTER this bake, which
    // re-triggers the documented "bloom additive paints garbage tint" bug (the
    // 2026-05-27 rebuild attempt was reverted for exactly this). Instead, flush
    // the state cache right now so the lingering bake state can't bleed a colored
    // garbage frame into the next composer.render (the per-frame reset in the
    // render override is the steady-state guard; this is the one-shot bake guard).
    renderer.resetState?.()
    _applyEnvToScene()
    console.log(`[photo] setEnvironment(${mode}) → ${_settings.environmentName || 'off'}`)
    showToast(`Environment: ${_settings.environmentName || 'off'}`, 2200)
    _invalidate()
  }

  function setEnvironmentBackground(enabled) {
    _settings.environmentBackground = enabled
    if (!_active) return
    _applyBackground()
    _invalidate()
  }

  // ── Translucency override (full + cylinders reps) ─────────────────────────

  function _applyTranslucencyOverride(mat, repr) {
    if (!mat || !mat.isMeshPhysicalMaterial) return
    if (repr !== 'full' && repr !== 'cylinders') return
    const t = _settings.translucency
    if (t <= 0) {
      mat.transmission = 0
      mat.transparent  = mat.opacity < 1
    } else {
      mat.transmission = t
      mat.transparent  = true
      mat.thickness    = 1.0
      mat.ior          = 1.4
    }
    mat.needsUpdate = true
  }

  function setTranslucency(amount) {
    _settings.translucency = amount
    if (!_active) return
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      if (obj.name === FLUORO_MESH_NAME && _settings.fluorophoreEmissive) return
      if (obj.userData.photoFloor) return
      const repr = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      _applyTranslucencyOverride(obj.material, repr)
    })
    _invalidate()
  }

  // ── Environmental effects (volumetric inscatter / mist) ───────────────────

  function _inscatterPass() {
    return _composerHandle?.inscatterPass ?? null
  }

  // Walk scene lights into _scratchPoints + _scratchAmbientColor. Pure gather;
  // pushing to a specific pass is _pushLightsTo() so the export path can reuse it.
  // Ambient + Directional collapse into a single ambient term (constant per march step).
  // PointLights become 1/r² emitters.
  function _gatherLightsForInscatter() {
    _scratchPoints.length = 0
    _scratchAmbientColor.setRGB(0, 0, 0)
    const visit = obj => {
      if (!obj.isLight) return
      if (obj.isAmbientLight || obj.isHemisphereLight) {
        _scratchAmbientColor.r += obj.color.r * obj.intensity
        _scratchAmbientColor.g += obj.color.g * obj.intensity
        _scratchAmbientColor.b += obj.color.b * obj.intensity
      } else if (obj.isDirectionalLight) {
        // Anisotropic in reality; approximate as a half-weight constant term.
        const w = obj.intensity * 0.5
        _scratchAmbientColor.r += obj.color.r * w
        _scratchAmbientColor.g += obj.color.g * w
        _scratchAmbientColor.b += obj.color.b * w
      }
    }
    // Skip the preset rig when it's hidden (sun-on single-light mode) so mist
    // inscatter matches the lighting actually rendered. (traverse ignores
    // .visible, so gate on the group flag explicitly.)
    if (_photoGroup?.visible) _photoGroup.traverse(visit)
    _sunGroup?.traverse(visit)
    for (const l of _fluoroLights) {
      _scratchPoints.push({
        position:    l.position,                                          // world (fluoroLightGroup has no transform)
        colorScaled: l.color.clone().multiplyScalar(l.intensity),
      })
    }
  }

  function _pushLightsTo(pass) {
    if (!pass) return
    pass.setLights({ points: _scratchPoints, ambient: _scratchAmbientColor })
  }

  function _pushInscatterParamsTo(pass) {
    if (!pass) return
    pass.setMistParams({
      density:  _settings.mistDensity,
      scatter:  _settings.mistHaloIntensity,
      fogColor: _scratchColor.set(_settings.mistColor),
    })
    pass.setNoiseParams({
      contrast: _settings.mistNoiseContrast,
      scale:    _settings.mistNoiseScale,
      speed:    _settings.mistNoiseSpeed,
    })
  }

  function _pushInscatterParams() { _pushInscatterParamsTo(_inscatterPass()) }

  function _applyEnvEffect() {
    const pass = _inscatterPass()
    if (!pass) return
    pass.enabled = (_settings.envEffect === 'mist')
    if (pass.enabled) {
      _pushInscatterParamsTo(pass)
      _gatherLightsForInscatter()
      _pushLightsTo(pass)
    }
  }

  // ── Fluorophore point lights ──────────────────────────────────────────────

  function _fluoroMesh() {
    return scene.getObjectByName(FLUORO_MESH_NAME) ?? null
  }

  function _spawnFluoroLights() {
    _clearFluoroLights()
    // Sun = sole light source → no fluorophore PointLights (the emissive glow of
    // the fluorophore beads themselves is a material property and is unaffected).
    if (_settings.sun) return
    const mesh = _fluoroMesh()
    if (!mesh || !mesh.isInstancedMesh) return
    if (!_fluoroLightGroup) {
      _fluoroLightGroup = new THREE.Group()
      _fluoroLightGroup.name = 'photoFluoroLights'
      scene.add(_fluoroLightGroup)
    }
    const m   = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const c   = new THREE.Color()
    const intensity = _settings.fluorophoreIntensity * _FLUORO_LIGHT_GAIN
    mesh.updateMatrixWorld(true)
    for (let i = 0; i < mesh.count; i++) {
      mesh.getMatrixAt(i, m)
      pos.setFromMatrixPosition(m).applyMatrix4(mesh.matrixWorld)
      if (mesh.instanceColor) c.fromArray(mesh.instanceColor.array, i * 3)
      else                    c.set(0xffffff)
      const light = new THREE.PointLight(c, intensity, 0, 2)  // 0 = infinite range, decay=2 (physical)
      light.position.copy(pos)
      _fluoroLightGroup.add(light)
      _fluoroLights.push(light)
    }
  }

  function _clearFluoroLights() {
    for (const l of _fluoroLights) {
      l.parent?.remove(l)
      l.dispose?.()
    }
    _fluoroLights = []
  }

  // Per-frame position sync — handles design transforms, cluster moves, animation.
  // Also rebuilds if instance count changed under us.
  function _syncFluoroLights() {
    if (!_settings.fluorophoreEmissive) return
    // Sun-sole: keep no fluorophore PointLights alive while the sun owns the scene.
    if (_settings.sun) { if (_fluoroLights.length) _clearFluoroLights(); return }
    const mesh = _fluoroMesh()
    if (!mesh || !mesh.isInstancedMesh) {
      if (_fluoroLights.length) _clearFluoroLights()
      return
    }
    if (_fluoroLights.length !== mesh.count) { _spawnFluoroLights(); return }
    const m   = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    mesh.updateMatrixWorld(true)
    for (let i = 0; i < _fluoroLights.length; i++) {
      mesh.getMatrixAt(i, m)
      pos.setFromMatrixPosition(m).applyMatrix4(mesh.matrixWorld)
      _fluoroLights[i].position.copy(pos)
    }
  }

  // ── Floor + shadow rig ────────────────────────────────────────────────────

  // Walk the photo light group and enable cast-shadow on every DirectionalLight,
  // fitting each shadow camera's ortho frustum to `bbox`. Also adds each light's
  // target to the scene (Three.js does not do this automatically) and aims it at
  // the bbox centre.
  function _fitDirLightShadow(light, bbox) {
    const size   = bbox.getSize(new THREE.Vector3())
    const center = bbox.getCenter(new THREE.Vector3())
    const radius = Math.max(size.length() * 0.6, 1.0)
    const cam = light.shadow.camera
    cam.left = -radius; cam.right  =  radius
    cam.top  =  radius; cam.bottom = -radius
    cam.near = 0.1;     cam.far    =  radius * 8
    cam.updateProjectionMatrix()
    light.shadow.mapSize.set(2048, 2048)
    light.shadow.bias       = -0.0005
    light.shadow.normalBias = 0.02
    if (!light.target.parent) scene.add(light.target)
    light.target.position.copy(center)
    light.target.updateMatrixWorld(true)
  }

  // One-key-light rule: exactly one directional light in the preset rig casts
  // a shadow — the first DirectionalLight encountered (treated as the "key").
  // All other preset directionals stay as fill. When the Sun light is enabled,
  // the Sun becomes the sole shadow caster and the preset's key is suppressed
  // too (see `_enableRigShadows`).
  function _enableRigShadows() {
    if (!_photoGroup) return
    const bbox = _floor.getLastBBox()
    if (!bbox) return
    const sunOwnsShadow = !!(_settings.sun && _sunLight)
    let keyAssigned = false
    _photoGroup.traverse(obj => {
      if (!obj.isDirectionalLight) return
      const shouldCast = !sunOwnsShadow && !keyAssigned
      obj.castShadow = shouldCast
      if (shouldCast) {
        _fitDirLightShadow(obj, bbox)
        keyAssigned = true
      }
    })
  }

  function _disableRigShadows() {
    if (!_photoGroup) return
    _photoGroup.traverse(obj => {
      if (obj.isDirectionalLight) obj.castShadow = false
    })
  }

  // ── Sun light ────────────────────────────────────────────────────────────

  // Which world-space axis is "up" for the sun's polar frame. Floor normal when
  // a floor is configured; falls back to world +Y. The visible face of a '-y'
  // floor is +Y (so up = +Y); for '+y' the visible face is -Y, etc.
  function _sunUpAxis() {
    const m = {
      '-y': new THREE.Vector3( 0,  1,  0),
      '+y': new THREE.Vector3( 0, -1,  0),
      '-x': new THREE.Vector3( 1,  0,  0),
      '+x': new THREE.Vector3(-1,  0,  0),
      '-z': new THREE.Vector3( 0,  0,  1),
      '+z': new THREE.Vector3( 0,  0, -1),
    }
    return m[_settings.floor] ?? new THREE.Vector3(0, 1, 0)
  }

  // Convert (azimuth, elevation) around `up` into a world-space direction that
  // points FROM the target TO the sun (so light.position = target + dir * d).
  // Azimuth=0 references world +X projected onto the floor plane (or +Z if up
  // is nearly parallel to +X). Elevation 0 = on the horizon; 90 = directly above.
  function _sunDirFromPolar(up, azDeg, elDeg) {
    const ref = (Math.abs(up.x) < 0.99)
      ? new THREE.Vector3(1, 0, 0)
      : new THREE.Vector3(0, 0, 1)
    const tangent = ref.clone().sub(up.clone().multiplyScalar(up.dot(ref))).normalize()
    const bitangent = new THREE.Vector3().crossVectors(up, tangent).normalize()
    const az = THREE.MathUtils.degToRad(azDeg)
    const el = THREE.MathUtils.degToRad(elDeg)
    const horiz = tangent.clone().multiplyScalar(Math.cos(az)).addScaledVector(bitangent, Math.sin(az))
    return horiz.multiplyScalar(Math.cos(el)).addScaledVector(up, Math.sin(el)).normalize()
  }

  function _ensureSunGroup() {
    if (_sunGroup) return
    _sunGroup = new THREE.Group()
    _sunGroup.name = 'photoSunLight'
    scene.add(_sunGroup)
  }

  function _disposeSunGroup() {
    if (_sunLight) {
      if (_sunLight.target?.parent) _sunLight.target.parent.remove(_sunLight.target)
      _sunLight.parent?.remove(_sunLight)
      _sunLight.dispose?.()
      _sunLight = null
    }
    if (_sunGroup) {
      scene.remove(_sunGroup)
      _sunGroup = null
    }
  }

  // When the Sun is enabled it becomes the TRULY single light source: hide the
  // entire preset studio rig (ambient + directional lights). Image-based
  // lighting (scene.environment) and fluorophore PointLights are also dropped —
  // see _applyEnvToScene (IBL) and _spawnFluoroLights/_syncFluoroLights (fluoro)
  // — so the sun is the only thing illuminating the geometry. All restored when
  // the sun is off. (A metallic rep under sun-only will read dark: metals need
  // an environment to reflect; that's expected with no IBL.)
  function _applyRigVisibility() {
    if (_photoGroup) _photoGroup.visible = !_settings.sun
  }

  // (Re)position the sun light from current settings. Uses the floor's bbox
  // when available (for shadow camera fit + target); falls back to scene
  // origin / unit distance if there's no floor or no scene yet.
  function _applySun() {
    if (!_active) return
    // Sun on → suppress the preset rig; sun off → bring it back. Covers entry
    // (called from activate) and every sun setter.
    _applyRigVisibility()
    // Sun-sole also gates image-based lighting + fluorophore PointLights. Re-run
    // both each time the sun toggles so they drop (sun on) / resume (sun off).
    _applyEnvToScene()
    if (_settings.fluorophoreEmissive) _spawnFluoroLights()
    if (!_settings.sun) {
      _disposeSunGroup()
      // Sun is off → preset rig reclaims the single-key shadow.
      if (_shadowRigApplied) _enableRigShadows()
      return
    }

    _ensureSunGroup()
    if (!_sunLight) {
      _sunLight = new THREE.DirectionalLight(0xffffff, 1)
      _sunGroup.add(_sunLight)
    }
    _sunLight.color.set(_settings.sunColor)
    _sunLight.intensity = _settings.sunStrength

    const bbox   = _floor.getLastBBox()
    const center = bbox ? bbox.getCenter(new THREE.Vector3()) : new THREE.Vector3()
    const size   = bbox ? bbox.getSize(new THREE.Vector3())   : new THREE.Vector3(10, 10, 10)
    const radius = Math.max(size.length(), 1.0)
    const dist   = radius * 2.0

    const up  = _sunUpAxis()
    const dir = _sunDirFromPolar(up, _settings.sunAzimuth, _settings.sunElevation)
    _sunLight.position.copy(center).addScaledVector(dir, dist)
    if (!_sunLight.target.parent) scene.add(_sunLight.target)
    _sunLight.target.position.copy(center)
    _sunLight.target.updateMatrixWorld(true)

    // If the shadow rig is currently active, fit the sun's shadow camera too.
    if (_shadowRigApplied && bbox) {
      _sunLight.castShadow = true
      _fitDirLightShadow(_sunLight, bbox)
    } else {
      _sunLight.castShadow = false
    }
    // Sun is now the (only) shadow caster; demote the preset rig's key light
    // back to fill so we don't get a double shadow.
    if (_shadowRigApplied) _enableRigShadows()
  }

  function setSun(on)             { _settings.sun          = !!on; _applySun(); _invalidate() }
  function setSunAzimuth(deg)     { _settings.sunAzimuth   = deg;  _applySun(); _invalidate() }
  function setSunElevation(deg)   { _settings.sunElevation = deg;  _applySun(); _invalidate() }
  function setSunStrength(v)      { _settings.sunStrength  = v;    _applySun(); _invalidate() }
  function setSunColor(hex)       { _settings.sunColor     = hex;  _applySun(); _invalidate() }

  // Flip castShadow=true on every scene mesh that can safely participate in
  // depth-only shadow rendering. Skips: helper lines, additive sprites, shared-
  // renderer LOD impostors (custom instance shaders → wrong depth), sphere
  // impostors (depth-only shader doesn't run the impostor math), and the floor
  // itself.
  function _enableMeshShadows() {
    _savedCastShadow.clear()
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      if (obj.material.isLineBasicMaterial || obj.material.isLineDashedMaterial) return
      if (obj.material.blending === THREE.AdditiveBlending) return
      if (obj.userData.sharedLodImpostor) return
      if (obj.userData.photoFloor) return
      if (obj.material.userData?.impostorRadius != null) return
      _savedCastShadow.set(obj, obj.castShadow)
      obj.castShadow = true
    })
  }

  function _restoreMeshShadows() {
    for (const [obj, val] of _savedCastShadow) obj.castShadow = val
    _savedCastShadow.clear()
  }

  // Apply / remove shadow plumbing on the renderer + rig + scene meshes. Idempotent.
  function _applyShadowRig(enabled) {
    if (enabled && !_shadowRigApplied) {
      _savedShadowMapEnabled = renderer.shadowMap.enabled
      _savedShadowMapType    = renderer.shadowMap.type
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type    = THREE.PCFSoftShadowMap
      _enableRigShadows()
      _enableMeshShadows()
      _shadowRigApplied = true
    } else if (!enabled && _shadowRigApplied) {
      _disableRigShadows()
      _restoreMeshShadows()
      renderer.shadowMap.enabled = _savedShadowMapEnabled
      if (_savedShadowMapType != null) renderer.shadowMap.type = _savedShadowMapType
      _shadowRigApplied = false
    }
  }

  function _rebuildFloor() {
    if (!_active) return
    _floor.build(_settings)
    const wantShadows = (_settings.floor !== 'off') && !!_settings.floorShadows
    _applyShadowRig(wantShadows)
    // Re-fit shadow cameras whenever the floor (and therefore bbox) was rebuilt.
    if (_shadowRigApplied) _enableRigShadows()
    // Sun's "up" axis is the floor normal and its target is the bbox centre —
    // both change with the floor, so re-place it whenever the floor rebuilds.
    _applySun()
    _invalidate()
  }

  function setFloor(axis) {
    _settings.floor = axis ?? 'off'
    _rebuildFloor()
  }
  function setFloorMaterial(name) { _settings.floorMaterial = name; _rebuildFloor() }
  function setFloorColor(hex)     { _settings.floorColor    = hex;  _rebuildFloor() }
  function setFloorOpacity(v)     { _settings.floorOpacity  = v;    _rebuildFloor() }
  function setFloorSize(v)        { _settings.floorSize     = v;    _rebuildFloor() }
  function setFloorOffset(v)      { _settings.floorOffset   = v;    _rebuildFloor() }
  function setFloorShadows(on)    { _settings.floorShadows  = !!on; _rebuildFloor() }
  function setFloorGrid(on)       { _settings.floorGrid     = !!on; _rebuildFloor() }
  function setFloorGridDensity(v) { _settings.floorGridDensity = v; _rebuildFloor() }
  function setFloorGridNeon(on)   { _settings.floorGridNeon = !!on; _rebuildFloor() }
  function setFloorGridColor(hex) { _settings.floorGridColor = hex; _rebuildFloor() }
  function setFloorGridGlow(v)    { _settings.floorGridGlow  = v;   _rebuildFloor() }
  function setFloorGridFade(v)    { _settings.floorGridFade  = v;   _rebuildFloor() }

  // ── Figure pass: outline + depth cue ──────────────────────────────────────

  function _figurePass() { return _composerHandle?.figurePass ?? null }
  function _gtaoPass()   { return _composerHandle?.gtaoPass   ?? null }

  /** Recompute the scene bbox corners + diagonal the depth-cue window uses. */
  function _refreshCueBox() {
    const box = _floor.computeSceneBBox?.()
    if (!box || box.isEmpty() || !Number.isFinite(box.min.x)) {
      _cueCorners = null
      _cueDiagonal = 0
      return
    }
    const { min, max } = box
    _cueCorners = [
      new THREE.Vector3(min.x, min.y, min.z), new THREE.Vector3(max.x, min.y, min.z),
      new THREE.Vector3(min.x, max.y, min.z), new THREE.Vector3(max.x, max.y, min.z),
      new THREE.Vector3(min.x, min.y, max.z), new THREE.Vector3(max.x, min.y, max.z),
      new THREE.Vector3(min.x, max.y, max.z), new THREE.Vector3(max.x, max.y, max.z),
    ]
    _cueDiagonal = Math.max(max.distanceTo(min), 1e-3)
  }

  /** Depth-cue window for the CURRENT camera pose.
   *
   *  START: the nearest corner of the structure along the view axis — so the
   *  fade always begins at the front of the object, whatever the camera does.
   *
   *  LENGTH: the bounding box DIAGONAL — a constant for the design, NOT the
   *  depth extent of the current view. This is the load-bearing choice. Scaling
   *  the window to the current depth extent (the obvious thing, and what this
   *  did first) normalizes every view to a full 0→1 fade, so a flat subject
   *  seen side-on gets the same total wash as a deep bundle seen end-on — the
   *  cue desaturates a thin helix for no reason. Against a fixed length, depth
   *  cue does what it is supposed to: near-nothing on a shallow view, strong
   *  when you are actually looking down the depth of a thick structure.
   *
   *  Pushed every frame (and per export tile) because the near corner tracks
   *  the camera. */
  function _pushCueRangeTo(pass) {
    if (!pass || !_cueCorners) return
    camera.getWorldDirection(_camForward)
    let near = Infinity
    for (const corner of _cueCorners) {
      const d = _cueVecScratch.subVectors(corner, camera.position).dot(_camForward)
      if (d < near) near = d
    }
    // The camera can sit inside the box (a close-up), which puts corners behind
    // it — clamp to the near plane so the fade never starts behind the viewer.
    near = Math.max(near, camera.near)
    pass.setCueRange(near, near + _cueDiagonal)
  }

  /** Push every outline/depth-cue setting into a figure pass and set its
   *  `enabled` (EffectComposer skips a disabled pass entirely, so both effects
   *  off = no depth pre-pass, no cost). Used for the live composer AND for the
   *  per-export composers — which is what keeps preview and export in sync. */
  function _pushFigureParamsTo(pass) {
    if (!pass) return
    pass.setParams({
      outline:                  _settings.outline,
      outlineColor:             _settings.outlineColor,
      outlineStrength:          _settings.outlineStrength,
      outlineThickness:         _settings.outlineThickness,
      outlineDepthSensitivity:  _settings.outlineDepthSensitivity,
      outlineCreaseSensitivity: _settings.outlineCreaseSensitivity,
      depthCue:                 _settings.depthCue,
      depthCueColor:            _settings.depthCueColor,
      depthCueStrength:         _settings.depthCueStrength,
    })
    _pushCueRangeTo(pass)
    pass.enabled = pass.hasEffect()
  }

  function _applyFigure() {
    if (!_active) return
    if (_settings.depthCue && !_cueCorners) _refreshCueBox()
    _pushFigureParamsTo(_figurePass())
    _invalidate()
  }

  function setOutline(on)         { _settings.outline = !!on; if (on) _refreshCueBox(); _applyFigure() }
  function setOutlineColor(hex)   { _settings.outlineColor    = hex; _applyFigure() }
  function setOutlineStrength(v)  { _settings.outlineStrength = v;   _applyFigure() }
  function setOutlineThickness(v) { _settings.outlineThickness = v;  _applyFigure() }
  function setOutlineSensitivity({ depth, crease } = {}) {
    if (depth  !== undefined) _settings.outlineDepthSensitivity  = depth
    if (crease !== undefined) _settings.outlineCreaseSensitivity = crease
    _applyFigure()
  }
  function setDepthCue(on)        { _settings.depthCue = !!on; if (on) _refreshCueBox(); _applyFigure() }
  function setDepthCueColor(hex)  { _settings.depthCueColor    = hex; _applyFigure() }
  function setDepthCueStrength(v) { _settings.depthCueStrength = v;   _applyFigure() }

  // ── Occlusion shading (GTAO) ──────────────────────────────────────────────

  function _pushAOParamsTo(pass) {
    if (!pass) return
    pass.blendIntensity = _settings.aoIntensity
    pass.updateGtaoMaterial({ radius: _settings.aoRadius })
    pass.enabled = !!_settings.ao
  }

  function _applyAO() {
    if (!_active) return
    _pushAOParamsTo(_gtaoPass())
    _invalidate()
  }

  function setAO(on)         { _settings.ao          = !!on; _applyAO() }
  function setAORadius(v)    { _settings.aoRadius    = v;    _applyAO() }
  function setAOIntensity(v) { _settings.aoIntensity = v;    _applyAO() }

  // ── Near-parallel projection ──────────────────────────────────────────────

  /** Change FOV while keeping the subject the same size on screen, by dollying
   *  the camera along its view axis. Without the dolly, dragging FOV down to 8°
   *  would simply zoom the structure to fill the screen, which is not what the
   *  control is for. See photo_renderer/figure_camera.js. */
  function _applyFovWithDolly(newFov) {
    const target = controls?.target
    const oldFov = camera.fov
    if (target && Number.isFinite(oldFov) && oldFov > 0) {
      const dist = camera.position.distanceTo(target)
      const newDist = dollyDistanceForFov(dist, oldFov, newFov)
      if (dist > 1e-6 && Number.isFinite(newDist)) {
        _camScratch.subVectors(camera.position, target).normalize().multiplyScalar(newDist)
        camera.position.copy(target).add(_camScratch)
      }
    }
    camera.fov = newFov
    camera.updateProjectionMatrix()
    controls?.update?.()
    _invalidate()
  }

  function setParallel(on) {
    _settings.parallel = !!on
    _settings.fov = on ? PARALLEL_FOV : PERSPECTIVE_FOV
    if (!_active) return
    _applyFovWithDolly(_settings.fov)
  }

  // ── Path tracer ───────────────────────────────────────────────────────────

  async function _enablePathTracing() {
    if (_ptBuilding || _ptEnabled) return
    _ptBuilding = true
    _ptSamples  = 0

    try {
      const { PathTracingRenderer, DynamicPathTracingSceneGenerator, PhysicalPathTracingMaterial }
        = await import('three-gpu-pathtracer')

      // Collect visible mesh objects
      const meshes = []
      scene.traverse(obj => {
        if ((obj.isMesh || obj.isInstancedMesh) && obj.visible) meshes.push(obj)
      })
      if (!meshes.length) { _ptBuilding = false; return }

      const generator = new DynamicPathTracingSceneGenerator(meshes)
      const { bvh, geometry, materials, textures, lights: sceneLights } = generator.generate()

      const w = renderer.domElement.width
      const h = renderer.domElement.height

      const ptMat = new PhysicalPathTracingMaterial()
      ptMat.bvh.updateFrom(bvh)
      ptMat.attributesArray.updateFrom(geometry, materials)
      ptMat.materials.updateFrom(renderer, materials, textures)
      ptMat.lights.updateFrom(sceneLights)
      ptMat.resolution.set(w, h)
      ptMat.bounces = 5
      ptMat.transmissiveBounces = 3

      _ptRenderer = new PathTracingRenderer(renderer)
      _ptRenderer.material = ptMat
      _ptRenderer.camera   = camera
      _ptRenderer.alpha    = true
      _ptRenderer.reset()

      // Build a copy material for blitting the PT target to the screen
      const { CopyShader } = await import('three/addons/shaders/CopyShader.js')
      const { ShaderMaterial } = await import('three')
      _ptFsQuad = new FullScreenQuad(new THREE.MeshBasicMaterial({ map: _ptRenderer.target.texture }))

      _ptEnabled  = true
      _ptBuilding = false

      // Override render fn: advance one sample then blit
      setRenderFn(() => {
        _ptRenderer.update()
        _ptSamples = _ptRenderer.samples
        _onSamplesUpdate?.(_ptSamples)
        renderer.setRenderTarget(null)
        renderer.autoClear = false
        _ptFsQuad.render(renderer)
        renderer.autoClear = true
      })
    } catch (err) {
      console.warn('[photo] Path tracing init failed:', err)
      _ptBuilding = false
    }
  }

  function _disablePathTracing() {
    _ptEnabled  = false
    _ptBuilding = false
    _ptSamples  = 0
    if (_ptRenderer) { _ptRenderer = null }
    if (_ptFsQuad)   { _ptFsQuad.dispose(); _ptFsQuad = null }
    // Restore composer-based render
    if (_composerHandle) _installComposerRenderFn()
  }

  // ── Activate / Deactivate ─────────────────────────────────────────────────

  function activate(initialSettings = {}) {
    if (_active) return
    _active = true
    Object.assign(_settings, initialSettings)

    // Save and mute original lights
    _hideOriginalLights()

    // Install photo-mode light group
    _photoGroup = new THREE.Group()
    _photoGroup.name = 'photoLights'
    scene.add(_photoGroup)
    applyLighting(_settings.lighting, _photoGroup)
    _applyLightingRotation()

    // Swap materials
    _swapMaterials()

    // Save renderer background + scene.environment so we can restore on exit.
    renderer.getClearColor(_savedBgColor)
    _savedBgAlpha   = renderer.getClearAlpha()
    _savedSceneEnv  = scene.environment

    // Switch the shared renderer to filmic tone mapping for the duration of
    // photo mode (restored in deactivate). Without this, HDR values clip at 1.0
    // and Bloom smears the clipped primaries into large yellow/purple washes.
    _savedToneMapping = renderer.toneMapping
    _savedExposure    = renderer.toneMappingExposure
    renderer.toneMapping         = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = _settings.exposure

    // Save the editor's FOV so deactivate() can restore the projection, then
    // apply the photo FOV with a dolly so the framing the user set is kept.
    _savedFov = camera.fov
    if (_settings.fov != null && _settings.fov !== camera.fov) {
      _applyFovWithDolly(_settings.fov)
    }

    // Build EffectComposer
    _composerHandle = createComposer(renderer, scene, camera, {
      ssao:          _settings.ssao,
      ao:            _settings.ao,
      aoRadius:      _settings.aoRadius,
      aoIntensity:   _settings.aoIntensity,
      bloom:         _settings.bloom,
      bloomStrength: _settings.bloomStrength,
      bloomRadius:   _settings.bloomRadius,
      bloomThreshold: _settings.bloomThreshold,
    })

    // Bake the HDRI environment AFTER the composer is built. PMREMGenerator
    // mutates renderer state (its own internal render targets) as a side effect
    // of `fromScene`/`fromEquirectangular`. If we bake BEFORE the composer is
    // constructed, the new EffectComposer + UnrealBloomPass inherit that lingering
    // state and the bloom additive blend writes garbage — producing a fully black
    // viewport or angle-dependent color tint over the scene. Baking after the
    // composer exists isolates PMREM's state churn from the composer's RT setup.
    if (_envSourceType !== 'off') {
      _envTexture = _bakeEnvFor(renderer)
    }
    _applyEnvToScene()

    // Apply env effect once the composer (and its inscatter pass) exists.
    _applyEnvEffect()

    // Build the resting-surface floor (if the active profile has one configured).
    _rebuildFloor()

    // Sun light is independent of the preset rig; build it after the floor so
    // it can use the floor's bbox/normal. No-op when `sun` is false.
    _applySun()

    // Figure controls (outline / depth cue / occlusion shading). The cue window
    // needs the scene bounds, so measure them once the scene is final.
    _refreshCueBox()
    _pushFigureParamsTo(_figurePass())
    _pushAOParamsTo(_gtaoPass())

    // Override render loop — sync fluoro lights and (when mist is on) push light
    // uniforms to the inscatter pass each frame so halos track design moves.
    _installComposerRenderFn()

    // Start path tracing if requested
    if (_settings.pathTracing) _enablePathTracing()
  }

  function deactivate() {
    if (!_active) return
    _active = false

    // Stop path tracing
    _disablePathTracing()

    // Restore render fn
    resetRenderFn()

    // Restore materials
    _restoreMaterials()

    // Remove fluorophore PointLights
    _clearFluoroLights()
    if (_fluoroLightGroup) { scene.remove(_fluoroLightGroup); _fluoroLightGroup = null }

    // Tear down floor + restore shadow rig BEFORE removing photo lights so the
    // restore walk still sees the directional lights it has to un-flag.
    _floor.dispose()
    _disposeSunGroup()
    _applyShadowRig(false)

    // Remove photo lights, restore originals
    if (_photoGroup) { scene.remove(_photoGroup); _photoGroup = null }
    _restoreOriginalLights()

    // Restore background + environment
    renderer.setClearColor(_savedBgColor, _savedBgAlpha)
    scene.background  = _savedBgAlpha === 0 ? null : _savedBgColor.clone()
    scene.environment = _savedSceneEnv ?? null
    _disposeEnvTexture()

    // Restore the live editor's tone mapping (it renders with NoToneMapping).
    if (_savedToneMapping != null) {
      renderer.toneMapping         = _savedToneMapping
      renderer.toneMappingExposure = _savedExposure
      _savedToneMapping = null
    }

    // Restore the editor's projection. Done WITH a dolly so the user keeps
    // whatever framing they orbited to inside photo mode — only the lens
    // changes back, not the shot. (Without this, exiting a parallel-projection
    // render would leave the editor stuck at an 8° FOV, 7× too far out.)
    if (_savedFov != null && camera.fov !== _savedFov) _applyFovWithDolly(_savedFov)
    _savedFov  = null
    _cueCorners = null

    // Dispose composer
    _composerHandle?.dispose()
    _composerHandle = null
  }

  // ── Live setting changes ───────────────────────────────────────────────────

  function _applyLightingRotation() {
    if (!_photoGroup) return
    _photoGroup.rotation.order = 'YXZ'
    _photoGroup.rotation.set(
      THREE.MathUtils.degToRad(_settings.lightingPitch),
      THREE.MathUtils.degToRad(_settings.lightingYaw),
      0,
    )
  }

  function setLighting(presetName) {
    _settings.lighting = presetName
    if (!_active || !_photoGroup) return
    applyLighting(presetName, _photoGroup)
    _applyLightingRotation()
    // applyLighting() recreates the directional lights with castShadow=false,
    // so re-apply the shadow rig if a floor with shadows is live.
    if (_shadowRigApplied) _enableRigShadows()
    _invalidate()
  }

  function setLightingDirection(yawDeg, pitchDeg) {
    if (yawDeg   != null) _settings.lightingYaw   = yawDeg
    if (pitchDeg != null) _settings.lightingPitch = pitchDeg
    _applyLightingRotation()
    _invalidate()
  }

  function setFluorophoreEmissive(enabled, intensity) {
    _settings.fluorophoreEmissive = enabled
    if (intensity != null) _settings.fluorophoreIntensity = intensity
    if (!_active) return
    let nMesh = 0
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      if (obj.name !== FLUORO_MESH_NAME) return
      // Adopt mesh into _savedMaterials if it appeared after activate().
      if (!_savedMaterials.has(obj)) _savedMaterials.set(obj, obj.material)
      const old = _savedMaterials.get(obj)
      const vc = Boolean(old.vertexColors)
      const op = old.opacity ?? 1.0
      obj.material.dispose?.()
      obj.material = enabled
        ? makeFluorophoreEmissive(_settings.fluorophoreIntensity, vc)
        : makeMaterial('full', _settings.full, vc, op)
      _reapplyShared(obj)
      nMesh++
    })
    if (enabled) _spawnFluoroLights()
    else         _clearFluoroLights()
    const nLights = _fluoroLights.length
    console.log(`[photo] setFluorophoreEmissive(${enabled}, ${_settings.fluorophoreIntensity}) → mesh=${nMesh}, lights=${nLights}`)
    showToast(
      enabled
        ? `Fluorophores → emissive ×${_settings.fluorophoreIntensity.toFixed(1)} (${nLights} lights). Enable Bloom for halo.`
        : `Fluorophores → off`,
      2400,
    )
    _invalidate()
  }

  function setFluorophoreIntensity(intensity) {
    _settings.fluorophoreIntensity = intensity
    if (!_active || !_settings.fluorophoreEmissive) return
    scene.traverse(obj => {
      if (obj.name === FLUORO_MESH_NAME && obj.material) {
        obj.material.emissiveIntensity = intensity
      }
    })
    const lightIntensity = intensity * _FLUORO_LIGHT_GAIN
    for (const l of _fluoroLights) l.intensity = lightIntensity
    _invalidate()
  }

  // ── Environmental effect setters ─────────────────────────────────────────

  function setEnvironmentalEffect(name) {
    _settings.envEffect = name
    if (!_active) return
    _applyEnvEffect()
    // PT path bypasses the composer entirely — inscatter pass doesn't apply.
  }

  function setMistDensity(d) {
    _settings.mistDensity = d
    if (!_active) return
    _pushInscatterParams()
  }

  function setMistColor(hexStr) {
    _settings.mistColor = hexStr
    if (!_active) return
    _pushInscatterParams()
  }

  function setMistHaloIntensity(amount) {
    _settings.mistHaloIntensity = amount
    if (!_active) return
    _pushInscatterParams()
  }

  function setMistNoise({ contrast, scale, speed } = {}) {
    if (contrast !== undefined) _settings.mistNoiseContrast = contrast
    if (scale    !== undefined) _settings.mistNoiseScale    = scale
    if (speed    !== undefined) _settings.mistNoiseSpeed    = speed
    if (!_active) return
    _pushInscatterParams()
  }

  // Debug helper exposed via window.__photoRenderer.setMistDebug(mode):
  //   0 = passthrough (just diffuse — should look identical to mist-off)
  //   1 = solid magenta (proves the pass is running)
  //   2 = depth as greyscale (proves depth pre-pass is working)
  //   3 = ambient inscatter only (no point-light contribution)
  //   anything else (e.g. 99) = full inscatter math
  function setMistDebug(mode) {
    const pass = _inscatterPass()
    if (!pass) { console.warn('[photo] no inscatter pass — activate photo mode first'); return }
    pass.setDebugMode(mode)
    console.log(`[photo] inscatter debug mode = ${mode}`)
  }

  function setMaterialPreset(repr, presetName) {
    _settings[repr] = presetName
    if (!_active) {
      console.log(`[photo] setMaterialPreset(${repr}, ${presetName}) — inactive, settings only`)
      showToast(`Photo ${repr}: ${presetName} (queued — activate photo mode first)`, 2200)
      return
    }
    let updated = 0, postActivate = 0, otherRepr = 0, ignored = 0
    const updatedNames = [], postActivateNames = []
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      if (obj.material.isLineBasicMaterial || obj.material.isLineDashedMaterial) { ignored++; return }
      if (obj.material.blending === THREE.AdditiveBlending) { ignored++; return }
      // Phase 7d: never swap the shared-renderer mid/far LOD impostors (custom
      // instancing shaders — a PBR swap collapses them to the source origin).
      if (obj.userData.sharedLodImpostor) { ignored++; return }
      if (obj.userData.photoFloor)        { ignored++; return }

      const r = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      if (r !== repr) { otherRepr++; return }
      // Fluorophore mesh owned by the emissive override — don't overwrite.
      if (obj.name === FLUORO_MESH_NAME && _settings.fluorophoreEmissive) {
        ignored++; return
      }

      const old = _savedMaterials.get(obj)
      if (!old) {
        // Mesh appeared after photo activate (e.g. atomistic/surface toggled on later).
        // Adopt it: save its current material so future preset swaps + deactivate work.
        _savedMaterials.set(obj, obj.material)
        const vc = Boolean(obj.material.vertexColors)
        const op = obj.material.opacity ?? 1.0
        obj.material = makeMaterial(repr, presetName, vc, op)
        _applyTranslucencyOverride(obj.material, repr)
        _reapplyShared(obj)
        postActivate++
        postActivateNames.push(obj.name || `<unnamed:${obj.type}>`)
        return
      }
      const vc = Boolean(old.vertexColors)
      const op = old.opacity ?? 1.0
      obj.material.dispose()
      obj.material = makeMaterial(repr, presetName, vc, op)
      _applyTranslucencyOverride(obj.material, repr)
      _reapplyShared(obj)
      updated++
      updatedNames.push(obj.name || `<unnamed:${obj.type}>`)
    })

    const total = updated + postActivate
    console.groupCollapsed(
      `[photo] setMaterialPreset(${repr}, ${presetName}) — `
      + `updated=${updated}, adopted=${postActivate}, otherRepr=${otherRepr}, ignored=${ignored}`,
    )
    console.log('preset params:', PRESETS[repr]?.[presetName])
    console.log('updated meshes:', updatedNames)
    console.log('adopted-after-activate meshes:', postActivateNames)
    console.groupEnd()

    const msg = total === 0
      ? `Photo ${repr}: 0 meshes matched (rep not visible?)`
      : postActivate > 0
        ? `Photo ${repr}: ${presetName} → ${updated}+${postActivate} new`
        : `Photo ${repr}: ${presetName} → ${updated} meshes`
    showToast(msg, 2200)

    _invalidate()
  }

  function setBackground(type, color = '#ffffff') {
    _settings.bgType  = type
    _settings.bgColor = color
    if (_active) _applyBackground()
  }

  function _installComposerRenderFn() {
    // Prime the throttle so the FIRST frame renders full quality (no motion, one
    // full-quality debt) rather than flashing an unstyled preview on entry.
    camera.updateMatrixWorld()
    _lastCam.copy(camera.matrixWorld)
    _camPrimed  = true
    _dirty      = true
    _previewing = false
    _idleFrames = _PREVIEW_SETTLE_FRAMES
    setRenderFn(() => {
      const moved = _cameraMoved()
      if (moved) { _idleFrames = 0; _previewing = true; _dirty = true }
      else       { _idleFrames++ }

      // A few still frames after motion stops → drop the preview and render the
      // final full-quality frame (the outstanding _dirty debt drives it).
      if (_previewing && !moved && _idleFrames >= _PREVIEW_SETTLE_FRAMES) _previewing = false

      // Idle with nothing owed: skip the composite (the last frame persists on
      // the canvas). A slow keepalive still redraws so an untracked scene change
      // (e.g. a live-sim frame applied while parked) appears within ~0.3 s.
      if (!_previewing && !_dirty && (_idleFrames % _IDLE_KEEPALIVE_FRAMES) !== 0) return

      if (_previewing) {
        // Cheap interactive preview: a single plain raster, no post chain. Keeps
        // orbiting/dollying responsive on heavy atomistic/surface geometry.
        renderer.resetState?.()
        renderer.render(scene, camera)
        return
      }

      _syncFluoroLights()
      if (_settings.envEffect === 'mist') {
        _gatherLightsForInscatter()
        _pushLightsTo(_inscatterPass())
      }
      // The depth-cue window is a function of where the camera is relative to
      // the structure, so it has to be refreshed as the user orbits/dollies.
      if (_settings.depthCue) _pushCueRangeTo(_figurePass())
      // Flush WebGLState's texture-unit binding cache before the composer
      // touches the scene. Without this, the bloom pass's heavy texture-unit
      // churn (5-level mip chain + high-pass + composite) can desync the
      // cache vs. actual GL bindings; on the next frame, MeshPhysicalMaterial
      // with metalness=1 + scene.environment can sample whatever texture
      // bloom last left on the env's unit → a uniformly black scene whenever
      // (bloom + HDRI + metallic) are all active. Disabling any of the three
      // happens to keep the relevant binding stable enough to avoid the bug.
      renderer.resetState?.()
      _composerHandle.composer.render()
      _dirty = false
    })
  }

  // SSAO + Bloom are always allocated in the composer (see post_processing.js);
  // toggling these controllers just flips `pass.enabled`. EffectComposer skips
  // disabled passes entirely, so the runtime cost when off is just an idle
  // mip-chain allocation.
  //
  // We deliberately do NOT rebuild the composer post-activate. The activate-
  // time fix for "bake AFTER composer" works because PMREM has never run on
  // the renderer yet; reconstructing later happens AFTER the activate-time
  // bake mutated renderer state, so the new UnrealBloomPass would inherit
  // that state and paint garbage when an HDRI env is active. The previous
  // "rebuild + re-bake" attempt didn't help because the construction step
  // happens BEFORE the re-bake within the rebuild — the construction sees
  // stale state. Avoiding reconstruction altogether is the right answer.
  function setSSAO(enabled) {
    _settings.ssao = enabled
    if (!_active) return
    const p = _composerHandle?.ssaoPass
    if (p) p.enabled = !!enabled
    _invalidate()
  }

  function setBloom(enabled, strength, radius, threshold) {
    _settings.bloom          = enabled
    if (strength   !== undefined) _settings.bloomStrength  = strength
    if (radius     !== undefined) _settings.bloomRadius    = radius
    if (threshold  !== undefined) _settings.bloomThreshold = threshold
    if (!_active) return
    const bp = _composerHandle?.bloomPass
    if (!bp) return
    bp.enabled   = !!enabled
    bp.strength  = _settings.bloomStrength
    bp.radius    = _settings.bloomRadius
    bp.threshold = _settings.bloomThreshold
    _invalidate()
  }

  function setFOV(fov) {
    _settings.fov = fov
    // A FOV at or below the parallel threshold IS the parallel projection —
    // keep the flag (and therefore the checkbox) honest either way.
    _settings.parallel = fov <= PARALLEL_FOV
    if (!_active) return
    _applyFovWithDolly(fov)
  }

  // Master exposure for filmic tone mapping. Higher = brighter before roll-off.
  function setExposure(v) {
    _settings.exposure = v
    if (!_active) return
    renderer.toneMappingExposure = v
    _invalidate()
  }

  function enablePathTracing(enabled) {
    _settings.pathTracing = enabled
    if (!_active) return
    if (enabled) _enablePathTracing()
    else _disablePathTracing()
  }

  function onSamplesUpdate(cb) { _onSamplesUpdate = cb }

  function getSampleCount() { return _ptSamples }

  // Diagnostic: the live enabled-state of the post-processing passes, read from
  // the actual composer (NOT _settings — which is only the stored intent). Used
  // by the photo_renderer tests to prove a setter reached the GPU-facing pass,
  // and handy from window.__photoRenderer when debugging a stuck effect. Returns
  // null before activate (no composer yet).
  function getComposerState() {
    const h = _composerHandle
    if (!h) return null
    return {
      bloom:          !!h.bloomPass?.enabled,
      bloomStrength:  h.bloomPass?.strength,
      bloomRadius:    h.bloomPass?.radius,
      bloomThreshold: h.bloomPass?.threshold,
      ssao:           !!h.ssaoPass?.enabled,
      mist:           !!h.inscatterPass?.enabled,
      // Figure pass is enabled iff at least one of outline / depth cue is on.
      figure:         !!h.figurePass?.enabled,
      outline:        (h.figurePass?.uniforms?.uOutline?.value ?? 0) > 0.5,
      depthCue:       (h.figurePass?.uniforms?.uCue?.value ?? 0) > 0.5,
      ao:             !!h.gtaoPass?.enabled,
      aoIntensity:    h.gtaoPass?.blendIntensity,
      toneMapping:    renderer.toneMapping,
      exposure:       renderer.toneMappingExposure,
    }
  }

  function isPathTracingBuilding() { return _ptBuilding }
  function isPathTracingEnabled()  { return _ptEnabled }
  function isActive()              { return _active }
  function getSettings()           { return { ..._settings } }
  // Floor plane world reach (or null) so the render loop can extend the camera
  // far clip to include the floor. Only meaningful while photo mode is active.
  function getFloorReach()         { return _active ? _floor.getReach() : null }

  // ── High-resolution PNG export ────────────────────────────────────────────

  /**
   * Begin a multi-frame export session. Creates ONE offscreen WebGLRenderer
   * + composer + env texture and reuses them across every renderFrame() call.
   *
   * Use this for video / animation exports — calling renderToBlob() in a
   * tight loop creates a fresh WebGL context each time, and browsers block
   * new contexts after roughly 30 are created (the "WebGLRenderer: Context
   * Lost" + "Web page caused context loss and was blocked" pair).
   *
   * Each renderFrame() returns a PNG Blob of the current scene at the
   * session's `width × height`. Call dispose() exactly once at the end.
   *
   * @param {number} width
   * @param {number} height
   * @returns {{renderFrame: () => Promise<Blob>, dispose: () => void}}
   */
  function beginFrameSession(width, height) {
    // Probe GPU max texture size once.
    const probeCanvas = document.createElement('canvas')
    const probeR = new THREE.WebGLRenderer({ canvas: probeCanvas, alpha: true })
    const maxTex = probeR.capabilities.maxTextureSize
    probeR.dispose()

    const tileMax = Math.min(maxTex, 4096)
    const tilesX  = Math.max(1, Math.ceil(width  / tileMax))
    const tilesY  = Math.max(1, Math.ceil(height / tileMax))
    const tileW   = Math.ceil(width  / tilesX)
    const tileH   = Math.ceil(height / tilesY)

    console.log(
      `[photo] beginFrameSession ${width}×${height}: gpu.maxTex=${maxTex}, `
      + `tiles=${tilesX}×${tilesY} @ ${tileW}×${tileH}`,
    )

    // CPU-side stitch canvas (reused across frames).
    const finalCanvas = document.createElement('canvas')
    finalCanvas.width  = width
    finalCanvas.height = height
    const finalCtx     = finalCanvas.getContext('2d')

    // ONE offscreen renderer for the entire session.
    const offCanvas = document.createElement('canvas')
    offCanvas.width  = tileW
    offCanvas.height = tileH
    const offRenderer = new THREE.WebGLRenderer({
      canvas: offCanvas,
      antialias: true,
      alpha:    true,
      preserveDrawingBuffer: true,
    })
    offRenderer.setPixelRatio(1)
    // Match the live preview's filmic tone mapping so exports don't clip/wash.
    offRenderer.toneMapping         = THREE.ACESFilmicToneMapping
    offRenderer.toneMappingExposure = _settings.exposure
    offRenderer.setSize(tileW, tileH, false)
    offRenderer.shadowMap.enabled = _shadowRigApplied
    if (_shadowRigApplied) offRenderer.shadowMap.type = THREE.PCFSoftShadowMap
    const { color, alpha } = _bgClearParams()
    offRenderer.setClearColor(color, alpha)

    const savedSceneEnv = scene.environment
    const savedSceneBg  = scene.background
    let exportEnvTex = null

    const composerOpts = {
      ssao:           _settings.ssao,
      ao:             _settings.ao,
      aoRadius:       _settings.aoRadius,
      aoIntensity:    _settings.aoIntensity,
      bloom:          _settings.bloom,
      bloomStrength:  _settings.bloomStrength,
      bloomRadius:    _settings.bloomRadius,
      bloomThreshold: _settings.bloomThreshold,
    }
    // ONE composer for the entire session. The composer's render targets
    // are sized to (tileW × tileH); we drive different tiles by changing
    // camera.setViewOffset() per render.
    //
    // IMPORTANT: build the composer BEFORE baking the env into this renderer's
    // context. PMREMGenerator mutates renderer state as a side effect; if the
    // bake happens first, the freshly-constructed UnrealBloomPass inherits
    // that state and produces an angle-dependent colour tint over the scene
    // (matches the activate() order).
    const sessionComposer = createComposer(offRenderer, scene, camera, composerOpts)
    if (_envSourceType !== 'off') {
      exportEnvTex = _bakeEnvFor(offRenderer)
      scene.environment = exportEnvTex
      if (_settings.environmentBackground && exportEnvTex) scene.background = exportEnvTex
    }
    if (_settings.envEffect === 'mist') {
      sessionComposer.inscatterPass.enabled = true
      _pushInscatterParamsTo(sessionComposer.inscatterPass)
      _gatherLightsForInscatter()
      _pushLightsTo(sessionComposer.inscatterPass)
    }
    // Figure pass + occlusion shading: this session's composer has its own pass
    // instances in its own GL context, so they need the settings pushed into
    // them exactly like the live one (same per-renderer rule as the HDRI bake).
    _pushFigureParamsTo(sessionComposer.figurePass)
    _pushAOParamsTo(sessionComposer.gtaoPass)

    let _disposed = false

    async function renderFrame() {
      if (_disposed) throw new Error('beginFrameSession: renderFrame() called after dispose()')
      const origAspect = camera.aspect
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      try {
        for (let ty = 0; ty < tilesY; ty++) {
          for (let tx = 0; tx < tilesX; tx++) {
            const xOff = tx * tileW
            const yOff = ty * tileH
            camera.setViewOffset(width, height, xOff, yOff, tileW, tileH)
            camera.updateProjectionMatrix()
            if (_settings.envEffect === 'mist') {
              _pushInscatterParamsTo(sessionComposer.inscatterPass)
              _gatherLightsForInscatter()
              _pushLightsTo(sessionComposer.inscatterPass)
            }
            if (_settings.depthCue) _pushCueRangeTo(sessionComposer.figurePass)
            _syncFluoroLights()
            // Same per-frame state-cache flush we do on the live renderer
            // (see _installComposerRenderFn). Without this, exports of a
            // bloom + HDRI + metallic scene can come out fully black even
            // when the live preview renders correctly.
            offRenderer.resetState?.()
            sessionComposer.composer.render()
            finalCtx.drawImage(offCanvas, xOff, yOff)
          }
        }
        return await new Promise(resolve => finalCanvas.toBlob(resolve, 'image/png'))
      } finally {
        camera.clearViewOffset()
        camera.aspect = origAspect
        camera.updateProjectionMatrix()
      }
    }

    function dispose() {
      if (_disposed) return
      _disposed = true
      try { sessionComposer.dispose() } catch { /* ignore */ }
      if (exportEnvTex) {
        scene.environment = savedSceneEnv
        scene.background  = savedSceneBg
        exportEnvTex.dispose()
      }
      try { offRenderer.dispose() } catch { /* ignore */ }
    }

    return { renderFrame, dispose }
  }

  /**
   * Render at target resolution and return a PNG Blob.
   * Tiled to bypass WebGL MAX_TEXTURE_SIZE limits: splits the image into
   * sub-camera frustums via camera.setViewOffset() and stitches into a
   * 2D canvas on the CPU side.
   *
   * @param {number} width
   * @param {number} height
   * @returns {Promise<Blob>}
   */
  async function renderToBlob(width, height) {
    // Probe GPU limit
    const probeCanvas = document.createElement('canvas')
    const probeR = new THREE.WebGLRenderer({ canvas: probeCanvas, alpha: true })
    const maxTex = probeR.capabilities.maxTextureSize
    probeR.dispose()

    // The composer allocates several full-size render targets (color, depth,
    // SSAO blur, optional bloom mip chain). Stay well below maxTex to leave
    // headroom and avoid GPU/driver edge cases at the boundary.
    const tileMax = Math.min(maxTex, 4096)
    const tilesX  = Math.max(1, Math.ceil(width  / tileMax))
    const tilesY  = Math.max(1, Math.ceil(height / tileMax))
    const tileW   = Math.ceil(width  / tilesX)
    const tileH   = Math.ceil(height / tilesY)

    console.log(
      `[photo] renderToBlob ${width}×${height}: gpu.maxTex=${maxTex}, `
      + `tiles=${tilesX}×${tilesY} @ ${tileW}×${tileH}`,
    )

    // CPU-side stitch canvas (no GL limit applies here).
    const finalCanvas = document.createElement('canvas')
    finalCanvas.width  = width
    finalCanvas.height = height
    const finalCtx     = finalCanvas.getContext('2d')

    // Single offscreen renderer reused for every tile.
    const offCanvas = document.createElement('canvas')
    offCanvas.width  = tileW
    offCanvas.height = tileH
    const offRenderer = new THREE.WebGLRenderer({
      canvas: offCanvas,
      antialias: true,
      alpha:    true,
      preserveDrawingBuffer: true,
    })
    offRenderer.setPixelRatio(1)
    // Match the live preview's filmic tone mapping so exports don't clip/wash.
    offRenderer.toneMapping         = THREE.ACESFilmicToneMapping
    offRenderer.toneMappingExposure = _settings.exposure
    offRenderer.setSize(tileW, tileH, false)
    offRenderer.shadowMap.enabled = _shadowRigApplied
    if (_shadowRigApplied) offRenderer.shadowMap.type = THREE.PCFSoftShadowMap

    if (offCanvas.width !== tileW || offCanvas.height !== tileH) {
      console.warn(
        `[photo] browser clamped tile canvas: requested ${tileW}×${tileH}, got ${offCanvas.width}×${offCanvas.height}. `
        + `Image may have gaps. Lower tileMax in photo_renderer.js.`,
      )
    }

    const { color, alpha } = _bgClearParams()
    offRenderer.setClearColor(color, alpha)

    const composerOpts = {
      ssao:          _settings.ssao,
      ao:            _settings.ao,
      aoRadius:      _settings.aoRadius,
      aoIntensity:   _settings.aoIntensity,
      bloom:         _settings.bloom,
      bloomStrength: _settings.bloomStrength,
      bloomRadius:   _settings.bloomRadius,
      bloomThreshold: _settings.bloomThreshold,
    }

    // Re-bake the environment for the offscreen renderer's GL context — the
    // main renderer's PMREM texture is unusable in another context.
    //
    // IMPORTANT: composer first, env bake second (matches activate's order).
    // PMREM mutates renderer state; if the bake happens first the freshly-built
    // UnrealBloomPass inherits that state and paints garbage.
    //
    // ONE composer reused across every tile — only camera.setViewOffset changes.
    // (Old code re-built the composer per tile, which compounded the PMREM-after
    // bug on every tile.)
    const exportComposer   = createComposer(offRenderer, scene, camera, composerOpts)
    const savedSceneEnv    = scene.environment
    const savedSceneBg     = scene.background
    let   exportEnvTex     = null
    if (_envSourceType !== 'off') {
      exportEnvTex      = _bakeEnvFor(offRenderer)
      scene.environment = exportEnvTex
      if (_settings.environmentBackground && exportEnvTex) {
        scene.background = exportEnvTex
      }
    }
    if (_settings.envEffect === 'mist') {
      exportComposer.inscatterPass.enabled = true
      _pushInscatterParamsTo(exportComposer.inscatterPass)
      _gatherLightsForInscatter()
      _pushLightsTo(exportComposer.inscatterPass)
    }
    // Figure pass + occlusion shading — per-renderer pass instances, same rule
    // as the env bake: push the settings into THIS composer or the export comes
    // out without the outline the preview is showing.
    _pushFigureParamsTo(exportComposer.figurePass)
    _pushAOParamsTo(exportComposer.gtaoPass)

    const origAspect = camera.aspect
    camera.aspect = width / height
    camera.updateProjectionMatrix()

    try {
      for (let ty = 0; ty < tilesY; ty++) {
        for (let tx = 0; tx < tilesX; tx++) {
          const xOff = tx * tileW
          const yOff = ty * tileH
          camera.setViewOffset(width, height, xOff, yOff, tileW, tileH)
          camera.updateProjectionMatrix()

          if (_settings.envEffect === 'mist') {
            _pushInscatterParamsTo(exportComposer.inscatterPass)
            _gatherLightsForInscatter()
            _pushLightsTo(exportComposer.inscatterPass)
          }
          if (_settings.depthCue) _pushCueRangeTo(exportComposer.figurePass)
          _syncFluoroLights()
          // Match the live render loop's per-frame state-cache flush, otherwise
          // bloom + HDRI + metallic exports can come out fully black.
          offRenderer.resetState?.()
          exportComposer.composer.render()

          finalCtx.drawImage(offCanvas, xOff, yOff)
        }
      }
      return await new Promise(resolve => finalCanvas.toBlob(resolve, 'image/png'))
    } finally {
      camera.clearViewOffset()
      camera.aspect = origAspect
      camera.updateProjectionMatrix()
      // Restore main-renderer env binding (still valid after offRenderer disposes).
      if (exportEnvTex) {
        scene.environment = savedSceneEnv
        scene.background  = savedSceneBg
        exportEnvTex.dispose()
      }
      try { exportComposer.dispose() } catch { /* ignore */ }
      offRenderer.dispose()
    }
  }

  // ── Resize (called by scene when window resizes while photo mode is active) ─

  function handleResize(width, height) {
    if (!_active || !_composerHandle) return
    _composerHandle.setSize(width, height)
    _camPrimed = false   // re-prime; a resize invalidates the cached matrix framing
    _invalidate()
    if (_ptEnabled && _ptRenderer) _ptRenderer.reset()
  }

  const _api = {
    activate,
    deactivate,
    setLighting,
    setLightingDirection,
    setMaterialPreset,
    setFluorophoreEmissive,
    setFluorophoreIntensity,
    setEnvironment,
    setEnvironmentBackground,
    setEnvironmentalEffect,
    setMistDensity,
    setMistColor,
    setMistHaloIntensity,
    setMistNoise,
    setMistDebug,
    setTranslucency,
    setSun,
    setSunAzimuth,
    setSunElevation,
    setSunStrength,
    setSunColor,
    setFloor,
    setFloorMaterial,
    setFloorColor,
    setFloorOpacity,
    setFloorSize,
    setFloorOffset,
    setFloorShadows,
    setFloorGrid,
    setFloorGridDensity,
    setFloorGridNeon,
    setFloorGridColor,
    setFloorGridGlow,
    setFloorGridFade,
    setBackground,
    setSSAO,
    setBloom,
    setFOV,
    setExposure,
    // Figure controls — each independent; the Publication style preset just
    // switches the right ones on (see photo_renderer/style_presets.js).
    setOutline,
    setOutlineColor,
    setOutlineStrength,
    setOutlineThickness,
    setOutlineSensitivity,
    setDepthCue,
    setDepthCueColor,
    setDepthCueStrength,
    setAO,
    setAORadius,
    setAOIntensity,
    setParallel,
    getComposerState,
    enablePathTracing,
    onSamplesUpdate,
    getSampleCount,
    isPathTracingBuilding,
    isPathTracingEnabled,
    isActive,
    getSettings,
    getFloorReach,
    resyncMaterials,
    renderToBlob,
    beginFrameSession,
    handleResize,
    // Force the next frame to redraw at full quality. Call after mutating the
    // scene in a way the render throttle can't detect on its own (e.g. a live
    // sim frame applied while the camera is parked). The idle keepalive already
    // catches such changes within ~0.3 s; this makes them instant.
    invalidate: _invalidate,

    // Exposed for debug helpers
    get _composerHandle() { return _composerHandle },
    get _savedMaterials() { return _savedMaterials },
    get PRESETS()         { return PRESETS },
    get LIGHTING_PRESETS(){ return LIGHTING_PRESETS },
  }

  // Every public `set*` mutates how the scene looks, so mark it dirty after it
  // runs — that way its change redraws immediately even while the render loop is
  // idle-throttled (see _installComposerRenderFn), without hand-annotating ~30
  // setter bodies (and without a future setter silently missing the redraw).
  for (const k of Object.keys(_api)) {
    if (/^set[A-Z]/.test(k) && typeof _api[k] === 'function') {
      const fn = _api[k]
      _api[k] = (...args) => { const r = fn(...args); _invalidate(); return r }
    }
  }

  return _api
}
