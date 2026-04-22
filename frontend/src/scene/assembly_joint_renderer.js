/**
 * Assembly Joint Renderer — orange shaft + rotation ring indicators for
 * AssemblyJoint objects, ring-drag to drive current_value, and hull-prism
 * based joint-axis definition (same geometry and interaction as cluster joints).
 *
 * Public API:
 *   initAssemblyJointRenderer(scene, camera, canvas, store, api, controls)
 *   → { rebuild(assembly),
 *        enterDefineMode(instanceAId, instanceBId, onExit),
 *        exitDefineMode(),
 *        pickJointRing(e),
 *        beginRingDrag(jointId, e),
 *        setVisible(bool),
 *        dispose() }
 *
 * enterDefineMode shows a semi-transparent hull prism around the child instance
 * (same lattice exterior-panel geometry as cluster joints).  Hovering over a
 * face shows a ghost arrow preview; clicking places the joint at that face with
 * the face normal as axis direction.
 */

import * as THREE from 'three'
import {
  buildBundleGeometry,
  buildPrismGeometry,
  buildPanelSurface,
  buildJointPreviewMesh,
  buildGridLines,
  buildJointHoverLines,
  SURFACE_COLOUR, SURFACE_OPACITY,
  CROSS_MARGIN, AXIAL_MARGIN,
  PREV_HALF_LEN,
  MIN_HC_FACES, MIN_SQ_FACES,
  GRID_PERIOD_HC, GRID_PERIOD_SQ,
  HOVER_RADIUS, HOVER_R, HOVER_G, HOVER_B,
} from './joint_renderer.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

// ── Geometry constants (same scale as joint_renderer.js) ──────────────────────
const SHAFT_R   = 0.13   // nm — shaft radius
const HALF_LEN  = 0.9    // nm — shaft half-length
const TIP_R     = 0.30   // nm — arrowhead radius
const TIP_H     = 0.72   // nm — arrowhead height
const RING_R    = 1.18   // nm — rotation ring radius
const RING_TUBE = 0.08   // nm — ring tube radius
const RING_SEGS = 48
const COLOUR    = 0xff8c00   // orange (same as cluster joint indicator)

const DRAG_THRESHOLD_PX = 6

const _Y = new THREE.Vector3(0, 1, 0)
const _Z = new THREE.Vector3(0, 0, 1)

// ── Module-level helpers (no Three.js state) ──────────────────────────────────

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

/** Build orange shaft + arrowhead + rotation ring group at world origin. */
function _buildIndicator(origin, direction) {
  const { q, ax } = _orientQ(direction)
  const group = new THREE.Group()

  const mat = new THREE.MeshBasicMaterial({
    color: COLOUR, depthTest: false, depthWrite: false, transparent: true,
  })

  // Shaft
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, HALF_LEN * 2, 8), mat.clone(),
  )
  shaft.renderOrder = 9999
  group.add(shaft)

  // Arrowhead at +Y tip
  const cone = new THREE.Mesh(new THREE.ConeGeometry(TIP_R, TIP_H, 8), mat.clone())
  cone.position.y = HALF_LEN + TIP_H * 0.5
  cone.renderOrder = 9999
  group.add(cone)

  // Rotation ring — perpendicular to shaft, at the shaft base (origin end)
  const ringMat = new THREE.MeshBasicMaterial({
    color: COLOUR, depthTest: false, depthWrite: false, transparent: true,
  })
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(RING_R, RING_TUBE, 8, RING_SEGS), ringMat,
  )
  ring.rotation.x          = -Math.PI / 2   // flat in shaft's local XZ plane
  ring.position.y          = -HALF_LEN      // at shaft base / axis_origin end
  ring.renderOrder         = 9999
  ring.userData.isJointRing = true
  group.add(ring)

  // Orient so local +Y = direction; place shaft so its base sits at axis_origin.
  group.quaternion.copy(q)
  group.position.copy(new THREE.Vector3(...origin)).addScaledVector(ax, HALF_LEN)
  group.renderOrder = 1000
  return group
}

// ── Main export ───────────────────────────────────────────────────────────────

