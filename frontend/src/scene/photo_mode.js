/**
 * Photo mode — figure-quality rendering of the design on screen.
 *
 * This began as the "Exp. Photomode" testbed and REPLACED photo mode v1 on
 * 2026-07-29; v1 is preserved verbatim under archive/photo_mode_v1/ (see its
 * README for what was dropped and why). Deliberately narrow: v1 had grown into
 * a general 3D render suite — HDRI, bloom, path tracer, floor, mist, style
 * presets — and the surface area buried the two things that actually make a
 * molecular figure. What this has:
 *
 *   • flat figure materials (no specular lobe at all)
 *   • a CAMERA-PINNED key light — ChimeraX's move_lights_with_camera, so the
 *     shadow sweeps across the structure as you reorient it
 *   • a neutral synthetic studio environment — broad reflected softboxes that
 *     keep metallic product materials readable without changing the backdrop
 *   • a real KEY-LIGHT SHADOW MAP, with no floor required, so an object casts
 *     onto whatever is behind it
 *   • an optional SHADOW-CATCHING floor (photo_renderer/shadow_catcher.js) —
 *     invisible except where the shadow lands, so the structure reads as sitting
 *     on something. Additive to the key shadow, never a precondition for it,
 *     which is the whole difference from v1's ground plane.
 *   • the ChimeraX depth-outline silhouette + a depth cue
 *   • flat-colour background, SMAA, and tiled PNG export
 *
 * No user-supplied HDRI, no bloom, no path tracer, no visible ground plane, no
 * mist — all deliberate.
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
 * deactivate, the same save/restore contract photo mode v1 honoured.
 */

import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass }     from 'three/addons/postprocessing/RenderPass.js'
import { SMAAPass }       from 'three/addons/postprocessing/SMAAPass.js'
import { OutputPass }     from 'three/addons/postprocessing/OutputPass.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'

import { makeMaterial }               from './photo_renderer/material_presets.js'
import { reprOf }                     from './photo_renderer/mesh_repr.js'
import { applyInstanceAlphaMaterial } from './instance_alpha.js'
import { FigurePass }                 from './photo_renderer/figure_pass.js'
import { dollyDistanceForFov, PARALLEL_FOV, PERSPECTIVE_FOV }
  from './photo_renderer/figure_camera.js'
import { applyLighting, LIGHTING_PRESETS } from './photo_renderer/lighting_presets.js'
import { computeShadowBounds, isShadowExcluded, findBoundsOutlier, rejectedObjects,
         sceneSignature } from './photo_renderer/shadow_bounds.js'
import { createShadowCatcher, FLOOR_AXES, DEFAULT_FLOOR_AXIS }
  from './photo_renderer/shadow_catcher.js'
import { initPhotoPanel }          from '../ui/photo_panel.js'

/**
 * Direction the key light shines FROM, in RIG-LOCAL space — which is camera
 * space while the rig is pinned, so these read as screen directions.
 *
 * The Sun in photo mode v1 steered in polar coordinates around the
 * FLOOR normal. There is no floor here and the rig is pinned to the viewer, so
 * the natural frame is the screen: azimuth sweeps around it (0 = from the right,
 * 90 = from directly above, 180 = from the left) and elevation tilts the light
 * toward the viewer (0 = grazing, in the screen plane; 90 = straight down the
 * barrel from the camera, which flattens the shadow away; negative = from behind
 * the subject, a rim light).
 *
 * The angle off the camera axis is simply `90 - elevation`.
 *
 * Defaults (135°, 35.264°) reproduce ChimeraX's own key direction exactly:
 * (-0.577, 0.577, 0.577), i.e. 45° up-and-left and 54.7° off the view axis.
 *
 * @returns {[number,number,number]} unit vector
 */
export function keyLightDirection(azimuthDeg, elevationDeg) {
  const az = (azimuthDeg   * Math.PI) / 180
  const el = (elevationDeg * Math.PI) / 180
  const c  = Math.cos(el)
  return [c * Math.cos(az), c * Math.sin(az), Math.sin(el)]
}

/** ChimeraX's own key direction, in the screen frame: 45° up-and-left, 54.7°
 *  off the camera axis. Exported so the panel's Reset button cannot drift. */
export const DEFAULT_KEY_AZIMUTH   = 135
export const DEFAULT_KEY_ELEVATION = 35.264

/** The fixed rig this tab uses. See LIGHTING_PRESETS.full for its geometry. */
const RIG_PRESET = 'full'

/** Factory defaults — the single source of truth for "what the experiment looks
 *  like out of the box". */
export const DEFAULT_PHOTO_SETTINGS = Object.freeze({
  // Material preset per representation, keyed exactly like
  // material_presets.js PRESETS/PRESET_LABELS. Defaults are the FIGURE
  // materials (specularIntensity 0 — no highlight anywhere), which is what this
  // tab looked like before materials were selectable.
  full:       'flat',
  cylinders:  'flat',
  surface:    'flat',
  atomistic:  'cpk-flat',

  // ── Figure effects (the publication look) ─────────────────────────────────
  // Silhouette outline: a dark contour at depth + normal discontinuities, so
  // overlapping helices separate without lighting having to do it.
  outline:                  false,
  outlineColor:             '#1b1f24',
  outlineStrength:          1.0,
  outlineThickness:         1.4,    // px
  outlineDepthSensitivity:  0.35,   // silhouettes (lower = more contours)  [Roberts mode only]
  outlineCreaseSensitivity: 0.85,   // creases within one surface           [Roberts mode only]
  // ChimeraX's depth-only silhouette. See figure_pass.js for the algorithm and
  // why the crease term above is deliberately unused here: normals are what make
  // a zoomed-out bead field collapse into black line-art, and ChimeraX has none.
  silhouette:               'chimerax',
  outlineDepthJump:         0.03,   // ChimeraX depth_jump default: 3% of the structure's depth
  // Depth cue: a distance fade toward a flat colour so the back of a thick
  // bundle recedes instead of turning to mush.
  depthCue:         false,
  depthCueColor:    '#ffffff',
  depthCueStrength: 0.35,

  // ── Camera ────────────────────────────────────────────────────────────────
  // "Parallel" is an 8° LONG LENS + dolly, not a real OrthographicCamera. A true
  // ortho swap would mean touching every consumer of the shared perspective
  // camera (the PERSPECTIVE_CAMERA shader defines baked into the post passes at
  // construction, OrbitControls' distance-based zoom, main.js's per-frame
  // near/far rewrite). At 8° the residual convergence over a 60 nm object is
  // sub-pixel at print resolution.
  parallel:   false,
  fov:        null,           // null = adopt the editor's lens on entry

  // ── Export ────────────────────────────────────────────────────────────────
  exportWidth:  4200,         // 300 DPI at 14 in wide
  exportHeight: 2970,

  bgType:     'color',        // 'color' | 'transparent'
  bgColor:    '#0b0d10',

  // ChimeraX stores light directions in CAMERA coordinates with
  // move_lights_with_camera = True, so the key light is pinned to the viewer and
  // its shadow sweeps across the structure as you reorient. Without this the rig
  // is welded to the world and orbiting just walks you into the dark side.
  pinLights:  true,

  // A real shadow map cast by the key light, deliberately NOT gated on a floor.
  keyShadow:  true,

  // Shadow-CATCHING floor: an invisible plane under the design that shows
  // nothing but the shadow landing on it (photo_renderer/shadow_catcher.js).
  // Note what this is NOT: photo mode v1's visible ground plane, which GATED the
  // whole shadow rig. Here the key shadow works with or without it — this only
  // adds a surface for the shadow to fall onto, so the structure reads as
  // sitting on something instead of floating in a void.
  floor:        true,
  floorOpacity: 0.35,         // ShadowMaterial opacity = how dark the pool is
  floorOffset:  0,            // nm OUTWARD from the chosen face; 0 = flush
  floorAxis:    DEFAULT_FLOOR_AXIS,   // which bbox face it sits against: ±x/±y/±z
  keyShadowMapSize: 2048,     // ChimeraX shadow_map_size; one map, so it is cheap
  keyShadowBias: 1.0,         // × the texel-scaled normalBias; raise to kill acne
  shadowStrength:   1.0,      // three's LightShadow.intensity; 1 = physical

  // Per-light intensities — ChimeraX's `lighting intensity / fillIntensity /
  // ambientIntensity`. THESE are the shadow-contrast controls: a cast shadow can
  // only subtract the KEY light, so its depth is key/(key+fill+ambient).
  //
  // MUST match LIGHTING_PRESETS.full: _rebuildRig applies these OVER the preset's
  // own values, so a mismatch silently overrides it. Pinned by a test.
  // Key-light direction in the screen frame (see keyLightDirection). Defaults
  // reproduce ChimeraX's own key: 45° up-left, 54.7° off the camera axis.
  keyAzimuth:       DEFAULT_KEY_AZIMUTH,
  keyElevation:     DEFAULT_KEY_ELEVATION,

  keyIntensity:     2.0,
  fillIntensity:    0.0,
  ambientIntensity: 0.15,

  // A neutral studio environment used as image-based lighting (IBL). This is
  // the part that makes a PBR metal readable: AmbientLight only supplies a
  // diffuse term, which a metalness=1 material does not have, while the broad
  // softboxes in RoomEnvironment show up across the metal's reflections. It is
  // lighting only — the chosen solid/transparent background remains visible.
  studioEnvironment:          true,
  studioEnvironmentIntensity: 1.0,
  studioEnvironmentRotation:  0,       // degrees around world Y
  shadowStrength:   1.0,      // three's LightShadow.intensity; 1 = physical
})


