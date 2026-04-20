/**
 * Debug overlay — shows object ID and state when hovering in the 3D scene.
 *
 * Toggle with the backtick key (`) or View > Debug Overlay.
 * When active a tooltip follows the cursor, showing the first hit object's
 * details: nucleotide, backbone bond, placed crossover (arc or cone), or blunt end.
 *
 * Hit detection strategy (in priority order):
 *   1. Screen-space proximity → placed crossover arcs (THREE.Line, can't raycast)
 *   2. Raycast → blunt end hit disks
 *   3. Raycast → backbone bond cones (cross-helix = placed crossover, same = bond)
 *   4. Raycast → backbone beads
 *
 * Usage:
 *   const dbg = initDebugOverlay(canvas, camera, designRenderer, {
 *     getBluntEnds, getUnfoldView,
 *   })
 *   dbg.toggle()
 *   dbg.isActive()
 *   dbg.dispose()
 */

import * as THREE from 'three'
import { store } from '../state/store.js'

const _raycaster = new THREE.Raycaster()
const _ndc       = new THREE.Vector2()

const ARC_PROX_PX    = 14   // screen-px threshold for arc midpoint proximity

export function initDebugOverlay(canvas, camera, designRenderer, opts = {}) {
  const { getBluntEnds, getUnfoldView } = opts

  let _active = false

  // ── Tooltip element ─────────────────────────────────────────────────────────

  const _tip = document.createElement('div')
  _tip.style.cssText = `
    position: fixed;
    pointer-events: none;
    display: none;
    background: rgba(8, 16, 26, 0.93);
    border: 1px solid #2a5a8a;
    border-radius: 5px;
    padding: 8px 11px;
    font-family: monospace;
    font-size: 11px;
    color: #c8daf0;
    line-height: 1.65;
    z-index: 99999;
    white-space: pre;
    max-width: 400px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.65);
  `
  document.body.appendChild(_tip)

  // ── Formatting helpers ──────────────────────────────────────────────────────

  function _header(text) {
    return `<span style="color:#5bc8ff;font-weight:bold;letter-spacing:.04em">${text}</span>\n`
  }

  function _row(label, value, color = '#d8eaff') {
    return `<span style="color:#607890">${label.padEnd(12)}</span><span style="color:${color}">${value}</span>\n`
  }

  function _sep() {
    return `<span style="color:#2a4a6a">${'─'.repeat(32)}</span>\n`
  }

  function _vec3(arr) {
    return `(${arr[0].toFixed(3)}, ${arr[1].toFixed(3)}, ${arr[2].toFixed(3)}) nm`
  }

  function _nucShort(nuc) {
    return `${nuc.helix_id}  bp=${nuc.bp_index}  ${nuc.direction}`
  }

  // ── Per-object info builders ────────────────────────────────────────────────

  function _nucHtml(nuc) {
    const loopSet = new Set(store.getState().loopStrandIds ?? [])
    const isLoop  = loopSet.has(nuc.strand_id)
    let s = _header('NUCLEOTIDE')
    s += _row('helix:', nuc.helix_id)
    s += _row('strand:', nuc.strand_id ?? '(unassigned)', nuc.strand_id ? '#d8eaff' : '#607890')
    s += _row('bp:', String(nuc.bp_index))
    s += _row('direction:', nuc.direction)
    s += _row('type:', nuc.strand_type ?? 'unassigned', nuc.strand_type === 'scaffold' ? '#29b6f6' : '#ffcc80')
    if (isLoop) s += _row('loop:', 'YES ⚠', '#ff4444')
    s += _row('bb pos:', _vec3(nuc.backbone_position))
    if (nuc.base_position) s += _row('base pos:', _vec3(nuc.base_position))
    return s
  }

  function _bondHtml(cone) {
    const { fromNuc: f, toNuc: t } = cone
    let s = _header('BACKBONE BOND')
    s += _row('strand:', cone.strandId ?? '(unassigned)', cone.strandId ? '#d8eaff' : '#607890')
    s += _row('type:', f.strand_type ?? 'unassigned', f.strand_type === 'scaffold' ? '#29b6f6' : '#ffcc80')
    s += _row('from:', _nucShort(f))
    s += _row('to:', _nucShort(t))
    return s
  }

  function _placedCrossoverHtml(fromNuc, toNuc, strandId, source) {
    const loopSet = new Set(store.getState().loopStrandIds ?? [])
    const isLoop  = loopSet.has(strandId)
    let s = _header(`PLACED CROSSOVER${source ? `  <span style="color:#607890;font-size:10px">[${source}]</span>` : ''}`)
    s += _row('strand:', strandId ?? '(unassigned)', strandId ? '#d8eaff' : '#607890')
    if (isLoop) s += _row('loop:', 'YES ⚠', '#ff4444')
    s += _sep()
    s += _row('from helix:', fromNuc.helix_id)
    s += _row('from bp:', String(fromNuc.bp_index))
    s += _row('from dir:', fromNuc.direction)
    s += _sep()
    s += _row('to helix:', toNuc.helix_id)
    s += _row('to bp:', String(toNuc.bp_index))
    s += _row('to dir:', toNuc.direction)
    return s
  }

  function _arrowHtml(arrow, part) {
    const shaftOp  = arrow.shaft?.material?.opacity ?? '—'
    const ssOp     = arrow.straightShaft?.material?.opacity ?? '—'
    let s = _header('AXIS ARROW')
    s += _row('helix:', arrow.helixId)
    s += _row('curved:', arrow.isCurved ? 'yes' : 'no')
    s += _row('hit part:', part)
    s += _sep()
    s += _row('aStart:', _vec3([arrow.aStart.x, arrow.aStart.y, arrow.aStart.z]))
    s += _row('aEnd:', _vec3([arrow.aEnd.x, arrow.aEnd.y, arrow.aEnd.z]))
    if (arrow.isCurved) {
      s += _sep()
      s += _row('shaft op:', typeof shaftOp === 'number' ? shaftOp.toFixed(2) : shaftOp,
        (typeof shaftOp === 'number' && shaftOp > 0.01) ? '#ffcc80' : '#607890')
      s += _row('straight op:', typeof ssOp === 'number' ? ssOp.toFixed(2) : ssOp,
        (typeof ssOp === 'number' && ssOp > 0.01) ? '#ffcc80' : '#607890')
    }
    return s
  }

  function _bluntHtml(b) {
    let s = _header('BLUNT END')
    s += _row('helix:', b.helixId)
    s += _row('end:', b.isStart ? "5′ (start)" : "3′ (end)")
    if (b.label) s += _row('label:', b.label)
    return s
  }

  // ── Show / hide ─────────────────────────────────────────────────────────────

  function _hide() {
    _tip.style.display = 'none'
  }

  function _show(cx, cy, html) {
    _tip.innerHTML = html.trimEnd()
    _tip.style.display = 'block'
    // Force layout so getBoundingClientRect is accurate.
    const margin = 14
    const r = _tip.getBoundingClientRect()
    let tx = cx + margin
    let ty = cy + margin
    if (tx + r.width  > window.innerWidth  - 4) tx = cx - r.width  - margin
    if (ty + r.height > window.innerHeight - 4) ty = cy - r.height - margin
    _tip.style.left = `${tx}px`
    _tip.style.top  = `${ty}px`
  }

  // ── Screen-space helpers ────────────────────────────────────────────────────

  /** Project a world-space Vector3 to canvas-relative screen coordinates. */
  function _toScreen(worldPos) {
    const v    = worldPos.clone().project(camera)
    const rect = canvas.getBoundingClientRect()
    return {
      x: (v.x *  0.5 + 0.5) * rect.width,
      y: (v.y * -0.5 + 0.5) * rect.height,
    }
  }

  /**
   * Find the closest entry whose world midpoint is within thresholdPx of
   * (sx, sy) in canvas-relative screen space.  Returns {entry, dist} or null.
   */
  function _closestByScreen(entries, getMidWorld, sx, sy, thresholdPx) {
    let best = null, bestDist = thresholdPx
    for (const entry of entries) {
      const mid = getMidWorld(entry)
      if (!mid) continue
      const sp = _toScreen(mid)
      const d  = Math.hypot(sp.x - sx, sp.y - sy)
      if (d < bestDist) { bestDist = d; best = entry }
    }
    return best
  }

  // ── Mouse handler ───────────────────────────────────────────────────────────

  function _onMouseMove(e) {
    if (!_active) return
    if (e.clientX > window.innerWidth - 300) { _hide(); return }

    const rect = canvas.getBoundingClientRect()
    const sx = e.clientX - rect.left
    const sy = e.clientY - rect.top

    _ndc.set(
       (sx / rect.width)  *  2 - 1,
      -(sy / rect.height) * 2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)

    // ── 1. Arc proximity (placed crossovers in unfold view) ─────────────────

    const arcEntries = getUnfoldView?.()?.getArcEntries?.() ?? []
    if (arcEntries.length) {
      const best = _closestByScreen(
        arcEntries,
        e => e.getMidWorld(),
        sx, sy, ARC_PROX_PX,
      )
      if (best) {
        _show(e.clientX, e.clientY,
          _placedCrossoverHtml(best.fromNuc, best.toNuc, best.strandId, 'arc'))
        return
      }
    }

    // ── 2. Raycasting ───────────────────────────────────────────────────────

    // Regular (non-instanced) meshes: blunt ends
    const regularObjects = []
    const beHits = getBluntEnds?.()?.getHitMeshes?.() ?? []
    for (const b of beHits) regularObjects.push({ mesh: b.mesh, type: 'blunt', data: b })

    // Axis arrows — map each component mesh to its arrow entry + part label.
    const arrowMeshMap = new Map()
    for (const arrow of designRenderer.getAxisArrows()) {
      if (arrow.shaft)         arrowMeshMap.set(arrow.shaft,         { arrow, part: arrow.isCurved ? 'tube shaft' : 'cylinder shaft' })
      if (arrow.straightShaft) arrowMeshMap.set(arrow.straightShaft, { arrow, part: 'straight shaft' })
      if (arrow.head)          arrowMeshMap.set(arrow.head,          { arrow, part: 'head (cone)' })
      if (arrow.origin)        arrowMeshMap.set(arrow.origin,        { arrow, part: 'origin (sphere)' })
    }

    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()
    const beadMeshes      = [...new Set(backboneEntries.map(e => e.instMesh))]
    const coneMeshes      = [...new Set(coneEntries.map(e => e.instMesh))]

    const allMeshes = [
      ...regularObjects.map(o => o.mesh),
      ...[...arrowMeshMap.keys()],
      ...coneMeshes,
      ...beadMeshes,
    ]
    if (!allMeshes.length) { _hide(); return }

    const hits = _raycaster.intersectObjects(allMeshes)
    if (!hits.length) { _hide(); return }

    const hit = hits[0]
    const obj = hit.object

    // Regular mesh hit (blunt end)?
    const reg = regularObjects.find(o => o.mesh === obj)
    if (reg) {
      _show(e.clientX, e.clientY, _bluntHtml(reg.data))
      return
    }

    // Axis arrow hit?
    const arrowHit = arrowMeshMap.get(obj)
    if (arrowHit) {
      _show(e.clientX, e.clientY, _arrowHtml(arrowHit.arrow, arrowHit.part))
      return
    }

    // Cone hit — distinguish cross-helix (placed crossover) from same-helix (bond)?
    const coneEntry = coneEntries.find(c => c.instMesh === obj && c.id === hit.instanceId)
    if (coneEntry) {
      const html = coneEntry.isCrossHelix
        ? _placedCrossoverHtml(coneEntry.fromNuc, coneEntry.toNuc, coneEntry.strandId, 'cone')
        : _bondHtml(coneEntry)
      _show(e.clientX, e.clientY, html)
      return
    }

    // Backbone bead hit?
    const beadEntry = backboneEntries.find(b => b.instMesh === obj && b.id === hit.instanceId)
    if (beadEntry) {
      _show(e.clientX, e.clientY, _nucHtml(beadEntry.nuc))
      return
    }

    _hide()
  }

  canvas.addEventListener('mousemove', _onMouseMove)

  // ── Public API ──────────────────────────────────────────────────────────────

  return {
    toggle() {
      _active = !_active
      if (!_active) _hide()
    },
    isActive: () => _active,
    dispose() {
      canvas.removeEventListener('mousemove', _onMouseMove)
      _tip.remove()
    },
  }
}