export function initAssemblyJointRenderer(scene, camera, canvas, store, api, controls) {
  const _jointGroup  = new THREE.Group()
  const _jointMeshes = new Map()   // jointId → THREE.Group
  const _rc          = new THREE.Raycaster()
  scene.add(_jointGroup)

  // ── Preview mesh (ghost arrow during define mode) ─────────────────────────
  const _previewMesh = buildJointPreviewMesh()
  scene.add(_previewMesh)

  // ── Define mode state ─────────────────────────────────────────────────────
  let _definingInstanceA  = null
  let _definingInstanceB  = null
  let _onExitCb           = null
  let _surfaceMesh        = null   // hull fill
  let _surfaceWire        = null   // wireframe overlay
  let _surfaceGrid        = null   // periodic bp rings
  let _surfaceHover       = null   // per-bp hover rings (vertex-coloured)
  let _hullMesh           = null   // silent gap-filler hull
  let _hullWire           = null
  let _bundleInfo         = null   // { bundleDir, axialMid, ringYs, vertsPerRing }
  let _pointerDownAt      = null
  let _hoverRafId         = null

  // ── NDC helper ───────────────────────────────────────────────────────────────
  function _ndc(e) {
    const r = canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - r.left) / r.width)  * 2 - 1,
      -((e.clientY - r.top)  / r.height) * 2 + 1,
    )
  }

  // ── Build world-space axes dict from API response + instance transform ───────
  function _worldAxes(helixAxesArray, mat4) {
    const dict = {}
    for (const ax of helixAxesArray) {
      const s = new THREE.Vector3(...ax.start).applyMatrix4(mat4)
      const e = new THREE.Vector3(...ax.end).applyMatrix4(mat4)
      dict[ax.helix_id] = { start: [s.x, s.y, s.z], end: [e.x, e.y, e.z] }
    }
    return dict
  }

  function _worldBackbone(nucleotides, mat4) {
    return nucleotides.map(nuc => {
      const p = new THREE.Vector3(...nuc.backbone_position).applyMatrix4(mat4)
      return { helix_id: nuc.helix_id, backbone_position: [p.x, p.y, p.z] }
    })
  }

  // ── Instance transform → THREE.Matrix4 ───────────────────────────────────────
  function _instMat4(inst) {
    const m = new THREE.Matrix4()
    if (inst?.transform?.values) m.fromArray(inst.transform.values).transpose()
    return m
  }

  // ── Hull surface lifecycle ────────────────────────────────────────────────────

  function _removeSurface() {
    if (_hoverRafId !== null) { cancelAnimationFrame(_hoverRafId); _hoverRafId = null }
    for (const obj of [_surfaceMesh, _surfaceWire, _surfaceGrid, _surfaceHover, _hullMesh, _hullWire]) {
      if (obj) { obj.geometry?.dispose(); obj.material?.dispose(); obj.parent?.remove(obj) }
    }
    _surfaceMesh = _surfaceWire = _surfaceGrid = _surfaceHover = null
    _hullMesh = _hullWire = null
    _bundleInfo = null
  }

  async function _showInstanceSurface(instanceId) {
    _removeSurface()

    const { currentAssembly } = store.getState()
    const inst = currentAssembly?.instances?.find(i => i.id === instanceId)
    if (!inst) return

    // Fetch geometry (local frame)
    let geoData
    try {
      const batch = await api.getAssemblyGeometry()
      const entry = batch?.instances?.[instanceId]
      if (!entry || entry.error) {
        // fallback to per-instance endpoint
        geoData = await api.getInstanceGeometry(instanceId)
        geoData.design = (await api.getInstanceDesign(instanceId))?.design ?? null
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

    // Transform axes + backbone to world space
    const mat4        = _instMat4(inst)
    const worldAxDict = _worldAxes(helixAxesArray, mat4)
    const worldBack   = _worldBackbone(nucleotides, mat4)

    // Pseudo-cluster with all helix IDs
    const pseudoCluster = { helix_ids: Object.keys(worldAxDict) }
    const N = latticeType?.toUpperCase() === 'SQUARE' ? MIN_SQ_FACES : MIN_HC_FACES

    const bg = buildBundleGeometry(pseudoCluster, worldAxDict, worldBack, N,
                                   CROSS_MARGIN, AXIAL_MARGIN, latticeType)
    if (!bg) return

    // Primary mesh (exterior panels if available, else prism fallback)
    const geo = bg.panels
      ? buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
      : buildPrismGeometry(bg.corners, bg.halfLen)

    const mat = new THREE.MeshBasicMaterial({
      color: SURFACE_COLOUR, transparent: true, opacity: SURFACE_OPACITY,
      side: THREE.DoubleSide, depthTest: true, depthWrite: false,
    })
    _surfaceMesh = new THREE.Mesh(geo, mat)
    _surfaceMesh.quaternion.copy(bg.rotQ)
    _surfaceMesh.position.copy(bg.bundleMid)
    _surfaceMesh.renderOrder = 100

    const wireGeo = new THREE.WireframeGeometry(geo)
    const wireMat = new THREE.LineBasicMaterial({
      color: SURFACE_COLOUR, transparent: true,
      opacity: Math.min(1, SURFACE_OPACITY * 3),
      depthTest: false, depthWrite: false,
    })
    _surfaceWire = new THREE.LineSegments(wireGeo, wireMat)
    _surfaceWire.quaternion.copy(bg.rotQ)
    _surfaceWire.position.copy(bg.bundleMid)
    _surfaceWire.renderOrder = 101

    // Periodic grid rings
    const periodBp = latticeType?.toUpperCase() === 'SQUARE' ? GRID_PERIOD_SQ : GRID_PERIOD_HC
    _surfaceGrid = buildGridLines(bg, periodBp, BDNA_RISE_PER_BP)

    // Per-bp hover rings
    const hoverResult = buildJointHoverLines(bg, BDNA_RISE_PER_BP)
    _surfaceHover = hoverResult.lines

    // Convex hull as silent gap-filler
    const hullGeo = buildPrismGeometry(bg.corners, bg.halfLen)
    const hullMat = new THREE.MeshBasicMaterial({
      color: SURFACE_COLOUR, transparent: true, opacity: 0,
      side: THREE.DoubleSide, depthTest: true, depthWrite: false,
    })
    _hullMesh = new THREE.Mesh(hullGeo, hullMat)
    _hullMesh.quaternion.copy(bg.rotQ)
    _hullMesh.position.copy(bg.bundleMid)
    _hullMesh.renderOrder = 100

    const hullWireGeo = new THREE.WireframeGeometry(hullGeo)
    const hullWireMat = new THREE.LineBasicMaterial({
      color: SURFACE_COLOUR, transparent: true, opacity: 0,
      depthTest: false, depthWrite: false,
    })
    _hullWire = new THREE.LineSegments(hullWireGeo, hullWireMat)
    _hullWire.quaternion.copy(bg.rotQ)
    _hullWire.position.copy(bg.bundleMid)
    _hullWire.renderOrder = 101

    scene.add(_surfaceMesh, _surfaceWire)
    if (_surfaceGrid) scene.add(_surfaceGrid)
    scene.add(_surfaceHover)
    scene.add(_hullMesh, _hullWire)

    _bundleInfo = {
      bundleDir:    bg.bundleDir,
      axialMid:     bg.axialMid,
      ringYs:       hoverResult.ringYs,
      vertsPerRing: hoverResult.vertsPerRing,
    }
  }

  // ── Hover grid ────────────────────────────────────────────────────────────────

  function _updateHoverGrid(hitPoint) {
    if (!_bundleInfo || !_surfaceHover) return
    const { bundleDir, axialMid, ringYs, vertsPerRing } = _bundleInfo
    const localYHit = hitPoint.dot(bundleDir) - axialMid
    const colAttr   = _surfaceHover.geometry.attributes.color
    const col       = colAttr.array
    let   vi        = 0
    for (let ri = 0; ri < ringYs.length; ri++) {
      const dist = Math.abs(ringYs[ri] - localYHit)
      const fade = Math.max(0, 1 - dist / HOVER_RADIUS)
      const r = HOVER_R * fade, g = HOVER_G * fade, b = HOVER_B * fade
      for (let k = 0; k < vertsPerRing; k++, vi++) {
        col[vi * 3] = r; col[vi * 3 + 1] = g; col[vi * 3 + 2] = b
      }
    }
    colAttr.needsUpdate = true
    _surfaceHover.visible = true
  }

  function _clearHoverGrid() {
    if (_hoverRafId !== null) { cancelAnimationFrame(_hoverRafId); _hoverRafId = null }
    if (_surfaceHover) _surfaceHover.visible = false
  }

  // ── Face hit detection (same priority chain as joint_renderer.js) ─────────────

  function _getFaceHit(e) {
    _rc.setFromCamera(_ndc(e), camera)

    function _resolveHit(hit) {
      const nm = new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)
      const worldNormal = hit.face.normal.clone().applyMatrix3(nm).normalize()
      const toCamera = new THREE.Vector3().subVectors(camera.position, hit.point)
      if (worldNormal.dot(toCamera) < 0) worldNormal.negate()
      return { point: hit.point, normal: worldNormal }
    }

    // Primary mesh (exterior panels): highest fidelity
    const primTargets = [_surfaceMesh].filter(Boolean)
    if (primTargets.length) {
      const hits = _rc.intersectObjects(primTargets)
      if (hits.length && hits[0].face) return _resolveHit(hits[0])
    }

    // Hull mesh: silent gap-filler so there are no "holes" between panels
    if (_hullMesh) {
      const hits = _rc.intersectObject(_hullMesh)
      if (hits.length && hits[0].face) return _resolveHit(hits[0])
    }

    return null
  }

  // ── Pointer events during define mode ────────────────────────────────────────

  function _onPointerDown(e) { _pointerDownAt = { x: e.clientX, y: e.clientY } }

  function _wasDrag(e) {
    if (!_pointerDownAt) return false
    const dx = e.clientX - _pointerDownAt.x, dy = e.clientY - _pointerDownAt.y
    return (dx * dx + dy * dy) > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX
  }

  function _onSurfaceMove(e) {
    const hit = _getFaceHit(e)
    if (!hit) {
      _previewMesh.visible = false
      _clearHoverGrid()
      return
    }
    const { q } = _orientQ([hit.normal.x, hit.normal.y, hit.normal.z])
    _previewMesh.quaternion.copy(q)
    _previewMesh.position.copy(hit.point).addScaledVector(hit.normal, PREV_HALF_LEN)
    _previewMesh.visible = true

    const hovPt = hit.point.clone()
    if (_hoverRafId !== null) cancelAnimationFrame(_hoverRafId)
    _hoverRafId = requestAnimationFrame(() => { _hoverRafId = null; _updateHoverGrid(hovPt) })
  }

  function _onSurfaceClick(e) {
    if (_wasDrag(e)) return
    const hit = _getFaceHit(e)
    if (!hit) return
    const instAId = _definingInstanceA
    const instBId = _definingInstanceB
    exitDefineMode()
    api.addAssemblyJoint({
      instance_a_id:  instAId,
      instance_b_id:  instBId,
      axis_origin:    [hit.point.x,  hit.point.y,  hit.point.z],
      axis_direction: [hit.normal.x, hit.normal.y, hit.normal.z],
      joint_type:     'revolute',
    })
  }

  function _onKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); exitDefineMode() }
  }

  // ── Public: enterDefineMode / exitDefineMode ──────────────────────────────────

  /**
   * Enter hull-surface face-click mode for joint axis definition.
   *
   * Shows a semi-transparent hull prism around instanceB (the child).
   * On face-click: places an AssemblyJoint with the face normal as axis direction.
   * On Escape or programmatic exitDefineMode(): cancels without creating a joint.
   *
   * @param {string|null} instanceAId  Parent instance (null = world frame)
   * @param {string}      instanceBId  Child instance whose hull is shown
   * @param {function}    onExit       Called when mode ends (click or cancel)
   */
  async function enterDefineMode(instanceAId, instanceBId, onExit = null) {
    exitDefineMode()
    _definingInstanceA = instanceAId
    _definingInstanceB = instanceBId
    _onExitCb          = onExit

    await _showInstanceSurface(instanceBId)

    canvas.style.cursor = 'crosshair'
    canvas.addEventListener('pointerdown', _onPointerDown)
    canvas.addEventListener('pointermove', _onSurfaceMove)
    canvas.addEventListener('click',       _onSurfaceClick)
    document.addEventListener('keydown',   _onKeyDown)
  }

  function exitDefineMode() {
    if (_hoverRafId !== null) { cancelAnimationFrame(_hoverRafId); _hoverRafId = null }
    _removeSurface()
    _previewMesh.visible = false
    canvas.removeEventListener('pointerdown', _onPointerDown)
    canvas.removeEventListener('pointermove', _onSurfaceMove)
    canvas.removeEventListener('click',       _onSurfaceClick)
    document.removeEventListener('keydown',   _onKeyDown)
    canvas.style.cursor = ''
    _definingInstanceA = null
    _definingInstanceB = null
    _pointerDownAt     = null
    const cb = _onExitCb
    _onExitCb = null
    cb?.()
  }

  // ── Public: rebuild ──────────────────────────────────────────────────────────
  function rebuild(assembly) {
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()

    const joints = assembly?.joints ?? []
    for (const joint of joints) {
      const grp = _buildIndicator(joint.axis_origin, joint.axis_direction)
      grp.userData.jointId = joint.id
      grp.traverse(o => { if (o.userData.isJointRing) o.userData.jointId = joint.id })
      _jointGroup.add(grp)
      _jointMeshes.set(joint.id, grp)
    }
  }

  // ── Public: pick ring ────────────────────────────────────────────────────────
  function pickJointRing(e) {
    if (!_jointMeshes.size) return null
    _rc.setFromCamera(_ndc(e), camera)
    const rings = []
    for (const grp of _jointMeshes.values()) {
      grp.traverse(o => { if (o.userData.isJointRing) rings.push(o) })
    }
    if (!rings.length) return null
    const hits = _rc.intersectObjects(rings, false)
    return hits.length ? hits[0].object.userData.jointId : null
  }

  // ── Ring drag ────────────────────────────────────────────────────────────────

  let _drag      = null
  let _sendTimer = null

  function _ringPlaneHit(e, axisDir, axisOrigin) {
    _rc.setFromCamera(_ndc(e), camera)
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(axisDir, axisOrigin)
    const hit   = new THREE.Vector3()
    return _rc.ray.intersectPlane(plane, hit) ? hit : null
  }

  function _angleInRing(worldPt, axisOrigin, axisDir, refVec) {
    const v = worldPt.clone().sub(axisOrigin)
    v.addScaledVector(axisDir, -v.dot(axisDir))
    if (v.lengthSq() < 1e-12) return 0
    v.normalize()
    const cross = new THREE.Vector3().crossVectors(refVec, v)
    return Math.atan2(cross.dot(axisDir), refVec.dot(v))
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

    const tmp      = Math.abs(axisDir.dot(_Y)) < 0.9 ? _Y.clone() : _Z.clone()
    const refVec   = tmp.clone().addScaledVector(axisDir, -tmp.dot(axisDir)).normalize()
    const startAngle = _angleInRing(hit, axisOrigin, axisDir, refVec)

    _drag = { jointId, axisDir, axisOrigin, refVec, startAngle,
              startValue: joint.current_value, currentValue: joint.current_value }

    controls.enabled = false
    canvas.addEventListener('pointermove', _onRingPointerMove)
    canvas.addEventListener('pointerup',   _onRingPointerUp)
    canvas.setPointerCapture(e.pointerId)
    e.stopPropagation()
  }

  // ── Visibility + dispose ─────────────────────────────────────────────────────

  function setVisible(on) { _jointGroup.visible = on }

  function dispose() {
    exitDefineMode()
    clearTimeout(_sendTimer)
    canvas.removeEventListener('pointermove', _onRingPointerMove)
    canvas.removeEventListener('pointerup',   _onRingPointerUp)
    _previewMesh.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _previewMesh.parent?.remove(_previewMesh)
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()
    _jointGroup.parent?.remove(_jointGroup)
  }

  return { rebuild, enterDefineMode, exitDefineMode, pickJointRing, beginRingDrag, setVisible, dispose }
}
