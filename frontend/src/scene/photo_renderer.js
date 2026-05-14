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
    environment:           'off',   // 'off' | 'room' | 'file'
    environmentName:       '',      // human-readable identifier
    environmentBackground: false,
    translucency:          0.0,     // 0..1, applied to full + cylinders reps
  }

  // Environment state — kept separately so we can restore on deactivate and
  // re-bake against the offscreen renderer during export.
  let _envSourceType   = 'off'      // 'off' | 'room' | 'file'
  let _envSourceHDR    = null       // DataTexture loaded by RGBELoader (raster source)
  let _envTexture      = null       // PMREM-baked texture currently in scene.environment
  let _savedSceneEnv   = undefined  // pre-photo-mode scene.environment

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

  function _swapMaterials() {
    _savedMaterials.clear()
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      // Don't touch the axis line meshes (they use LineBasicMaterial)
      if (obj.material.isLineBasicMaterial || obj.material.isLineDashedMaterial) return
      // Skip helpers and glow layers (additive blending sprites)
      if (obj.material.blending === THREE.AdditiveBlending) return

      const vc = Boolean(obj.material.vertexColors)
      const op = obj.material.opacity ?? 1.0
      _savedMaterials.set(obj, obj.material)

      if (obj.name === FLUORO_MESH_NAME && _settings.fluorophoreEmissive) {
        obj.material = makeFluorophoreEmissive(_settings.fluorophoreIntensity, vc)
        return
      }
      const repr = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      const presetName = _settings[repr] ?? 'matte'
      obj.material = makeMaterial(repr, presetName, vc, op)
      _applyTranslucencyOverride(obj.material, repr)
    })
  }

  function _restoreMaterials() {
    for (const [obj, mat] of _savedMaterials) {
      obj.material = mat
    }
    _savedMaterials.clear()
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
      const repr = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      _applyTranslucencyOverride(obj.material, repr)
    })
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
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
    if (_composerHandle) {
      setRenderFn(() => {
        _syncFluoroLights()
        _composerHandle.composer.render()
      })
    }
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
    // Bake current environment (if one was set via setEnvironment before activate)
    if (_envSourceType !== 'off') {
      _envTexture = _bakeEnvFor(renderer)
    }
    _applyEnvToScene()

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

    // Override render loop — sync fluoro lights per frame so they track design moves.
    setRenderFn(() => {
      _syncFluoroLights()
      _composerHandle.composer.render()
    })

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
        postActivate++
        postActivateNames.push(obj.name || `<unnamed:${obj.type}>`)
        return
      }
      const vc = Boolean(old.vertexColors)
      const op = old.opacity ?? 1.0
      obj.material.dispose()
      obj.material = makeMaterial(repr, presetName, vc, op)
      _applyTranslucencyOverride(obj.material, repr)
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

  function setSSAO(enabled) {
    _settings.ssao = enabled
    if (!_active) return
    // Rebuild composer with new SSAO state
    _composerHandle?.dispose()
    _composerHandle = createComposer(renderer, scene, camera, {
      ssao:          enabled,
      bloom:         _settings.bloom,
      bloomStrength: _settings.bloomStrength,
      bloomRadius:   _settings.bloomRadius,
      bloomThreshold: _settings.bloomThreshold,
    })
    if (!_ptEnabled) setRenderFn(() => { _syncFluoroLights(); _composerHandle.composer.render() })
  }

  function setBloom(enabled, strength, radius, threshold) {
    _settings.bloom          = enabled
    if (strength   !== undefined) _settings.bloomStrength  = strength
    if (radius     !== undefined) _settings.bloomRadius    = radius
    if (threshold  !== undefined) _settings.bloomThreshold = threshold
    if (!_active) return
    _composerHandle?.dispose()
    _composerHandle = createComposer(renderer, scene, camera, {
      ssao: _settings.ssao, bloom: enabled,
      bloomStrength: _settings.bloomStrength,
      bloomRadius: _settings.bloomRadius,
      bloomThreshold: _settings.bloomThreshold,
    })
    if (!_ptEnabled) setRenderFn(() => { _syncFluoroLights(); _composerHandle.composer.render() })
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

  // ── High-resolution PNG export ────────────────────────────────────────────

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
    offRenderer.shadowMap.enabled = false

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

          const exportComposer = createComposer(offRenderer, scene, camera, composerOpts)
          _syncFluoroLights()
          exportComposer.composer.render()
          exportComposer.dispose()

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
    setTranslucency,
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
    renderToBlob,
    handleResize,

    // Exposed for debug helpers
    get _composerHandle() { return _composerHandle },
    get _savedMaterials() { return _savedMaterials },
    get PRESETS()         { return PRESETS },
    get LIGHTING_PRESETS(){ return LIGHTING_PRESETS },
  }
}
