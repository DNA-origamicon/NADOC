/**
 * Assembly Joint Renderer — connector indicators, mate type indicators, ring-drag.
 *
 * Public API:
 *   initAssemblyJointRenderer(scene, camera, canvas, store, api, controls)
 *   → { rebuild(assembly),
 *        enterConnectorDefineMode(instanceId, onExit),
 *        exitConnectorDefineMode(),
 *        enterMateDefineMode(onExit, onLivePreview),
 *        exitMateDefineMode(),
 *        pickJointRing(e),
 *        beginRingDrag(jointId, e),
 *        setVisible(bool),
 *        dispose() }
 *
 * enterConnectorDefineMode shows a semi-transparent hull prism around the selected
 * instance.  Hovering over a face shows a ghost arrow preview; clicking places a
 * connector (InterfacePoint) at that face with the face normal as the axis direction.
 *
 * enterMateDefineMode shows gold sphere+arrow indicators on all existing connectors and
 * injects a sidebar panel. Click connectors to set child/parent (or use dropdowns), choose
 * mate type and options, then press "Create Mate".
 */

import * as THREE from 'three'
import {
  ringPlaneHit as _ringPlaneHitUtil,
  angleInRing  as _angleInRingUtil,
  makeRefVec,
} from './assembly_revolute_math.js'
import {
  buildBundleGeometry,
  buildPrismGeometry,
  buildPanelSurface,
  buildSpineSections,
  buildSweptHullGeometry,
  buildJointPreviewMesh,
  SURFACE_COLOUR, SURFACE_OPACITY,
  CROSS_MARGIN, AXIAL_MARGIN,
  PREV_HALF_LEN,
  MIN_HC_FACES, MIN_SQ_FACES,
} from './joint_renderer.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

// ── Joint indicator geometry constants ───────────────────────────────────────
const SHAFT_R   = 0.13
const HALF_LEN  = 0.9
const TIP_R     = 0.30
const TIP_H     = 0.72
const RING_R    = 1.18
const RING_TUBE = 0.08
const RING_SEGS = 48
const COLOUR    = 0xff8c00   // orange (joint)
const BROKEN_COLOUR = 0xff3333   // red (broken mate indicator)
const ACTIVE_RING_COLOUR = 0x3fb950   // green (selected ring, mirrors CONN_PARENT_COL)

// ── Phase 3e: shared InstancedMesh templates ─────────────────────────────────
// Tagged userData.shared = true so disposal walks skip them (per
// project_polymerize_origami: the shared-template pattern shipped Phase 1).
//
// Each template's local Y-axis aligns with the joint's axis direction. The
// per-mesh offsets that the old _buildIndicator applied to shaft/cone/ring
// (cone at +HALF_LEN+TIP_H/2, ring at -HALF_LEN, ring rotated -π/2) are BAKED
// into each geometry via translate/rotate so the per-joint instance matrix is
// just (translate to origin + HALF_LEN*ax) × (orient Y→ax).
const _JOINT_SHAFT_GEO = (() => {
  const g = new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, HALF_LEN * 2, 8)
  // Shaft already centred on local origin; no extra translate.
  g.userData.shared = true
  return g
})()
const _JOINT_CONE_GEO = (() => {
  const g = new THREE.ConeGeometry(TIP_R, TIP_H, 8)
  g.translate(0, HALF_LEN + TIP_H * 0.5, 0)
  g.userData.shared = true
  return g
})()
const _JOINT_RING_GEO = (() => {
  const g = new THREE.TorusGeometry(RING_R, RING_TUBE, 8, RING_SEGS)
  // Old code: ring.rotation.x = -π/2 then ring.position.y = -HALF_LEN.
  g.rotateX(-Math.PI / 2)
  g.translate(0, -HALF_LEN, 0)
  g.userData.shared = true
  return g
})()

// ── Connector indicator geometry constants ────────────────────────────────────
const CONN_SHAFT_R  = 0.06
const CONN_HALF_LEN = 0.7
const CONN_TIP_R    = 0.18
const CONN_TIP_H    = 0.40
const CONN_SPHERE_R = 0.38
const CONN_COLOUR     = 0xf0a500   // amber/gold (blunt-end + InterfacePoint)
const CONN_SEL_COL    = 0x58a6ff   // blue (selected child/first connector)
const CONN_PARENT_COL = 0x3fb950   // green (selected parent/second connector)
const CONN_HOV_COL    = 0xffffff   // white (hovered)
// Distinct color for bend center-of-curvature picks during Define-Mate.
// Cyan-blue — already the project's "geometric-aux" color (active-cluster
// glow). No clash with gold blunt-ends or orange joint rings.
const CONN_BEND_CENTER_COL = 0x39d6f0
// Bend-center picks render as an octahedron instead of a sphere so the user
// can distinguish them at a glance from gold blunt-end spheres.
const CONN_BEND_CENTER_GEO_R = CONN_SPHERE_R * 1.15

// Distance-based connector-indicator visibility (mate-define mode only).
// Hides connectors that aren't near the camera so designs with many
// overhangs aren't overwhelmed; fades them in to translucent as the
// camera approaches; hovering near (in screen-space) bumps individual
// indicators to full opacity via a Gaussian falloff so the cursor draws
// nearby connectors out of the haze.
const CONN_FADE_FAR_NM  = 60.0   // beyond this distance, indicators are hidden
const CONN_FADE_NEAR_NM = 20.0   // closer than this, indicators are at full translucent
const CONN_TRANS_OPACITY = 0.50

// Gaussian mouse-proximity boost (screen-space). At cursor exactly on a
// connector → opacity 1.0; at CONN_HOVER_SIGMA_PX it drops to ~37% of the
// boost ("one sigma"); beyond CONN_HOVER_CUTOFF_PX no boost applied.
// Mirrors the lattice-cell proximity effect in slice_plane.js but with a
// Gaussian falloff rather than linear.
const CONN_HOVER_SIGMA_PX  = 60
const CONN_HOVER_CUTOFF_PX = 180

const DRAG_THRESHOLD_PX = 6

// Used by _orientQ for indicator geometry (not for ring-drag math — that lives in assembly_revolute_math.js)
const _Y = new THREE.Vector3(0, 1, 0)
const _Z = new THREE.Vector3(0, 0, 1)

// ── Module-level helpers ──────────────────────────────────────────────────────

/** Quaternion to orient local +Y → direction. */
function _orientQ(dir3) {
  const q  = new THREE.Quaternion()
  const ax = new THREE.Vector3(...dir3).normalize()
  if (ax.lengthSq() < 1e-9) return { q, ax: _Y.clone() }
  if (Math.abs(ax.dot(_Y)) < 0.9999) {
    q.setFromUnitVectors(_Y, ax)
  } else if (ax.y < 0) {
    q.setFromAxisAngle(_Z, Math.PI)
  }
  return { q, ax }
}

/** Build orange (or red-broken) shaft + arrowhead + rotation ring for a joint indicator. */
function _buildIndicator(origin, direction, broken = false) {
  const { q, ax } = _orientQ(direction)
  const group = new THREE.Group()
  group.name = broken ? 'assemblyMateIndicator(broken)' : 'assemblyMateIndicator'
  group.userData.tag = 'assembly-mate-indicator'
  const colour = broken ? 0xff3333 : COLOUR

  const mat = new THREE.MeshBasicMaterial({
    color: colour, depthTest: false, depthWrite: false, transparent: true,
  })

  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, HALF_LEN * 2, 8), mat.clone(),
  )
  shaft.renderOrder = 9999
  group.add(shaft)

  const cone = new THREE.Mesh(new THREE.ConeGeometry(TIP_R, TIP_H, 8), mat.clone())
  cone.position.y = HALF_LEN + TIP_H * 0.5
  cone.renderOrder = 9999
  group.add(cone)

  const ringMat = new THREE.MeshBasicMaterial({
    color: colour, depthTest: false, depthWrite: false, transparent: true,
  })
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(RING_R, RING_TUBE, 8, RING_SEGS), ringMat,
  )
  ring.rotation.x           = -Math.PI / 2
  ring.position.y           = -HALF_LEN
  ring.renderOrder          = 9999
  ring.userData.isJointRing = true
  group.add(ring)

  group.quaternion.copy(q)
  group.position.copy(new THREE.Vector3(...origin)).addScaledVector(ax, HALF_LEN)
  group.renderOrder = 1000
  return group
}

/**
 * Compose the per-joint world matrix that places a shared-indicator template
 * at the joint pose. The Y-axis baked into the templates aligns with the
 * joint's `direction`; the translation places the template at
 * `origin + HALF_LEN*ax` (matches the old per-group .position.addScaledVector).
 *
 * @returns { matrix: THREE.Matrix4 } reusing the caller's Matrix4 if provided.
 */
function _jointInstanceMatrix(origin, direction, out) {
  const { q, ax } = _orientQ(direction)
  const pos = new THREE.Vector3(...origin).addScaledVector(ax, HALF_LEN)
  const m = out ?? new THREE.Matrix4()
  m.compose(pos, q, new THREE.Vector3(1, 1, 1))
  return m
}

/**
 * Build a connector indicator: sphere (click target) + directional arrow.
 * Returns { group: THREE.Group, hitMesh: THREE.Mesh }.
 */
function _buildConnectorIndicator(worldPos, worldNorm, color = CONN_COLOUR, markerKind = 'sphere') {
  const dir = new THREE.Vector3(worldNorm[0], worldNorm[1], worldNorm[2]).normalize()
  const { q } = _orientQ([dir.x, dir.y, dir.z])
  const grp = new THREE.Group()
  grp.position.set(worldPos[0], worldPos[1], worldPos[2])

  const mat = () => new THREE.MeshBasicMaterial({
    color, depthTest: false, depthWrite: false, transparent: true,
  })

  // Hit marker at connector origin — primary click/pick target. Bend centers
  // render as an octahedron so the user can distinguish them from gold
  // blunt-end spheres at a glance.
  const hitGeo = markerKind === 'bend_center'
    ? new THREE.OctahedronGeometry(CONN_BEND_CENTER_GEO_R, 0)
    : new THREE.SphereGeometry(CONN_SPHERE_R, 8, 6)
  const hitMesh = new THREE.Mesh(hitGeo, mat())
  hitMesh.renderOrder = 9999
  grp.add(hitMesh)

  // Arrow (shaft + cone) oriented along normal direction
  const arrowGrp = new THREE.Group()
  arrowGrp.quaternion.copy(q)

  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(CONN_SHAFT_R, CONN_SHAFT_R, CONN_HALF_LEN * 2, 6), mat(),
  )
  shaft.position.y = CONN_HALF_LEN
  shaft.renderOrder = 9999

  const cone = new THREE.Mesh(new THREE.ConeGeometry(CONN_TIP_R, CONN_TIP_H, 6), mat())
  cone.position.y = CONN_HALF_LEN * 2 + CONN_TIP_H * 0.5
  cone.renderOrder = 9999

  arrowGrp.add(shaft, cone)
  grp.add(arrowGrp)

  return { group: grp, hitMesh }
}

// ── Main export ───────────────────────────────────────────────────────────────

