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

// ── Connector indicator geometry constants ────────────────────────────────────
const CONN_SHAFT_R  = 0.06
const CONN_HALF_LEN = 0.7
const CONN_TIP_R    = 0.18
const CONN_TIP_H    = 0.40
const CONN_SPHERE_R = 0.38
const CONN_COLOUR     = 0xf0a500   // amber/gold
const CONN_SEL_COL    = 0x58a6ff   // blue (selected child/first connector)
const CONN_PARENT_COL = 0x3fb950   // green (selected parent/second connector)
const CONN_HOV_COL    = 0xffffff   // white (hovered)

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
 * Build a connector indicator: sphere (click target) + directional arrow.
 * Returns { group: THREE.Group, hitMesh: THREE.Mesh }.
 */
function _buildConnectorIndicator(worldPos, worldNorm, color = CONN_COLOUR) {
  const dir = new THREE.Vector3(worldNorm[0], worldNorm[1], worldNorm[2]).normalize()
  const { q } = _orientQ([dir.x, dir.y, dir.z])
  const grp = new THREE.Group()
  grp.position.set(worldPos[0], worldPos[1], worldPos[2])

  const mat = () => new THREE.MeshBasicMaterial({
    color, depthTest: false, depthWrite: false, transparent: true,
  })

  // Sphere at connector origin — primary click/pick target
  const hitMesh = new THREE.Mesh(new THREE.SphereGeometry(CONN_SPHERE_R, 8, 6), mat())
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
  const _jointGroup      = new THREE.Group()
  const _jointMeshes     = new Map()   // jointId → THREE.Group
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
      mesh.material.color.set(isFirst ? CONN_SEL_COL : isSecond ? CONN_PARENT_COL : CONN_COLOUR)
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
      const { group, hitMesh } = _buildConnectorIndicator(be.worldPos, be.worldNorm)
      hitMesh.userData = { instanceId: be.instanceId, label: be.label, worldPos: be.worldPos, worldNorm: be.worldNorm }
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
    title.style.cssText = 'font-size:11px;font-weight:600;color:#c9d1d9;margin-bottom:10px;letter-spacing:.04em;'
    panel.appendChild(title)

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
      lbl.style.cssText = 'font-size:10px;color:#6e7681;margin-bottom:2px;'
      row.appendChild(lbl); row.appendChild(child)
      return row
    }

    const childSel  = makeSelect(false, '_mate-child-sel')
    const parentSel = makeSelect(true,  '_mate-parent-sel')
    panel.appendChild(labelledRow('Child Connector',  childSel))
    panel.appendChild(labelledRow('Parent Connector', parentSel))

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
          <div style="font-size:10px;color:#6e7681;margin-bottom:2px">Fixed Angle (°)</div>
          <input id="_mate-fixed-angle" type="number" value="0" step="1"
            style="width:100%;box-sizing:border-box;background:#161b22;color:#c9d1d9;
                   border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;">
        `
      } else if (typeSel.value === 'revolute') {
        fieldsEl.innerHTML = `
          <div style="display:flex;gap:6px">
            <div style="flex:1">
              <div style="font-size:10px;color:#6e7681;margin-bottom:2px">Min Angle (°)</div>
              <input id="_mate-min-angle" type="number" value="-180" step="1"
                style="width:100%;box-sizing:border-box;background:#161b22;color:#c9d1d9;
                       border:1px solid #30363d;border-radius:3px;padding:3px 6px;font-size:11px;">
            </div>
            <div style="flex:1">
              <div style="font-size:10px;color:#6e7681;margin-bottom:2px">Max Angle (°)</div>
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
      _applyPreview()
    })
    parentSel.addEventListener('change', () => {
      const val = parentSel.value
      _mateSecond = val === '__world__' ? null : (_connectorDataMap.get(val) ?? undefined)
      _resetConnectorColors()
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

    // Auto-register blunt-end connectors as InterfacePoints before creating the joint.
    // 400 = label already exists (idempotent — safe to ignore).
    const _registerBlunt = async (conn) => {
      if (!conn?.isBluntEnd || !conn.localPos) return
      try {
        await api.addInstanceConnector(conn.instanceId, {
          label:    conn.label,
          position: conn.localPos,
          normal:   conn.localNorm,
        })
      } catch (_) {}
    }
    await _registerBlunt(first)
    await _registerBlunt(second)

    if (second) {
      const result = _computeAlignTransform(first, second, { ...opts, jointType })
      if (result) {
        // Use propagateFk so FK is propagated to the aligned instance's kinematic children
        await api.propagateFk(result.instanceId, result.matrix.clone().transpose().toArray())
        axisOrigin = result.axisOrigin
        axisDir    = result.axisDir
      } else {
        alert('Cannot auto-align: both parts are fixed.')
      }
    }

    const DEG = Math.PI / 180
    await api.addAssemblyJoint({
      instance_a_id:     second?.instanceId ?? null,
      instance_b_id:     first.instanceId,
      axis_origin:       axisOrigin,
      axis_direction:    axisDir,
      joint_type:        jointType,
      min_limit:         minAngleDeg !== undefined ? minAngleDeg * DEG : null,
      max_limit:         maxAngleDeg !== undefined ? maxAngleDeg * DEG : null,
      connector_a_label: second?.label ?? null,
      connector_b_label: first.label,
    })
  }

  // ── Pointer events — mate define mode ────────────────────────────────────
  function _onMatePointerDown(e) { _pointerDownAt = { x: e.clientX, y: e.clientY } }

  function _onMatePointerMove(e) {
    if (!_connectorMeshes.length) return
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
      const baseCol = isFirst ? CONN_SEL_COL : isSecond ? CONN_PARENT_COL : CONN_COLOUR
      mesh.material.color.set(mesh === hovered ? CONN_HOV_COL : baseCol)
    }
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

    canvas.style.cursor = 'crosshair'
    canvas.addEventListener('pointerdown', _onMatePointerDown)
    canvas.addEventListener('pointermove', _onMatePointerMove)
    canvas.addEventListener('click',       _onMateClick)
    document.addEventListener('keydown',   _onMateKeyDown)
  }

  function exitMateDefineMode(skipPreviewClear = false) {
    if (!_mateMode) return
    if (!skipPreviewClear) _clearPreview()
    _onLivePreview = null
    _mateMode      = false
    _mateFirst     = null
    _mateSecond    = undefined
    _syncBluntConnIndicators()  // clears blunt indicators now that _mateMode is false
    _removeMateOverlays()
    _resetConnectorColors()
    _connectorGroup.visible = false
    canvas.removeEventListener('pointerdown', _onMatePointerDown)
    canvas.removeEventListener('pointermove', _onMatePointerMove)
    canvas.removeEventListener('click',       _onMateClick)
    document.removeEventListener('keydown',   _onMateKeyDown)
    canvas.style.cursor = ''
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

  // ── Public: rebuild ──────────────────────────────────────────────────────
  function rebuild(assembly) {
    // ── Joint indicators ─────────────────────────────────────────────────
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()

    const joints   = assembly?.joints   ?? []
    const instances = assembly?.instances ?? []
    for (const joint of joints) {
      const broken = _isBrokenMate(joint, instances)
      const grp = _buildIndicator(joint.axis_origin, joint.axis_direction, broken)
      grp.userData.jointId = joint.id
      grp.traverse(o => { if (o.userData.isJointRing) o.userData.jointId = joint.id })
      _jointGroup.add(grp)
      _jointMeshes.set(joint.id, grp)
    }

    // ── Connector indicators ─────────────────────────────────────────────
    _connectorGroup.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _connectorGroup.clear()
    _connectorMeshes.length = 0
    _connectorDataMap.clear()

    for (const inst of instances) {
      const mat4     = _instMat4(inst)
      const instName = inst.name ?? inst.id.slice(0, 6)
      for (const ip of (inst.interface_points ?? [])) {
        const pos  = new THREE.Vector3(ip.position.x, ip.position.y, ip.position.z).applyMatrix4(mat4)
        const norm = new THREE.Vector3(ip.normal.x, ip.normal.y, ip.normal.z).transformDirection(mat4).normalize()
        const wPos = [pos.x, pos.y, pos.z]
        const wNrm = [norm.x, norm.y, norm.z]
        _connectorDataMap.set(`${inst.id}::${ip.label}`, {
          instanceId: inst.id, label: ip.label,
          worldPos: wPos, worldNorm: wNrm, instanceLabel: instName,
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
  }

  // ── Public: pick ring ────────────────────────────────────────────────────
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

  function setVisible(on) {
    _jointGroup.visible     = on
    _connectorGroup.visible = on && _mateMode
    _bluntConnGroup.visible = on && _mateMode
  }

  function dispose() {
    exitConnectorDefineMode()
    exitMateDefineMode()
    clearTimeout(_sendTimer)
    clearTimeout(_instSendTimer)
    clearTimeout(_instPrisSendTimer)
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
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()
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
  }

  return {
    rebuild,
    enterConnectorDefineMode,
    exitConnectorDefineMode,
    enterMateDefineMode,
    exitMateDefineMode,
    isMateMode: () => _mateMode,
    pickJointRing,
    beginRingDrag,
    beginRevoluteDragForJoint,
    beginPrismaticDragForJoint,
    setLiveJointTransform,
    setVisible,
    dispose,
    /** Update blunt-end connector candidates shown in mate-define mode. */
    setExtraConnectors(data) {
      _extraConnectors = data ?? []
      _syncBluntConnIndicators()
    },
  }
}
