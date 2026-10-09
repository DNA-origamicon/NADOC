/**
 * Extrusion-direction arrows for selected 5'/3' ends — with drag-to-resize.
 *
 * Shows a thick cyan arrow at each selected end bead pointing outward along the
 * helix axis.  The arrows are draggable: grabbing and moving one arrow extends
 * or shortens ALL visible end arrows by the same bp delta simultaneously.
 *
 * End arrows derive only from canonical base/end refs. Alt-picked measurement
 * anchors are intentionally separate tool state and never create resize arrows.
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
import { BDNA_RISE_PER_BP } from '../constants.js'
import { resizeStrandEnds } from '../api/client.js'
import { adjacentBpFree, oneNtResizableEnd } from '../shared/strand_end_resize.js'
import { baseKey, parseBaseKey } from './base_ref.js'
import { canonicalSelection } from './selection_model.js'
import { createEndResizeAxis, projectRayToResizeAxis } from './end_resize_axis.js'

// ── Arrow dimensions (nm) ─────────────────────────────────────────────────────

const ARROW_OFFSET = 0.30   // clearance from bead centre before shaft starts
const SHAFT_LEN    = 0.90   // shaft length
const SHAFT_RAD    = 0.13   // shaft radius
const HEAD_LEN     = 0.60   // cone height
const HEAD_RAD     = 0.30   // cone base radius
const ARROW_COLOR  = 0x00e5ff  // cyan

// ── Drag constants ────────────────────────────────────────────────────────────

const MAX_EXTEND_BP = 200     // max bp change per drag

const _Y = new THREE.Vector3(0, 1, 0)   // CylinderGeometry / ConeGeometry default axis

// ─────────────────────────────────────────────────────────────────────────────

/**
 * bp length the terminal end may be trimmed *through* in a single drag — the
 * shorten budget (the drag clamp keeps ≥ 1 bp by using `runLength - 1`).
 *
 * Normally this is just the terminal domain's own length. BUT when that terminal
 * domain is an **inline overhang** (a staple tail past the scaffold, tagged
 * `ovhg_inline_…`), the backend resize *merges it back* into the adjacent
 * same-helix scaffold domain on commit. That means the free end can be dragged
 * straight *through* the scaffold boundary — dissolving the overhang entirely —
 * exactly like resizing in the cadnano editor. To allow that, count the whole
 * contiguous same-helix run (overhang + its scaffold-covered neighbour), not
 * just the overhang domain, so the 3D drag isn't hard-stopped at the boundary.
 *
 * The `ovhg_inline_` prefix + same-helix-neighbour gate mirror the backend's
 * merge condition exactly (`_reconcile_inline_overhangs`): a non-inline overhang
 * id, or a crossover tail whose neighbour is on a *different* helix, does NOT
 * merge, so for those we keep the single-domain limit.
 *
 * @param {object}  strand       a design strand ({ domains: [...] })
 * @param {boolean} isFivePrime  true = 5′ terminal (domains[0]); false = 3′
 * @returns {number} run length in bp (≥ 1)
 */
export function terminalRunLength(strand, isFivePrime) {
  const domains = strand?.domains
  if (!domains?.length) return 1
  const td = isFivePrime ? domains[0] : domains[domains.length - 1]
  if (!td) return 1
  let len = Math.abs(td.end_bp - td.start_bp) + 1
  if (typeof td.overhang_id === 'string' && td.overhang_id.startsWith('ovhg_inline_')) {
    const adj = isFivePrime ? domains[1] : domains[domains.length - 2]
    if (adj && adj.helix_id === td.helix_id) {
      len += Math.abs(adj.end_bp - adj.start_bp) + 1
    }
  }
  return len
}

// Re-exported for existing tests; canonical home is shared/strand_end_resize.js
// (shared with the cadnano 2D editor's end-drag).
export { adjacentBpFree, oneNtResizableEnd }

// ─────────────────────────────────────────────────────────────────────────────