export function initAssemblyJointRenderer(scene, camera, canvas, store, api, controls) {
  // ── Phase 3e gate (mirrors createAssemblyRenderer's useShared toggle) ────
  // When window.NADOC_SHARED_RENDERER === true, joint indicators are drawn as
  // three shared InstancedMesh objects (shaft + cone + ring) instead of
  // ~3 Mesh per joint × N joints individual draws. Off by default so the
  // legacy per-joint Group path stays in use until the flag-flip cleanup.
  const _useSharedJoints = (typeof window !== 'undefined') && (window.NADOC_SHARED_RENDERER === true)

  const _jointGroup      = new THREE.Group()
  const _jointMeshes     = new Map()   // jointId → THREE.Group (legacy path only)
  /** jointId → [instance_a_id, instance_b_id] — drives selection-gated visibility. */
  const _jointEndpoints  = new Map()
  /** Selected part instance. Per-instance joint + connector indicators draw ONLY
   *  for it (null → none). Keeps the indicator overlay from issuing ~15 draw
   *  calls per part at assembly scale — see path_to_thousands LOD benchmark. */
  let _activeInstanceId  = null

  // ── Phase 3e: shared InstancedMesh state ─────────────────────────────────
  // Only populated when _useSharedJoints is true. Three InstancedMesh objects
  // share the per-joint transform — picking maps `intersection.instanceId`
  // back to a jointId via _sharedJointIds[instanceId].
  let _sharedShaftMesh = null
  let _sharedConeMesh  = null
  let _sharedRingMesh  = null
  /** jointId-ordered array. _sharedJointIds[i] is the joint at instance slot i. */
  let _sharedJointIds  = []
  /** parallel array of per-joint world matrices kept for fast setLiveJointTransform. */
  let _sharedJointMatrices = []
  /** Map<jointId, instanceIdx> for setLiveJointTransform / setActive lookups. */
  const _sharedJointIdxById = new Map()
  /** Map<jointId, boolean> broken flag. Drives ring/shaft tint via setColorAt. */
  const _sharedJointBroken  = new Map()
  /** Currently active (selected) joint id; null = none. Ring rendered green. */
  let _sharedActiveJointId = null
  const _connectorGroup  = new THREE.Group()
  const _connectorMeshes = []          // hitMesh objects (sphere) with userData
  // Blunt-end connector indicators — separate group, visible only in mate-define mode
  const _bluntConnGroup  = new THREE.Group()
  _bluntConnGroup.visible = false
  let _extraConnectors   = []          // blunt-end data from assemblyRenderer
  let _bluntConnMeshes   = []          // hitMeshes added for blunt ends
  const _bluntConnKeys   = new Set()   // "instId::label" keys added for blunt ends
  const _rc              = new THREE.Raycaster()
  scene.add(_jointGroup)
  scene.add(_connectorGroup)
  scene.add(_bluntConnGroup)

  // ── Preview mesh (ghost arrow during connector define mode) ───────────────
  const _previewMesh = buildJointPreviewMesh()
  scene.add(_previewMesh)

  // ── Connector define mode state ───────────────────────────────────────────
  let _definingInstanceId = null
  let _onExitCb           = null
  let _surfaceMesh   = null
  let _surfaceWire   = null
  let _hullMesh      = null
  let _hullWire      = null
  let _pointerDownAt = null

  // ── Mate define mode state ────────────────────────────────────────────────
  let _mateMode          = false
  let _mateOnExitCb      = null
  let _mateFirst         = null       // { instanceId, label, worldPos, worldNorm, instanceLabel }
  let _mateSecond        = undefined  // undefined=not set, null=World, obj=connector
  let _mateSidebarEl     = null
  let _onLivePreview     = null       // (instanceId, THREE.Matrix4) → void
  let _previewInstanceId = null       // currently previewed instance id
  const _connectorDataMap = new Map() // "instanceId::label" → connData

  // ── NDC helper ───────────────────────────────────────────────────────────
  function _ndc(e) {
    const r = canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - r.left) / r.width)  * 2 - 1,
      -((e.clientY - r.top)  / r.height) * 2 + 1,
    )
  }

  // ── Instance geometry helpers ────────────────────────────────────────────
  function _worldAxes(helixAxesArray, mat4) {
    const dict = {}
    for (const ax of helixAxesArray) {
      const s = new THREE.Vector3(...ax.start).applyMatrix4(mat4)
      const e = new THREE.Vector3(...ax.end).applyMatrix4(mat4)
      const samples = (ax.samples ?? [ax.start, ax.end]).map(pt => {
        const p = new THREE.Vector3(...pt).applyMatrix4(mat4)
        return [p.x, p.y, p.z]
      })
      dict[ax.helix_id] = { start: [s.x, s.y, s.z], end: [e.x, e.y, e.z], samples }
    }
    return dict
  }

  function _worldBackbone(nucleotides, mat4) {
    return nucleotides.map(nuc => {
      const p = new THREE.Vector3(...nuc.backbone_position).applyMatrix4(mat4)
      return { helix_id: nuc.helix_id, backbone_position: [p.x, p.y, p.z] }
    })
  }

  function _instMat4(inst) {
    const m = new THREE.Matrix4()
    if (inst?.transform?.values) m.fromArray(inst.transform.values).transpose()
    return m
  }

  // ── Hull surface lifecycle ────────────────────────────────────────────────
  function _removeSurface() {
    for (const obj of [_surfaceMesh, _surfaceWire, _hullMesh, _hullWire]) {
      if (obj) { obj.geometry?.dispose(); obj.material?.dispose(); obj.parent?.remove(obj) }
    }
    _surfaceMesh = _surfaceWire = _hullMesh = _hullWire = null
  }

  async function _showInstanceSurface(instanceId) {
    _removeSurface()

    const { currentAssembly } = store.getState()
    const inst = currentAssembly?.instances?.find(i => i.id === instanceId)
    if (!inst) return

    let geoData
    try {
      const batch = await api.getAssemblyGeometry()
      const entry = batch?.instances?.[instanceId]
      if (!entry || entry.error) {
        geoData = await api.getInstanceGeometry(instanceId)
      } else {
        geoData = entry
      }
    } catch (err) {
      console.warn('[assembly_joint_renderer] geometry fetch failed:', err)
      return
    }

    const helixAxesArray = geoData?.helix_axes ?? []
    const nucleotides    = geoData?.nucleotides ?? []
    const latticeType    = geoData?.design?.lattice_type ?? null
    if (!helixAxesArray.length) return

    const mat4        = _instMat4(inst)
    const worldAxDict = _worldAxes(helixAxesArray, mat4)
    const worldBack   = _worldBackbone(nucleotides, mat4)

    const pseudoCluster = { helix_ids: Object.keys(worldAxDict) }
    const N = latticeType?.toUpperCase() === 'SQUARE' ? MIN_SQ_FACES : MIN_HC_FACES

    // ── Curved swept hull (primary surface for bent designs) ──────────────
    const isCurved = Object.values(worldAxDict).some(ax => (ax.samples?.length ?? 0) > 2)
    if (isCurved) {
      const sections = buildSpineSections(pseudoCluster, worldAxDict, CROSS_MARGIN, AXIAL_MARGIN)
      if (sections) {
        const sweptGeo = buildSweptHullGeometry(sections)
        _surfaceMesh = new THREE.Mesh(sweptGeo, new THREE.MeshBasicMaterial({
          color: SURFACE_COLOUR, transparent: true, opacity: SURFACE_OPACITY,
          side: THREE.DoubleSide, depthTest: true, depthWrite: false,
        }))
        _surfaceMesh.renderOrder = 100
        _surfaceWire = new THREE.LineSegments(
          new THREE.WireframeGeometry(sweptGeo),
          new THREE.LineBasicMaterial({
            color: SURFACE_COLOUR, transparent: true,
            opacity: Math.min(1, SURFACE_OPACITY * 3),
            depthTest: false, depthWrite: false,
          }),
        )
        _surfaceWire.renderOrder = 101
        scene.add(_surfaceMesh, _surfaceWire)
      }
    }

    // ── Straight bundle geometry (hover grid, rings, straight hull fallback) ─
    const bg = buildBundleGeometry(pseudoCluster, worldAxDict, worldBack, N,
                                   CROSS_MARGIN, AXIAL_MARGIN, latticeType)
    if (!bg && !_surfaceMesh) return

    if (bg) {
      if (!_surfaceMesh) {
        // Straight part — use panel/prism surface as primary raycaster target
        const geo = bg.panels
          ? buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
          : buildPrismGeometry(bg.corners, bg.halfLen)
        _surfaceMesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
          color: SURFACE_COLOUR, transparent: true, opacity: SURFACE_OPACITY,
          side: THREE.DoubleSide, depthTest: true, depthWrite: false,
        }))
        _surfaceMesh.quaternion.copy(bg.rotQ)
        _surfaceMesh.position.copy(bg.bundleMid)
        _surfaceMesh.renderOrder = 100
        _surfaceWire = new THREE.LineSegments(
          new THREE.WireframeGeometry(geo),
          new THREE.LineBasicMaterial({
            color: SURFACE_COLOUR, transparent: true,
            opacity: Math.min(1, SURFACE_OPACITY * 3),
            depthTest: false, depthWrite: false,
          }),
        )
        _surfaceWire.quaternion.copy(bg.rotQ)
        _surfaceWire.position.copy(bg.bundleMid)
        _surfaceWire.renderOrder = 101
        scene.add(_surfaceMesh, _surfaceWire)
      }

      // Silent straight prism gap-filler (invisible backup raycaster target)
      const hullGeo = buildPrismGeometry(bg.corners, bg.halfLen)
      _hullMesh = new THREE.Mesh(hullGeo, new THREE.MeshBasicMaterial({
        color: SURFACE_COLOUR, transparent: true, opacity: 0,
        side: THREE.DoubleSide, depthTest: true, depthWrite: false,
      }))
      _hullMesh.quaternion.copy(bg.rotQ)
      _hullMesh.position.copy(bg.bundleMid)
      _hullMesh.renderOrder = 100
      _hullWire = new THREE.LineSegments(
        new THREE.WireframeGeometry(hullGeo),
        new THREE.LineBasicMaterial({ color: SURFACE_COLOUR, transparent: true, opacity: 0,
          depthTest: false, depthWrite: false }),
      )
      _hullWire.quaternion.copy(bg.rotQ)
      _hullWire.position.copy(bg.bundleMid)
      _hullWire.renderOrder = 101
      scene.add(_hullMesh, _hullWire)
    }
  }

  // ── Face hit detection ────────────────────────────────────────────────────
  function _getFaceHit(e) {
    _rc.setFromCamera(_ndc(e), camera)

    function _resolveHit(hit) {
      const nm = new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)
      const worldNormal = hit.face.normal.clone().applyMatrix3(nm).normalize()
      const toCamera = new THREE.Vector3().subVectors(camera.position, hit.point)
      if (worldNormal.dot(toCamera) < 0) worldNormal.negate()
      return { point: hit.point, normal: worldNormal }
    }

    const primTargets = [_surfaceMesh].filter(Boolean)
    if (primTargets.length) {
      const hits = _rc.intersectObjects(primTargets)
      if (hits.length && hits[0].face) return _resolveHit(hits[0])
    }

    if (_hullMesh) {
      const hits = _rc.intersectObject(_hullMesh)
      if (hits.length && hits[0].face) return _resolveHit(hits[0])
    }

    return null
  }

  // ── Pointer events — connector define mode ────────────────────────────────
  function _onPointerDown(e) { _pointerDownAt = { x: e.clientX, y: e.clientY } }

  function _wasDrag(e) {
    if (!_pointerDownAt) return false
    const dx = e.clientX - _pointerDownAt.x, dy = e.clientY - _pointerDownAt.y
    return (dx * dx + dy * dy) > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX
  }

  function _onConnectorSurfaceMove(e) {
    const hit = _getFaceHit(e)
    if (!hit) { _previewMesh.visible = false; return }
    const { q } = _orientQ([hit.normal.x, hit.normal.y, hit.normal.z])
    _previewMesh.quaternion.copy(q)
    _previewMesh.position.copy(hit.point).addScaledVector(hit.normal, PREV_HALF_LEN)
    _previewMesh.visible = true
  }

  function _onConnectorSurfaceClick(e) {
    if (_wasDrag(e)) return
    const hit = _getFaceHit(e)
    if (!hit) return
    const instId = _definingInstanceId
    exitConnectorDefineMode()
    // Transform world-space hit to instance local frame
    const inst = store.getState().currentAssembly?.instances?.find(i => i.id === instId)
    const m4   = _instMat4(inst)
    const inv  = m4.clone().invert()
    const lp   = hit.point.clone().applyMatrix4(inv)
    const ln   = hit.normal.clone().transformDirection(inv).normalize()
    api.addInstanceConnector(instId, {
      position: [lp.x, lp.y, lp.z],
      normal:   [ln.x, ln.y, ln.z],
    })
  }

  function _onConnectorKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); exitConnectorDefineMode() }
  }

  // ── Connector define mode: enter / exit ──────────────────────────────────

  /**
   * Show hull surface for instanceId; click places a connector (InterfacePoint).
   * @param {string}   instanceId
   * @param {function} onExit  called when mode ends
   */
  async function enterConnectorDefineMode(instanceId, onExit = null) {
    exitConnectorDefineMode()
    _definingInstanceId = instanceId
    _onExitCb           = onExit

    await _showInstanceSurface(instanceId)

    canvas.style.cursor = 'crosshair'
    canvas.addEventListener('pointerdown', _onPointerDown)
    canvas.addEventListener('pointermove', _onConnectorSurfaceMove)
    canvas.addEventListener('click',       _onConnectorSurfaceClick)
    document.addEventListener('keydown',   _onConnectorKeyDown)
  }

  function exitConnectorDefineMode() {
    _removeSurface()
    _previewMesh.visible = false
    canvas.removeEventListener('pointerdown', _onPointerDown)
    canvas.removeEventListener('pointermove', _onConnectorSurfaceMove)
    canvas.removeEventListener('click',       _onConnectorSurfaceClick)
    document.removeEventListener('keydown',   _onConnectorKeyDown)
    canvas.style.cursor = ''
    _definingInstanceId = null
    _pointerDownAt      = null
    const cb = _onExitCb
    _onExitCb = null
    cb?.()
  }

  // ── Mate define mode helpers ──────────────────────────────────────────────

  function _resetConnectorColors() {
    for (const mesh of _connectorMeshes) {
      const isFirst = _mateFirst &&
        mesh.userData.instanceId === _mateFirst.instanceId &&
        mesh.userData.label      === _mateFirst.label
      const isSecond = _mateSecond &&
        mesh.userData.instanceId === _mateSecond.instanceId &&
        mesh.userData.label      === _mateSecond.label
      const isBendCenter = mesh.userData.isBendCenter === true
      const baseCol = isBendCenter ? CONN_BEND_CENTER_COL : CONN_COLOUR
      mesh.material.color.set(isFirst ? CONN_SEL_COL : isSecond ? CONN_PARENT_COL : baseCol)
    }
  }

  function _removeMateOverlays() {
    if (_mateSidebarEl) { _mateSidebarEl.remove(); _mateSidebarEl = null }
  }

  // ── Blunt-end connector sync ─────────────────────────────────────────────
  // Rebuilds _bluntConnGroup and updates _connectorMeshes/_connectorDataMap
  // to include (or exclude) blunt-end connectors based on current _mateMode.
  function _syncBluntConnIndicators() {
    // Remove old blunt meshes from _connectorMeshes
    for (const m of _bluntConnMeshes) {
      const idx = _connectorMeshes.indexOf(m)
      if (idx >= 0) _connectorMeshes.splice(idx, 1)
    }
    // Remove old blunt keys from _connectorDataMap
    for (const key of _bluntConnKeys) _connectorDataMap.delete(key)
    _bluntConnKeys.clear()
    // Dispose old blunt indicator geometry
    _bluntConnGroup.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
    _bluntConnGroup.clear()
    _bluntConnMeshes = []
    _bluntConnGroup.visible = false

    if (!_mateMode || !_extraConnectors.length) return

    for (const be of _extraConnectors) {
      const key = `${be.instanceId}::${be.label}`
      if (_connectorDataMap.has(key)) continue  // already a real interface_point
      _connectorDataMap.set(key, be)
      _bluntConnKeys.add(key)
      const isBendCenter = be.isBendCenter === true
      const color = isBendCenter ? CONN_BEND_CENTER_COL : CONN_COLOUR
      const markerKind = isBendCenter ? 'bend_center' : 'sphere'
      const { group, hitMesh } = _buildConnectorIndicator(be.worldPos, be.worldNorm, color, markerKind)
      hitMesh.userData = {
        instanceId: be.instanceId, label: be.label,
        worldPos: be.worldPos, worldNorm: be.worldNorm,
        clusterId: be.clusterId ?? null,
        isBluntEnd:   be.isBluntEnd   === true,
        isBendCenter: isBendCenter,
      }
      _bluntConnGroup.add(group)
      _bluntConnMeshes.push(hitMesh)
      _connectorMeshes.push(hitMesh)
    }
    _bluntConnGroup.visible = true
  }

  // ── Mate sidebar panel ───────────────────────────────────────────────────
  function _buildMateSidebarPanel() {
    const panel = document.createElement('div')
    panel.id = '_mate-sidebar'
    panel.style.cssText = 'padding:10px 12px;border-bottom:1px solid #21262d;background:#0d1117;'

    const title = document.createElement('div')
    title.textContent = 'DEFINE MATE'
    title.style.cssText = 'font-size:11px;font-weight:600;color:#c9d1d9;margin-bottom:6px;letter-spacing:.04em;'
    panel.appendChild(title)

    const hint = document.createElement('div')
    hint.textContent = 'Pick the part to MOVE first (child), then the part it mates to (parent stays put).'
    hint.style.cssText = 'font-size:var(--text-xs);color:#6e7681;margin-bottom:10px;line-height:1.4;'
    panel.appendChild(hint)

    function makeSelect(includeWorld, selId) {
      const sel = document.createElement('select')
      sel.id = selId
      sel.style.cssText = 'width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;cursor:pointer;'
      const ph = document.createElement('option')
      ph.value = ''; ph.textContent = '— select —'; ph.disabled = true; ph.selected = true
      sel.appendChild(ph)
      if (includeWorld) {
        const wopt = document.createElement('option')
        wopt.value = '__world__'; wopt.textContent = 'World'
        sel.appendChild(wopt)
      }
      for (const [key, data] of _connectorDataMap) {
        const opt = document.createElement('option')
        opt.value = key
        opt.textContent = `${data.instanceLabel} : ${data.label}`
        sel.appendChild(opt)
      }
      return sel
    }

    function labelledRow(labelText, child, mb = '7px') {
      const row = document.createElement('div')
      row.style.marginBottom = mb
      const lbl = document.createElement('div')
      lbl.textContent = labelText
      lbl.style.cssText = 'font-size:var(--text-xs);color:#6e7681;margin-bottom:2px;'
      row.appendChild(lbl); row.appendChild(child)
      return row
    }

    const childSel  = makeSelect(false, '_mate-child-sel')
    const parentSel = makeSelect(true,  '_mate-parent-sel')
    panel.appendChild(labelledRow('Child Connector',  childSel))
    panel.appendChild(labelledRow('Parent Connector', parentSel))

    // Live "which part moves" status — updated as connectors are picked.
    const moveInfo = document.createElement('div')
    moveInfo.id = '_mate-move-info'
    moveInfo.style.cssText = 'font-size:var(--text-xs);margin:0 0 9px;line-height:1.4;min-height:14px;color:#6e7681;'
    panel.appendChild(moveInfo)

    // Invert toggle
    const invertRow = document.createElement('div')
    invertRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:7px;'
    const invertCb = document.createElement('input')
    invertCb.type = 'checkbox'; invertCb.id = '_mate-invert-cb'
    const invertLbl = document.createElement('label')
    invertLbl.htmlFor = '_mate-invert-cb'
    invertLbl.textContent = 'Invert direction'
    invertLbl.style.cssText = 'font-size:11px;color:#c9d1d9;cursor:pointer;user-select:none;'
    invertRow.appendChild(invertCb); invertRow.appendChild(invertLbl)
    panel.appendChild(invertRow)

    // Mate type
    const typeSel = document.createElement('select')
    typeSel.id = '_mate-type-sel'
    typeSel.style.cssText = 'width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;cursor:pointer;'
    for (const [v, t] of [['rigid', 'Rigid'], ['revolute', 'Revolute'], ['prismatic', 'Prismatic'], ['spherical', 'Spherical']]) {
      const opt = document.createElement('option'); opt.value = v; opt.textContent = t
      typeSel.appendChild(opt)
    }
    panel.appendChild(labelledRow('Mate Type', typeSel))

    // Type-specific fields
    const fieldsEl = document.createElement('div')
    fieldsEl.style.marginBottom = '8px'
    panel.appendChild(fieldsEl)

    function updateFields() {
      fieldsEl.innerHTML = ''
      if (typeSel.value === 'rigid') {
        fieldsEl.innerHTML = `
          <div style="font-size:var(--text-xs);color:#6e7681;margin-bottom:2px">Fixed Angle (°)</div>
          <input id="_mate-fixed-angle" type="number" value="0" step="1"
            style="width:100%;box-sizing:border-box;background:#161b22;color:#c9d1d9;
                   border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;">
        `
      } else if (typeSel.value === 'revolute') {
        fieldsEl.innerHTML = `
          <div style="display:flex;gap:6px">
            <div style="flex:1">
              <div style="font-size:var(--text-xs);color:#6e7681;margin-bottom:2px">Min Angle (°)</div>
              <input id="_mate-min-angle" type="number" value="-180" step="1"
                style="width:100%;box-sizing:border-box;background:#161b22;color:#c9d1d9;
                       border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;">
            </div>
            <div style="flex:1">
              <div style="font-size:var(--text-xs);color:#6e7681;margin-bottom:2px">Max Angle (°)</div>
              <input id="_mate-max-angle" type="number" value="180" step="1"
                style="width:100%;box-sizing:border-box;background:#161b22;color:#c9d1d9;
                       border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;">
            </div>
          </div>
        `
      }
      _applyPreview()
    }
    updateFields()
    typeSel.addEventListener('change', updateFields)
    fieldsEl.addEventListener('input', () => _applyPreview())

    // Preview toggle
    const previewRow = document.createElement('div')
    previewRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;'
    const previewCb = document.createElement('input')
    previewCb.type = 'checkbox'; previewCb.id = '_mate-preview-cb'; previewCb.checked = true
    const previewLbl = document.createElement('label')
    previewLbl.htmlFor = '_mate-preview-cb'
    previewLbl.textContent = 'Preview'
    previewLbl.style.cssText = 'font-size:11px;color:#c9d1d9;cursor:pointer;user-select:none;'
    previewRow.appendChild(previewCb); previewRow.appendChild(previewLbl)
    panel.appendChild(previewRow)

    // Buttons
    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;gap:6px;'
    const createBtn = document.createElement('button')
    createBtn.textContent = 'Create Mate'
    createBtn.style.cssText = 'flex:1;padding:5px;background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;cursor:pointer;font-size:11px;'
    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'
    cancelBtn.style.cssText = 'flex:1;padding:5px;background:#161b22;border:1px solid #484f58;color:#6e7681;border-radius:3px;cursor:pointer;font-size:11px;'
    btnRow.appendChild(createBtn); btnRow.appendChild(cancelBtn)
    panel.appendChild(btnRow)

    // Dropdown → state sync
    childSel.addEventListener('change', () => {
      _mateFirst = _connectorDataMap.get(childSel.value) ?? null
      _resetConnectorColors()
      _updateMateMoveInfo()
      _applyPreview()
    })
    parentSel.addEventListener('change', () => {
      const val = parentSel.value
      _mateSecond = val === '__world__' ? null : (_connectorDataMap.get(val) ?? undefined)
      _resetConnectorColors()
      _updateMateMoveInfo()
      _applyPreview()
    })
    invertCb.addEventListener('change', () => _applyPreview())
    previewCb.addEventListener('change', () => _applyPreview())

    createBtn.addEventListener('click', async () => {
      if (!_mateFirst) { alert('Select a child connector.'); return }
      if (_mateSecond === undefined) { alert('Select a parent connector.'); return }
      const type   = typeSel.value
      const invert = invertCb.checked
      let fixedAngleDeg = 0, minAngleDeg, maxAngleDeg
      if (type === 'rigid') {
        fixedAngleDeg = parseFloat(fieldsEl.querySelector('#_mate-fixed-angle')?.value ?? 0) || 0
      } else if (type === 'revolute') {
        minAngleDeg = parseFloat(fieldsEl.querySelector('#_mate-min-angle')?.value ?? -180)
        maxAngleDeg = parseFloat(fieldsEl.querySelector('#_mate-max-angle')?.value ?? 180)
      }
      const first = _mateFirst, second = _mateSecond
      exitMateDefineMode(true)  // keep preview visible until rebuild() settles it
      await _alignAndAddJoint(first, second, type, { invert, fixedAngleDeg, minAngleDeg, maxAngleDeg })
    })

    cancelBtn.addEventListener('click', () => exitMateDefineMode())

    return panel
  }

  function _syncDropdownsToState() {
    if (!_mateSidebarEl) return
    const childSel  = _mateSidebarEl.querySelector('#_mate-child-sel')
    const parentSel = _mateSidebarEl.querySelector('#_mate-parent-sel')
    if (childSel) {
      childSel.value = _mateFirst ? `${_mateFirst.instanceId}::${_mateFirst.label}` : ''
    }
    if (parentSel) {
      if (_mateSecond === undefined)    parentSel.value = ''
      else if (_mateSecond === null)    parentSel.value = '__world__'
      else parentSel.value = `${_mateSecond.instanceId}::${_mateSecond.label}`
    }
  }

  // ── Alignment math (pure — no side effects) ─────────────────────────────
  /**
   * Compute the rigid-body transform that aligns the two connectors.
   * Returns { instanceId, matrix, axisOrigin, axisDir } for the instance that moves,
   * or null if second is World/null, or if both instances are fixed.
   */
  function _computeAlignTransform(first, second, opts = {}) {
    if (!second) return null
    const { invert = false, fixedAngleDeg = 0, jointType = 'rigid' } = opts
    const assembly  = store.getState().currentAssembly
    const childInst  = assembly?.instances?.find(i => i.id === first.instanceId)
    const parentInst = assembly?.instances?.find(i => i.id === second.instanceId)
    if (!childInst || !parentInst) return null

    const childFixed  = childInst.fixed  ?? false
    const parentFixed = parentInst.fixed ?? false
    if (childFixed && parentFixed) return null

    function applyFixed(M, axVec, origin) {
      if (jointType !== 'rigid' || fixedAngleDeg === 0) return M
      const R = new THREE.Matrix4().makeRotationAxis(axVec, fixedAngleDeg * Math.PI / 180)
      const E = new THREE.Matrix4().makeTranslation(origin.x, origin.y, origin.z)
      E.multiply(R)
      E.multiply(new THREE.Matrix4().makeTranslation(-origin.x, -origin.y, -origin.z))
      return E.multiply(M)
    }

    if (!childFixed) {
      const M_old = new THREE.Matrix4().fromArray(childInst.transform.values).transpose()
      const n1 = new THREE.Vector3(...first.worldNorm).normalize()
      const n2 = new THREE.Vector3(...second.worldNorm)
      if (!invert) n2.negate()
      n2.normalize()
      const q  = new THREE.Quaternion().setFromUnitVectors(n1, n2)
      const p2 = new THREE.Vector3(...second.worldPos)
      const t  = p2.clone().sub(new THREE.Vector3(...first.worldPos).applyQuaternion(q))
      const dM = new THREE.Matrix4().makeRotationFromQuaternion(q)
      dM.setPosition(t)
      return {
        instanceId: first.instanceId,
        matrix:     applyFixed(dM.multiply(M_old), new THREE.Vector3(...second.worldNorm).normalize(), p2),
        axisOrigin: second.worldPos.slice(),
        axisDir:    second.worldNorm.slice(),
      }
    } else {
      const M_old = new THREE.Matrix4().fromArray(parentInst.transform.values).transpose()
      const n1 = new THREE.Vector3(...second.worldNorm).normalize()
      const n2 = new THREE.Vector3(...first.worldNorm)
      if (!invert) n2.negate()
      n2.normalize()
      const q  = new THREE.Quaternion().setFromUnitVectors(n1, n2)
      const p2 = new THREE.Vector3(...first.worldPos)
      const t  = p2.clone().sub(new THREE.Vector3(...second.worldPos).applyQuaternion(q))
      const dM = new THREE.Matrix4().makeRotationFromQuaternion(q)
      dM.setPosition(t)
      return {
        instanceId: second.instanceId,
        matrix:     applyFixed(dM.multiply(M_old), new THREE.Vector3(...first.worldNorm).normalize(), p2),
        axisOrigin: first.worldPos.slice(),
        axisDir:    first.worldNorm.slice(),
      }
    }
  }

  // ── Preview helpers ──────────────────────────────────────────────────────
  function _clearPreview() {
    if (_previewInstanceId && _onLivePreview) {
      const inst = store.getState().currentAssembly?.instances?.find(i => i.id === _previewInstanceId)
      if (inst) {
        _onLivePreview(_previewInstanceId,
          new THREE.Matrix4().fromArray(inst.transform.values).transpose())
      }
    }
    _previewInstanceId = null
  }

  // Describe which part moves vs stays, given the current child/parent picks +
  // their `fixed` flags. The child moves to the parent; if the child is pinned
  // the parent moves instead; if both are pinned, neither can. Mirrors the
  // decision in `_computeAlignTransform`.
  function _updateMateMoveInfo() {
    const el = _mateSidebarEl?.querySelector('#_mate-move-info')
    if (!el) return
    const asm = store.getState().currentAssembly
    const nameOf  = (id, fb) => asm?.instances?.find(i => i.id === id)?.name ?? fb ?? '?'
    const fixedOf = (id)     => asm?.instances?.find(i => i.id === id)?.fixed ?? false
    let text = 'Pick the connector on the part you want to MOVE.', color = '#6e7681'
    if (_mateFirst) {
      const childName = nameOf(_mateFirst.instanceId, _mateFirst.instanceLabel)
      if (_mateSecond === undefined) {
        text = `“${childName}” will move — now pick the connector it mates to.`; color = '#58a6ff'
      } else if (_mateSecond === null) {
        text = `“${childName}” will be anchored in place (mated to World).`; color = '#58a6ff'
      } else {
        const parentName = nameOf(_mateSecond.instanceId, _mateSecond.instanceLabel)
        const cFixed = fixedOf(_mateFirst.instanceId), pFixed = fixedOf(_mateSecond.instanceId)
        if (cFixed && pFixed) {
          text = `⚠ Both “${childName}” and “${parentName}” are pinned — neither can move.`; color = '#d29922'
        } else if (cFixed) {
          text = `“${parentName}” will MOVE  ·  “${childName}” stays fixed (pinned).`; color = '#3fb950'
        } else {
          text = `“${childName}” will MOVE  ·  “${parentName}” stays fixed.`; color = '#3fb950'
        }
      }
    }
    el.textContent = text
    el.style.color = color
  }

  function _applyPreview() {
    if (!_onLivePreview || !_mateSidebarEl) return
    if (!_mateSidebarEl.querySelector('#_mate-preview-cb')?.checked) { _clearPreview(); return }
    if (!_mateFirst || _mateSecond === undefined || _mateSecond === null) { _clearPreview(); return }

    const type           = _mateSidebarEl.querySelector('#_mate-type-sel')?.value ?? 'rigid'
    const invert         = _mateSidebarEl.querySelector('#_mate-invert-cb')?.checked ?? false
    const fixedAngleDeg  = type === 'rigid'
      ? (parseFloat(_mateSidebarEl.querySelector('#_mate-fixed-angle')?.value ?? 0) || 0) : 0

    const result = _computeAlignTransform(_mateFirst, _mateSecond, { invert, fixedAngleDeg, jointType: type })
    if (!result) { _clearPreview(); return }

    if (_previewInstanceId && _previewInstanceId !== result.instanceId) _clearPreview()
    _previewInstanceId = result.instanceId
    _onLivePreview(result.instanceId, result.matrix)
  }

  // ── Auto-align connector mate ────────────────────────────────────────────
  async function _alignAndAddJoint(first, second, jointType, opts = {}) {
    const { minAngleDeg, maxAngleDeg } = opts
    let axisOrigin = first.worldPos.slice()
    let axisDir    = first.worldNorm.slice()
    let movedId    = null
    let transform  = null

    // Alignment math stays on the frontend (it reads live world-space connector
    // frames already in the renderer).  The result drives the FK move; the
    // backend does connector registration + FK + joint atomically.
    if (second) {
      const result = _computeAlignTransform(first, second, { ...opts, jointType })
      if (result) {
        movedId    = result.instanceId
        transform  = { values: result.matrix.clone().transpose().toArray() }
        axisOrigin = result.axisOrigin
        axisDir    = result.axisDir
      } else {
        alert('Cannot auto-align: both parts are fixed.')
      }
    }

    const DEG = Math.PI / 180
    const _connSpec = (c) => c ? {
      instance_id:    c.instanceId,
      label:          c.label,
      position:       c.localPos  ?? [0, 0, 0],
      normal:         c.localNorm ?? [0, 0, 1],
      cluster_id:     c.clusterId ?? null,
      is_blunt_end:   !!(c.isBluntEnd   && c.localPos),
      is_bend_center: !!(c.isBendCenter && c.localPos),
    } : null

    // ONE round-trip: register blunt ends + propagate FK + add joint server-side.
    await api.createMate({
      child_connector:   _connSpec(first),
      parent_connector:  _connSpec(second),
      moved_instance_id: movedId,
      transform,
      name:              'Joint',
      joint_type:        jointType,
      axis_origin:       axisOrigin,
      axis_direction:    axisDir,
      min_limit:         minAngleDeg !== undefined ? minAngleDeg * DEG : null,
      max_limit:         maxAngleDeg !== undefined ? maxAngleDeg * DEG : null,
    })
  }

  // ── Pointer events — mate define mode ────────────────────────────────────
  function _onMatePointerDown(e) { _pointerDownAt = { x: e.clientX, y: e.clientY } }

  // Scratch vectors reused by per-frame visibility update — created once to
  // avoid allocations during pointer-move / camera-change firehoses.
  const _connV3   = new THREE.Vector3()
  const _connProj = new THREE.Vector3()

  // Last canvas-local cursor position (px); null when cursor outside canvas
  // or before the first pointermove. Used for the Gaussian proximity boost.
  let _mateCursorPx = null

  /**
   * Distance-based visibility for connector indicators in mate-define mode:
   *   • dist (camera→connector) > CONN_FADE_FAR_NM → invisible (group + hit-mesh
   *                                                   both hidden so they don't
   *                                                   clutter the scene OR catch
   *                                                   raycasts)
   *   • CONN_FADE_NEAR_NM..FAR fade-in           → opacity ramps 0 → CONN_TRANS_OPACITY
   *   • dist ≤ CONN_FADE_NEAR_NM                 → opacity = CONN_TRANS_OPACITY (translucent base)
   *
   * On top of the camera-distance base opacity, a Gaussian boost is added
   * based on the connector's SCREEN-SPACE distance to the cursor:
   *   • boost(d_px) = exp(-(d_px / sigma)^2), zeroed beyond CUTOFF.
   *   • final = base + (1 - base) * boost — so dead-on cursor → 1.0,
   *     cursor far → just the camera-distance base, mid-range → smooth ramp.
   *
   * Selected-as-first / selected-as-second connectors are pinned to 1.0 so
   * they stay obvious during the second-pick step. Raycast-hovered mesh
   * is also pinned in case the raster Gauss centre is slightly off the
   * mesh centre.
   *
   * Outside mate-define mode this is a no-op (the connector group is
   * already toggled off in exitMateDefineMode).
   *
   * @param {THREE.Mesh|null} hoveredMesh — the hit-mesh under the cursor right now (if any)
   */
  function _updateConnectorVisibility(hoveredMesh = null) {
    if (!_mateMode) return
    const camPos = camera.position
    const rect = canvas.getBoundingClientRect()
    const haveCursor = _mateCursorPx != null
    for (const mesh of _connectorMeshes) {
      const grp = mesh.parent
      if (!grp) continue
      grp.getWorldPosition(_connV3)
      const dist = camPos.distanceTo(_connV3)
      const isHovered = mesh === hoveredMesh
      const isSelected =
        (_mateFirst && mesh.userData.instanceId === _mateFirst.instanceId
                     && mesh.userData.label      === _mateFirst.label) ||
        (_mateSecond && _mateSecond !== null
                     && mesh.userData.instanceId === _mateSecond.instanceId
                     && mesh.userData.label      === _mateSecond.label)

      // Camera-distance base opacity (the "haze").
      let base
      if (dist <= CONN_FADE_NEAR_NM) {
        base = CONN_TRANS_OPACITY
      } else if (dist >= CONN_FADE_FAR_NM) {
        base = 0
      } else {
        const t = (dist - CONN_FADE_NEAR_NM) / (CONN_FADE_FAR_NM - CONN_FADE_NEAR_NM)
        base = CONN_TRANS_OPACITY * (1 - t)
      }

      // Gaussian screen-space proximity boost from the cursor.
      let boost = 0
      if (haveCursor) {
        _connProj.copy(_connV3).project(camera)
        const sx = ( _connProj.x * 0.5 + 0.5) * rect.width
        const sy = (-_connProj.y * 0.5 + 0.5) * rect.height
        // Only count proximity for connectors actually in front of the
        // camera (z within [-1, 1] after projection). Behind-camera
        // projections wrap and would spuriously highlight indicators
        // outside the visible frustum.
        if (_connProj.z > -1 && _connProj.z < 1) {
          const dpx = Math.hypot(sx - _mateCursorPx.x, sy - _mateCursorPx.y)
          if (dpx < CONN_HOVER_CUTOFF_PX) {
            const sigma = CONN_HOVER_SIGMA_PX
            boost = Math.exp(-(dpx * dpx) / (sigma * sigma))
          }
        }
      }

      let opacity
      if (isHovered || isSelected) {
        opacity = 1.0
      } else {
        opacity = base + (1 - base) * boost
      }

      const visible = opacity > 0.01
      grp.visible = visible
      mesh.visible = visible   // also gates raycasting (intersectObjects respects .visible)
      if (visible) {
        grp.traverse(o => {
          if (o.material && o.material.transparent) o.material.opacity = opacity
        })
      }
    }
  }

  // Camera-change listener so the fade follows zoom/pan without needing a
  // mouse move. Only does work while mate mode is active.
  function _onCameraChangeForConnectors() {
    if (_mateMode) _updateConnectorVisibility()
  }
  controls?.addEventListener?.('change', _onCameraChangeForConnectors)

  function _onMatePointerMove(e) {
    if (!_connectorMeshes.length) return
    // Update cursor position for the Gaussian proximity boost. Even when
    // no mesh is directly under the cursor, nearby connectors should rise
    // out of the haze.
    const rect = canvas.getBoundingClientRect()
    _mateCursorPx = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    // Refresh visibility BEFORE raycasting so a connector that just came
    // into range (camera or cursor) is pickable on this very same move
    // event (raycaster filters by .visible).
    _updateConnectorVisibility(null)
    _rc.setFromCamera(_ndc(e), camera)
    const hits    = _rc.intersectObjects(_connectorMeshes, false)
    const hovered = hits.length ? hits[0].object : null
    for (const mesh of _connectorMeshes) {
      const isFirst = _mateFirst &&
        mesh.userData.instanceId === _mateFirst.instanceId &&
        mesh.userData.label      === _mateFirst.label
      const isSecond = _mateSecond &&
        mesh.userData.instanceId === _mateSecond.instanceId &&
        mesh.userData.label      === _mateSecond.label
      const isBendCenter = mesh.userData.isBendCenter === true
      const restCol = isBendCenter ? CONN_BEND_CENTER_COL : CONN_COLOUR
      const baseCol = isFirst ? CONN_SEL_COL : isSecond ? CONN_PARENT_COL : restCol
      mesh.material.color.set(mesh === hovered ? CONN_HOV_COL : baseCol)
    }
    // Second pass with the hover target so the hovered indicator bumps to
    // full opacity / solid.
    _updateConnectorVisibility(hovered)

    // No hover preview: the part only previews its mated pose AFTER the user
    // commits the second connector (via click or the parent dropdown), handled
    // by _onMateClick / parentSel → _applyPreview.  Merely hovering candidates
    // must not move anything.
  }

  function _onMatePointerLeave() {
    // Cursor left the canvas — drop the Gaussian boost so the indicators
    // settle back to their camera-distance base opacity.
    _mateCursorPx = null
    if (_mateMode) _updateConnectorVisibility(null)
  }

  function _onMateClick(e) {
    if (_wasDrag(e)) return
    if (!_connectorMeshes.length) return
    _rc.setFromCamera(_ndc(e), camera)
    const hits = _rc.intersectObjects(_connectorMeshes, false)
    if (!hits.length) return

    const mesh = hits[0].object
    const { instanceId, label } = mesh.userData
    const conn = _connectorDataMap.get(`${instanceId}::${label}`)
    if (!conn) return

    if (!_mateFirst) {
      _mateFirst = conn
    } else if (_mateSecond === undefined) {
      if (instanceId === _mateFirst.instanceId && label === _mateFirst.label) return
      _mateSecond = conn
    } else {
      // Both set — restart with new child
      _mateFirst  = conn
      _mateSecond = undefined
    }
    _resetConnectorColors()
    _syncDropdownsToState()
    _updateMateMoveInfo()
    _applyPreview()
  }

  function _onMateKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); exitMateDefineMode() }
  }

  // ── Mate define mode: enter / exit ───────────────────────────────────────

  /**
   * Enter mate definition mode. Shows a sidebar panel for selecting connectors,
   * mate type, and options, then creates the joint on "Create Mate".
   * @param {function} onExit
   */
  function enterMateDefineMode(onExit = null, onLivePreview = null) {
    exitConnectorDefineMode()
    exitMateDefineMode()
    _mateMode          = true
    _mateOnExitCb      = onExit
    _onLivePreview     = onLivePreview
    _previewInstanceId = null
    _mateFirst         = null
    _mateSecond        = undefined

    // Populate blunt-end connectors before building the sidebar so they appear in dropdowns
    _syncBluntConnIndicators()
    _connectorGroup.visible = true
    // Initial pass — hides all connectors that aren't already near the
    // camera, so entering mate-mode on a large design doesn't flash all
    // indicators on screen at once.
    _updateConnectorVisibility()

    _mateSidebarEl = _buildMateSidebarPanel()
    // Inject below the mates list inside the assembly panel
    const matesSection = document.getElementById('_assembly-mates-section')
    if (matesSection) {
      matesSection.after(_mateSidebarEl)
    } else {
      const toolFilter = document.getElementById('tool-filter-section')
      if (toolFilter) toolFilter.after(_mateSidebarEl)
      else document.body.appendChild(_mateSidebarEl)
    }
    _updateMateMoveInfo()   // seed the "pick a connector to move" prompt

    canvas.style.cursor = 'crosshair'
    canvas.addEventListener('pointerdown',  _onMatePointerDown)
    canvas.addEventListener('pointermove',  _onMatePointerMove)
    canvas.addEventListener('pointerleave', _onMatePointerLeave)
    canvas.addEventListener('click',        _onMateClick)
    document.addEventListener('keydown',    _onMateKeyDown)
  }

  function exitMateDefineMode(skipPreviewClear = false) {
    if (!_mateMode) return
    if (!skipPreviewClear) _clearPreview()
    _onLivePreview = null
    _mateMode      = false
    _mateFirst     = null
    _mateSecond    = undefined
    // Restore connector indicator opacity / visibility to the default so
    // when mate-define is re-entered next time they don't start at the
    // last-faded opacity. (The group is hidden right below; this just
    // resets the per-mesh state inside it.)
    for (const m of _connectorMeshes) {
      const grp = m.parent
      if (!grp) continue
      grp.visible = true
      m.visible = true
      grp.traverse(o => { if (o.material) o.material.opacity = 1 })
    }
    _syncBluntConnIndicators()  // clears blunt indicators now that _mateMode is false
    _removeMateOverlays()
    _resetConnectorColors()
    // Back to normal view: keep the connector group itself visible but re-gate
    // its children to the selected instance (was: hide the whole group).
    _connectorGroup.visible = true
    _applyActiveVisibility()
    canvas.removeEventListener('pointerdown',  _onMatePointerDown)
    canvas.removeEventListener('pointermove',  _onMatePointerMove)
    canvas.removeEventListener('pointerleave', _onMatePointerLeave)
    canvas.removeEventListener('click',        _onMateClick)
    document.removeEventListener('keydown',    _onMateKeyDown)
    canvas.style.cursor = ''
    _mateCursorPx = null
    _pointerDownAt = null
    const cb = _mateOnExitCb
    _mateOnExitCb = null
    cb?.()
  }

  // ── Broken-mate detection ────────────────────────────────────────────────
  function _isBrokenMate(joint, instances) {
    if (!joint.connector_b_label) return false
    const instB = instances.find(i => i.id === joint.instance_b_id)
    if (instB && !instB.interface_points.some(ip => ip.label === joint.connector_b_label)) return true
    if (joint.connector_a_label && joint.instance_a_id) {
      const instA = instances.find(i => i.id === joint.instance_a_id)
      if (instA && !instA.interface_points.some(ip => ip.label === joint.connector_a_label)) return true
    }
    return false
  }

  // ── Phase 3e: shared InstancedMesh helpers ───────────────────────────────
  //
  // The shared-path stores three InstancedMesh objects (shaft, cone, ring),
  // each with count == numJoints. Per-joint transforms ride the standard
  // `instanceMatrix` (so Three's native InstancedMesh raycast picks correctly
  // without a custom raycaster). Per-joint coloring rides `instanceColor`:
  //   - broken mate → red (BROKEN_COLOUR) on shaft + cone + ring
  //   - selected joint's ring → green (ACTIVE_RING_COLOUR), shaft+cone stay
  //     orange (mirrors the "green ring on the active row" trick from the
  //     CONN_PARENT_COL = 0x3fb950 convention)
  //
  // The CONN_PARENT_COL = 0x3fb950 value referenced in the spec lives at the
  // top of this file; ACTIVE_RING_COLOUR mirrors it.
  //
  // `mesh.visible = true` is explicitly set after every count assignment per
  // the path_to_thousands "mesh.visible matters" lesson: Three doesn't
  // default visibility correctly on freshly resized InstancedMeshes touched
  // by buildHelixObjects' LOD path, and although these joint InstancedMeshes
  // are fresh allocations not LOD'd, we honor the rule defensively.
  const _SHARED_COLOR_ORANGE = new THREE.Color(COLOUR)
  const _SHARED_COLOR_BROKEN = new THREE.Color(BROKEN_COLOUR)
  const _SHARED_COLOR_ACTIVE = new THREE.Color(ACTIVE_RING_COLOUR)
  const _sharedScratchMat = new THREE.Matrix4()

  function _disposeSharedJointMeshes() {
    for (const mesh of [_sharedShaftMesh, _sharedConeMesh, _sharedRingMesh]) {
      if (!mesh) continue
      mesh.parent?.remove(mesh)
      // Geometry is module-level shared (userData.shared=true) → don't dispose.
      mesh.material?.dispose()
      // instanceMatrix/instanceColor are owned by the InstancedMesh; GC reclaims.
    }
    _sharedShaftMesh = null
    _sharedConeMesh  = null
    _sharedRingMesh  = null
    _sharedJointIds = []
    _sharedJointMatrices = []
    _sharedJointIdxById.clear()
    _sharedJointBroken.clear()
  }

  function _writeSharedRingColor(i, jointId) {
    if (!_sharedRingMesh) return
    const broken = _sharedJointBroken.get(jointId)
    const isActive = (jointId === _sharedActiveJointId)
    let c
    if (broken) c = _SHARED_COLOR_BROKEN
    else if (isActive) c = _SHARED_COLOR_ACTIVE
    else c = _SHARED_COLOR_ORANGE
    _sharedRingMesh.setColorAt(i, c)
  }

  function _writeSharedNonRingColors(i, jointId) {
    const broken = _sharedJointBroken.get(jointId)
    const c = broken ? _SHARED_COLOR_BROKEN : _SHARED_COLOR_ORANGE
    if (_sharedShaftMesh) _sharedShaftMesh.setColorAt(i, c)
    if (_sharedConeMesh)  _sharedConeMesh.setColorAt(i, c)
  }

  /** Build the three InstancedMesh objects sized for `numJoints` joints. */
  function _allocateSharedJointMeshes(numJoints) {
    _disposeSharedJointMeshes()
    if (numJoints <= 0) return

    function _mat() {
      return new THREE.MeshBasicMaterial({
        color: 0xffffff,                  // tinted per-instance via instanceColor
        depthTest: false, depthWrite: false, transparent: true,
      })
    }

    _sharedShaftMesh = new THREE.InstancedMesh(_JOINT_SHAFT_GEO, _mat(), numJoints)
    _sharedConeMesh  = new THREE.InstancedMesh(_JOINT_CONE_GEO,  _mat(), numJoints)
    _sharedRingMesh  = new THREE.InstancedMesh(_JOINT_RING_GEO,  _mat(), numJoints)

    for (const mesh of [_sharedShaftMesh, _sharedConeMesh, _sharedRingMesh]) {
      mesh.count = numJoints
      mesh.renderOrder = 1000
      mesh.frustumCulled = false   // baked offsets + per-joint matrices invalidate the source AABB
      mesh.userData.tag = 'assembly-mate-indicator-shared'
      // Allocate the InstancedBufferAttribute for per-instance color so
      // setColorAt is non-null below.
      mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(numJoints * 3), 3)
      // Per the mesh.visible lesson at path_to_thousands worktree gotchas:
      // every InstancedMesh whose count>0 must be explicitly set visible=true.
      mesh.visible = true
      _jointGroup.add(mesh)
    }

    // Ring is the picking target for the revolute drag — flag every instance
    // slot via userData so pickJointRing can filter (no per-instance userData
    // exists in Three.js, so we filter by mesh identity instead). Easier:
    // pickJointRing intersects only _sharedRingMesh; pickJointAny intersects
    // all three. The legacy `userData.isJointRing` per-mesh check is replaced
    // by mesh-identity comparison.
    _sharedRingMesh.userData.isSharedRingMesh = true
  }

  /** Re-upload per-instance attributes after population/edit. */
  function _flushSharedJointAttrs() {
    for (const mesh of [_sharedShaftMesh, _sharedConeMesh, _sharedRingMesh]) {
      if (!mesh) continue
      if (mesh.instanceMatrix) mesh.instanceMatrix.needsUpdate = true
      if (mesh.instanceColor)  mesh.instanceColor.needsUpdate = true
    }
  }

  /** Update the per-joint matrix at instance slot i across all three meshes. */
  function _writeSharedJointMatrix(i, matrix) {
    if (_sharedShaftMesh) _sharedShaftMesh.setMatrixAt(i, matrix)
    if (_sharedConeMesh)  _sharedConeMesh.setMatrixAt(i, matrix)
    if (_sharedRingMesh)  _sharedRingMesh.setMatrixAt(i, matrix)
  }

  /** Rebuild the shared-joint indicators from the assembly's joints array. */
  function _rebuildSharedJoints(joints, instances) {
    const N = joints.length
    _allocateSharedJointMeshes(N)
    if (N === 0) return

    _sharedJointIds        = new Array(N)
    _sharedJointMatrices   = new Array(N)
    _sharedJointIdxById.clear()
    _sharedJointBroken.clear()

    for (let i = 0; i < N; i++) {
      const joint = joints[i]
      const broken = _isBrokenMate(joint, instances)
      const mat = _jointInstanceMatrix(joint.axis_origin, joint.axis_direction)
      _writeSharedJointMatrix(i, mat)
      _sharedJointIds[i] = joint.id
      _sharedJointMatrices[i] = mat
      _sharedJointIdxById.set(joint.id, i)
      _sharedJointBroken.set(joint.id, broken)
      _writeSharedNonRingColors(i, joint.id)
      _writeSharedRingColor(i, joint.id)
    }
    _flushSharedJointAttrs()
  }

  // ── Public: rebuild ──────────────────────────────────────────────────────
  function rebuild(assembly) {
    // ── Joint indicators ─────────────────────────────────────────────────
    // Legacy per-joint Group path: dispose old groups before rebuild.
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        // Templates from the shared path tag geometry with userData.shared.
        // Skip those (the legacy _buildIndicator allocates fresh geometry per
        // call so this branch is a no-op today, but the guard mirrors the
        // assembly_renderer disposal convention).
        if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()
    _jointEndpoints.clear()

    const joints   = assembly?.joints   ?? []
    const instances = assembly?.instances ?? []
    if (_useSharedJoints) {
      _rebuildSharedJoints(joints, instances)
    } else {
      for (const joint of joints) {
        const broken = _isBrokenMate(joint, instances)
        const grp = _buildIndicator(joint.axis_origin, joint.axis_direction, broken)
        grp.userData.jointId = joint.id
        grp.traverse(o => { if (o.userData.isJointRing) o.userData.jointId = joint.id })
        _jointGroup.add(grp)
        _jointMeshes.set(joint.id, grp)
        _jointEndpoints.set(joint.id, [joint.instance_a_id ?? null, joint.instance_b_id ?? null])
      }
    }

    // ── Connector indicators ─────────────────────────────────────────────
    // Render at cluster-aware positions when the backend has supplied them
    // for this assembly state (matches DNA geometry + backend snap math +
    // mate-highlight markers). The non-cluster (T_inst @ p_local) path is
    // an immediate fallback for the first frame, then replaced as soon as
    // the async fetch returns. Without this the connector dots floated
    // several nm away from the actual DNA blunt ends whenever an IP's
    // cluster_id referenced a non-identity cluster (e.g. after a Relax
    // Bond), which propagated into mate creation: clicking the dots pre-
    // aligned in the wrong space and mate_relative_transform captured the
    // mismatch as a translation.
    _connectorGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _connectorGroup.clear()
    _connectorMeshes.length = 0
    _connectorDataMap.clear()

    const cachedFrames = _connectorFramesCache
    for (const inst of instances) {
      const mat4     = _instMat4(inst)
      const instName = inst.name ?? inst.id.slice(0, 6)
      const fetched  = cachedFrames?.[inst.id]
      for (const ip of (inst.interface_points ?? [])) {
        let wPos, wNrm
        const fr = fetched?.[ip.label]
        if (fr) {
          wPos = [fr.pos[0], fr.pos[1], fr.pos[2]]
          wNrm = [fr.normal[0], fr.normal[1], fr.normal[2]]
        } else {
          const pos  = new THREE.Vector3(ip.position.x, ip.position.y, ip.position.z).applyMatrix4(mat4)
          const norm = new THREE.Vector3(ip.normal.x, ip.normal.y, ip.normal.z).transformDirection(mat4).normalize()
          wPos = [pos.x, pos.y, pos.z]
          wNrm = [norm.x, norm.y, norm.z]
        }
        _connectorDataMap.set(`${inst.id}::${ip.label}`, {
          instanceId: inst.id, label: ip.label,
          worldPos: wPos, worldNorm: wNrm, instanceLabel: instName,
          clusterId: ip.cluster_id ?? null,
        })
        const { group, hitMesh } = _buildConnectorIndicator(wPos, wNrm)
        hitMesh.userData = { instanceId: inst.id, label: ip.label, worldPos: wPos, worldNorm: wNrm }
        _connectorGroup.add(group)
        _connectorMeshes.push(hitMesh)
      }
    }

    if (_mateMode) {
      _syncBluntConnIndicators()
      _resetConnectorColors()
    }

    // Kick off a fresh fetch of cluster-aware frames and re-render the
    // connector layer when it arrives. Cached for the next synchronous
    // rebuild (so subsequent rebuilds within the same assembly state render
    // correctly on the first frame).
    _refreshConnectorFrames(assembly)
    _applyActiveVisibility()
  }

  // ── Cluster-aware connector position cache ────────────────────────────
  let _connectorFramesCache = null
  let _connectorFramesReqId = 0
  function _refreshConnectorFrames(assembly) {
    if (!assembly?.instances?.length) {
      _connectorFramesCache = null
      return
    }
    const reqId = ++_connectorFramesReqId
    api.getAllConnectorFrames().then(frames => {
      // Drop stale responses if the user moved on to another rebuild.
      if (reqId !== _connectorFramesReqId) return
      _connectorFramesCache = frames ?? {}
      // Re-run the connector indicator pass with the cluster-aware frames
      // by re-invoking rebuild on the current assembly. The cache is now
      // populated so the second pass picks them up.
      const cur = store.getState().currentAssembly
      if (cur) _rebuildConnectorsOnly(cur)
    }).catch(err => {
      console.warn('[assembly_joint_renderer] connector-frames fetch failed:', err)
    })
  }

  function _rebuildConnectorsOnly(assembly) {
    // Mirror the connector-indicator block of rebuild() without touching
    // the joint indicators (which already render at the correct
    // axis_origin from the assembly state).
    _connectorGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _connectorGroup.clear()
    _connectorMeshes.length = 0
    _connectorDataMap.clear()
    const cachedFrames = _connectorFramesCache
    for (const inst of (assembly?.instances ?? [])) {
      const mat4     = _instMat4(inst)
      const instName = inst.name ?? inst.id.slice(0, 6)
      const fetched  = cachedFrames?.[inst.id]
      for (const ip of (inst.interface_points ?? [])) {
        let wPos, wNrm
        const fr = fetched?.[ip.label]
        if (fr) {
          wPos = [fr.pos[0], fr.pos[1], fr.pos[2]]
          wNrm = [fr.normal[0], fr.normal[1], fr.normal[2]]
        } else {
          const pos  = new THREE.Vector3(ip.position.x, ip.position.y, ip.position.z).applyMatrix4(mat4)
          const norm = new THREE.Vector3(ip.normal.x, ip.normal.y, ip.normal.z).transformDirection(mat4).normalize()
          wPos = [pos.x, pos.y, pos.z]
          wNrm = [norm.x, norm.y, norm.z]
        }
        _connectorDataMap.set(`${inst.id}::${ip.label}`, {
          instanceId: inst.id, label: ip.label,
          worldPos: wPos, worldNorm: wNrm, instanceLabel: instName,
          clusterId: ip.cluster_id ?? null,
        })
        const { group, hitMesh } = _buildConnectorIndicator(wPos, wNrm)
        hitMesh.userData = { instanceId: inst.id, label: ip.label, worldPos: wPos, worldNorm: wNrm }
        _connectorGroup.add(group)
        _connectorMeshes.push(hitMesh)
      }
    }
    if (_mateMode) { _syncBluntConnIndicators(); _resetConnectorColors() }
    _applyActiveVisibility()
  }

  // ── Public: pick ring ────────────────────────────────────────────────────
  function pickJointRing(e) {
    _rc.setFromCamera(_ndc(e), camera)
    if (_useSharedJoints) {
      if (!_sharedRingMesh || _sharedRingMesh.count === 0) return null
      const hits = _rc.intersectObject(_sharedRingMesh, false)
      if (!hits.length) return null
      const idx = hits[0].instanceId
      if (idx == null) return null
      return _sharedJointIds[idx] ?? null
    }
    if (!_jointMeshes.size) return null
    const rings = []
    for (const grp of _jointMeshes.values()) {
      if (!grp.visible) continue   // hidden (non-selected) joints aren't pickable
      grp.traverse(o => { if (o.userData.isJointRing) rings.push(o) })
    }
    if (!rings.length) return null
    const hits = _rc.intersectObjects(rings, false)
    return hits.length ? hits[0].object.userData.jointId : null
  }

  // ── Public: pick the entire indicator (shaft / cone / ring) ─────────────
  //
  // Used by the Polymerize panel: clicking the orange indicator anywhere
  // selects the mate.  pickJointRing stays ring-only so revolute drag isn't
  // hijacked by clicks on the arrow body.
  function pickJointAny(e) {
    _rc.setFromCamera(_ndc(e), camera)
    if (_useSharedJoints) {
      const meshes = [_sharedShaftMesh, _sharedConeMesh, _sharedRingMesh].filter(m => m && m.count > 0)
      if (!meshes.length) return null
      const hits = _rc.intersectObjects(meshes, false)
      if (!hits.length) return null
      const idx = hits[0].instanceId
      if (idx == null) return null
      return _sharedJointIds[idx] ?? null
    }
    if (!_jointMeshes.size) return null
    const targets = []
    for (const grp of _jointMeshes.values()) {
      if (!grp.visible) continue   // hidden (non-selected) joints aren't pickable
      grp.traverse(o => { if (o.isMesh) targets.push(o) })
    }
    if (!targets.length) return null
    const hits = _rc.intersectObjects(targets, false)
    if (!hits.length) return null
    let obj = hits[0].object
    while (obj) {
      for (const [jointId, grp] of _jointMeshes) {
        if (obj === grp) return jointId
      }
      obj = obj.parent
    }
    return null
  }

  // ── Ring drag ─────────────────────────────────────────────────────────────
  let _drag      = null
  let _sendTimer = null

  function _ringPlaneHit(e, axisDir, axisOrigin) {
    return _ringPlaneHitUtil(_rc, e, camera, canvas, axisDir, axisOrigin)
  }

  function _angleInRing(worldPt, axisOrigin, axisDir, refVec) {
    return _angleInRingUtil(worldPt, axisOrigin, axisDir, refVec)
  }

  function _sendDebounced(jointId, value) {
    clearTimeout(_sendTimer)
    _sendTimer = setTimeout(() => {
      api.patchAssemblyJoint(jointId, { current_value: value })
    }, 80)
  }

  function _onRingPointerMove(e) {
    if (!_drag) return
    const hit = _ringPlaneHit(e, _drag.axisDir, _drag.axisOrigin)
    if (!hit) return
    const angle    = _angleInRing(hit, _drag.axisOrigin, _drag.axisDir, _drag.refVec)
    const delta    = angle - _drag.startAngle
    const newValue = _drag.startValue + delta
    _drag.currentValue = newValue
    _sendDebounced(_drag.jointId, newValue)
  }

  function _onRingPointerUp() {
    if (!_drag) return
    clearTimeout(_sendTimer)
    const { jointId, currentValue } = _drag
    _drag = null
    controls.enabled = true
    canvas.removeEventListener('pointermove', _onRingPointerMove)
    canvas.removeEventListener('pointerup',   _onRingPointerUp)
    api.patchAssemblyJoint(jointId, { current_value: currentValue })
  }

  /**
   * Start dragging the rotation ring for a given joint.
   * Called from main.js pointerdown when pickJointRing() returns a hit.
   */
  function beginRingDrag(jointId, e) {
    const { currentAssembly } = store.getState()
    const joint = currentAssembly?.joints?.find(j => j.id === jointId)
    if (!joint) return

    const axisDir    = new THREE.Vector3(...joint.axis_direction).normalize()
    const axisOrigin = new THREE.Vector3(...joint.axis_origin)

    const hit = _ringPlaneHit(e, axisDir, axisOrigin)
    if (!hit) return

    const refVec     = makeRefVec(axisDir)
    const startAngle = _angleInRing(hit, axisOrigin, axisDir, refVec)

    _drag = { jointId, axisDir, axisOrigin, refVec, startAngle,
              startValue: joint.current_value, currentValue: joint.current_value }

    controls.enabled = false
    canvas.addEventListener('pointermove', _onRingPointerMove)
    canvas.addEventListener('pointerup',   _onRingPointerUp)
    canvas.setPointerCapture(e.pointerId)
    e.stopPropagation()
  }

  // ── Instance revolute drag (triggered from part mesh, not ring indicator) ──
  let _instDrag      = null
  let _instSendTimer = null

  function _onInstRevoluteMoveE(e) {
    if (!_instDrag) return
    const hit = _ringPlaneHit(e, _instDrag.axisDir, _instDrag.axisOrigin)
    if (!hit) return
    const angle    = _angleInRing(hit, _instDrag.axisOrigin, _instDrag.axisDir, _instDrag.refVec)
    const delta    = angle - _instDrag.startAngle
    const newValue = _instDrag.startValue + delta
    _instDrag.currentValue = newValue
    _instDrag.onLiveTransform?.(newValue)
    // Debounce backend current_value update
    clearTimeout(_instSendTimer)
    _instSendTimer = setTimeout(() => {
      api.patchAssemblyJoint(_instDrag.jointId, { current_value: newValue })
    }, 80)
  }

  function _onInstRevoluteUpE() {
    if (!_instDrag) return
    clearTimeout(_instSendTimer)
    const { jointId, currentValue, onCommit } = _instDrag
    _instDrag = null
    controls.enabled = true
    canvas.removeEventListener('pointermove', _onInstRevoluteMoveE)
    canvas.removeEventListener('pointerup',   _onInstRevoluteUpE)
    api.patchAssemblyJoint(jointId, { current_value: currentValue })
    onCommit?.()
  }

  /**
   * Start a revolute drag for an instance by clicking its mesh directly.
   * Same math as beginRingDrag but triggered without needing to hit the ring indicator.
   *
   * @param {Object}   joint       AssemblyJoint (revolute)
   * @param {Object}   childInst   PartInstance (instance_b)
   * @param {PointerEvent} e
   * @param {Function} onLiveTransform  (newAngleRad) => void  — caller updates renderer
   * @param {Function} onCommit         () => void  — called after final PATCH
   */
  function beginRevoluteDragForJoint(joint, childInst, e, onLiveTransform, onCommit) {
    const axisDir    = new THREE.Vector3(...joint.axis_direction).normalize()
    const axisOrigin = new THREE.Vector3(...joint.axis_origin)

    const hit = _ringPlaneHit(e, axisDir, axisOrigin)
    if (!hit) return

    const refVec     = makeRefVec(axisDir)
    const startAngle = _angleInRing(hit, axisOrigin, axisDir, refVec)
    const startValue = joint.current_value ?? 0

    _instDrag = {
      jointId: joint.id, axisDir, axisOrigin, refVec,
      startAngle, startValue, currentValue: startValue,
      onLiveTransform, onCommit,
    }

    controls.enabled = false
    canvas.addEventListener('pointermove', _onInstRevoluteMoveE)
    canvas.addEventListener('pointerup',   _onInstRevoluteUpE)
    canvas.setPointerCapture(e.pointerId)
    e.stopPropagation()
  }

  // ── Instance prismatic drag (triggered from part mesh, constrained to axis) ──
  let _instPrisDrag      = null
  let _instPrisSendTimer = null

  function _onInstPrismaticMoveE(e) {
    if (!_instPrisDrag) return
    const { axisDir, axisOrigin, startHit, startValue, onLiveTransform } = _instPrisDrag

    const rect = canvas.getBoundingClientRect()
    const ndc  = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    _rc.setFromCamera(ndc, camera)
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(axisDir, axisOrigin)
    const hit   = new THREE.Vector3()
    if (!_rc.ray.intersectPlane(plane, hit)) return

    const delta      = hit.clone().sub(startHit)
    const axisComp   = delta.dot(axisDir)
    const newValue   = startValue + axisComp
    _instPrisDrag.currentValue = newValue
    onLiveTransform?.(newValue)

    clearTimeout(_instPrisSendTimer)
    _instPrisSendTimer = setTimeout(() => {
      api.patchAssemblyJoint(_instPrisDrag.jointId, { current_value: newValue })
    }, 80)
  }

  function _onInstPrismaticUpE() {
    if (!_instPrisDrag) return
    clearTimeout(_instPrisSendTimer)
    const { jointId, currentValue, onCommit } = _instPrisDrag
    _instPrisDrag = null
    controls.enabled = true
    canvas.removeEventListener('pointermove', _onInstPrismaticMoveE)
    canvas.removeEventListener('pointerup',   _onInstPrismaticUpE)
    api.patchAssemblyJoint(jointId, { current_value: currentValue })
    onCommit?.()
  }

  /**
   * Start a prismatic drag for an instance by clicking its mesh directly.
   * Projects mouse movement onto the joint's axis direction.
   *
   * @param {Object}   joint           AssemblyJoint (prismatic)
   * @param {Object}   childInst       PartInstance (instance_b)
   * @param {PointerEvent} e
   * @param {Function} onLiveTransform (newDistance) => void
   * @param {Function} onCommit        () => void
   */
  function beginPrismaticDragForJoint(joint, childInst, e, onLiveTransform, onCommit) {
    const axisDir    = new THREE.Vector3(...joint.axis_direction).normalize()
    const axisOrigin = new THREE.Vector3(...joint.axis_origin)

    const rect = canvas.getBoundingClientRect()
    const ndc  = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    _rc.setFromCamera(ndc, camera)
    const plane   = new THREE.Plane().setFromNormalAndCoplanarPoint(axisDir, axisOrigin)
    const startHit = new THREE.Vector3()
    if (!_rc.ray.intersectPlane(plane, startHit)) return

    const startValue = joint.current_value ?? 0

    _instPrisDrag = {
      jointId: joint.id, axisDir, axisOrigin, startHit,
      startValue, currentValue: startValue,
      onLiveTransform, onCommit,
    }

    controls.enabled = false
    canvas.addEventListener('pointermove', _onInstPrismaticMoveE)
    canvas.addEventListener('pointerup',   _onInstPrismaticUpE)
    canvas.setPointerCapture(e.pointerId)
    e.stopPropagation()
  }

  // ── Visibility + dispose ──────────────────────────────────────────────────
  function setLiveJointTransform(instanceId, newMatrix4, assembly) {
    if (!assembly) return
    const parentInst = assembly.instances?.find(i => i.id === instanceId)
    if (!parentInst?.transform?.values) return
    const committedMat = new THREE.Matrix4().fromArray(parentInst.transform.values).transpose()
    const delta = newMatrix4.clone().multiply(committedMat.clone().invert())

    if (_useSharedJoints) {
      // Update only the per-joint instance rows touched by this drag.
      let anyChanged = false
      for (const joint of assembly.joints ?? []) {
        if (joint.instance_a_id !== instanceId) continue
        const idx = _sharedJointIdxById.get(joint.id)
        if (idx == null) continue
        const origin = new THREE.Vector3(...joint.axis_origin).applyMatrix4(delta).toArray()
        const dirVec = new THREE.Vector3(...joint.axis_direction).transformDirection(delta).normalize()
        const mat = _jointInstanceMatrix(origin, [dirVec.x, dirVec.y, dirVec.z], _sharedScratchMat)
        // Persist into the parallel JS array (so picking after live-drag uses
        // the updated pose) and into the per-mesh instanceMatrix attributes.
        _sharedJointMatrices[idx] = mat.clone()
        _writeSharedJointMatrix(idx, mat)
        anyChanged = true
      }
      if (anyChanged) {
        for (const mesh of [_sharedShaftMesh, _sharedConeMesh, _sharedRingMesh]) {
          if (mesh?.instanceMatrix) mesh.instanceMatrix.needsUpdate = true
        }
      }
      return
    }

    for (const joint of assembly.joints ?? []) {
      if (joint.instance_a_id !== instanceId) continue
      const grp = _jointMeshes.get(joint.id)
      if (!grp) continue
      const origin = new THREE.Vector3(...joint.axis_origin).applyMatrix4(delta)
      const dir = new THREE.Vector3(...joint.axis_direction).transformDirection(delta).normalize()
      const { q, ax } = _orientQ([dir.x, dir.y, dir.z])
      grp.position.copy(origin).addScaledVector(ax, HALF_LEN)
      grp.quaternion.copy(q)
    }
  }

  /**
   * Show per-instance joint + connector indicators ONLY for the selected
   * instance; hide all others (none if nothing is selected). A joint shows
   * when the active instance is one of its endpoints. This is the scale fix:
   * the indicator overlay is ~15 non-instanced draw calls PER part, so always
   * drawing every part's indicators dominates the frame at N≥50 (LOD bench).
   *
   * Exemptions: mate-define mode manages connector visibility itself (it shows
   * + distance-fades ALL connectors for cross-part picking), so we skip
   * connectors while `_mateMode`. The shared-InstancedMesh joint path
   * (`_useSharedJoints`, ~3 draws total) isn't gated — it isn't the bottleneck.
   */
  function _applyActiveVisibility() {
    const active = _activeInstanceId
    if (!_useSharedJoints) {
      for (const [jointId, grp] of _jointMeshes) {
        const ep = _jointEndpoints.get(jointId)
        grp.visible = !!active && !!ep && (ep[0] === active || ep[1] === active)
      }
    }
    if (!_mateMode) {
      for (const mesh of _connectorMeshes) {
        const grp = mesh.parent
        if (grp) grp.visible = !!active && mesh.userData?.instanceId === active
      }
    }
  }

  /** Set the selected part instance and re-apply indicator visibility. */
  function setActiveInstance(instanceId) {
    _activeInstanceId = instanceId ?? null
    _applyActiveVisibility()
  }

  function setVisible(on) {
    _jointGroup.visible     = on
    _connectorGroup.visible = on
    _bluntConnGroup.visible = on && _mateMode
    if (on) _applyActiveVisibility()
  }

  function dispose() {
    exitConnectorDefineMode()
    exitMateDefineMode()
    clearTimeout(_sendTimer)
    clearTimeout(_instSendTimer)
    clearTimeout(_instPrisSendTimer)
    controls?.removeEventListener?.('change', _onCameraChangeForConnectors)
    canvas.removeEventListener('pointermove', _onRingPointerMove)
    canvas.removeEventListener('pointerup',   _onRingPointerUp)
    canvas.removeEventListener('pointermove', _onInstRevoluteMoveE)
    canvas.removeEventListener('pointerup',   _onInstRevoluteUpE)
    canvas.removeEventListener('pointermove', _onInstPrismaticMoveE)
    canvas.removeEventListener('pointerup',   _onInstPrismaticUpE)
    _previewMesh.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _previewMesh.parent?.remove(_previewMesh)
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()
    _disposeSharedJointMeshes()
    _connectorGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _connectorGroup.clear()
    _connectorMeshes.length = 0
    _bluntConnGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _bluntConnGroup.clear()
    _bluntConnMeshes = []
    _jointGroup.parent?.remove(_jointGroup)
    _connectorGroup.parent?.remove(_connectorGroup)
    _bluntConnGroup.parent?.remove(_bluntConnGroup)
    _mateHighlightGroup.parent?.remove(_mateHighlightGroup)
  }

  // ── Selected-mate connector highlights ────────────────────────────────────
  // When the user clicks a mate row in the sidebar, the assembly panel
  // fetches the cluster-aware world positions of both connectors and asks
  // us to draw a big highlight marker at each. The two markers use
  // contrasting colours so it's obvious which connector belongs to
  // instance_a (blue) vs. instance_b (green). Useful for debugging cases
  // where the joint indicator's axis_origin disagrees with where the
  // connectors physically are.
  const _mateHighlightGroup = new THREE.Group()
  scene.add(_mateHighlightGroup)

  function _disposeHighlightGroup() {
    _mateHighlightGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _mateHighlightGroup.clear()
  }

  function _buildHighlightMarker(pos, normal, color) {
    const grp = new THREE.Group()
    grp.position.set(pos[0], pos[1], pos[2])
    const mat = () => new THREE.MeshBasicMaterial({
      color, depthTest: false, depthWrite: false, transparent: true, opacity: 0.85,
    })
    // Pulsing-sized sphere at the connector origin.
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.7, 16, 12), mat())
    sphere.renderOrder = 10000
    grp.add(sphere)
    // A second, larger translucent halo so the marker is unmissable.
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(1.3, 16, 12),
      new THREE.MeshBasicMaterial({
        color, depthTest: false, depthWrite: false, transparent: true, opacity: 0.18,
      }),
    )
    halo.renderOrder = 9998
    grp.add(halo)
    // Arrow along the normal so orientation drift is visible too.
    if (normal && (Math.abs(normal[0]) + Math.abs(normal[1]) + Math.abs(normal[2])) > 1e-6) {
      const dir = new THREE.Vector3(normal[0], normal[1], normal[2]).normalize()
      const { q } = _orientQ([dir.x, dir.y, dir.z])
      const arrowGrp = new THREE.Group()
      arrowGrp.quaternion.copy(q)
      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(0.10, 0.10, 1.8, 8), mat(),
      )
      shaft.position.y = 0.9
      shaft.renderOrder = 10000
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 8), mat())
      cone.position.y = 1.8 + 0.3
      cone.renderOrder = 10000
      arrowGrp.add(shaft, cone)
      grp.add(arrowGrp)
    }
    return grp
  }

  /** Show a highlight pair at the given connector frames; pass null to clear. */
  function showMateConnectorHighlights(frames) {
    _disposeHighlightGroup()
    if (!frames) return
    if (frames.a) _mateHighlightGroup.add(_buildHighlightMarker(frames.a.pos, frames.a.normal, CONN_SEL_COL))
    if (frames.b) _mateHighlightGroup.add(_buildHighlightMarker(frames.b.pos, frames.b.normal, CONN_PARENT_COL))
  }

  function clearMateConnectorHighlights() {
    _disposeHighlightGroup()
  }

  // ── Debug markers: multi-position connector inspection ───────────────────
  // Renders SIDE-BY-SIDE markers for each candidate connector position
  // computation so the user can visually identify which interpretation
  // matches the actual DNA blunt end. Marker colour conventions:
  //   • WHITE = T_inst @ ip.position (what every code path uses today;
  //             this is where the small connector dot also sits).
  //   • RED   = T_inst @ Ct @ ip.position (double-cluster — what cluster-
  //             aware code would compute; included so the user can see
  //             how far off it would be).
  //   • YELLOW (axis_origin) = the joint's stored axis_origin (where the
  //             orange icon renders). On a healthy mate this coincides
  //             with both A and B's T_inst_only.
  // Each marker is a small sphere (smaller than the main highlight) so
  // multiple can be distinguished when they cluster near the same point.
  function _buildDebugMarker(pos, color, radius = 0.45, opacity = 0.9) {
    const grp = new THREE.Group()
    grp.position.set(pos[0], pos[1], pos[2])
    const mat = new THREE.MeshBasicMaterial({
      color, depthTest: false, depthWrite: false, transparent: true, opacity,
    })
    const s = new THREE.Mesh(new THREE.SphereGeometry(radius, 12, 8), mat)
    s.renderOrder = 10001
    grp.add(s)
    return grp
  }

  function showMateDebugMarkers(debugFrames) {
    _disposeHighlightGroup()
    if (!debugFrames) return
    const COL_TINST    = 0xffffff  // white — what everything uses today
    const COL_TINST_CT = 0xff4444  // red   — double-cluster (the wrong path)
    const COL_AO       = 0xffd700  // gold  — axis_origin
    for (const side of ['a', 'b']) {
      const s = debugFrames[side]
      if (!s || s.missing) continue
      if (s.T_inst_only) _mateHighlightGroup.add(_buildDebugMarker(s.T_inst_only, COL_TINST, 0.55, 0.95))
      if (s.T_inst_and_Ct) _mateHighlightGroup.add(_buildDebugMarker(s.T_inst_and_Ct, COL_TINST_CT, 0.45, 0.85))
    }
    if (debugFrames.axis_origin) {
      _mateHighlightGroup.add(_buildDebugMarker(debugFrames.axis_origin, COL_AO, 0.35, 0.95))
    }
  }

  // ── Phase 3e follow-up: public setters for shared-path selection/broken ──
  //
  // The shared-path joint indicators carry per-instance color via
  // `instanceColor` (allocated in _allocateSharedJointMeshes). The private
  // helpers `_writeSharedRingColor` and `_writeSharedNonRingColors` read
  // `_sharedActiveJointId` + `_sharedJointBroken` and write the right tint
  // (green for active ring, red for broken shaft/cone/ring, orange default).
  // _rebuildSharedJoints calls them at build time. These two public setters
  // expose the same wiring to runtime updates.
  //
  // On the legacy per-instance path the broken-mate red is baked into the
  // material at _buildIndicator time, and there is no analogous "active joint"
  // highlight today (the green ring was added with the shared path). So both
  // setters are no-ops when _useSharedJoints === false — callers can fire them
  // unconditionally without per-path branching, and the per-instance rebuild
  // will continue to drive broken-mate color via _isBrokenMate as before.

  /**
   * Mark a joint as the active (selected) one. The ring of the matching
   * instance slot tints green (ACTIVE_RING_COLOUR); the previously-active
   * joint's ring (if any) reverts to its default color. Pass null/undefined
   * to clear the active state entirely.
   * No-op on the legacy per-instance path.
   */
  function setActiveJoint(jointId) {
    if (!_useSharedJoints) return
    const prev = _sharedActiveJointId
    const next = (jointId == null) ? null : jointId
    if (prev === next) return
    _sharedActiveJointId = next
    // Rewrite ring color for the joint(s) whose active-state changed.
    // _writeSharedRingColor reads _sharedActiveJointId so we just rewrite
    // the affected slots.
    if (prev != null) {
      const iPrev = _sharedJointIdxById.get(prev)
      if (iPrev !== undefined) _writeSharedRingColor(iPrev, prev)
    }
    if (next != null) {
      const iNext = _sharedJointIdxById.get(next)
      if (iNext !== undefined) _writeSharedRingColor(iNext, next)
    }
    if (_sharedRingMesh?.instanceColor) {
      _sharedRingMesh.instanceColor.needsUpdate = true
    }
  }

  /**
   * Toggle the broken-mate red tint on a joint's shaft/cone/ring. When the
   * joint is also the active one, the ring still wins at red (broken takes
   * priority over active in _writeSharedRingColor) — matching the legacy
   * per-instance _buildIndicator(broken=true) behavior where the entire
   * indicator was red.
   * No-op on the legacy per-instance path or when jointId is unknown.
   */
  function setMateBroken(jointId, broken) {
    if (!_useSharedJoints) return
    if (jointId == null) return
    const i = _sharedJointIdxById.get(jointId)
    if (i === undefined) return
    const flag = !!broken
    if (_sharedJointBroken.get(jointId) === flag) return
    _sharedJointBroken.set(jointId, flag)
    _writeSharedNonRingColors(i, jointId)
    _writeSharedRingColor(i, jointId)
    if (_sharedShaftMesh?.instanceColor) _sharedShaftMesh.instanceColor.needsUpdate = true
    if (_sharedConeMesh?.instanceColor)  _sharedConeMesh.instanceColor.needsUpdate  = true
    if (_sharedRingMesh?.instanceColor)  _sharedRingMesh.instanceColor.needsUpdate  = true
  }

  return {
    rebuild,
    enterConnectorDefineMode,
    exitConnectorDefineMode,
    enterMateDefineMode,
    exitMateDefineMode,
    isMateMode: () => _mateMode,
    pickJointRing,
    pickJointAny,
    beginRingDrag,
    beginRevoluteDragForJoint,
    beginPrismaticDragForJoint,
    setLiveJointTransform,
    setVisible,
    setActiveInstance,
    dispose,
    showMateConnectorHighlights,
    clearMateConnectorHighlights,
    showMateDebugMarkers,
    setActiveJoint,
    setMateBroken,
    /** Update blunt-end connector candidates shown in mate-define mode. */
    setExtraConnectors(data) {
      _extraConnectors = data ?? []
      _syncBluntConnIndicators()
    },
  }
}
