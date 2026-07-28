/**
 * Experimental photo mode — a deliberately small testbed for the rendering
 * ideas we want to evaluate before they earn a place in the real photo tab.
 *
 * It is NOT a second photo mode with feature parity. What it has:
 *
 *   • flat figure materials (no specular lobe at all)
 *   • a CAMERA-PINNED key light — ChimeraX's move_lights_with_camera, so the
 *     shadow sweeps across the structure as you reorient it
 *   • a real KEY-LIGHT SHADOW MAP, with no floor required, so an object casts
 *     onto whatever is behind it
 *   • a plain background and SMAA
 *
 * No HDRI, no bloom, no path tracer, no floor, no mist, no export.
 *
 * REMOVED 2026-07-28 — multishadow ambient occlusion. A faithful port of
 * ChimeraX's 64-direction ambient shadows shipped here and was cut after
 * side-by-side evaluation: at origami scale each of the 64 per-direction maps
 * is far too coarse to resolve a 2 nm duplex (ChimeraX's 1024 default gives
 * ~2.3 nm/texel on a 150 nm structure), so it never produced the long-range
 * cast shadows it does on a 5 nm protein — only a vague wash that fought the
 * key shadow. The one part worth keeping was its frustum fitting, which now
 * lives in photo_renderer/shadow_bounds.js. See
 * photo_mode_ao_and_lowpoly_spec.md for the full findings.
 *
 * Display-layer only — never mutates Design topology (Three-Layer Law).
 * Every piece of state it changes is saved on activate and restored on
 * deactivate, the same contract the shipping photo renderer honours.
 */

import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass }     from 'three/addons/postprocessing/RenderPass.js'
import { SMAAPass }       from 'three/addons/postprocessing/SMAAPass.js'
import { OutputPass }     from 'three/addons/postprocessing/OutputPass.js'

import { makeMaterial }               from './photo_renderer/material_presets.js'
import { applyLighting, LIGHTING_PRESETS } from './photo_renderer/lighting_presets.js'
import { computeShadowBounds, isShadowExcluded, findBoundsOutlier, rejectedObjects,
         sceneSignature } from './photo_renderer/shadow_bounds.js'
import { initPhotoExpPanel }          from '../ui/photo_exp_panel.js'

/** Factory defaults — the single source of truth for "what the experiment looks
 *  like out of the box". */
export const DEFAULT_EXP_SETTINGS = Object.freeze({
  lighting:   'full',         // key in LIGHTING_PRESETS
  bgType:     'color',        // 'color' | 'transparent'
  bgColor:    '#0b0d10',

  // ChimeraX stores light directions in CAMERA coordinates with
  // move_lights_with_camera = True, so the key light is pinned to the viewer and
  // its shadow sweeps across the structure as you reorient. Without this the rig
  // is welded to the world and orbiting just walks you into the dark side.
  pinLights:  true,

  // A real shadow map cast by the key light, deliberately NOT gated on a floor.
  keyShadow:  true,
  keyShadowMapSize: 2048,     // ChimeraX shadow_map_size; one map, so it is cheap
  keyShadowBias: 1.0,         // × the texel-scaled normalBias; raise to kill acne
  shadowStrength:   1.0,      // three's LightShadow.intensity; 1 = physical
})


/**
 * Swap every eligible mesh to the flat figure material, returning a restore
 * handle. Deliberately representation-AGNOSTIC: it keys off what the material
 * *is*, never off mesh names, so beads, slabs, cones, cylinders, atoms, bonds,
 * the marching-cubes surface and hull prisms are all covered without a lookup
 * table to keep in sync.
 *
 * Preserved from the source material: `side` (the surface mesh is DoubleSide
 * because its junction edges are non-manifold), `vertexColors`, sub-1 opacity,
 * and — unlike the shipping photo mode — the material COLOUR when the mesh has
 * neither vertex colours nor instance colours, so a uniformly-coloured mesh
 * (hull prism, cylinder proxy) doesn't turn white.
 *
 * Skipped: impostor materials (their sphere ray-paint lives in an
 * onBeforeCompile patch that a fresh material would drop), shared-renderer LOD
 * impostors, additive glow sprites, helper lines, and the photo floor.
 *
 * @param {THREE.Object3D} root
 * @returns {{restore: () => void, count: number}}
 */