/**
 * Swap every eligible mesh to its representation's photo material, returning a
 * restore handle. `presets` maps representation → preset name (see
 * material_presets.js); omit it for the flat figure materials.
 *
 * The mesh→representation decision is shared with photo mode v1 via
 * mesh_repr.js rather than duplicated, so a renderer adding a mesh name only has
 * to be taught about it once.
 *
 * Preserved from the source material: `side` (the surface mesh is DoubleSide
 * because its junction edges are non-manifold), `vertexColors`, sub-1 opacity,
 * and — unlike photo mode v1 — the material COLOUR when the mesh has
 * neither vertex colours nor instance colours, so a uniformly-coloured mesh
 * (hull prism, cylinder proxy) doesn't turn white.
 *
 * Skipped: impostor materials (their sphere ray-paint lives in an
 * onBeforeCompile patch that a fresh material would drop), shared-renderer LOD
 * impostors, additive glow sprites, helper lines, the shadow catcher, and
 * anything whose material is `visible:false` (three's own gizmo drag plane).
 *
 * @param {THREE.Object3D} root
 * @returns {{restore: () => void, count: number}}
 */
/** How often (in rendered frames) to re-fingerprint the geometry. ~0.5 s at 60 fps. */
const SIGNATURE_CHECK_FRAMES = 30

