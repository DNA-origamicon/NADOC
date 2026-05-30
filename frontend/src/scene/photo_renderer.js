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
  curvedHelixCylindersProxy: 'cylinders',
  curvedOvhgGroup:           'cylinders',
  'dna-surface':             'surface',
}

// Detect surface mesh by DoubleSide material when name doesn't match
function _inferRepr(obj) {
  if (obj.material?.side === THREE.DoubleSide) return 'surface'
  if (obj.material instanceof THREE.MeshStandardMaterial) return 'atomistic'
  return 'full'
}

// ── Photo renderer factory ────────────────────────────────────────────────────

export function createPhotoRenderer(sceneCtx) {
  const { scene, camera, renderer, setRenderFn, resetRenderFn } = sceneCtx

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
  const _settings = {
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
    fov:        null,   // null = keep current
    ortho:      false,
    pathTracing: false,
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
  }

  // Environment state — kept separately so we can restore on deactivate and
  // re-bake against the offscreen renderer during export.
  let _envSourceType   = 'room'     // 'off' | 'room' | 'file' (default: studio reflections)
  let _envSourceHDR    = null       // DataTexture loaded by RGBELoader (raster source)
  let _envTexture      = null       // PMREM-baked texture currently in scene.environment
  let _savedSceneEnv   = undefined  // pre-photo-mode scene.environment

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

  // ── Path tracing state ────────────────────────────────────────────────────
  let _ptRenderer    = null
  let _ptFsQuad      = null   // FullScreenQuad for blitting PT result
  let _ptSamples     = 0
  let _ptBuilding    = false
  let _ptEnabled     = false
  let _onSamplesUpdate = null  // callback(count) from panel

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
    scene.environment = _envTexture
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
    _applyEnvToScene()
    console.log(`[photo] setEnvironment(${mode}) → ${_settings.environmentName || 'off'}`)
    showToast(`Environment: ${_settings.environmentName || 'off'}`, 2200)
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
  }

  function setEnvironmentBackground(enabled) {
    _settings.environmentBackground = enabled
    if (!_active) return
    _applyBackground()
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    _photoGroup?.traverse(visit)
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

  // (Re)position the sun light from current settings. Uses the floor's bbox
  // when available (for shadow camera fit + target); falls back to scene
  // origin / unit distance if there's no floor or no scene yet.
  function _applySun() {
    if (!_active) return
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

  function setSun(on)             { _settings.sun          = !!on; _applySun(); if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 } }
  function setSunAzimuth(deg)     { _settings.sunAzimuth   = deg;  _applySun(); if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 } }
  function setSunElevation(deg)   { _settings.sunElevation = deg;  _applySun(); if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 } }
  function setSunStrength(v)      { _settings.sunStrength  = v;    _applySun(); if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 } }
  function setSunColor(hex)       { _settings.sunColor     = hex;  _applySun(); if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 } }

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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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

    // Save and optionally override FOV
    if (_settings.fov != null) {
      camera.fov = _settings.fov
      camera.updateProjectionMatrix()
    }

    // Build EffectComposer
    _composerHandle = createComposer(renderer, scene, camera, {
      ssao:          _settings.ssao,
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
  }

  function setLightingDirection(yawDeg, pitchDeg) {
    if (yawDeg   != null) _settings.lightingYaw   = yawDeg
    if (pitchDeg != null) _settings.lightingPitch = pitchDeg
    _applyLightingRotation()
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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

    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
  }

  function setBackground(type, color = '#ffffff') {
    _settings.bgType  = type
    _settings.bgColor = color
    if (_active) _applyBackground()
  }

  function _installComposerRenderFn() {
    setRenderFn(() => {
      _syncFluoroLights()
      if (_settings.envEffect === 'mist') {
        _gatherLightsForInscatter()
        _pushLightsTo(_inscatterPass())
      }
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
  }

  function setFOV(fov) {
    _settings.fov = fov
    if (!_active) return
    camera.fov = fov
    camera.updateProjectionMatrix()
  }

  function enablePathTracing(enabled) {
    _settings.pathTracing = enabled
    if (!_active) return
    if (enabled) _enablePathTracing()
    else _disablePathTracing()
  }

  function onSamplesUpdate(cb) { _onSamplesUpdate = cb }

  function getSampleCount() { return _ptSamples }
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
    if (_ptEnabled && _ptRenderer) _ptRenderer.reset()
  }

  return {
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
    setBackground,
    setSSAO,
    setBloom,
    setFOV,
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

    // Exposed for debug helpers
    get _composerHandle() { return _composerHandle },
    get _savedMaterials() { return _savedMaterials },
    get PRESETS()         { return PRESETS },
    get LIGHTING_PRESETS(){ return LIGHTING_PRESETS },
  }
}