/** How often (in rendered frames) to re-fingerprint the geometry. ~0.5 s at 60 fps. */
const SIGNATURE_CHECK_FRAMES = 30

export function swapToFlatMaterials(root) {
  const saved = new Map()
  root.traverse(obj => {
    if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
    const src = obj.material
    if (Array.isArray(src)) return
    if (src.isLineBasicMaterial || src.isLineDashedMaterial) return
    if (src.blending === THREE.AdditiveBlending) return
    if (src.userData?.isImpostor || src.userData?.impostorRadius != null) return
    if (obj.userData?.sharedLodImpostor) return
    if (obj.userData?.photoFloor) return

    const vc = Boolean(src.vertexColors)
    const mat = makeMaterial('full', 'flat', vc, 1.0)
    mat.side = src.side
    if (src.transparent && src.opacity < 1) {
      mat.transparent = true
      mat.opacity     = src.opacity
    }
    // Only force white where a per-instance / per-vertex colour will supply the
    // real colour; otherwise carry the source colour through.
    if (!vc && !obj.instanceColor && src.color) mat.color.copy(src.color)

    saved.set(obj, src)
    obj.material = mat
  })
  return {
    count: saved.size,
    restore() {
      for (const [obj, mat] of saved) {
        const swapped = obj.material
        obj.material = mat
        if (swapped !== mat) swapped?.dispose?.()
      }
      saved.clear()
    },
  }
}

/**
 * @param {object} sceneCtx — the shared scene context from scene.js
 * @returns experimental photo-mode controller
 */