export function swapToFlatMaterials(root, presets = null) {
  const saved = new Map()
  root.traverse(obj => {
    if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.material) return
    const src = obj.material
    if (Array.isArray(src)) return
    if (src.isLineBasicMaterial || src.isLineDashedMaterial) return
    if (src.blending === THREE.AdditiveBlending) return
    if (src.userData?.isImpostor || src.userData?.impostorRadius != null) return
    // Assembly surfaces use ordinary instanceMatrix transforms and can safely
    // receive the selected surface material. Other shared-LOD meshes carry
    // custom texture-instancing shaders which a material replacement would drop.
    if (obj.userData?.sharedLodImpostor
        && obj.name !== 'assemblySurface'
        && !obj.userData?.applySharedInstancing) return
    if (obj.userData?.photoFloor) return
    // A material flagged `visible:false` means "never draw this", and a fresh
    // material defaults to visible:true — the same class of bug as depthWrite
    // below. The live offender is three's own TransformControlsPlane: a
    // 100000×100000 invisible drag plane that TransformControls adds to the
    // scene when a gizmo attaches. Swapped, it became a translucent infinite
    // ground plane that also passed the depthWrite test in isShadowExcluded and
    // started receiving the key shadow — which is where the accidental "floor"
    // that appeared on selecting a cluster in photo mode came from. Skipping the
    // mesh entirely (rather than copying `visible` across) also keeps it out of
    // the restore map, since nothing about it changed.
    if (src.visible === false) return

    const vc = Boolean(src.vertexColors)
    // Representation is read from the ORIGINAL material, before any swap —
    // MeshPhysicalMaterial extends MeshStandardMaterial, so inferring after a
    // swap makes every unnamed mesh look 'atomistic' (see mesh_repr.js).
    const repr   = reprOf(obj)
    const preset = presets?.[repr] ?? (repr === 'atomistic' ? 'cpk-flat' : 'flat')
    const mat = makeMaterial(repr, preset, vc, 1.0)
    mat.side = src.side
    // Preserve the depth contract. Overlay geometry (ghost planes, hit targets,
    // immobilisation surfaces) is drawn depthWrite:false precisely so it cannot
    // occlude the structure; a fresh material defaults to TRUE, which turned
    // those overlays into opaque occluders AND shadow casters, and defeated the
    // depthWrite exclusion in shadow_bounds.js (which tests the CURRENT material).
    // …but a material that only dropped depthWrite to blend correctly at a
    // user-chosen opacity (the base-pair slabs and their crossover extra-base
    // twins, whose sidebar opacity slider tracks depthWrite per LESSONS D8) is
    // STRUCTURE, not overlay. It opts back in with `photoForceDepthWrite` so it
    // stays a shadow caster/receiver in the figure at any opacity.
    mat.depthWrite = src.userData?.photoForceDepthWrite ? true : src.depthWrite
    mat.depthTest  = src.depthTest
    // Per-instance alpha (reference ghosting, mixed representation, per-cluster
    // opacity) lives in an onBeforeCompile patch, which a fresh material has no
    // trace of — so without this the faded geometry rendered fully OPAQUE in photo
    // mode and in the tiled export. The instanceAlpha geometry attribute survives
    // the swap untouched (geometry is never replaced here), so re-installing the
    // same shared patch is the whole fix. Note it also has to set `transparent`:
    // makeMaterial forces transparent:false/opacity:1 for non-surface reps, and the
    // opacity carry-over just below is gated on src.opacity < 1 — which is false
    // here, because the fade lives in the attribute, not in the material.
    if (src.userData?.instanceAlphaPatch) applyInstanceAlphaMaterial(mat)
    if (src.transparent && src.opacity < 1) {
      mat.transparent = true
      mat.opacity     = src.opacity
    }
    // Only force white where a per-instance / per-vertex colour will supply the
    // real colour; otherwise carry the source colour through.
    if (!vc && !obj.instanceColor && src.color) mat.color.copy(src.color)

    saved.set(obj, src)
    obj.material = mat
    // The shared assembly renderer composes source-local geometry with each
    // assembly placement in an onBeforeCompile vertex patch. A fresh photo
    // material drops that patch, collapsing Full/Beads geometry to the source
    // origin (and in sufficiently large assemblies destabilising the GL pass).
    // The renderer stores the exact reinstaller on every affected mesh.
    obj.userData?.applySharedInstancing?.(mat)
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
 * @returns photo-mode controller
 */
export function createPhotoMode(sceneCtx) {
  const { scene, camera, renderer, controls, setRenderFn, resetRenderFn,
          setResizeCallback, clearResizeCallback, getPhotoBounds } = sceneCtx
  const bakeStudioEnvironment = sceneCtx.bakeStudioEnvironment ?? ((targetRenderer) => {
    // The jsdom unit harness intentionally supplies a renderer-shaped object,
    // not a WebGLRenderer. Production and offscreen export renderers carry this
    // flag; keeping the guard here leaves the mode's CPU contracts testable.
    if (!targetRenderer?.isWebGLRenderer) return null
    const pmrem = new THREE.PMREMGenerator(targetRenderer)
    const room  = new RoomEnvironment()
    try {
      // A slight convolution avoids razor-edged cards while retaining the broad
      // highlight bands that describe curved metal.
      return pmrem.fromScene(room, 0.04).texture
    } finally {
      room.dispose?.()
      pmrem.dispose()
    }
  })

  const _settings = { ...DEFAULT_PHOTO_SETTINGS }

  let _active      = false
  let _composer    = null
  let _matSwap     = null
  let _lightGroup  = null
  let _lightTarget = null        // sits at the rig's local origin = scene centre
  let _keyLight    = null        // the one directional that casts the shadow
  let _savedLights = []          // [{light, visible, castShadow}] editor/late scene lights
  let _savedEnv    = undefined
  let _savedEnvIntensity = 1
  let _savedEnvRotation  = null
  let _studioEnvTexture  = null
  let _savedBg     = undefined
  const _savedClearColor = new THREE.Color()
  let _savedClearAlpha   = 1
  let _savedToneMapping  = null
  let _savedExposure     = null
  let _savedShadowEnabled = null
  let _savedShadowType    = null
  const _savedMeshShadows = new Map()   // mesh → {cast, receive, customDepthMaterial}
  let _bounds = null                    // {center, radius} the rig is fitted to
  let _figurePass = null
  let _savedFov   = null
  const _dollyScratch = new THREE.Vector3()
  const _camForward   = new THREE.Vector3()
  const _cueScratch   = new THREE.Vector3()
  let _rejected = new Set()             // objects too large to be part of the structure
  let _signature = null                 // geometry fingerprint the rig is fitted to
  let _sigFrame  = 0
  let _floor     = null                 // shadow catcher, created on activate

  /** Convert an authoritative renderer-owned Box3 into the richer bounds shape
   * used by the photo rig. The shared assembly renderer keeps placement
   * transforms in GPU textures, so Three's generic setFromObject cannot measure
   * those meshes (their instanceMatrix is intentionally collapsed to one row).
   */
  function _boundsFromBox(box) {
    if (!box || box.isEmpty?.()) return null
    const sphere = new THREE.Sphere()
    box.getBoundingSphere(sphere)
    if (!(sphere.radius > 0) || !Number.isFinite(sphere.radius)) return null
    const b = box.clone()
    const mn = b.min, mx = b.max
    return {
      center: sphere.center.clone(), radius: sphere.radius, box: b,
      corners: [
        new THREE.Vector3(mn.x, mn.y, mn.z), new THREE.Vector3(mx.x, mn.y, mn.z),
        new THREE.Vector3(mn.x, mx.y, mn.z), new THREE.Vector3(mx.x, mx.y, mn.z),
        new THREE.Vector3(mn.x, mn.y, mx.z), new THREE.Vector3(mx.x, mn.y, mx.z),
        new THREE.Vector3(mn.x, mx.y, mx.z), new THREE.Vector3(mx.x, mx.y, mx.z),
      ],
      diagonal: b.getSize(new THREE.Vector3()).length(),
      contributors: [], rejected: [], medianExtent: 0,
    }
  }

  function _measureBounds() {
    const authoritative = _boundsFromBox(getPhotoBounds?.())
    return authoritative ?? computeShadowBounds(scene)
  }

  // ── Scene state save / restore ─────────────────────────────────────────────

  function _hideEditorLights() {
    _savedLights = []
    scene.traverse(obj => {
      if (!obj.isLight) return
      if (_lightGroup && obj.parent === _lightGroup) return
      _savedLights.push({ light: obj, visible: obj.visible, castShadow: obj.castShadow })
      obj.visible = false
    })
  }

  function _restoreEditorLights() {
    for (const { light, visible, castShadow } of _savedLights) {
      light.visible = visible
      light.castShadow = castShadow
    }
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

  // ── Studio environment: broad reflected light for PBR materials ───────────

  /** Bind the preview renderer's PMREM without changing the visible backdrop. */
  function _applyStudioEnvironment() {
    scene.environment = _settings.studioEnvironment ? _studioEnvTexture : null
    scene.environmentIntensity = _settings.studioEnvironmentIntensity
    scene.environmentRotation.set(
      0,
      THREE.MathUtils.degToRad(_settings.studioEnvironmentRotation),
      0,
    )
  }

  /** Bake once per WebGL context. A PMREM render-target texture cannot be shared
   *  with the separate context used by tiled still/video export. */
  function _ensurePreviewStudioEnvironment() {
    if (_studioEnvTexture || !_settings.studioEnvironment) return
    _studioEnvTexture = bakeStudioEnvironment(renderer)
    // PMREMGenerator uses its own render targets and texture bindings. Flush the
    // live renderer's cache before EffectComposer draws the next frame.
    renderer.resetState?.()
  }

  function _disposePreviewStudioEnvironment() {
    _studioEnvTexture?.dispose?.()
    _studioEnvTexture = null
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
    // Fixed rig geometry — there is no preset selector. The Key/Fill/Ambient
    // sliders ARE the preset; the dropdown's only remaining effect was to reset
    // them to an ambient-dominant balance that hid the cast shadow (`flat` had
    // no directional at all, silently disabling the whole key-shadow block).
    applyLighting(RIG_PRESET, _lightGroup)

    _bounds = _measureBounds()
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
      // The KEY light is steered by azimuth/elevation; the fill keeps the
      // preset's own direction. Both are pushed onto the 2R sphere so the rig's
      // geometry is scene-scale-independent.
      const dir = (seenDirectional === 1)
        ? new THREE.Vector3(...keyLightDirection(_settings.keyAzimuth, _settings.keyElevation))
        : (child.position.lengthSq() > 0
            ? child.position.clone().normalize()
            : new THREE.Vector3(0, 1, 0))
      child.position.copy(dir.multiplyScalar(2 * R))
      child.target = _lightTarget
      child.castShadow = false
      if (!_keyLight) _keyLight = child          // first directional = the key
    }
    _applyKeyShadow()
  }

  /**
   * Refit to MOVED geometry without rebuilding the rig.
   *
   * `_rebuildRig` tears the light group down and constructs fresh Ambient +
   * Directional lights every call (`applyLighting` clears the group first), which
   * throws away the key light's shadow MAP — a 2048² texture reallocated per
   * call. Fine once on a settings change; ruinous at 30 fps, which is what an
   * animation export asks for.
   *
   * Everything that actually depends on where the structure IS lives in
   * `_bounds`: the shadow frustum, the depth-cue window and the floor placement.
   * So refit those, slide the rig to the new centre, keep each light's DIRECTION
   * and just re-length it to the new 2R sphere — and let `_applyKeyShadow` redo
   * the frustum and the floor. The lights, and their shadow maps, survive.
   */
  function _refitBounds() {
    if (!_lightGroup) return
    _bounds    = _measureBounds()
    _rejected  = rejectedObjects(_bounds)
    _signature = sceneSignature(scene)
    _sigFrame  = 0

    const R = _bounds?.radius ?? 1
    if (_bounds) _lightGroup.position.copy(_bounds.center)
    for (const child of _lightGroup.children) {
      // setLength, not a fresh direction: azimuth/elevation are settings and the
      // fill keeps the preset's own direction — only the scene's scale moved.
      if (child.isDirectionalLight && child.position.lengthSq() > 0) {
        child.position.setLength(2 * R)
      }
    }
    _applyKeyShadow()
  }

  /**
   * Fit the shadow-catching floor to the current bounds.
   *
   * Called from the tail of `_applyKeyShadow`, which is both the end of every
   * `_rebuildRig` (fresh bounds) and the direct entry point for every shadow
   * setting — so the plane can never be left fitted to stale bounds or sampling
   * a shadow map that was just turned off. `invalidate()` covers the flag flip:
   * `shadowMap.enabled` is compiled into the program and three never re-checks
   * it, exactly as for the swapped physical materials.
   */
  function _applyFloor() {
    if (!_floor) return
    _floor.update(_bounds, {
      enabled: _settings.floor && _settings.keyShadow,
      opacity: _settings.floorOpacity,
      offset:  _settings.floorOffset,
      axis:    _settings.floorAxis,
    })
    _floor.invalidate()
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
   * Photomode has exactly one real shadow source: the key DirectionalLight.
   * Keep this as a runtime invariant rather than an assumption about whichever
   * lights another scene subsystem may add after activate(). Editor lights are
   * hidden on entry, but a late-added visible light must never start a second
   * shadow map behind our back.
   */
  function _enforceSingleShadowSource() {
    if (!_active) return
    scene.traverse(light => {
      if (!light.isLight || light === _keyLight) return
      if (!_savedLights.some(saved => saved.light === light)) {
        _savedLights.push({ light, visible: light.visible, castShadow: light.castShadow })
      }
      light.castShadow = false
    })
    if (_keyLight) _keyLight.castShadow = !!_settings.keyShadow
  }

  /**
   * Give the key light the ONE real shadow map in photomode. There is no active
   * ambient-occlusion/multishadow pass; studio environment and AmbientLight add
   * illumination only and cannot cast or sample a second shadow.
   *
   * Deliberately NOT gated on a floor being present — self-shadowing across a
   * helix bundle is the point, and a ground plane is the last thing a figure
   * wants. (Photo mode v1 gated its shadow rig behind `floor !== 'off'`;
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
        _keyLight.shadow.intensity  = _settings.shadowStrength
        _keyLight.shadow.needsUpdate = true
      }
    }
    _enforceSingleShadowSource()
    _applyMeshShadowFlags(want)
    _applyFloor()
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
      // The shadow catcher owns its own flags (never casts, always receives) and
      // is not the editor's mesh, so it must stay out of the save/restore map.
      // Falling through would set receiveShadow = !isShadowExcluded(obj) = FALSE
      // on the one object whose entire job is to receive.
      if (obj.userData?.photoFloor) return
      if (_savedMeshShadows.has(obj)) return
      _savedMeshShadows.set(obj, {
        cast: obj.castShadow,
        receive: obj.receiveShadow,
        customDepthMaterial: obj.customDepthMaterial,
      })

      // Three normally substitutes a stock MeshDepthMaterial for the shadow
      // pass. Shared assembly meshes keep their placement matrices in textures,
      // so that stock depth shader draws every copy at the source origin. Clone
      // the live material's vertex/discard patch onto a depth material instead.
      // This covers Full/Beads, cylinder/hull LODs and atom impostors; ordinary
      // surfaces retain Three's normal instanceMatrix depth path.
      const needsSharedDepth = (obj.userData?.sharedInstanced
        || (obj.userData?.sharedLodImpostor && obj.name !== 'assemblySurface'))
        && typeof obj.material?.onBeforeCompile === 'function'
      if (needsSharedDepth && !obj.customDepthMaterial) {
        const depth = new THREE.MeshDepthMaterial({
          depthPacking: THREE.RGBADepthPacking,
          side: obj.material.side,
        })
        const sourceCompile = obj.material.onBeforeCompile.bind(obj.material)
        depth.onBeforeCompile = shader => {
          sourceCompile(shader)
          // Beauty shaders multiply/highlight RGB after positioning. On a depth
          // material that RGB stores packed depth, so remove only those colour
          // writes while retaining visibility/disc discard and gl_FragDepth.
          shader.fragmentShader = shader.fragmentShader
            .replace(/^\s*gl_FragColor\.rgb \*= [^;]+;\s*$/gm, '')
            .replace(/\s*if \(u_activeInstanceIdx[^}]+\}\s*/g, '\n')
        }
        depth.customProgramCacheKey = () => `photoSharedDepth_${depth.uuid}`
        obj.customDepthMaterial = depth
      }

      const canCast = !isShadowExcluded(obj)
        && !_rejected.has(obj)            // a 100 µm plane would shadow everything
        && (!obj.material?.userData?.isImpostor || !!obj.customDepthMaterial)
        && (obj.material?.userData?.impostorRadius == null || !!obj.customDepthMaterial)
        && (!obj.userData?.sharedLodImpostor || !!obj.customDepthMaterial
            || obj.name === 'assemblySurface')
      obj.castShadow    = canCast
      obj.receiveShadow = !isShadowExcluded(obj)
    })
  }

  function _restoreMeshShadowFlags() {
    for (const [obj, s] of _savedMeshShadows) {
      obj.castShadow    = s.cast
      obj.receiveShadow = s.receive
      if (obj.customDepthMaterial !== s.customDepthMaterial) {
        obj.customDepthMaterial?.dispose?.()
        obj.customDepthMaterial = s.customDepthMaterial ?? undefined
      }
    }
    _savedMeshShadows.clear()
  }

  function _buildComposer() {
    _composer?.dispose?.()
    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    const composer = new EffectComposer(renderer)
    composer.addPass(new RenderPass(scene, camera))
    // Before SMAA so the contour gets antialiased with everything else.
    _figurePass = new FigurePass(scene, camera)
    composer.addPass(_figurePass)
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
    _savedFov = camera.fov
    _savedEnv = scene.environment
    _savedEnvIntensity = scene.environmentIntensity
    _savedEnvRotation  = scene.environmentRotation.clone()
    _savedBg  = scene.background
    scene.environment = null

    _lightGroup = new THREE.Group()
    _lightGroup.name = 'expPhotoLights'
    scene.add(_lightGroup)
    _hideEditorLights()

    _matSwap = swapToFlatMaterials(scene, _materialPresets())
    _applyBackground()

    // Before _rebuildRig, which fits the catcher at the tail of _applyKeyShadow.
    // Safe to create pre-swap-independent: the catcher's material carries
    // userData.photoFloor and is never swapped.
    _floor = createShadowCatcher(scene)

    _buildComposer()

    // Composer first, PMREM second. PMREM baking churns WebGL render targets;
    // constructing the post chain before that bake and resetting renderer state
    // afterward keeps the first composed frame deterministic.
    _ensurePreviewStudioEnvironment()
    _applyStudioEnvironment()

    // Rig last: it fits itself to the scene bounds, and the material swap above
    // does not move geometry, so the bounds are already final.
    _rebuildRig()
    _applyFigure()
    if (_settings.fov != null) _applyFovWithDolly(_settings.fov)
    if (_settings.pinLights) _syncRigToCamera()

    setResizeCallback?.(() => {
      const s = renderer.getDrawingBufferSize(new THREE.Vector2())
      _composer?.setSize(s.x, s.y)
      _figurePass?.setSize(s.x, s.y)
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
   * ChimeraX's per-frame `use_shadow_map`.
   */
  function _perFrameSync() {
    _enforceSingleShadowSource()
    if (_settings.pinLights) _syncRigToCamera()
    // The cue window's START tracks the camera, so it is pushed every frame.
    // The outline needs the same push for its scene-depth span.
    if (_settings.depthCue || _settings.outline) _pushCueRange()
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
    _figurePass = null
    _matSwap?.restore()
    _matSwap = null

    // Shadow state — restore BEFORE the rig is torn down (the flags live on the
    // scene meshes and the lights we are about to drop).
    _floor?.remove()
    _floor = null
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
    scene.environmentIntensity = _savedEnvIntensity
    if (_savedEnvRotation) scene.environmentRotation.copy(_savedEnvRotation)
    scene.background  = _savedBg
    _disposePreviewStudioEnvironment()
    _savedEnv = undefined
    _savedEnvRotation = null
    _savedBg  = undefined
    renderer.setClearColor(_savedClearColor, _savedClearAlpha)
    // Restore the editor's lens WITH a dolly, so the user keeps the framing
    // they orbited to rather than snapping back to the old distance.
    if (_savedFov != null && camera.fov !== _savedFov) _applyFovWithDolly(_savedFov)
    _savedFov = null
    if (_savedToneMapping !== null) renderer.toneMapping = _savedToneMapping
    if (_savedExposure    !== null) renderer.toneMappingExposure = _savedExposure
    _savedToneMapping = null
    _savedExposure    = null
  }

  // ── Settings ───────────────────────────────────────────────────────────────

  /**
   * Depth-cue window for the CURRENT camera pose. START = the nearest bbox
   * corner along the view axis, so the fade always begins at the front of the
   * object. LENGTH = the bbox DIAGONAL, a CONSTANT for the design — not the
   * current view's depth extent. Scaling to the current extent normalises every
   * view to a full 0→1 fade, which washes out a thin helix seen side-on for no
   * reason; against a fixed length the cue is near-nothing on a shallow view and
   * strong only when you are genuinely looking down the depth of a bundle.
   */
  function _pushCueRangeTo(pass) {
    if (!pass || !_bounds?.corners) return
    camera.getWorldDirection(_camForward)
    let near = Infinity
    for (const c of _bounds.corners) {
      const d = _cueScratch.subVectors(c, camera.position).dot(_camForward)
      if (d < near) near = d
    }
    // The camera can sit inside the box on a close-up, putting corners behind
    // it — clamp so the fade never starts behind the viewer.
    near = Math.max(near, camera.near)
    pass.setCueRange(near, near + (_bounds.diagonal || 1))
    // Same span feeds ChimeraX's depth_jump — it is a fraction OF the structure's
    // depth, so a 3% jump means the same nm gap whether you framed a 20 nm tile
    // or a 400 nm origami.
    pass.setSceneDepth(_bounds.diagonal || 0)
  }

  function _pushCueRange() { _pushCueRangeTo(_figurePass) }

  /**
   * The FigurePass parameter block, in one place.
   *
   * The preview pass and every offscreen export pass live in DIFFERENT GL
   * contexts and are separate instances, so each has to be fed this itself —
   * that is the "export parity is not automatic" rule. Having one source for it
   * is what stops the preview and the export drifting apart silently.
   */
  function _figureParams() {
    return {
      outline:                  _settings.outline,
      outlineColor:             _settings.outlineColor,
      outlineStrength:          _settings.outlineStrength,
      outlineThickness:         _settings.outlineThickness,
      outlineDepthSensitivity:  _settings.outlineDepthSensitivity,
      outlineCreaseSensitivity: _settings.outlineCreaseSensitivity,
      silhouette:               _settings.silhouette,
      outlineDepthJump:         _settings.outlineDepthJump,
      depthCue:                 _settings.depthCue,
      depthCueColor:            _settings.depthCueColor,
      depthCueStrength:         _settings.depthCueStrength,
    }
  }

  function _applyFigure() {
    if (!_figurePass) return
    _figurePass.setParams(_figureParams())
    _pushCueRange()
    // EffectComposer skips a disabled pass entirely, so both effects off costs
    // nothing — no depth/normal pre-pass at all.
    _figurePass.enabled = _figurePass.hasEffect()
  }

  function setOutline(on)          { _settings.outline = !!on; _applyFigure() }
  function setOutlineColor(hex)    { _settings.outlineColor = hex; _applyFigure() }
  function setOutlineStrength(v)   { _settings.outlineStrength = v; _applyFigure() }
  function setOutlineThickness(v)  { _settings.outlineThickness = v; _applyFigure() }
  function setOutlineSensitivity({ depth, crease } = {}) {
    if (depth  !== undefined) _settings.outlineDepthSensitivity  = depth
    if (crease !== undefined) _settings.outlineCreaseSensitivity = crease
    _applyFigure()
  }
  function setOutlineDepthJump(v)  { _settings.outlineDepthJump = v; _applyFigure() }
  function setDepthCue(on)         { _settings.depthCue = !!on; _applyFigure() }
  function setDepthCueColor(hex)   { _settings.depthCueColor = hex; _applyFigure() }
  function setDepthCueStrength(v)  { _settings.depthCueStrength = v; _applyFigure() }

  // ── Camera ────────────────────────────────────────────────────────────────

  /** Change the lens AND dolly to preserve framing, so narrowing the FOV
   *  flattens perspective instead of zooming in. */
  function _applyFovWithDolly(newFov) {
    const target = controls?.target
    const oldFov = camera.fov
    if (target && Number.isFinite(oldFov) && oldFov > 0) {
      const dist = camera.position.distanceTo(target)
      const newDist = dollyDistanceForFov(dist, oldFov, newFov)
      if (dist > 1e-6 && Number.isFinite(newDist)) {
        _dollyScratch.subVectors(camera.position, target).normalize().multiplyScalar(newDist)
        camera.position.copy(target).add(_dollyScratch)
      }
    }
    camera.fov = newFov
    camera.updateProjectionMatrix()
    controls?.update?.()
  }

  function setFOV(fov) {
    _settings.fov = fov
    // A FOV at or below the threshold IS the parallel projection — keep the
    // flag (and the checkbox) honest either way.
    _settings.parallel = fov <= PARALLEL_FOV
    if (_active) _applyFovWithDolly(fov)
  }

  /** Back to the default 55° lens (and out of parallel projection), dollying so
   *  the framing survives. Lives here, not in the panel, for the same reason
   *  resetKeyDirection() does: one home for the defaults. */
  function resetFOV() { setFOV(PERSPECTIVE_FOV) }

  function setParallel(on) {
    _settings.parallel = !!on
    _settings.fov = on ? PARALLEL_FOV : PERSPECTIVE_FOV
    if (_active) _applyFovWithDolly(_settings.fov)
  }

  // ── Export ────────────────────────────────────────────────────────────────

  function setExportSize(w, h) {
    if (Number.isFinite(w) && w > 0) _settings.exportWidth  = Math.round(w)
    if (Number.isFinite(h) && h > 0) _settings.exportHeight = Math.round(h)
  }

  /**
   * The per-frame scene sync an OFFLINE render has to do for itself.
   *
   * The live preview gets this from `_perFrameSync`, which only runs inside the
   * render-loop override installed by `setRenderFn`. A frame-stepped export
   * never ticks that loop, so without this a long export silently degrades:
   *
   *  - **Meshes get REPLACED mid-timeline.** Trajectory keyframes swap the heavy
   *    atomistic/surface rep in and out, and pre-baked geometry frames rebuild
   *    beads. Fresh meshes arrive with the EDITOR's materials and shadow flags,
   *    so the photo look just stops applying to them. `sceneSignature` catches
   *    exactly this, and `resync()` re-swaps + refits.
   *  - **Geometry MOVES without any mesh changing.** Cluster rotations and
   *    binding hinges move the bounding box while the mesh set is identical, so
   *    the fingerprint cannot see it and the shadow frustum stays fitted to
   *    where the structure used to be. Only a caller that knows the scene is
   *    animating should pay for a full refit per frame — hence `followMotion`.
   */
  function _syncForOfflineFrame(followMotion) {
    if (sceneSignature(scene) !== _signature) {
      resync()                    // re-swaps materials, restores flags, refits rig + cue
    } else if (followMotion) {
      _refitBounds()              // same meshes, moved geometry → frustum + floor only
    }
    // The rig is welded to the camera, and a camera-pose keyframe moves the
    // camera every frame — without this the key light stays where it was when
    // the mode was activated and the shading stops tracking the shot.
    if (_settings.pinLights) _syncRigToCamera()
    // NB the cue window is NOT pushed here: it depends on the per-tile
    // projection, so the session pushes it inside the tile loop instead.
  }

  /**
   * Open a reusable offscreen render session at `width × height`.
   *
   * ONE offscreen renderer, composer and FigurePass for every frame. This is
   * not an optimisation: browsers block new WebGL contexts after roughly 30
   * ("Web page caused context loss and was blocked"), so building a fresh
   * context per frame dies partway through any real animation.
   *
   * TILED, because a render target above the GPU's MAX_TEXTURE_SIZE silently
   * clamps and produces a black image — 300 DPI (4200×2970) already exceeds the
   * 4096 limit common on WSL/integrated GPUs. `camera.setViewOffset` renders a
   * sub-rectangle of the full frame per tile; the CPU-side 2D canvas has no such
   * limit, so the stitch is safe.
   *
   * The offscreen renderer is a SEPARATE GL context, so it needs its own
   * composer, its own figure-pass parameters and its own shadowMap flag — none
   * of the live renderer's GPU state carries over. That is the rule that keeps
   * preview and export in sync.
   *
   * @param {number} width
   * @param {number} height
   * @param {{followMotion?: boolean}} [opts] — `followMotion` refits the shadow
   *   frustum every frame, for callers stepping an animation. Stills leave it off.
   * @returns {{renderFrame: () => Promise<Blob>, dispose: () => void, tiles: number}}
   */
  function beginFrameSession(width, height, { followMotion = false } = {}) {
    if (!_active) throw new Error('photo: beginFrameSession requires the mode to be active')

    const probeCanvas = document.createElement('canvas')
    const probeR = new THREE.WebGLRenderer({ canvas: probeCanvas, alpha: true })
    const maxTex = probeR.capabilities.maxTextureSize
    probeR.dispose()

    const tileMax = Math.min(maxTex, 4096)
    const tilesX  = Math.max(1, Math.ceil(width  / tileMax))
    const tilesY  = Math.max(1, Math.ceil(height / tileMax))
    const tileW   = Math.ceil(width  / tilesX)
    const tileH   = Math.ceil(height / tilesY)

    const finalCanvas  = document.createElement('canvas')
    finalCanvas.width  = width
    finalCanvas.height = height
    // willReadFrequently: the video path reads this canvas back with getImageData on
    // every frame, and a GPU-backed 2D context pays a full readback each time.
    const finalCtx     = finalCanvas.getContext('2d', { willReadFrequently: true })

    const offCanvas = document.createElement('canvas')
    offCanvas.width  = tileW
    offCanvas.height = tileH
    const offRenderer = new THREE.WebGLRenderer({
      canvas: offCanvas, antialias: true, alpha: true, preserveDrawingBuffer: true,
    })
    offRenderer.setPixelRatio(1)
    offRenderer.toneMapping         = THREE.ACESFilmicToneMapping
    offRenderer.toneMappingExposure = 1.0
    offRenderer.setSize(tileW, tileH, false)
    // The offscreen renderer is a separate GL context — it needs the shadow flag
    // set explicitly, or the export comes back without the cast shadow.
    const wantShadow = !!(_settings.keyShadow && _keyLight?.castShadow)
    offRenderer.shadowMap.enabled = wantShadow
    if (wantShadow) offRenderer.shadowMap.type = THREE.PCFSoftShadowMap
    if (_settings.bgType === 'transparent') offRenderer.setClearColor(0x000000, 0)
    else offRenderer.setClearColor(new THREE.Color(_settings.bgColor), 1)

    const composer = new EffectComposer(offRenderer)
    composer.addPass(new RenderPass(scene, camera))
    const figure = new FigurePass(scene, camera)
    composer.addPass(figure)
    composer.addPass(new SMAAPass(tileW, tileH))
    composer.addPass(new OutputPass())
    composer.setSize(tileW, tileH)

    // PMREM textures are WebGL-context-local. Re-bake the same neutral studio
    // for the export renderer or metallic exports would be black even though
    // the live preview is correctly lit.
    const exportEnvTexture = _settings.studioEnvironment
      ? bakeStudioEnvironment(offRenderer)
      : null
    offRenderer.resetState?.()

    let _disposed = false

    /**
     * Render every tile into `finalCanvas` and return it.
     *
     * The canvas IS the frame — `renderFrame()` only wraps this in a PNG because a
     * still export wants a file. A video export does not: it used to pay a full
     * PNG deflate-encode + decode + blit per frame purely to get back the bytes
     * already sitting here. Callers that want pixels take this and read them.
     *
     * The returned canvas is session-owned and REUSED by the next call — consume it
     * before rendering the next frame.
     */
    function renderFrameToCanvas() {
      if (_disposed) throw new Error('photo: renderFrame() called after dispose()')
      _syncForOfflineFrame(followMotion)

      const savedAspect = camera.aspect
      try {
        camera.aspect = width / height
        // The tiles are drawn with drawImage, which COMPOSITES. On a transparent
        // background that lets the previous frame show through the new one, so the
        // canvas has to start empty on every frame, not just the first.
        finalCtx.clearRect(0, 0, width, height)
        for (let ty = 0; ty < tilesY; ty++) {
          for (let tx = 0; tx < tilesX; tx++) {
            camera.setViewOffset(width, height, tx * tileW, ty * tileH, tileW, tileH)
            camera.updateProjectionMatrix()
            // Per-tile: the cue window's near corner depends on the projection.
            figure.setParams(_figureParams())
            _pushCueRangeTo(figure)
            figure.enabled = figure.hasEffect()
            // Keep the context-local export PMREM bound only for this synchronous
            // draw. Restoring immediately preserves the live preview between
            // asynchronously encoded video/still frames.
            const liveEnv = scene.environment
            scene.environment = _settings.studioEnvironment ? exportEnvTexture : null
            try {
              composer.render()
            } finally {
              scene.environment = liveEnv
            }
            finalCtx.drawImage(offCanvas, tx * tileW, ty * tileH)
          }
        }
      } finally {
        camera.clearViewOffset()
        camera.aspect = savedAspect
        camera.updateProjectionMatrix()
      }
      return finalCanvas
    }

    async function renderFrame() {
      renderFrameToCanvas()
      return new Promise(resolve => finalCanvas.toBlob(resolve, 'image/png'))
    }

    function dispose() {
      if (_disposed) return
      _disposed = true
      composer.dispose?.()
      figure.dispose?.()
      exportEnvTexture?.dispose?.()
      offRenderer.dispose()
    }

    return { renderFrame, renderFrameToCanvas, dispose, tiles: tilesX * tilesY }
  }

  /**
   * Render one frame at an arbitrary resolution and return a PNG Blob.
   * A one-shot session — see `beginFrameSession` for the tiling and
   * separate-GL-context rules that govern both.
   */
  async function renderToBlob(width, height) {
    if (!_active) throw new Error('photo: renderToBlob requires the mode to be active')
    const session = beginFrameSession(width, height)
    try {
      return await session.renderFrame()
    } finally {
      session.dispose()
    }
  }

  /** The four preset names, in the shape swapToFlatMaterials expects. */
  function _materialPresets() {
    const { full, cylinders, surface, atomistic } = _settings
    return { full, cylinders, surface, atomistic }
  }

  /** Change one representation's material. Re-swaps in place — cheap, and it
   *  keeps the shadow flags/bounds valid because no geometry moved. */
  function setMaterialPreset(repr, preset) {
    if (!(repr in _materialPresets())) return
    _settings[repr] = preset
    if (!_active) return
    _matSwap?.restore()
    _matSwap = swapToFlatMaterials(scene, _materialPresets())
    _restoreMeshShadowFlags()
    _applyKeyShadow()
  }

  /** Steer the key light (and therefore its shadow) around the screen. */
  function setKeyAzimuth(deg)   { _settings.keyAzimuth = deg;   if (_active) _rebuildRig() }
  function setKeyElevation(deg) { _settings.keyElevation = deg; if (_active) _rebuildRig() }

  /** Back to ChimeraX's own key direction. Lives here, not in the panel, so the
   *  defaults have exactly one home and the panel needs no import of them
   *  (which would close an import cycle: the mode already imports the panel). */
  function resetKeyDirection() {
    _settings.keyAzimuth   = DEFAULT_KEY_AZIMUTH
    _settings.keyElevation = DEFAULT_KEY_ELEVATION
    if (_active) _rebuildRig()
  }

  /** Absolute per-light intensities — the real shadow-contrast controls. */
  function setKeyIntensity(v)     { _settings.keyIntensity = Math.max(0, v);     if (_active) _rebuildRig() }
  function setFillIntensity(v)    { _settings.fillIntensity = Math.max(0, v);    if (_active) _rebuildRig() }
  function setAmbientIntensity(v) { _settings.ambientIntensity = Math.max(0, v); if (_active) _rebuildRig() }
  function setShadowStrength(v) {
    _settings.shadowStrength = Math.max(0, Math.min(1, v))
    if (_active) _applyKeyShadow()
  }

  /** Neutral image-based studio light. Unlike AmbientLight, this contributes a
   *  specular environment for metalness=1 materials. */
  function setStudioEnvironment(on) {
    _settings.studioEnvironment = !!on
    if (!_active) return
    _ensurePreviewStudioEnvironment()
    _applyStudioEnvironment()
  }

  function setStudioEnvironmentIntensity(v) {
    _settings.studioEnvironmentIntensity = Number.isFinite(v) ? Math.max(0, v) : 0
    if (_active) _applyStudioEnvironment()
  }

  function setStudioEnvironmentRotation(deg) {
    _settings.studioEnvironmentRotation = Number.isFinite(deg) ? deg : 0
    if (_active) _applyStudioEnvironment()
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

  /** Shadow-catching floor. Unlike photo mode v1's ground plane this gates
   *  nothing — the key shadow is unchanged with it off. */
  function setFloor(on) {
    _settings.floor = !!on
    if (_active) _applyFloor()
  }

  function setFloorOpacity(v) {
    _settings.floorOpacity = Math.max(0, Math.min(1, v))
    if (_active) _applyFloor()
  }

  /** nm outward from the chosen face. 0 = flush (hard contact shadow); larger
   *  pushes the plane away for a detached, softer pool. */
  function setFloorOffset(nm) {
    _settings.floorOffset = Number.isFinite(nm) ? nm : 0
    if (_active) _applyFloor()
  }

  /** Which side of the design the plane sits against: '-y' (floor), '+y'
   *  (ceiling), '±x' / '±z' (walls). World axes — the plane must stay put while
   *  the camera-pinned key light sweeps across it. */
  function setFloorAxis(axis) {
    if (!FLOOR_AXES.includes(axis)) return
    _settings.floorAxis = axis
    if (_active) _applyFloor()
  }

  /** World centre + reach of the catcher, for main.js's adaptive far clip. */
  function getFloorReach() { return _floor?.getReach() ?? null }

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
    _matSwap = swapToFlatMaterials(scene, _materialPresets())
    // Fresh meshes arrive with the editor's shadow flags and the bounds may have
    // moved, so the rig has to refit and the flags be re-applied.
    _restoreMeshShadowFlags()
    _rebuildRig()
    _applyFigure()          // bounds moved → the cue window has to be refitted
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
   * Exposed on window.__photoMode — being able to
   * answer that question without a rebuild is worth the ~40 lines.
   */
  function getDiagnostics() {
    const key = _keyLight
    const shadow = key?.shadow
    let casters = 0, receivers = 0, physical = 0, compiled = 0, withShadowDefine = 0
    const shadowObjects = []
    const lights = []
    scene.traverse(obj => {
      if (obj.isLight) {
        let effectivelyVisible = obj.visible
        for (let parent = obj.parent; effectivelyVisible && parent; parent = parent.parent) {
          effectivelyVisible = parent.visible
        }
        lights.push({
          name: obj.name || '(unnamed)',
          type: obj.type,
          visible: !!effectivelyVisible,
          intensity: obj.intensity,
          castShadow: !!obj.castShadow,
          isKey: obj === _keyLight,
        })
      }
      if (!obj.isMesh && !obj.isInstancedMesh) return
      const m = obj.material
      let effectivelyVisible = obj.visible && m?.visible !== false
        && (!obj.isInstancedMesh || obj.count > 0)
      for (let parent = obj.parent; effectivelyVisible && parent; parent = parent.parent) {
        effectivelyVisible = parent.visible
      }
      if (effectivelyVisible && obj.castShadow) casters++
      if (effectivelyVisible && obj.receiveShadow) receivers++
      if (effectivelyVisible && (obj.castShadow || obj.receiveShadow)) shadowObjects.push({
        name: obj.name || '(unnamed)',
        type: obj.isInstancedMesh ? `InstancedMesh×${obj.count}` : obj.type,
        material: m?.type ?? null,
        cast: !!obj.castShadow,
        receive: !!obj.receiveShadow,
        customDepth: obj.customDepthMaterial?.type ?? null,
        sharedInstanced: !!obj.userData?.sharedInstanced,
        sharedLod: !!obj.userData?.sharedLodImpostor,
        photoFloor: !!obj.userData?.photoFloor,
        visible: !!obj.visible,
      })
      if (!effectivelyVisible || !m?.isMeshPhysicalMaterial) return
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
    let shadowGeometry = null
    if (key && shadow?.camera && _bounds) {
      // Measure the actual ray, not just the parent-group quaternion. This
      // catches a detached DirectionalLight target and makes camera pinning
      // directly comparable between a design and an assembly.
      scene.updateMatrixWorld(true)
      camera.updateMatrixWorld(true)
      shadow.camera.updateMatrixWorld(true)
      const lightPos = key.getWorldPosition(new THREE.Vector3())
      const targetPos = key.target?.getWorldPosition(new THREE.Vector3()) ?? _bounds.center.clone()
      const worldRay = targetPos.clone().sub(lightPos).normalize()
      const cameraRay = worldRay.clone().applyQuaternion(camQ.clone().invert())
      const shadowRay = shadow.camera.getWorldDirection(new THREE.Vector3())
      const ndcCorners = (_bounds.corners ?? []).map(corner =>
        corner.clone().project(shadow.camera))
      const axisRange = axis => ndcCorners.length ? {
        min: Math.min(...ndcCorners.map(v => v[axis])),
        max: Math.max(...ndcCorners.map(v => v[axis])),
      } : null
      const ndc = { x: axisRange('x'), y: axisRange('y'), z: axisRange('z') }
      const roundVec = vector => vector.toArray().map(v => +v.toFixed(5))
      shadowGeometry = {
        worldRay: roundVec(worldRay),
        cameraRay: roundVec(cameraRay),
        shadowCameraRay: roundVec(shadowRay),
        shadowCameraAlignment: +worldRay.dot(shadowRay).toFixed(6),
        targetCenterError: +targetPos.distanceTo(_bounds.center).toFixed(6),
        ndc: Object.fromEntries(Object.entries(ndc).map(([axis, range]) => [axis,
          range ? { min: +range.min.toFixed(5), max: +range.max.toFixed(5) } : null])),
        outsideCorners: ndcCorners.filter(v =>
          Math.abs(v.x) > 1.0001 || Math.abs(v.y) > 1.0001 || Math.abs(v.z) > 1.0001).length,
        // Fraction of the map's width/height occupied by the authoritative box.
        // Very small values expose an inflated assembly bound and lost precision.
        occupancy: ndc.x && ndc.y ? {
          x: +((ndc.x.max - ndc.x.min) / 2).toFixed(5),
          y: +((ndc.y.max - ndc.y.min) / 2).toFixed(5),
        } : null,
      }
    }
    return {
      active: _active,
      rendererShadowMapEnabled: renderer.shadowMap?.enabled,
      rendererShadowAutoUpdate: renderer.shadowMap?.autoUpdate,
      shadowCastingLights: lights.filter(light => light.visible && light.castShadow),
      allLights: lights,
      studioEnvironment: {
        enabled: _settings.studioEnvironment,
        bound: scene.environment != null,
        intensity: scene.environmentIntensity,
      },
      figureEffects: {
        outline: !!_settings.outline,
        depthCue: !!_settings.depthCue,
        passEnabled: !!_figurePass?.enabled,
      },
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
      shadowGeometry,
      meshes: { casters, receivers, physical, compiled, withShadowDefine, shadowObjects },
      bake: getStatus(),
    }
  }

  return {
    activate, deactivate,
    getDiagnostics,
    isActive: () => _active,
    setBackground, setMaterialPreset,
    setFOV, resetFOV, setParallel, setExportSize, renderToBlob, beginFrameSession,
    setOutline, setOutlineColor, setOutlineStrength, setOutlineThickness,
    setOutlineSensitivity, setOutlineDepthJump,
    setDepthCue, setDepthCueColor, setDepthCueStrength,
    setPinLights, setKeyShadow, setKeyShadowBias, setKeyShadowMapSize,
    setFloor, setFloorOpacity, setFloorOffset, setFloorAxis, getFloorReach,
    setKeyAzimuth, setKeyElevation, resetKeyDirection,
    setKeyIntensity, setFillIntensity, setAmbientIntensity, setShadowStrength,
    setStudioEnvironment, setStudioEnvironmentIntensity, setStudioEnvironmentRotation,
    resync,
    getSettings, getStatus,
    // Test/console seams.
    _syncFrame:    _perFrameSync,
    _getKeyLight:  () => _keyLight,
    _getFigurePass: () => _figurePass,
    _getCamera:     () => camera,
    _getLightGroup: () => _lightGroup,
    _getFloor:      () => _floor,
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
export function initPhotoMode({
  store, sceneCtx, designRenderer, assemblyRenderer,
  assemblyJointRenderer, bluntEnds, originAxes,
  player, exportPhotoVideo, trajectoryKeyframes = null,
}) {
  const mode = createPhotoMode({
    ...sceneCtx,
    // Shared assembly LODs compose placements in shader textures and therefore
    // cannot be bounded correctly by Three's generic scene traversal. The
    // assembly renderer already owns the authoritative world-space box.
    getPhotoBounds: () => store.getState().assemblyActive
      ? assemblyRenderer?.getBoundingBox?.()
      : null,
  })
  let _panel = null
  let _savedOriginAxesVisible = null

  function enter() {
    if (mode.isActive()) return
    if (!_panel) _panel = initPhotoPanel(mode, {
      onExit: () => {
        exit()
        // The button is labelled "Exit Photo Mode", so leave the Photo pane as
        // well as removing its render override. The sidebar is initialized just
        // after this controller; the lazy lookup avoids a construction cycle.
        window.__leftSidebar?.selectTab?.('feature-log')
      },
      store, player, exportPhotoVideo, trajectoryKeyframes,
    })

    // Same gizmo suppression photo mode v1 used — an editor overlay in
    // a render being judged for its shading is noise, and the `toneMapped:false`
    // origin triad has a real artifact history (ANGLE/D3D11 + bloom).
    //
    // Hide these BEFORE activate(): activation computes the shadow/depth/floor
    // bounds immediately. Assembly transform controls contain many small helper
    // meshes; leaving them visible during that fit can make the actual assembly
    // look like a gross outlier and produce a null/zero-radius rig. BigO-poly is
    // the regression fixture that exposed this ordering dependency.
    designRenderer?.setAxisArrowsVisible?.(false)
    if (originAxes) {
      _savedOriginAxesVisible = originAxes.visible
      originAxes.visible = false
    }
    bluntEnds?.setVisible?.(false)
    assemblyRenderer?.setPhotoMode?.(true)
    assemblyJointRenderer?.setVisible?.(false)

    mode.activate()
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
