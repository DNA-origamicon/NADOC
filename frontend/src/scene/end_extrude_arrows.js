/**
 * Extrusion-direction arrows for selected 5'/3' ends — with drag-to-resize.
 *
 * Shows a thick cyan arrow at each selected end bead pointing outward along the
 * helix axis.  The arrows are draggable: grabbing and moving one arrow extends
 * or shortens ALL visible end arrows by the same bp delta simultaneously.
 *
 * Two selection sources are unified:
 *   1. _ctrlBeads (ctrl-click or lasso with ends filter on) — via onCtrlBeadsChange
 *   2. store.selectedObject.type === 'nucleotide' (regular 3-click bead selection)
 *
 * Drag behaviour:
 *   - Cursor is projected onto the dragged arrow's helix axis.
 *   - Snaps to integer bp positions.
 *   - Ghost cylinder shown during drag (cyan = extend, red-orange = trim).
 *   - All arrows move together by the same extensionDelta.
 *   - Orbit controls are disabled during drag.
 *   - mouseup commits via POST /design/strand-end-resize.
 *   - Escape cancels without committing.
 */

import * as THREE from 'three'
import { store }           from '../state/store.js'
import { resizeStrandEnds } from '../api/client.js'

// ── Arrow dimensions (nm) ─────────────────────────────────────────────────────

const ARROW_OFFSET = 0.30   // clearance from bead centre before shaft starts
const SHAFT_LEN    = 0.90   // shaft length
const SHAFT_RAD    = 0.13   // shaft radius
const HEAD_LEN     = 0.60   // cone height
const HEAD_RAD     = 0.30   // cone base radius
const ARROW_COLOR  = 0x00e5ff  // cyan

// ── Drag constants ────────────────────────────────────────────────────────────

const RISE_PER_BP   = 0.334   // nm — matches backend BDNA_RISE_PER_BP
const MAX_EXTEND_BP = 200     // max bp change per drag

const _Y = new THREE.Vector3(0, 1, 0)   // CylinderGeometry / ConeGeometry default axis

// ─────────────────────────────────────────────────────────────────────────────

/**
 * @param {THREE.Scene}         scene
 * @param {THREE.Camera}        camera
 * @param {HTMLCanvasElement}   canvas
 * @param {object}              selectionManager  — exposes onCtrlBeadsChange / getCtrlBeads
 * @param {object}              designRenderer    — exposes getBackboneEntries()
 * @param {object|null}         controls          — OrbitControls / TrackballControls instance
 */