export function createExpPhotoMode(sceneCtx) {
  const { scene, camera, renderer, setRenderFn, resetRenderFn,
          setResizeCallback, clearResizeCallback } = sceneCtx

  const _settings = { ...DEFAULT_EXP_SETTINGS }

  let _active      = false
  let _composer    = null
  let _matSwap     = null
  let _lightGroup  = null
  let _lightTarget = null        // sits at the rig's local origin = scene centre
  let _keyLight    = null        // the one directional that casts the shadow
  let _savedLights = []          // [{light, visible}] of the editor's own lights
  let _savedEnv    = undefined
  let _savedBg     = undefined
  const _savedClearColor = new THREE.Color()
  let _savedClearAlpha   = 1
  let _savedToneMapping  = null
  let _savedExposure     = null
  let _savedShadowEnabled = null
  let _savedShadowType    = null
  const _savedMeshShadows = new Map()   // mesh → {cast, receive}
  let _bounds = null                    // {center, radius} the rig is fitted to
  let _rejected = new Set()             // objects too large to be part of the structure
  let _signature = null                 // geometry fingerprint the rig is fitted to
  let _sigFrame  = 0

  // ── Scene state save / restore ─────────────────────────────────────────────

  function _hideEditorLights() {
    _savedLights = []
    scene.traverse(obj => {
      if (!obj.isLight) return
      if (_lightGroup && obj.parent === _lightGroup) return
      _savedLights.push({ light: obj, visible: obj.visible })
      obj.visible = false
    })
  }

  function _restoreEditorLights() {
    for (const { light, visible } of _savedLights) light.visible = visible
    _savedLights = []
  }

  function _applyBackground() {
    if (_settings.bgType === 'transparent') {
      scene.background = null
      renderer.setClearColor(0x000000, 0)
    } else {
      const c = new THREE.Color(_settings.bgColor)
      scene.background = c
      renderer.setClearColor(c, 1)
    }
  }

  // ── Light rig: camera-pinned, fitted to the scene's bounding sphere ─────────

  /**
   * Rebuild the rig for the active preset and fit it to the scene.
   *
   * The rig is a Group parked at the scene CENTRE with the lights pushed out onto
   * a sphere of radius 2R, and a target object at the group's local origin. Two
   * consequences, both load-bearing:
   *   • rotating the group sweeps the lights around the structure while every
   *     light keeps aiming at the centre — that is what makes camera-pinning a
   *     single quaternion copy;
   *   • the shadow frustum can be fitted ONCE, because a sphere looks the same
   *     from every direction. No per-frame refit as the rig spins.
   */
  function _rebuildRig() {
    if (!_lightGroup) return
    applyLighting(_settings.lighting, _lightGroup)

    _bounds = computeShadowBounds(scene)
    _rejected = rejectedObjects(_bounds)
    _signature = sceneSignature(scene)
    _sigFrame = 0
    const outlier = findBoundsOutlier(_bounds)
    if (outlier) {
      console.warn(
        `[exp-photo] Excluded ${outlier.rejectedCount} oversized object(s) from shadows/occlusion — `
        + `they would have set the frustum instead of the structure.\n`
        + `  Largest: "${outlier.worst.name}" (${outlier.worst.type}, ${outlier.worst.material}) spanning `
        + `${outlier.worst.extent} nm — ${outlier.ratio}× the median mesh (${outlier.medianExtent.toFixed(1)} nm).\n`
        + `  Frustum radius is now ${_bounds.radius.toFixed(1)} nm. If that object SHOULD occlude, `
        + `raise OUTLIER_RATIO in multishadow_ao.js.`,
        outlier,
      )
    }
    const R = _bounds?.radius ?? 1
    if (_bounds) _lightGroup.position.copy(_bounds.center)
    else _lightGroup.position.set(0, 0, 0)

    _lightTarget = new THREE.Object3D()
    _lightGroup.add(_lightTarget)

    // Per-light intensities override the preset's, so the sliders are absolute
    // values like ChimeraX's `lighting intensity` rather than relative nudges.
    for (const child of _lightGroup.children) {
      if (child.isAmbientLight) child.intensity = _settings.ambientIntensity
    }

    _keyLight = null
    let seenDirectional = 0
    for (const child of _lightGroup.children) {
      if (!child.isDirectionalLight) continue
      child.intensity = (seenDirectional++ === 0)
        ? _settings.keyIntensity
        : _settings.fillIntensity
      // Preset positions are DIRECTIONS here; push them onto the 2R sphere so
      // the geometry of the rig is scene-scale-independent.
      const dir = child.position.lengthSq() > 0
        ? child.position.clone().normalize()
        : new THREE.Vector3(0, 1, 0)
      child.position.copy(dir.multiplyScalar(2 * R))
      child.target = _lightTarget
      child.castShadow = false
      if (!_keyLight) _keyLight = child          // first directional = the key
    }
    _applyKeyShadow()
  }

  /** Pin the rig to the camera — ChimeraX's move_lights_with_camera.
   *  World quaternion, not the local one: the render camera is unparented today,
   *  but a nested camera would silently mis-orient the whole rig. */
  const _camQuat = new THREE.Quaternion()
  function _syncRigToCamera() {
    if (!_lightGroup) return
    camera.updateMatrixWorld()
    _lightGroup.quaternion.copy(camera.getWorldQuaternion(_camQuat))
  }

  /**
   * Give the key light a real shadow map. This is the SECOND shadow system in
   * `lighting full`, entirely separate from ambient occlusion: three re-renders
   * it every frame (so it tracks the camera-pinned light), while the occlusion
   * bake stays cached. Exactly the asymmetry ChimeraX has.
   *
   * Deliberately NOT gated on a floor being present — self-shadowing across a
   * helix bundle is the point, and a ground plane is the last thing a figure
   * wants. (The shipping photo mode gates its shadow rig behind `floor !== 'off'`;
   * that gate is what makes helix-on-helix shadow impossible there.)
   */
  function _applyKeyShadow() {
    const want = _settings.keyShadow && !!_keyLight
    if (want && _savedShadowEnabled === null) {
      _savedShadowEnabled = renderer.shadowMap.enabled
      _savedShadowType    = renderer.shadowMap.type
    }
    // `shadowMap.enabled` is compiled INTO every material's program and three
    // does not re-check it in setProgram (see _suspendShadowMapUpdates in
    // multishadow_ao.js). Toggling it therefore has no effect on already-compiled
    // materials unless we force the recompile ourselves.
    const flagChanged = renderer.shadowMap.enabled !== want
    renderer.shadowMap.enabled = want
    if (want) renderer.shadowMap.type = THREE.PCFSoftShadowMap
    if (flagChanged) _forceMaterialRecompile()

    if (_keyLight) {
      _keyLight.castShadow = want
      if (want) {
        const R = _bounds?.radius ?? 1
        const cam = _keyLight.shadow.camera
        cam.left = -R; cam.right = R
        cam.top  =  R; cam.bottom = -R
        cam.near = Math.max(1e-4, R * 0.05)
        cam.far  = 4 * R
        cam.updateProjectionMatrix()
        const mapPx = _settings.keyShadowMapSize
        if (_keyLight.shadow.mapSize.width !== mapPx) {
          // A shadow map already allocated at another size must be dropped or
          // three keeps rendering into the old texture.
          _keyLight.shadow.map?.dispose()
          _keyLight.shadow.map = null
          _keyLight.shadow.mapSize.set(mapPx, mapPx)
        }
        // Bias must scale with the SHADOW-MAP TEXEL, not with the scene radius.
        // Scaling to the radius is the usual advice and it is badly wrong here:
        // origami features are ~0.2 nm beads inside a structure tens to hundreds
        // of nm across, so a radius-proportional offset reaches several bead
        // diameters (0.24 nm at R=60, 0.8 nm at R=200) and pushes every sample
        // clean past the geometry that should be shadowing it — erasing the
        // shadow instead of just de-acneing it. One texel of the ortho shadow
        // frustum is the physically motivated unit and stays sane at any scale.
        const texel = (2 * R) / mapPx
        _keyLight.shadow.bias       = -0.0005
        _keyLight.shadow.normalBias = texel * _settings.keyShadowBias
        _keyLight.shadow.intensity  = _settings.shadowStrength
        _keyLight.shadow.needsUpdate = true
      }
    }
    _applyMeshShadowFlags(want)
  }

  /** Mark every swapped material for recompile — needed whenever a value that
   *  three bakes into the program (shadowMapEnabled) changes after first draw. */
  function _forceMaterialRecompile() {
    scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
      if (!obj.material.isMeshPhysicalMaterial) return
      obj.material.needsUpdate = true
    })
  }

  function _applyMeshShadowFlags(on) {
    if (!on) { _restoreMeshShadowFlags(); return }
    scene.traverse(obj => {
      if (!obj.isMesh && !obj.isInstancedMesh) return
      if (_savedMeshShadows.has(obj)) return
      _savedMeshShadows.set(obj, { cast: obj.castShadow, receive: obj.receiveShadow })
      // Impostors and shared-LOD instancing cannot cast correctly: three drives
      // its shadow pass with the built-in depth material, which has neither the
      // billboard nor the composed instance transform. Let them RECEIVE (that is
      // a fragment-side lookup and works) but not cast.
      const canCast = !isShadowExcluded(obj)
        && !_rejected.has(obj)            // a 100 µm plane would shadow everything
        && !obj.material?.userData?.isImpostor
        && obj.material?.userData?.impostorRadius == null
        && !obj.userData?.sharedLodImpostor
      obj.castShadow    = canCast
      obj.receiveShadow = !isShadowExcluded(obj)
    })
  }

  function _restoreMeshShadowFlags() {
    for (const [obj, s] of _savedMeshShadows) {
      obj.castShadow    = s.cast
      obj.receiveShadow = s.receive
    }
    _savedMeshShadows.clear()
  }

  function _buildComposer() {
    _composer?.dispose?.()
    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    const composer = new EffectComposer(renderer)
    composer.addPass(new RenderPass(scene, camera))
    composer.addPass(new SMAAPass(size.x, size.y))
    composer.addPass(new OutputPass())
    // AFTER every addPass — composer.setSize forwards to each pass it holds, so
    // sizing first would leave anything added later at its 1×1 placeholder.
    composer.setSize(size.x, size.y)
    _composer = composer
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  function activate() {
    if (_active) return
    _active = true

    // Renderer state.
    _savedToneMapping = renderer.toneMapping
    _savedExposure    = renderer.toneMappingExposure
    renderer.toneMapping         = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.0
    renderer.getClearColor(_savedClearColor)
    _savedClearAlpha = renderer.getClearAlpha()

    // Scene state.
    _savedEnv = scene.environment
    _savedBg  = scene.background
    scene.environment = null          // ambient occlusion IS the ambient light here

    _lightGroup = new THREE.Group()
    _lightGroup.name = 'expPhotoLights'
    scene.add(_lightGroup)
    _hideEditorLights()

    _matSwap = swapToFlatMaterials(scene)
    _applyBackground()

    _buildComposer()

    // Rig last: it fits itself to the scene bounds, and the material swap above
    // does not move geometry, so the bounds are already final.
    _rebuildRig()
    if (_settings.pinLights) _syncRigToCamera()

    setResizeCallback?.(() => {
      const s = renderer.getDrawingBufferSize(new THREE.Vector2())
      _composer?.setSize(s.x, s.y)
    })

    setRenderFn(() => {
      _perFrameSync()
      _composer?.render()
    })
  }

  /**
   * The per-frame CPU work, split out from the render fn so it is exercisable
   * without a GL context.
   *
   * Camera-pinned rig: one quaternion copy. three then re-renders the key
   * light's shadow map itself every frame, because the light moved — exactly
   * ChimeraX's per-frame `use_shadow_map`. The occlusion bake, by contrast, is
   * view-INDEPENDENT and `ensureBaked` is a no-op after the first frame.
   */
  function _perFrameSync() {
    if (_settings.pinLights) _syncRigToCamera()
    // Periodically re-fingerprint the geometry. A representation switch replaces
    // every mesh while writing NO store field, so without this the shadow
    // frustum stays fitted to geometry that is no longer on screen.
    if (++_sigFrame >= SIGNATURE_CHECK_FRAMES) {
      _sigFrame = 0
      if (sceneSignature(scene) !== _signature) resync()
    }
  }

  function deactivate() {
    if (!_active) return
    _active = false

    resetRenderFn()
    clearResizeCallback?.()

    _composer?.dispose?.()
    _composer = null
    _matSwap?.restore()
    _matSwap = null

    // Shadow state — restore BEFORE the rig is torn down (the flags live on the
    // scene meshes and the lights we are about to drop).
    _restoreMeshShadowFlags()
    if (_savedShadowEnabled !== null) {
      renderer.shadowMap.enabled = _savedShadowEnabled
      if (_savedShadowType !== null) renderer.shadowMap.type = _savedShadowType
      _savedShadowEnabled = null
      _savedShadowType    = null
    }

    if (_lightGroup) {
      applyLighting('flat', _lightGroup)      // dispose the rig's lights
      while (_lightGroup.children.length) _lightGroup.remove(_lightGroup.children[0])
      scene.remove(_lightGroup)
      _lightGroup = null
    }
    _lightTarget = null
    _keyLight    = null
    _bounds      = null
    _restoreEditorLights()

    scene.environment = _savedEnv
    scene.background  = _savedBg
    _savedEnv = undefined
    _savedBg  = undefined
    renderer.setClearColor(_savedClearColor, _savedClearAlpha)
    if (_savedToneMapping !== null) renderer.toneMapping = _savedToneMapping
    if (_savedExposure    !== null) renderer.toneMappingExposure = _savedExposure
    _savedToneMapping = null
    _savedExposure    = null
  }

  // ── Settings ───────────────────────────────────────────────────────────────

  function setLighting(name) {
    _settings.lighting = name
    // Adopt the preset's own intensities, otherwise sliders left over from the
    // previous preset silently override it and switching looks like a no-op.
    const p = LIGHTING_PRESETS[name]
    if (p) {
      _settings.ambientIntensity = p.ambient.intensity
      _settings.keyIntensity     = p.lights[0]?.intensity ?? 0
      _settings.fillIntensity    = p.lights[1]?.intensity ?? 0
    }
    if (_active) _rebuildRig()
  }

  /** ChimeraX move_lights_with_camera. Off → the rig is welded to the world. */
  function setPinLights(on) {
    _settings.pinLights = !!on
    if (!_active) return
    if (_settings.pinLights) _syncRigToCamera()
    else _lightGroup?.quaternion.identity()
  }

  function setKeyShadow(on) {
    _settings.keyShadow = !!on
    if (_active) _applyKeyShadow()
  }

  function setKeyShadowMapSize(px) {
    _settings.keyShadowMapSize = Math.max(256, Math.floor(px))
    if (_active) _applyKeyShadow()
  }

  function setKeyShadowBias(v) {
    _settings.keyShadowBias = Math.max(0, v)
    if (_active) _applyKeyShadow()
  }

  /** Absolute per-light intensities — the real shadow-contrast controls. */
  function setKeyIntensity(v)     { _settings.keyIntensity = Math.max(0, v);     if (_active) _rebuildRig() }
  function setFillIntensity(v)    { _settings.fillIntensity = Math.max(0, v);    if (_active) _rebuildRig() }
  function setAmbientIntensity(v) { _settings.ambientIntensity = Math.max(0, v); if (_active) _rebuildRig() }
  function setShadowStrength(v) {
    _settings.shadowStrength = Math.max(0, Math.min(1, v))
    if (_active) _applyKeyShadow()
  }

  function setBackground(type, color) {
    if (type)  _settings.bgType  = type
    if (color) _settings.bgColor = color
    if (_active) _applyBackground()
  }

  /** Re-apply the material swap after the scene's meshes were rebuilt while the
   *  mode is active (the rebuild produces fresh meshes with editor materials),
   *  and invalidate the bake since the geometry is new. */
  function resync() {
    if (!_active) return
    _matSwap?.restore()
    _matSwap = swapToFlatMaterials(scene)
    // Fresh meshes arrive with the editor's shadow flags and the bounds may have
    // moved, so the rig has to refit and the flags be re-applied.
    _restoreMeshShadowFlags()
    _rebuildRig()
    if (_settings.pinLights) _syncRigToCamera()
  }

  function getSettings() { return { ..._settings } }

  /** Diagnostics for the panel + console: is the bake warm, how long it took. */
  function getStatus() {
    return {
      active: _active,
      keyShadow: !!(_keyLight?.castShadow),
      pinned:    _active && _settings.pinLights,
      radius:    _bounds?.radius ?? 0,
      mapSize:   _settings.keyShadowMapSize,
    }
  }

  /**
   * One-call answer to "why is the key shadow not showing?".
   *
   * Reports the whole chain a shadow has to survive: the renderer flag, the
   * light, the fitted frustum, whether three actually rendered a shadow map,
   * whether the materials COMPILED with shadow sampling (the parameter three
   * bakes in and never re-checks), and how many meshes cast vs receive.
   *
   * Exposed on window.__photoExpMode — this tab is a testbed, so being able to
   * answer that question without a rebuild is worth the ~40 lines.
   */
  function getDiagnostics() {
    const key = _keyLight
    const shadow = key?.shadow
    let casters = 0, receivers = 0, physical = 0, compiled = 0, withShadowDefine = 0
    scene.traverse(obj => {
      if (!obj.isMesh && !obj.isInstancedMesh) return
      if (obj.castShadow) casters++
      if (obj.receiveShadow) receivers++
      const m = obj.material
      if (!m?.isMeshPhysicalMaterial) return
      physical++
      // `program` only exists once three has compiled the material; its cache
      // key carries the parameter list, so USE_SHADOWMAP presence is visible.
      const prog = m.program ?? m.__webglProgram
      if (prog) {
        compiled++
        const src = prog.fragmentShader ?? prog.cacheKey ?? ''
        if (String(src).includes('USE_SHADOWMAP') || String(src).includes('shadowmap')) withShadowDefine++
      }
    })
    const camQ = new THREE.Quaternion()
    camera.getWorldQuaternion(camQ)
    return {
      active: _active,
      lighting: _settings.lighting,
      rendererShadowMapEnabled: renderer.shadowMap?.enabled,
      rendererShadowAutoUpdate: renderer.shadowMap?.autoUpdate,
      keyLight: key ? {
        castShadow: key.castShadow,
        intensity:  key.intensity,
        worldPos:   key.getWorldPosition(new THREE.Vector3()).toArray().map(v => +v.toFixed(2)),
        targetPos:  key.target?.getWorldPosition(new THREE.Vector3()).toArray().map(v => +v.toFixed(2)),
        mapRendered: !!shadow?.map,          // null until three has drawn it
        mapSize:     shadow?.mapSize?.width,
        normalBias:  shadow?.normalBias,
        frustumHalfWidth: shadow?.camera?.right,
        near: shadow?.camera?.near, far: shadow?.camera?.far,
      } : null,
      bounds: _bounds ? {
        center: _bounds.center.toArray().map(v => +v.toFixed(2)),
        radius: +_bounds.radius.toFixed(2),
        // Biggest contributors first: if the top entry dwarfs the rest, IT is
        // what set the frustum and why nothing casts a visible shadow.
        largest:  (_bounds.contributors ?? []).slice(0, 6).map(({ object, ...c }) => c),
        rejected: (_bounds.rejected ?? []).map(({ object, ...c }) => c),
        outlier:  findBoundsOutlier(_bounds),
      } : null,
      rigPinned: _settings.pinLights,
      rigMatchesCamera: _lightGroup ? _lightGroup.quaternion.angleTo(camQ) < 1e-3 : null,
      meshes: { casters, receivers, physical, compiled, withShadowDefine },
      bake: getStatus(),
    }
  }

  return {
    activate, deactivate,
    getDiagnostics,
    isActive: () => _active,
    setLighting, setBackground,
    setPinLights, setKeyShadow, setKeyShadowBias, setKeyShadowMapSize,
    setKeyIntensity, setFillIntensity, setAmbientIntensity, setShadowStrength,
    resync,
    getSettings, getStatus,
    // Test/console seams.
    _syncFrame:    _perFrameSync,
    _getKeyLight:  () => _keyLight,
    _getLightGroup: () => _lightGroup,
  }
}

