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

import { PRESETS, makeMaterial }         from './photo_renderer/material_presets.js'
import { LIGHTING_PRESETS, applyLighting } from './photo_renderer/lighting_presets.js'
import { createComposer }                  from './photo_renderer/post_processing.js'

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
  let _photoGroup      = null       // THREE.Group holding photo-mode lights
  let _savedBgColor    = new THREE.Color()
  let _savedBgAlpha    = 0

  // ── Current settings (persisted across activate/deactivate for UI binding) ──
  const _settings = {
    lighting:  'studio',
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
  }

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

      const repr = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      const presetName = _settings[repr] ?? 'matte'
      const vc = Boolean(obj.material.vertexColors)
      const op = obj.material.opacity ?? 1.0

      _savedMaterials.set(obj, obj.material)
      obj.material = makeMaterial(repr, presetName, vc, op)
    })
  }

  function _restoreMaterials() {
    for (const [obj, mat] of _savedMaterials) {
      obj.material = mat
    }
    _savedMaterials.clear()
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
      setRenderFn(() => _composerHandle.composer.render())
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

    // Swap materials
    _swapMaterials()

    // Save renderer background
    renderer.getClearColor(_savedBgColor)
    _savedBgAlpha = renderer.getClearAlpha()
    _applyBackground()

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

    // Override render loop
    setRenderFn(() => _composerHandle.composer.render())

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

    // Remove photo lights, restore originals
    if (_photoGroup) { scene.remove(_photoGroup); _photoGroup = null }
    _restoreOriginalLights()

    // Restore background
    renderer.setClearColor(_savedBgColor, _savedBgAlpha)
    scene.background = _savedBgAlpha === 0 ? null : _savedBgColor.clone()

    // Dispose composer
    _composerHandle?.dispose()
    _composerHandle = null
  }

  // ── Live setting changes ───────────────────────────────────────────────────

  function setLighting(presetName) {
    _settings.lighting = presetName
    if (!_active || !_photoGroup) return
    applyLighting(presetName, _photoGroup)
    if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }
  }

  function setMaterialPreset(repr, presetName) {
    _settings[repr] = presetName
    if (!_active) return
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      const r = MESH_NAME_TO_REPR[obj.name] ?? _inferRepr(obj)
      if (r !== repr) return
      const old = _savedMaterials.get(obj)
      if (!old) return
      const vc = Boolean(old.vertexColors)
      const op = old.opacity ?? 1.0
      obj.material.dispose()
      obj.material = makeMaterial(repr, presetName, vc, op)
    })
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
    if (!_ptEnabled) setRenderFn(() => _composerHandle.composer.render())
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
    if (!_ptEnabled) setRenderFn(() => _composerHandle.composer.render())
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
   * Always uses the SSAO Tier-1 pipeline for reliable, fast export.
   * Creates a dedicated offscreen renderer so the main view is unaffected.
   *
   * @param {number} width
   * @param {number} height
   * @returns {Promise<Blob>}
   */
  async function renderToBlob(width, height) {
    // Build offscreen canvas + renderer
    const offCanvas = document.createElement('canvas')
    offCanvas.width  = width
    offCanvas.height = height
    const offRenderer = new THREE.WebGLRenderer({
      canvas: offCanvas,
      antialias: true,
      alpha:    true,
      preserveDrawingBuffer: true,
    })
    offRenderer.setSize(width, height, false)
    offRenderer.setPixelRatio(1)
    offRenderer.shadowMap.enabled = false

    // Apply background to export renderer
    const { color, alpha } = _bgClearParams()
    offRenderer.setClearColor(color, alpha)

    // Temporarily adjust camera aspect
    const origAspect = camera.aspect
    camera.aspect = width / height
    camera.updateProjectionMatrix()

    try {
      const exportComposer = createComposer(offRenderer, scene, camera, {
        ssao:          _settings.ssao,
        bloom:         _settings.bloom,
        bloomStrength: _settings.bloomStrength,
        bloomRadius:   _settings.bloomRadius,
        bloomThreshold: _settings.bloomThreshold,
      })
      exportComposer.composer.render()
      exportComposer.dispose()

      return await new Promise(resolve => offCanvas.toBlob(resolve, 'image/png'))
    } finally {
      camera.aspect = origAspect
      camera.updateProjectionMatrix()
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
    setMaterialPreset,
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