export function initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, controls, opts = {}) {
  const { getCamera, getControls } = opts
  const _cam  = () => getCamera?.()   ?? camera
  const _ctrl = () => getControls?.() ?? controls

  const raycaster = new THREE.Raycaster()
  const _ndc      = new THREE.Vector2()

  function _setNdc(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    _ndc.x =  ((clientX - rect.left) / rect.width)  * 2 - 1
    _ndc.y = -((clientY - rect.top)  / rect.height) * 2 + 1
  }

  // ── Drag tooltip (DOM overlay) ────────────────────────────────────────────

  const _tooltip = document.createElement('div')
  Object.assign(_tooltip.style, {
    position:        'fixed',
    display:         'none',
    padding:         '3px 8px',
    background:      'rgba(0,0,0,0.75)',
    color:           '#fff',
    fontFamily:      'monospace',
    fontSize:        '13px',
    borderRadius:    '4px',
    pointerEvents:   'none',
    userSelect:      'none',
    whiteSpace:      'nowrap',
    zIndex:          '9999',
    transform:       'translate(14px, -50%)',
  })
  document.body.appendChild(_tooltip)

  function _showTooltip(clientX, clientY, delta) {
    _tooltip.textContent = delta > 0 ? `[+${delta}]` : `[${delta}]`
    _tooltip.style.left  = `${clientX}px`
    _tooltip.style.top   = `${clientY}px`
    _tooltip.style.display = ''
    _tooltip.style.color = delta >= 0 ? '#00e5ff' : '#ff6633'
  }

  function _hideTooltip() {
    _tooltip.style.display = 'none'
  }

  // ── Scene groups ──────────────────────────────────────────────────────────

  const _group = new THREE.Group()
  _group.name  = 'endExtrudeArrows'
  scene.add(_group)

  const _previewGroup = new THREE.Group()
  _previewGroup.name  = 'endExtrudeArrowsPreview'
  scene.add(_previewGroup)

  console.debug('[EndExtrudeArrows] initialised')

  // ── Shared geometries / materials ─────────────────────────────────────────

  const _shaftGeo = new THREE.CylinderGeometry(SHAFT_RAD, SHAFT_RAD, SHAFT_LEN, 8)
  const _headGeo  = new THREE.ConeGeometry(HEAD_RAD, HEAD_LEN, 8)
  const _mat      = new THREE.MeshPhongMaterial({ color: ARROW_COLOR })

  // Preview materials (ghost cylinders during drag)
  const _extMat  = new THREE.MeshPhongMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.35 })
  const _trimMat = new THREE.MeshPhongMaterial({ color: 0xff4400, transparent: true, opacity: 0.35 })

  // ── State ─────────────────────────────────────────────────────────────────

  let _arrowGroups = []
  let _ctrlBeads   = []   // latest snapshot from onCtrlBeadsChange

  // Drag state
  let _dragging       = false
  let _dragBeads      = []            // dragMeta snapshots at drag start
  let _dragExtMin     = -MAX_EXTEND_BP
  let _dragExtMax     = +MAX_EXTEND_BP
  let _dragOriginMeta = null          // meta of the grabbed arrow
  let _lastDelta      = 0             // last committed extensionDelta

  // ── Entry lookup ──────────────────────────────────────────────────────────

  function _entryForNuc(nuc) {
    const entries = designRenderer.getBackboneEntries()
    const e = entries.find(
      be => be.nuc.helix_id  === nuc.helix_id  &&
            be.nuc.bp_index  === nuc.bp_index  &&
            be.nuc.direction === nuc.direction,
    )
    return e ? { entry: e, nuc } : null
  }

  // ── Collect all end-bead sources ──────────────────────────────────────────

  function _collectBeads() {
    const beads = [..._ctrlBeads]
    const { selectedObject } = store.getState()
    if (selectedObject?.type === 'nucleotide') {
      const nuc = selectedObject.data
      if (nuc && (nuc.is_five_prime || nuc.is_three_prime)) {
        const alreadyPresent = beads.some(
          b => b.nuc.helix_id === nuc.helix_id && b.nuc.bp_index === nuc.bp_index,
        )
        if (!alreadyPresent) {
          const bead = _entryForNuc(nuc)
          if (bead) beads.push(bead)
        }
      }
    }
    return beads
  }

  // ── Drag-limit computation ────────────────────────────────────────────────

  /**
   * Compute the global [extMin, extMax] in extensionDelta terms.
   * extensionDelta > 0 = extend outward; < 0 = trim.
   */
  function _computeDragLimits(metas, currentDesign) {
    let extMin = -MAX_EXTEND_BP
    let extMax = +MAX_EXTEND_BP

    if (!currentDesign) return { extMin, extMax }

    for (const meta of metas) {
      const { terminalLen, outwardSign } = meta
      const shortenLimit = terminalLen - 1   // max trim (keep ≥ 1 bp)

      // Shorten limit (always applies regardless of direction)
      // outwardSign = +1: extending = positive extDelta; trimming = negative
      //   → extMin = max(extMin, -shortenLimit)
      // outwardSign = -1: extending = positive extDelta; trimming = negative
      //   → same formula applies because extDelta sign is "outward"
      extMin = Math.max(extMin, -shortenLimit)

      // Collision check: find nearest occupied bp in the EXTENDING direction
      const { helix_id, direction, bp_index: currentBp, strand_id } = meta.bead.nuc
      const dirStr = direction   // 'FORWARD' or 'REVERSE'

      // Collect all bp ranges from other domains on the same helix + direction
      let nearestObstacle = Infinity  // bp distance to nearest collision

      for (const strand of currentDesign.strands) {
        if (strand.id === strand_id) continue
        for (const domain of strand.domains) {
          if (domain.helix_id !== helix_id) continue
          if (domain.direction !== dirStr) continue
          // All bp values occupied by this domain
          const lo = Math.min(domain.start_bp, domain.end_bp)
          const hi = Math.max(domain.start_bp, domain.end_bp)
          if (outwardSign === +1) {
            // Extending = going to higher bp; collision = domain with lo > currentBp
            if (lo > currentBp) {
              nearestObstacle = Math.min(nearestObstacle, lo - currentBp - 1)
            }
          } else {
            // Extending = going to lower bp; collision = domain with hi < currentBp
            if (hi < currentBp) {
              nearestObstacle = Math.min(nearestObstacle, currentBp - hi - 1)
            }
          }
        }
      }

      if (nearestObstacle < Infinity) {
        extMax = Math.min(extMax, nearestObstacle)
      }
    }

    return { extMin, extMax }
  }

  // ── Project cursor → extensionDelta ──────────────────────────────────────

  function _projectToExtDelta(clientX, clientY, originMeta) {
    _setNdc(clientX, clientY)
    raycaster.setFromCamera(_ndc, _cam())
    const ray = raycaster.ray

    // Closest point on helix axis to the cursor ray
    // Line1: ray.origin + t * ray.direction
    // Line2: aStart   + s * axisDir
    const w0    = ray.origin.clone().sub(originMeta.aStart)
    const b     = ray.direction.dot(originMeta.axisDir)
    const denom = 1 - b * b
    if (Math.abs(denom) < 1e-8) return 0   // rays nearly parallel

    const s = (originMeta.axisDir.dot(w0) - b * ray.direction.dot(w0)) / denom

    // extensionDelta: positive = outward (extend), negative = inward (trim)
    return (s - originMeta.sOrigin) / RISE_PER_BP * originMeta.outwardSign
  }

  // ── Rebuild ───────────────────────────────────────────────────────────────

  function _rebuild() {
    for (const ag of _arrowGroups) _group.remove(ag)
    _arrowGroups = []

    const beads    = _collectBeads()
    const endBeads = beads.filter(b => b.nuc.is_five_prime || b.nuc.is_three_prime)

    console.debug(
      `[EndExtrudeArrows] rebuild — ctrl: ${_ctrlBeads.length}, ` +
      `total: ${beads.length}, ends: ${endBeads.length}`,
    )

    if (!endBeads.length) return

    const { currentDesign, currentHelixAxes } = store.getState()
    if (!currentDesign) return

    const helixById   = new Map(currentDesign.helices.map(h => [h.id, h]))
    const strandById  = new Map(currentDesign.strands.map(s => [s.id, s]))

    for (const bead of endBeads) {
      const { nuc } = bead

      const helix = helixById.get(nuc.helix_id)
      if (!helix) continue

      // ── Axis endpoints (deformed if available) ──────────────────────────
      const axDef  = currentHelixAxes?.[nuc.helix_id]
      const aStart = axDef
        ? new THREE.Vector3(...axDef.start)
        : new THREE.Vector3(helix.axis_start.x, helix.axis_start.y, helix.axis_start.z)
      const aEnd   = axDef
        ? new THREE.Vector3(...axDef.end)
        : new THREE.Vector3(helix.axis_end.x, helix.axis_end.y, helix.axis_end.z)

      const axisVec = aEnd.clone().sub(aStart)
      const axisDir = axisVec.clone().normalize()

      // ── Outward direction ────────────────────────────────────────────────
      const beadPos   = bead.entry.pos
      const nearStart = beadPos.distanceToSquared(aStart) <= beadPos.distanceToSquared(aEnd)
      const outwardSign = nearStart ? -1 : +1   // +1 = toward aEnd, -1 = toward aStart

      let outward
      if (axDef?.samples?.length >= 2) {
        const s = axDef.samples
        const n = s.length
        if (nearStart) {
          outward = new THREE.Vector3(
            s[0][0] - s[1][0], s[0][1] - s[1][1], s[0][2] - s[1][2],
          ).normalize()
        } else {
          outward = new THREE.Vector3(
            s[n-1][0] - s[n-2][0], s[n-1][1] - s[n-2][1], s[n-1][2] - s[n-2][2],
          ).normalize()
        }
      } else {
        outward = nearStart ? axisDir.clone().negate() : axisDir.clone()
      }

      // ── Terminal domain length (for shorten limit) ───────────────────────
      const strand = strandById.get(nuc.strand_id)
      let terminalLen = 1
      if (strand) {
        const td = nuc.is_five_prime ? strand.domains[0] : strand.domains[strand.domains.length - 1]
        if (td) terminalLen = Math.abs(td.end_bp - td.start_bp) + 1
      }

      // sOrigin = distance along axis (nm) from aStart to bead position
      const sOrigin = beadPos.clone().sub(aStart).dot(axisDir)

      // ── Cadnano override ─────────────────────────────────────────────────
      // In cadnano mode beads lie on a flat track along Z (z = bp_index × RISE_PER_BP).
      // Override axis, origin and outward direction to use the cadnano Z axis so
      // that arrow orientation and drag projection both work in the flat 2D layout.
      //   FORWARD 3' and REVERSE 5' ends are at the high-bp (high-Z) edge → outward = +Z
      //   FORWARD 5' and REVERSE 3' ends are at the low-bp (low-Z) edge  → outward = −Z
      const { cadnanoActive } = store.getState()
      let _axisDir = axisDir, _aStart = aStart, _sOrigin = sOrigin
      let _outward = outward, _outwardSign = outwardSign
      if (cadnanoActive) {
        const goesHigherZ = nuc.direction === 'FORWARD' ? nuc.is_three_prime : nuc.is_five_prime
        _outwardSign = goesHigherZ ? +1 : -1
        _outward     = new THREE.Vector3(0, 0, _outwardSign)
        _axisDir     = new THREE.Vector3(0, 0, 1)
        _aStart      = new THREE.Vector3(beadPos.x, beadPos.y, 0)
        _sOrigin     = beadPos.z
      }

      // ── Build arrow group ────────────────────────────────────────────────
      const shaft = new THREE.Mesh(_shaftGeo, _mat)
      shaft.position.y = ARROW_OFFSET + SHAFT_LEN / 2

      const head = new THREE.Mesh(_headGeo, _mat)
      head.position.y = ARROW_OFFSET + SHAFT_LEN + HEAD_LEN / 2

      const ag = new THREE.Group()
      ag.add(shaft)
      ag.add(head)
      ag.position.copy(beadPos)
      ag.quaternion.setFromUnitVectors(_Y, _outward)

      // Store metadata for drag
      ag.userData.dragMeta = {
        bead,
        outwardSign: _outwardSign,
        sOrigin:     _sOrigin,
        aStart:      _aStart.clone(),
        axisDir:     _axisDir.clone(),
        terminalLen,
      }

      _group.add(ag)
      _arrowGroups.push(ag)
    }

    console.debug(`[EndExtrudeArrows] ${_arrowGroups.length} arrow(s)`)
  }

  // ── Preview during drag ───────────────────────────────────────────────────

  function _clearPreview() {
    for (const m of _previewGroup.children) m.geometry.dispose()
    _previewGroup.clear()
  }

  function _applyPreview(extensionDelta) {
    _clearPreview()

    for (const ag of _arrowGroups) {
      const meta = ag.userData.dragMeta
      if (!meta) continue

      // New axis distance: outward moves arrow in outwardSign * axisDir direction
      const sNew = meta.sOrigin + extensionDelta * RISE_PER_BP * meta.outwardSign

      // Move arrow group to new position
      const posNew = meta.aStart.clone().addScaledVector(meta.axisDir, sNew)
      ag.position.copy(posNew)

      // Ghost cylinder showing the delta region
      const cylLen = Math.abs(extensionDelta) * RISE_PER_BP
      if (cylLen > 0.01) {
        const sMid   = (meta.sOrigin + sNew) / 2
        const midPos = meta.aStart.clone().addScaledVector(meta.axisDir, sMid)

        const cylGeo = new THREE.CylinderGeometry(SHAFT_RAD * 1.8, SHAFT_RAD * 1.8, cylLen, 8)
        const cylMesh = new THREE.Mesh(cylGeo, extensionDelta >= 0 ? _extMat : _trimMat)

        cylMesh.position.copy(midPos)
        // Align cylinder to axisDir (cylinder default axis is Y)
        cylMesh.quaternion.setFromUnitVectors(_Y, meta.axisDir)

        _previewGroup.add(cylMesh)
      }
    }
  }

  // ── Drag handlers ─────────────────────────────────────────────────────────

  function _onDragMove(e) {
    if (!_dragging || !_dragOriginMeta) return
    const raw     = _projectToExtDelta(e.clientX, e.clientY, _dragOriginMeta)
    const snapped = Math.round(raw)
    _lastDelta    = Math.max(_dragExtMin, Math.min(_dragExtMax, snapped))
    _applyPreview(_lastDelta)
    _showTooltip(e.clientX, e.clientY, _lastDelta)
  }

  async function _onDragUp() {
    const delta     = _lastDelta
    const dragBeads = _dragBeads   // still valid after _endDrag (only _arrowGroups is rebuilt)
    _endDrag()
    if (delta === 0) return

    const entries = dragBeads.map(meta => ({
      strand_id: meta.bead.nuc.strand_id,
      helix_id:  meta.bead.nuc.helix_id,
      end:       meta.bead.nuc.is_five_prime ? '5p' : '3p',
      delta_bp:  delta * meta.outwardSign,
    }))

    console.debug(`[EndExtrudeArrows] commit resize — delta: ${delta}, entries:`, entries)
    await resizeStrandEnds(entries)

    // After the API resolves, store has new geometry and all bead positions have
    // been updated (including cadnano reapply).  If the selection was on one of
    // the resized end beads, re-select it at its new bp position so the bead
    // highlight and arrow both move to where the strand now ends.
    const { currentGeometry, selectedObject } = store.getState()
    if (!currentGeometry || selectedObject?.type !== 'nucleotide') return
    const oldNuc = selectedObject.data
    const movedMeta = dragBeads.find(meta =>
      meta.bead.nuc.strand_id === oldNuc?.strand_id &&
      meta.bead.nuc.helix_id  === oldNuc?.helix_id  &&
      (meta.bead.nuc.is_five_prime ? oldNuc.is_five_prime : oldNuc.is_three_prime),
    )
    if (!movedMeta) return
    const newNuc = currentGeometry.find(n =>
      n.strand_id === movedMeta.bead.nuc.strand_id &&
      n.helix_id  === movedMeta.bead.nuc.helix_id  &&
      n.direction === movedMeta.bead.nuc.direction  &&
      (movedMeta.bead.nuc.is_five_prime ? n.is_five_prime : n.is_three_prime),
    )
    if (newNuc) selectionManager.selectNucleotide(newNuc)
  }

  function _onDragKey(e) {
    if (e.key === 'Escape') {
      _lastDelta = 0
      _endDrag()
    }
  }

  function _endDrag() {
    _dragging = false
    const activeCtrl = _ctrl()
    if (activeCtrl) activeCtrl.enabled = true
    canvas.style.cursor = ''
    _hideTooltip()
    document.removeEventListener('pointermove',   _onDragMove)
    document.removeEventListener('pointerup',     _onDragUp)
    document.removeEventListener('pointercancel', _onDragUp)
    document.removeEventListener('keydown',       _onDragKey)
    _clearPreview()
    _rebuild()   // restore arrows to committed positions
  }

  // ── Hover ─────────────────────────────────────────────────────────────────

  let _hoveredGroup = null

  function _findArrowHit(clientX, clientY) {
    if (!_arrowGroups.length) return null
    _setNdc(clientX, clientY)
    raycaster.setFromCamera(_ndc, _cam())
    const meshes = _arrowGroups.flatMap(ag => ag.children)
    const hits   = raycaster.intersectObjects(meshes)
    if (!hits.length) return null
    // Find the arrow group that owns the hit mesh
    return _arrowGroups.find(ag => ag.children.includes(hits[0].object)) ?? null
  }

  function _onPointerMove(e) {
    if (_dragging) return
    const hit = _findArrowHit(e.clientX, e.clientY)
    if (hit !== _hoveredGroup) {
      if (_hoveredGroup) _hoveredGroup.scale.setScalar(1.0)
      _hoveredGroup = hit
      if (_hoveredGroup) _hoveredGroup.scale.setScalar(1.1)
    }
    canvas.style.cursor = hit ? 'grab' : ''
  }

  // ── Pointer down (capture phase — intercept before OrbitControls) ─────────

  function _onPointerDown(e) {
    if (e.button !== 0 || !_arrowGroups.length) return
    const hitGroup = _findArrowHit(e.clientX, e.clientY)
    if (!hitGroup) return

    e.stopImmediatePropagation()

    _dragOriginMeta = hitGroup.userData.dragMeta
    _dragBeads      = _arrowGroups.map(ag => ag.userData.dragMeta).filter(Boolean)
    _lastDelta      = 0

    const { currentDesign } = store.getState()
    const limits = _computeDragLimits(_dragBeads, currentDesign)
    _dragExtMin = limits.extMin
    _dragExtMax = limits.extMax

    _dragging = true
    const activeCtrl = _ctrl()
    if (activeCtrl) activeCtrl.enabled = false
    canvas.style.cursor = 'grabbing'

    document.addEventListener('pointermove',   _onDragMove)
    document.addEventListener('pointerup',     _onDragUp)
    document.addEventListener('pointercancel', _onDragUp)
    document.addEventListener('keydown',       _onDragKey)
  }

  // ── Register canvas listeners ─────────────────────────────────────────────

  canvas.addEventListener('pointermove', _onPointerMove)
  canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })

  // ── Reactivity ────────────────────────────────────────────────────────────

  selectionManager.onCtrlBeadsChange(beads => {
    console.debug(`[EndExtrudeArrows] onCtrlBeadsChange — ${beads.length} bead(s)`)
    _ctrlBeads = beads
    _rebuild()
  })

  store.subscribe((next, prev) => {
    if (next.currentDesign    !== prev.currentDesign ||
        next.currentHelixAxes !== prev.currentHelixAxes ||
        next.selectedObject   !== prev.selectedObject) {
      _rebuild()
    }
  })

  // ── Public API ────────────────────────────────────────────────────────────

  return {
    refresh() { _rebuild() },

    dispose() {
      canvas.removeEventListener('pointermove', _onPointerMove)
      canvas.removeEventListener('pointerdown', _onPointerDown, { capture: true })
      for (const ag of _arrowGroups) _group.remove(ag)
      _arrowGroups = []
      _clearPreview()
      _shaftGeo.dispose()
      _headGeo.dispose()
      _mat.dispose()
      _extMat.dispose()
      _trimMat.dispose()
      scene.remove(_group)
      scene.remove(_previewGroup)
      _tooltip.remove()
    },
  }
}