// ── Tab orchestration ────────────────────────────────────────────────────────

/**
 * Wire the "Exp. Photomode" left-sidebar tab: construct the renderer + panel,
 * hide the editor gizmos on entry, restore them on exit, and keep the occlusion
 * bake in step with geometry changes.
 *
 * Mirrors initPhotoMode's contract so main.js gains only an import, one factory
 * init and two `exit()` calls in the lifecycle spine.
 *
 * @returns {{enter: () => void, exit: () => void, mode: object}}
 */
export function initPhotoExpMode({
  store, sceneCtx, designRenderer, assemblyRenderer,
  assemblyJointRenderer, bluntEnds, originAxes,
}) {
  const mode = createExpPhotoMode(sceneCtx)
  let _panel = null
  let _savedOriginAxesVisible = null

  function enter() {
    if (mode.isActive()) return
    if (!_panel) _panel = initPhotoExpPanel(mode, { onExit: () => exit() })

    mode.activate()

    // Same gizmo suppression as the shipping photo mode — an editor overlay in
    // a render being judged for its shading is noise, and the `toneMapped:false`
    // origin triad has a real artifact history (ANGLE/D3D11 + bloom).
    designRenderer?.setAxisArrowsVisible?.(false)
    if (originAxes) {
      _savedOriginAxesVisible = originAxes.visible
      originAxes.visible = false
    }
    bluntEnds?.setVisible?.(false)
    assemblyRenderer?.setPhotoMode?.(true)
    assemblyJointRenderer?.setVisible?.(false)

    _panel.onEnter()
  }

  function exit() {
    if (!mode.isActive()) return
    mode.deactivate()

    designRenderer?.setAxisArrowsVisible?.(true)
    if (originAxes && _savedOriginAxesVisible !== null) {
      originAxes.visible = _savedOriginAxesVisible
      _savedOriginAxesVisible = null
    }
    bluntEnds?.setVisible?.(store.getState().toolFilters?.bluntEnds ?? true)
    assemblyRenderer?.setPhotoMode?.(false)
    assemblyJointRenderer?.setVisible?.(true)

    _panel?.onExit()
  }

  // ── Keeping the rig in step with the geometry ──────────────────────────────
  // The camera is irrelevant (the shadow map re-renders every frame anyway) —
  // but anything that REPLACES meshes needs the material swap re-applied and
  // the shadow frustum refitted. Store changes catch the design/assembly swaps;
  // representation switches write no store field at all and are caught by the
  // geometry fingerprint in _perFrameSync.
  store.subscribe((next, prev) => {
    if (!mode.isActive()) return
    if (next.currentDesign   !== prev.currentDesign
     || next.currentAssembly !== prev.currentAssembly
     || next.staplesHidden   !== prev.staplesHidden
     || next.isolatedStrandId !== prev.isolatedStrandId) {
      mode.resync()
    }
  })
  assemblyRenderer?.onRebuildComplete?.(() => { if (mode.isActive()) mode.resync() })

  return { enter, exit, mode }
}