/**
 * @param {THREE.Scene}         scene
 * @param {THREE.Camera}        camera
 * @param {HTMLCanvasElement}   canvas
 * @param {object}              selectionManager  — selection gesture owner
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
  const _extMat  = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.55 })
  const _trimMat = new THREE.MeshBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.55 })

  // ── State ─────────────────────────────────────────────────────────────────

  let _arrowGroups = []

  // Drag state
  let _dragging       = false
  let _dragBeads      = []            // dragMeta snapshots at drag start
  let _dragExtMin     = -MAX_EXTEND_BP
  let _dragExtMax     = +MAX_EXTEND_BP
  let _dragOriginMeta = null          // meta of the grabbed arrow
  let _dragPointerOffset = 0
  let _lastDelta      = 0             // last committed extensionDelta

  // ── Entry lookup ──────────────────────────────────────────────────────────

  function _entryForSelectionRef(ref) {
    if (ref?.kind !== 'base' && ref?.kind !== 'end') return null
    const target = parseBaseKey(ref.key)
    if (!target || target.helix_id === '__xb__') return null
    const entry = designRenderer.getBackboneEntries().find(be =>
      be.nuc.helix_id === target.helix_id &&
      be.nuc.bp_index === target.bp_index &&
      be.nuc.direction === target.direction &&
      (be._copy ?? 0) === (target.copy ?? 0))
    return entry ? { entry, nuc: entry.nuc } : null
  }

  // ── Collect all end-bead sources ──────────────────────────────────────────

  function _collectBeads() {
    const beads = []
    for (const ref of canonicalSelection(store.getState()).items) {
      const bead = _entryForSelectionRef(ref)
      const nuc = bead?.nuc
      if (bead && (nuc.is_five_prime || nuc.is_three_prime)) {
        const alreadyPresent = beads.some(
          b => b.nuc.helix_id === nuc.helix_id && b.nuc.bp_index === nuc.bp_index &&
            b.nuc.direction === nuc.direction,
        )
        if (!alreadyPresent) beads.push(bead)
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

    const { resizeAxis, bead, outwardSign } = originMeta
    const bp = bead.nuc.bp_index
    // Project past the clamp by the handle length, so subtracting the grip
    // offset does not make the last few allowed base pairs unreachable.
    const margin = (ARROW_OFFSET + SHAFT_LEN + HEAD_LEN) / BDNA_RISE_PER_BP + 1
    const projected = projectRayToResizeAxis(ray, resizeAxis,
      bp + (_dragExtMin - margin) * outwardSign, bp + (_dragExtMax + margin) * outwardSign)
    return (projected - bp) * outwardSign
  }

  // ── Rebuild ───────────────────────────────────────────────────────────────

  function _rebuild() {
    for (const ag of _arrowGroups) _group.remove(ag)
    _arrowGroups = []

    const beads    = _collectBeads()
    const endBeads = beads.filter(b => b.nuc.is_five_prime || b.nuc.is_three_prime)

    console.debug(
      `[EndExtrudeArrows] rebuild — selected: ${beads.length}, ends: ${endBeads.length}`,
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

      // Which terminus this arrow drives. A 1-nt strand's bead is BOTH ends;
      // pick the end that can actually be resized (free extension side) so a stub
      // pinned by a crossover on one side is still resizable on the other.
      const isOneNt = nuc.is_five_prime && nuc.is_three_prime
      const endRole = isOneNt
        ? oneNtResizableEnd(nuc, currentDesign.strands)
        : (nuc.is_five_prime ? '5p' : '3p')
      // Direction comes from the selected terminus, not spatial proximity to
      // helix endpoints (a bend can put the opposite endpoint closer).
      const outwardSign = ((endRole === '3p') !== (nuc.direction === 'REVERSE')) ? 1 : -1
      const beadPos = bead.entry.pos
      const resizeAxis = createEndResizeAxis(helix, currentHelixAxes?.[nuc.helix_id],
        nuc.bp_index, beadPos, store.getState().cadnanoActive)
      const outward = resizeAxis.tangent(nuc.bp_index).multiplyScalar(outwardSign)
      const strand = strandById.get(nuc.strand_id)
      const terminalLen = strand ? terminalRunLength(strand, endRole === '5p') : 1

      // ── Build arrow group ────────────────────────────────────────────────
      const shaft = new THREE.Mesh(_shaftGeo, _mat)
      shaft.position.y = ARROW_OFFSET + SHAFT_LEN / 2

      const head = new THREE.Mesh(_headGeo, _mat)
      head.position.y = ARROW_OFFSET + SHAFT_LEN + HEAD_LEN / 2

      const ag = new THREE.Group()
      ag.add(shaft)
      ag.add(head)
      ag.position.copy(beadPos)
      ag.quaternion.setFromUnitVectors(_Y, outward)

      // Store metadata for drag
      ag.userData.dragMeta = {
        bead,
        endRole,
        outwardSign,
        resizeAxis,
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

      const from = meta.bead.nuc.bp_index
      const to = from + extensionDelta * meta.outwardSign
      ag.position.copy(meta.resizeAxis.point(to))
      ag.quaternion.setFromUnitVectors(_Y, meta.resizeAxis.tangent(to).multiplyScalar(meta.outwardSign))

      const path = meta.resizeAxis.path(from, to)
      for (let i = 1; i < path.length; i++) {
        const a = path[i - 1].position, b = path[i].position
        const direction = b.clone().sub(a)
        const length = direction.length()
        if (length < 0.01) continue
        const geometry = new THREE.CylinderGeometry(SHAFT_RAD * 1.8, SHAFT_RAD * 1.8, length, 8)
        const mesh = new THREE.Mesh(geometry, extensionDelta >= 0 ? _extMat : _trimMat)
        mesh.position.copy(a).lerp(b, 0.5)
        mesh.quaternion.setFromUnitVectors(_Y, direction.normalize())
        _previewGroup.add(mesh)
      }
    }
  }

  // ── Drag handlers ─────────────────────────────────────────────────────────

  function _onDragMove(e) {
    if (!_dragging || !_dragOriginMeta) return
    const raw     = _projectToExtDelta(e.clientX, e.clientY, _dragOriginMeta) - _dragPointerOffset
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

    await _commitResize(dragBeads, delta)
  }

  async function _commitResize(dragBeads, delta, onCommitted) {
    const previousSelection = canonicalSelection(store.getState())
    const entries = dragBeads.map(meta => ({
      strand_id: meta.bead.nuc.strand_id,
      helix_id:  meta.bead.nuc.helix_id,
      end:       meta.endRole ?? (meta.bead.nuc.is_five_prime ? '5p' : '3p'),
      delta_bp:  delta * meta.outwardSign,
    }))

    console.debug(`[EndExtrudeArrows] commit resize — delta: ${delta}, entries:`, entries)
    const result = await (onCommitted
      ? resizeStrandEnds(entries, { onCommitted }) : resizeStrandEnds(entries))
    if (!result) throw new Error("End resize failed")

    // After the API resolves, store has new geometry and all bead positions have
    // been updated (including cadnano reapply).  If the selection was on one of
    // the resized end beads, re-select it at its new bp position so the bead
    // highlight and arrow both move to where the strand now ends.
    const state = store.getState()
    const { currentGeometry } = state
    if (!currentGeometry || !opts.selectionController) return
    const moved = new Map(dragBeads.map(meta => [baseKey(meta.bead.nuc, meta.bead.entry?._copy ?? meta.bead.nuc.copy_k ?? 0), meta]))
    const surviving = new Set(canonicalSelection(state).items.map(ref => JSON.stringify(ref)))
    const refs = previousSelection.items.flatMap(ref => {
      const meta = (ref.kind === 'base' || ref.kind === 'end') ? moved.get(ref.key) : null
      if (!meta) return surviving.has(JSON.stringify(ref)) ? [ref] : []
      const old = meta.bead.nuc
      const five = (meta.endRole ?? (old.is_five_prime ? '5p' : '3p')) === '5p'
      const nuc = currentGeometry.find(n => n.strand_id === old.strand_id &&
        n.helix_id === old.helix_id && n.direction === old.direction &&
        (five ? n.is_five_prime : n.is_three_prime))
      return nuc ? [{ kind: ref.kind, key: baseKey(nuc, nuc.copy_k ?? 0) }] : []
    })
    // Keep every resized end selected, including after topology reconciliation
    // removes its old base key. A second pull must resize the same entire set.
    opts.selectionController.replace(refs)
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
    _dragPointerOffset = _projectToExtDelta(e.clientX, e.clientY, _dragOriginMeta)

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

  store.subscribe((next, prev) => {
    if (next.currentDesign    !== prev.currentDesign ||
        next.currentHelixAxes !== prev.currentHelixAxes ||
        next.selection        !== prev.selection) {
      _rebuild()
    }
  })

  // ── Public API ────────────────────────────────────────────────────────────

  let vrVersion = 0
  let vrSnapshot = null
  let vrSignature = ''
  let vrDesign = null
  let vrBusy = false

  function vrHandles() {
    const state = store.getState()
    const metas = _arrowGroups.map(ag => ag.userData.dragMeta)
    const limits = _computeDragLimits(metas, state.currentDesign)
    const handles = !_group.visible || state.cadnanoActive || vrBusy ? [] : _arrowGroups.map(ag => ({
      position: ag.userData.dragMeta.bead.nuc.backbone_position ?? ag.position.toArray(),
      direction: new THREE.Vector3(0, 1, 0).applyQuaternion(ag.quaternion).toArray(),
    }))
    const signature = JSON.stringify([handles, limits, metas.map(m => [m.bead.nuc.strand_id, m.bead.nuc.bp_index, m.endRole])])
    if (signature !== vrSignature || vrDesign !== state.currentDesign) {
      vrSignature = signature
      vrDesign = state.currentDesign
      vrSnapshot = { version: ++vrVersion, minimum: limits.extMin, maximum: limits.extMax, handles, metas }
    }
    if (!vrSnapshot) return { version: 0, minimum: 0, maximum: 0, handles: [] }
    const { metas: _, ...payload } = vrSnapshot
    return payload
  }

  return {
    vrHandles,
    invalidateVRHandles() { vrSignature = '' },
    async resizeFromVR(version, delta, onCommitted) {
      vrHandles()
      if (vrBusy || !vrSnapshot?.handles.length || version !== vrSnapshot.version ||
          !Number.isSafeInteger(delta) || delta < vrSnapshot.minimum || delta > vrSnapshot.maximum) {
        throw new Error('End selection or design changed; grab the arrow again')
      }
      const metas = vrSnapshot.metas
      vrBusy = true
      try { if (delta) await _commitResize(metas, delta, onCommitted) }
      finally { vrBusy = false; vrSignature = ''; _rebuild() }
    },
    refresh() { _rebuild() },

    /**
     * Show or hide the entire arrow group.
     * Called by assembly mode so extrude handles don't appear on hover while
     * design geometry is suppressed.
     */
    setVisible(bool) { _group.visible = bool },

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
