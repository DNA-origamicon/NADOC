/**
 * plate_view.js — 96-well plate + IDT tube list (shared by the 3D part editor
 * and the cadnano editor).
 *
 * Lays staple strands into a 96-well plate for IDT ordering. Staples that carry
 * a chemical modification (fluorophore etc.) OR exceed 60 nt are segregated out
 * of the plate into a tube list (recommend higher synthesis scale + HPLC).
 *
 * Self-contained Canvas-2D renderer: it re-implements the cadnano pan/zoom idiom
 * (right/middle-drag pan, wheel zoom-on-cursor, DPI-aware transform) WITHOUT
 * importing pathview internals, so both editors can use it freely. It never
 * reads a store or design — each editor passes a NORMALIZED strand list and a
 * saved layout, and mutations are routed back through the onSaveLayout callback.
 *
 * Normalized strand record (one per staple the editor wants on the plate):
 *   { strandId, color, lengthNt, groupId, groupOrder, hasMod, modName, sequence, name }
 *
 * Public API:
 *   initPlateView(canvasEl, {
 *     wrapEl, toolbarEl, getTubesContainer,
 *     onSaveLayout(layout), onStrandClick(strandId), enableGroupMode,
 *   }) → {
 *     setData(strands, savedLayout), autoFill(),
 *     setOrientation('8x12'|'12x8'), setSelectionMode('staple'|'color'|'group'),
 *     sendToTubes(strandId), sendToPlates(strandId), getLayout(),
 *     resetView(), destroy(),
 *   }
 *
 * layout shape (sent to onSaveLayout / accepted by setData):
 *   { orientation, plate_count, wells: [{strand_id,plate,row,col}], tubes: [{strand_id,reason}] }
 */

import { createContextMenu } from './primitives/context_menu.js'
import { deferrableContextMenu } from '../scene/right_click_menu.js'

// ── Layout constants (world units; px at zoom=1) ─────────────────────────────
const WELL_PITCH = 30
const WELL_R     = 12
const ROWLABEL_W = 22
const HEADER_H   = 20
const TITLE_H    = 20
const PLATE_GAP  = 36
const PLATE_PAD  = 14

const PER_PLATE  = 96
const TUBE_LEN_THRESHOLD = 60      // staple > 60 nt → tube

const MIN_ZOOM = 0.15
const MAX_ZOOM = 4
const DRAG_THRESHOLD = 4            // px before a left-drag counts as a move

// ── Colours ──────────────────────────────────────────────────────────────────
const CLR_BG        = '#f0f2f5'
const CLR_PLATE_BG  = '#ffffff'
const CLR_PLATE_EDGE= '#9aa6b2'
const CLR_WELL_EMPTY= 'rgba(195, 208, 220, 0.45)'
const CLR_WELL_EDGE = '#c4cdd5'
const CLR_LABEL     = '#3a4a58'
const CLR_TITLE     = '#1a2530'
const CLR_SEL_RING  = '#111418'
const CLR_SEL_HALO  = '#ffffff'
const CLR_DROP_RING = '#1f6feb'

const LABEL_FONT = '11px sans-serif'
const TITLE_FONT = 'bold 12px sans-serif'


export function initPlateView(canvasEl, opts = {}) {
  const {
    wrapEl,
    toolbarEl,
    getTubesContainer,
    onSaveLayout,
    onStrandClick,
    enableGroupMode = false,
  } = opts
  const ctx = canvasEl.getContext('2d')

  // ── State ───────────────────────────────────────────────────────────────────
  let _strands = []                 // normalized records (editor order)
  let _byId    = new Map()          // strandId → record
  let _orientation = '8x12'
  let _plateCount  = 1

  // Plated layout: strandId → global linear well index (plate*96 + within).
  let _wellOf = new Map()
  // Tube layout: strandId → reason ('modification'|'long'|'both'|'manual').
  let _tubes  = new Map()
  // Remember the most recent well while a strand is in a tube so an immediate
  // round trip restores the physical layout when that well is still available.
  let _returnWellOf = new Map()

  let _mode = 'staple'              // 'staple' | 'color' | 'group'
  let _selected = new Set()         // selected strandIds (highlight)

  // Pan/zoom (CSS px; world→css = world*zoom + pan).
  let _zoom = 1, _panX = 0, _panY = 0
  let _panActive = false
  let _panStartCX = 0, _panStartCY = 0, _panStartPanX = 0, _panStartPanY = 0
  let _rightDown = null
  // Once the user pans/zooms we stop auto-fitting on resize, so a sidebar-width
  // animation (or container resize) re-fits the plates until they take control.
  let _userAdjusted = false

  // Left-drag (manual move) state.
  let _ldown = null                 // { strandId, well, cx, cy, moved }
  let _dropWell = null              // hovered target well during a drag

  let _tooltipEl = null
  let _resizeObs = null
  let _contextMenu = null

  // ── Orientation helpers ──────────────────────────────────────────────────────
  // Orientation is purely a DISPLAY rotation: the physical well address (row A–H,
  // col 1–12) and the within-plate fill order are identical in both orientations.
  // 8x12 is the standard landscape plate; 12x8 is its 90° CLOCKWISE rotation
  // (A1 in the upper-right, A–H along the top, 1–12 down the right side).
  function _grid() { return _orientation === '8x12' ? { rows: 8, cols: 12 } : { rows: 12, cols: 8 } }

  // physical (row 0-7, col 0-11) → within-plate index (always row-major).
  function _rcToWithin(r, c) { return r * 12 + c }
  // within-plate index → physical (row, col).
  function _withinToRC(w) { return { r: Math.floor(w / 12), c: w % 12 } }

  // physical (r,c) → screen grid cell (gridRow, gridCol).
  //  8x12: identity (r down, c across).
  //  12x8: 90° CW rotation → gr = c, gc = 7 - r  (A1 → top-right).
  function _rcToScreen(r, c) {
    return _orientation === '8x12' ? { gr: r, gc: c } : { gr: c, gc: 7 - r }
  }
  // screen grid cell → physical (r,c) — inverse of _rcToScreen.
  function _screenToRC(gr, gc) {
    return _orientation === '8x12' ? { r: gr, c: gc } : { r: 7 - gc, c: gr }
  }
  function _wellLabel(r, c) { return String.fromCharCode(65 + r) + (c + 1) }

  // global linear index → { plate, r, c }
  function _idxToPRC(idx) {
    const plate = Math.floor(idx / PER_PLATE)
    const { r, c } = _withinToRC(idx % PER_PLATE)
    return { plate, r, c }
  }

  function _occupantAt(well) {
    if (well == null) return null
    return [..._wellOf].find(([, idx]) => idx === well)?.[0] ?? null
  }

  // ── Geometry: world coords of a plate's wells area ───────────────────────────
  function _plateTopY(p) {
    const { rows } = _grid()
    return p * (TITLE_H + HEADER_H + rows * WELL_PITCH + PLATE_GAP)
  }
  function _wellCenter(plate, gr, gc) {
    const x0 = ROWLABEL_W
    const y0 = _plateTopY(plate) + TITLE_H + HEADER_H
    return {
      x: x0 + gc * WELL_PITCH + WELL_PITCH / 2,
      y: y0 + gr * WELL_PITCH + WELL_PITCH / 2,
    }
  }
  // Right-side gutter holds the 1–12 row labels in the rotated (12x8) view.
  function _rightGutter() { return _orientation === '12x8' ? ROWLABEL_W : PLATE_PAD }
  function _worldSize() {
    const { rows, cols } = _grid()
    const w = ROWLABEL_W + cols * WELL_PITCH + _rightGutter()
    const h = _plateCount * (TITLE_H + HEADER_H + rows * WELL_PITCH) + (_plateCount - 1) * PLATE_GAP
    return { w, h }
  }

  // ── Coordinate conversion ─────────────────────────────────────────────────────
  function _cssToWorld(cx, cy) { return { wx: (cx - _panX) / _zoom, wy: (cy - _panY) / _zoom } }

  // world (wx,wy) → global well index, or null
  function _worldToWell(wx, wy) {
    const { rows, cols } = _grid()
    for (let p = 0; p < _plateCount; p++) {
      const x0 = ROWLABEL_W
      const y0 = _plateTopY(p) + TITLE_H + HEADER_H
      const gc = Math.floor((wx - x0) / WELL_PITCH)
      const gr = Math.floor((wy - y0) / WELL_PITCH)
      if (gc < 0 || gc >= cols || gr < 0 || gr >= rows) continue
      const { r, c } = _screenToRC(gr, gc)
      return p * PER_PLATE + _rcToWithin(r, c)
    }
    return null
  }

  // ── Drawing ───────────────────────────────────────────────────────────────────
  function _draw() {
    const dpr = canvasEl._dpr || 1
    const cssW = canvasEl.cssWidth || canvasEl.width
    const cssH = canvasEl.cssHeight || canvasEl.height
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, cssW, cssH)

    if (_strands.length === 0) {
      ctx.fillStyle = '#7a8fa0'
      ctx.font = '13px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('No staples in this design.', cssW / 2, cssH / 2)
      ctx.textAlign = 'start'
      return
    }

    ctx.setTransform(dpr * _zoom, 0, 0, dpr * _zoom, dpr * _panX, dpr * _panY)

    const { rows, cols } = _grid()
    // Inverse: global index occupant lookup.
    const occupant = new Map()       // globalIdx → strandId
    for (const [sid, idx] of _wellOf) occupant.set(idx, sid)

    // Frame spans the full per-plate content width incl. the side gutter that
    // holds the row labels (numbers on the right in 12x8) so they sit inside it.
    const frameW = ROWLABEL_W + cols * WELL_PITCH + _rightGutter()
    for (let p = 0; p < _plateCount; p++) {
      const topY = _plateTopY(p)
      // Plate frame
      ctx.fillStyle = CLR_PLATE_BG
      ctx.strokeStyle = CLR_PLATE_EDGE
      ctx.lineWidth = 1.5
      const frameY = topY + TITLE_H - 4
      const frameH = HEADER_H + rows * WELL_PITCH + 8
      _roundRect(0, frameY, frameW, frameH, 8)
      ctx.fill(); ctx.stroke()

      // Title
      ctx.fillStyle = CLR_TITLE
      ctx.font = TITLE_FONT
      ctx.textAlign = 'left'
      ctx.fillText(`Plate ${p + 1}`, ROWLABEL_W, topY + TITLE_H - 6)

      // Column headers (top): numbers 1–12 (8x12) or letters A–H (12x8).
      ctx.fillStyle = CLR_LABEL
      ctx.font = LABEL_FONT
      ctx.textAlign = 'center'
      for (let gc = 0; gc < cols; gc++) {
        const { r, c } = _screenToRC(0, gc)
        const lab = _orientation === '8x12' ? String(c + 1) : String.fromCharCode(65 + r)
        const cx = ROWLABEL_W + gc * WELL_PITCH + WELL_PITCH / 2
        ctx.fillText(lab, cx, topY + TITLE_H + HEADER_H - 6)
      }
      // Row headers: letters A–H on the LEFT (8x12), or numbers 1–12 on the
      // RIGHT (12x8 — the 90° CW-rotated view).
      const _onRight = _orientation === '12x8'
      const _labelX = _onRight ? ROWLABEL_W + cols * WELL_PITCH + ROWLABEL_W / 2 : ROWLABEL_W / 2
      for (let gr = 0; gr < rows; gr++) {
        const { r, c } = _screenToRC(gr, _onRight ? cols - 1 : 0)
        const lab = _onRight ? String(c + 1) : String.fromCharCode(65 + r)
        const cy = _plateTopY(p) + TITLE_H + HEADER_H + gr * WELL_PITCH + WELL_PITCH / 2
        ctx.fillText(lab, _labelX, cy + 4)
      }

      // Wells
      for (let gr = 0; gr < rows; gr++) {
        for (let gc = 0; gc < cols; gc++) {
          const { r, c } = _screenToRC(gr, gc)
          const gidx = p * PER_PLATE + _rcToWithin(r, c)
          const { x, y } = _wellCenter(p, gr, gc)
          const sid = occupant.get(gidx)
          ctx.beginPath()
          ctx.arc(x, y, WELL_R, 0, Math.PI * 2)
          if (sid) {
            const rec = _byId.get(sid)
            ctx.fillStyle = rec?.color || '#cccccc'
            ctx.fill()
            ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineWidth = 1; ctx.stroke()
            if (_selected.has(sid)) {
              ctx.beginPath(); ctx.arc(x, y, WELL_R + 3.5, 0, Math.PI * 2)
              ctx.strokeStyle = CLR_SEL_HALO; ctx.lineWidth = 4; ctx.stroke()
              ctx.beginPath(); ctx.arc(x, y, WELL_R + 3.5, 0, Math.PI * 2)
              ctx.strokeStyle = CLR_SEL_RING; ctx.lineWidth = 2; ctx.stroke()
            }
          } else {
            ctx.fillStyle = CLR_WELL_EMPTY; ctx.fill()
            ctx.strokeStyle = CLR_WELL_EDGE; ctx.lineWidth = 1; ctx.stroke()
          }
          // Drag-target outline
          if (_dropWell === gidx) {
            ctx.beginPath(); ctx.arc(x, y, WELL_R + 2, 0, Math.PI * 2)
            ctx.strokeStyle = CLR_DROP_RING; ctx.lineWidth = 2.5
            ctx.setLineDash([4, 3]); ctx.stroke(); ctx.setLineDash([])
          }
        }
      }
    }
    ctx.textAlign = 'start'
  }

  function _roundRect(x, y, w, h, r) {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.arcTo(x + w, y, x + w, y + h, r)
    ctx.arcTo(x + w, y + h, x, y + h, r)
    ctx.arcTo(x, y + h, x, y, r)
    ctx.arcTo(x, y, x + w, y, r)
    ctx.closePath()
  }

  // ── Auto-fill + segregation ───────────────────────────────────────────────────
  function _segregate() {
    const tubes = []
    const plated = []
    for (const s of _strands) {
      const longOligo = s.lengthNt > TUBE_LEN_THRESHOLD
      if (s.hasMod || longOligo) {
        const reason = (s.hasMod && longOligo) ? 'both' : (s.hasMod ? 'modification' : 'long')
        tubes.push({ s, reason })
      } else {
        plated.push(s)
      }
    }
    return { tubes, plated }
  }

  function _tubeReason(rec) {
    const longOligo = rec?.lengthNt > TUBE_LEN_THRESHOLD
    if (rec?.hasMod && longOligo) return 'both'
    if (rec?.hasMod) return 'modification'
    if (longOligo) return 'long'
    return 'manual'
  }

  function autoFill() {
    const { tubes, plated } = _segregate()
    plated.sort((a, b) => {
      if (a.groupOrder !== b.groupOrder) return a.groupOrder - b.groupOrder
      const ca = a.color || '', cb = b.color || ''
      if (ca !== cb) return ca < cb ? -1 : 1
      if (a.lengthNt !== b.lengthNt) return a.lengthNt - b.lengthNt
      return a.strandId < b.strandId ? -1 : (a.strandId > b.strandId ? 1 : 0)
    })
    _wellOf = new Map()
    plated.forEach((s, i) => _wellOf.set(s.strandId, i))
    _tubes = new Map(tubes.map(t => [t.s.strandId, t.reason]))
    _returnWellOf.clear()
    _plateCount = Math.max(1, Math.ceil(plated.length / PER_PLATE))
    _selected.clear()
    _renderTubes()
    _syncToolbar()
    _draw()
    _save()
  }

  // ── Manual moves ───────────────────────────────────────────────────────────────
  function _resolveUnit(strandId) {
    return _resolveUnitIn(_wellOf, strandId)
  }

  function _resolveUnitIn(source, strandId) {
    if (!strandId || !source.has(strandId)) return []
    if (_mode === 'staple') return [strandId]
    const rec = _byId.get(strandId)
    if (!rec) return [strandId]
    const key = _mode === 'color' ? 'color' : 'groupId'
    const val = rec[key]
    // Only members at the source location move; keep stable design order.
    return [...source.keys()]
      .filter(sid => (_byId.get(sid)?.[key]) === val)
      .sort((a, b) => _strands.findIndex(s => s.strandId === a) - _strands.findIndex(s => s.strandId === b))
  }

  function _recomputePlateCount() {
    let hi = -1
    for (const idx of _wellOf.values()) hi = Math.max(hi, idx)
    _plateCount = Math.max(1, Math.floor(Math.max(0, hi) / PER_PLATE) + 1)
  }

  function _finishTransfer(unit) {
    _selected = new Set(unit)
    _recomputePlateCount()
    _renderTubes()
    _syncToolbar()
    _draw()
    _save()
    return unit
  }

  /** Move the current staple/color/group unit from wells into tubes. */
  function sendToTubes(strandId) {
    const unit = _resolveUnitIn(_wellOf, strandId)
    if (!unit.length) return []
    for (const sid of unit) {
      const oldWell = _wellOf.get(sid)
      if (oldWell == null) continue
      _returnWellOf.set(sid, oldWell)
      _wellOf.delete(sid)
      _tubes.set(sid, _tubeReason(_byId.get(sid)))
    }
    return _finishTransfer(unit)
  }

  /** Move the current staple/color/group unit from tubes into open wells. */
  function sendToPlates(strandId) {
    const unit = _resolveUnitIn(_tubes, strandId)
    if (!unit.length) return []
    const occupied = new Set(_wellOf.values())
    let firstFree = 0
    const takeFirstFree = () => {
      while (occupied.has(firstFree)) firstFree += 1
      return firstFree
    }
    for (const sid of unit) {
      let dest = _returnWellOf.get(sid)
      if (!Number.isInteger(dest) || dest < 0 || occupied.has(dest)) dest = takeFirstFree()
      _wellOf.set(sid, dest)
      _tubes.delete(sid)
      _returnWellOf.delete(sid)
      occupied.add(dest)
    }
    return _finishTransfer(unit)
  }

  function _moveUnit(unit, fromWell, toWell) {
    if (!unit.length || fromWell == null || toWell == null || fromWell === toWell) return false
    const delta = toWell - fromWell
    // Old wells of unit members.
    const oldWells = new Map(unit.map(sid => [sid, _wellOf.get(sid)]))
    const unitSet = new Set(unit)
    // Current occupants by well (excluding unit members — they're being moved).
    const occ = new Map()
    for (const [sid, idx] of _wellOf) if (!unitSet.has(sid)) occ.set(idx, sid)
    // Grow plate count if the block lands past the last plate.
    let maxIdx = 0
    for (const sid of unit) maxIdx = Math.max(maxIdx, oldWells.get(sid) + delta)
    for (const [idx] of occ) maxIdx = Math.max(maxIdx, idx)
    _plateCount = Math.max(_plateCount, Math.floor(maxIdx / PER_PLATE) + 1)
    // Place unit at translated wells; displaced occupants fall into vacated wells.
    const next = new Map(occ)               // start from non-unit occupants
    for (const sid of unit) {
      const dest = oldWells.get(sid) + delta
      const displaced = next.get(dest)
      next.set(dest, sid)
      if (displaced && displaced !== sid) {
        next.set(oldWells.get(sid), displaced)   // swap into the vacated well
      }
    }
    // Rebuild _wellOf from the well→strand map.
    _wellOf = new Map()
    for (const [idx, sid] of next) _wellOf.set(sid, idx)
    // Recompute plate count from the densest occupied well.
    let hi = 0
    for (const idx of _wellOf.values()) hi = Math.max(hi, idx)
    _plateCount = Math.max(1, Math.floor(hi / PER_PLATE) + 1)
    return true
  }

  // ── Pointer handlers ─────────────────────────────────────────────────────────
  function _evtCss(ev) {
    const rect = canvasEl.getBoundingClientRect()
    return { cx: ev.clientX - rect.left, cy: ev.clientY - rect.top }
  }

  function _onPointerDown(ev) {
    const { cx, cy } = _evtCss(ev)
    if (ev.button === 1 || ev.button === 2) {        // pan
      if (ev.button === 2) _rightDown = { cx, cy }
      _panActive = true
      _panStartCX = cx; _panStartCY = cy; _panStartPanX = _panX; _panStartPanY = _panY
      canvasEl.setPointerCapture(ev.pointerId); ev.preventDefault()
      return
    }
    if (ev.button !== 0) return
    const { wx, wy } = _cssToWorld(cx, cy)
    const well = _worldToWell(wx, wy)
    const sid = _occupantAt(well)
    if (sid) {
      _selected = new Set(_resolveUnit(sid))
      onStrandClick?.(sid)
      _ldown = { strandId: sid, well, cx, cy, moved: false }
    } else {
      _selected.clear()
      onStrandClick?.(null)
      _ldown = null
    }
    _draw()
  }

  function _onPointerMove(ev) {
    const { cx, cy } = _evtCss(ev)
    if (_panActive) {
      _userAdjusted = true
      _panX = _panStartPanX + (cx - _panStartCX)
      _panY = _panStartPanY + (cy - _panStartCY)
      _draw(); return
    }
    if (_ldown) {
      if (!_ldown.moved && Math.hypot(cx - _ldown.cx, cy - _ldown.cy) > DRAG_THRESHOLD) _ldown.moved = true
      if (_ldown.moved) {
        const { wx, wy } = _cssToWorld(cx, cy)
        _dropWell = _worldToWell(wx, wy)
        _draw()
      }
      return
    }
    // Hover tooltip
    const { wx, wy } = _cssToWorld(cx, cy)
    const well = _worldToWell(wx, wy)
    const sid = _occupantAt(well)
    if (sid) {
      const rec = _byId.get(sid)
      const { plate, r, c } = _idxToPRC(well)
      _showTooltip(ev.clientX, ev.clientY,
        `${rec?.name ?? sid}\n${rec?.lengthNt ?? '?'} nt · Plate ${plate + 1} ${_wellLabel(r, c)}`)
    } else {
      _hideTooltip()
    }
  }

  function _onPointerUp(ev) {
    if (_panActive) { _panActive = false; try { canvasEl.releasePointerCapture(ev.pointerId) } catch {} return }
    if (_ldown && _ldown.moved && _dropWell != null) {
      const unit = _resolveUnit(_ldown.strandId)
      let changed
      if (_mode === 'staple') {
        // Move/swap a single staple.
        const occupantId = _occupantAt(_dropWell)
        if (occupantId && occupantId !== _ldown.strandId) {
          const a = _wellOf.get(_ldown.strandId)
          _wellOf.set(_ldown.strandId, _dropWell)
          _wellOf.set(occupantId, a)
          changed = true
        } else if (!occupantId) {
          _wellOf.set(_ldown.strandId, _dropWell)
          changed = true
        }
        if (changed) {
          _recomputePlateCount()
        }
      } else {
        changed = _moveUnit(unit, _ldown.well, _dropWell)
      }
      if (changed) { _renderTubes(); _syncToolbar(); _save() }
    }
    _ldown = null
    _dropWell = null
    _draw()
  }

  function _onPointerLeave() { if (!_panActive && !_ldown) _hideTooltip() }

  function _openTransferMenu(clientX, clientY, item) {
    _contextMenu?.close()
    _contextMenu = createContextMenu({
      x: clientX,
      y: clientY,
      items: [{
        label: item.location === 'well' ? 'Send to tubes' : 'Send to plates',
        onClick: () => item.location === 'well'
          ? sendToTubes(item.strandId)
          : sendToPlates(item.strandId),
      }],
      onClose: () => { _contextMenu = null },
    })
  }

  function _onContextMenu(ev) {
    const { cx, cy } = _evtCss(ev)
    if (_rightDown && Math.hypot(cx - _rightDown.cx, cy - _rightDown.cy) > DRAG_THRESHOLD) {
      _rightDown = null
      return
    }
    _rightDown = null
    const { wx, wy } = _cssToWorld(cx, cy)
    const sid = _occupantAt(_worldToWell(wx, wy))
    if (!sid) return
    _hideTooltip()
    _selected = new Set(_resolveUnitIn(_wellOf, sid))
    onStrandClick?.(sid)
    _draw()
    _openTransferMenu(ev.clientX, ev.clientY, { location: 'well', strandId: sid })
  }

  const _contextMenuHandler = deferrableContextMenu(canvasEl, _onContextMenu)

  function _onWheel(ev) {
    ev.preventDefault()
    const { cx, cy } = _evtCss(ev)
    const factor = ev.deltaY < 0 ? 1.15 : 0.87
    const nz = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, _zoom * factor))
    if (nz !== _zoom) {
      _userAdjusted = true
      _panX = cx - (cx - _panX) * (nz / _zoom)
      _panY = cy - (cy - _panY) * (nz / _zoom)
      _zoom = nz
      _draw()
    }
  }

  // ── Tooltip ────────────────────────────────────────────────────────────────────
  function _showTooltip(clientX, clientY, text) {
    if (!_tooltipEl) {
      _tooltipEl = document.createElement('div')
      _tooltipEl.style.cssText = 'position:fixed;z-index:9300;pointer-events:none;'
        + 'background:#161b22;border:1px solid #30363d;border-radius:4px;padding:5px 8px;'
        + 'font-family:monospace;font-size:11px;color:#c9d1d9;white-space:pre'
      document.body.appendChild(_tooltipEl)
    }
    _tooltipEl.textContent = text
    _tooltipEl.style.left = `${clientX + 12}px`
    _tooltipEl.style.top  = `${clientY + 12}px`
    _tooltipEl.style.display = 'block'
  }
  function _hideTooltip() { if (_tooltipEl) _tooltipEl.style.display = 'none' }

  // ── Tube list (IDT-ready) ──────────────────────────────────────────────────────
  function _renderTubes() {
    const host = getTubesContainer?.()
    if (!host) return
    host.classList.add('plate-tubes-panel')
    const rows = [..._tubes.entries()]
      .map(([sid, reason]) => ({ rec: _byId.get(sid), reason }))
      .filter(x => x.rec)
      .sort((a, b) => (a.rec.name || a.rec.strandId).localeCompare(b.rec.name || b.rec.strandId))

    if (rows.length === 0) {
      host.innerHTML = '<div class="plate-tubes-box"><div style="padding:8px;color:#7a8fa0;font-size:12px">'
        + 'No tubes — every staple fits in the plate.</div></div>'
      return
    }

    const reasonText = { modification: 'modified', long: '>60 nt', both: 'modified, >60 nt', manual: 'manual' }
    const head = `<div class="plate-tubes-header">
        <strong style="font-size:12px">Tubes (${rows.length})</strong>
        <button data-act="copy-all" style="font-size:11px;padding:2px 8px;cursor:pointer">Copy all (TSV)</button>
        <span style="font-size:11px;color:#7a8fa0">order at 250 nmol + HPLC</span>
      </div>`
    const body = rows.map(({ rec, reason }) => {
      const seq = rec.sequence || ''
      return `<tr data-strand-id="${_esc(rec.strandId)}" data-color="${_esc(rec.color || '')}" data-group-id="${_esc(rec.groupId || '')}">
        <td style="padding:3px 6px">${_esc(rec.name || rec.strandId)}</td>
        <td style="padding:3px 6px;font-family:monospace;font-size:11px;word-break:break-all">${_esc(seq)}</td>
        <td style="padding:3px 6px;text-align:right">${rec.lengthNt}</td>
        <td style="padding:3px 6px">${_esc(rec.modName || '—')}</td>
        <td style="padding:3px 6px;color:#7a8fa0">${reasonText[reason]}</td>
        <td style="padding:3px 6px">250 nmol</td>
        <td style="padding:3px 6px">HPLC</td>
        <td style="padding:3px 6px"><button data-copy="${_esc(seq)}" style="font-size:11px;cursor:pointer">⧉</button></td>
      </tr>`
    }).join('')
    host.innerHTML = `<div class="plate-tubes-box">${head}<div class="plate-tubes-scroll"><table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead><tr style="text-align:left;border-bottom:1px solid #d0d7de;color:#57606a">
          <th style="padding:3px 6px">Name</th><th style="padding:3px 6px">Sequence</th>
          <th style="padding:3px 6px">Len</th><th style="padding:3px 6px">Mod</th>
          <th style="padding:3px 6px">Reason</th><th style="padding:3px 6px">Scale</th>
          <th style="padding:3px 6px">Purif.</th><th></th></tr></thead>
        <tbody>${body}</tbody></table></div></div>`

    host.querySelector('[data-act="copy-all"]')?.addEventListener('click', () => {
      const tsv = rows.map(({ rec }) =>
        `${rec.name || rec.strandId}\t${rec.sequence || ''}\t250 nmol\tHPLC`).join('\n')
      navigator.clipboard?.writeText('Name\tSequence\tScale\tPurification\n' + tsv)
    })
    host.querySelectorAll('[data-copy]').forEach(btn =>
      btn.addEventListener('click', () => navigator.clipboard?.writeText(btn.getAttribute('data-copy'))))
    host.querySelectorAll('[data-strand-id]').forEach(row => {
      row.addEventListener('contextmenu', ev => {
        ev.preventDefault()
        ev.stopPropagation()
        const sid = row.getAttribute('data-strand-id')
        _selected = new Set(_resolveUnitIn(_tubes, sid))
        onStrandClick?.(sid)
        _draw()
        _openTransferMenu(ev.clientX, ev.clientY, { location: 'tube', strandId: sid })
      })
    })
  }

  function _esc(s) {
    return String(s).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]))
  }

  // ── Save ──────────────────────────────────────────────────────────────────────
  function _serialize() {
    const wells = []
    const placed = [..._wellOf.entries()].sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]))
    for (const [sid, idx] of placed) {
      const { plate, r, c } = _idxToPRC(idx)
      wells.push({ strand_id: sid, plate, row: r, col: c })
    }
    const tubes = [..._tubes.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([sid, reason]) => ({ strand_id: sid, reason }))
    return { orientation: _orientation, plate_count: _plateCount, wells, tubes }
  }
  function _save() { onSaveLayout?.(_serialize()) }

  // ── Toolbar ─────────────────────────────────────────────────────────────────
  let _statusEl = null, _modeBtn = null, _orientBtn = null
  function _buildToolbar() {
    if (!toolbarEl) return
    toolbarEl.innerHTML = ''
    toolbarEl.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px'
    const mk = (label, title) => {
      const b = document.createElement('button')
      b.textContent = label; if (title) b.title = title
      b.style.cssText = 'font-size:12px;padding:3px 8px;cursor:pointer'
      toolbarEl.appendChild(b); return b
    }
    const fillBtn = mk('Auto-fill', 'Arrange staples by group → colour → length')
    fillBtn.addEventListener('click', () => autoFill())
    _orientBtn = mk('8×12')
    _orientBtn.addEventListener('click', () => setOrientation(_orientation === '8x12' ? '12x8' : '8x12'))
    _modeBtn = mk('Mode: Staple', 'Cycle what a drag moves')
    _modeBtn.addEventListener('click', () => {
      const order = enableGroupMode ? ['staple', 'color', 'group'] : ['staple', 'color']
      setSelectionMode(order[(order.indexOf(_mode) + 1) % order.length])
    })
    const resetBtn = mk('Reset view')
    resetBtn.addEventListener('click', () => resetView())
    _statusEl = document.createElement('span')
    _statusEl.style.cssText = 'font-size:11px;color:#7a8fa0;margin-left:auto'
    toolbarEl.appendChild(_statusEl)
    _syncToolbar()
  }
  function _syncToolbar() {
    if (_orientBtn) _orientBtn.textContent = _orientation === '8x12' ? '8×12' : '12×8'
    if (_modeBtn) _modeBtn.textContent = 'Mode: ' + _mode.charAt(0).toUpperCase() + _mode.slice(1)
    if (_statusEl) {
      const plated = _wellOf.size, tubes = _tubes.size
      const placed = plated + tubes
      const unplaced = _strands.length - placed
      _statusEl.textContent = `${plated} plated · ${tubes} tubes`
        + (unplaced > 0 ? ` · ${unplaced} unplaced` : '')
    }
  }

  // ── Resize / fit ────────────────────────────────────────────────────────────
  function _resize() {
    const el = wrapEl || canvasEl
    const rect = el.getBoundingClientRect()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvasEl.width  = Math.max(1, Math.floor(rect.width * dpr))
    canvasEl.height = Math.max(1, Math.floor(rect.height * dpr))
    canvasEl._dpr = dpr
    canvasEl.cssWidth = rect.width
    canvasEl.cssHeight = rect.height
  }
  function resetView() {
    _resize()
    const cssW = canvasEl.cssWidth || 0, cssH = canvasEl.cssHeight || 0
    // Pane hidden / not laid out yet (e.g. sidebar mid-expand) — defer the fit;
    // the ResizeObserver re-fits once the canvas has a real size.
    if (cssW < 2 || cssH < 2) { _userAdjusted = false; return }
    const { w, h } = _worldSize()
    const pad = 16
    const zx = (cssW - pad * 2) / Math.max(1, w)
    const zy = (cssH - pad * 2) / Math.max(1, h)
    _zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.min(zx, zy)))
    _panX = (cssW - w * _zoom) / 2
    _panY = pad
    _userAdjusted = false
    _draw()
  }

  // ── Public methods ────────────────────────────────────────────────────────────
  function setData(strands, savedLayout) {
    _contextMenu?.close()
    _strands = Array.isArray(strands) ? strands.slice() : []
    _byId = new Map(_strands.map(s => [s.strandId, s]))
    const ids = new Set(_byId.keys())
    if (savedLayout && (savedLayout.wells?.length || savedLayout.tubes?.length)) {
      _orientation = savedLayout.orientation === '12x8' ? '12x8' : '8x12'
      _wellOf = new Map()
      for (const w of savedLayout.wells || []) {
        if (!ids.has(w.strand_id)) continue                 // prune stale
        _wellOf.set(w.strand_id, w.plate * PER_PLATE + _rcToWithin(w.row, w.col))
      }
      _tubes = new Map()
      for (const t of savedLayout.tubes || []) {
        if (ids.has(t.strand_id)) _tubes.set(t.strand_id, t.reason)
      }
      let hi = 0; for (const idx of _wellOf.values()) hi = Math.max(hi, idx)
      _plateCount = Math.max(savedLayout.plate_count || 1, Math.floor(hi / PER_PLATE) + 1)
    } else {
      _wellOf = new Map(); _tubes = new Map(); _plateCount = 1
    }
    _returnWellOf.clear()
    _selected.clear()
    _syncToolbar()
    _renderTubes()
    resetView()
  }

  function setOrientation(o) {
    const next = o === '12x8' ? '12x8' : '8x12'
    if (next === _orientation) return
    // Orientation is a pure display rotation: physical well addresses and the
    // fill order are unchanged — only the drawing + label placement rotate.
    _orientation = next
    _syncToolbar()
    resetView()
    _save()
  }

  function setSelectionMode(m) {
    if (m === 'group' && !enableGroupMode) m = 'staple'
    _mode = (m === 'color' || m === 'group') ? m : 'staple'
    _selected.clear()
    _syncToolbar()
    _draw()
  }

  // ── Wire events ───────────────────────────────────────────────────────────────
  canvasEl.addEventListener('pointerdown',  _onPointerDown)
  canvasEl.addEventListener('pointermove',  _onPointerMove)
  canvasEl.addEventListener('pointerup',    _onPointerUp)
  canvasEl.addEventListener('pointerleave', _onPointerLeave)
  canvasEl.addEventListener('contextmenu',  _contextMenuHandler)
  canvasEl.addEventListener('wheel',        _onWheel, { passive: false })
  if (wrapEl && typeof ResizeObserver !== 'undefined') {
    _resizeObs = new ResizeObserver(() => {
      _resize()
      const vis = (canvasEl.cssWidth || 0) >= 2 && (canvasEl.cssHeight || 0) >= 2
      if (!vis) { _userAdjusted = false; return }   // hidden → re-fit on next appearance
      // Auto-fit through the sidebar's width animation until the user pans/zooms.
      if (_userAdjusted) _draw()
      else resetView()
    })
    _resizeObs.observe(wrapEl)
  }
  _buildToolbar()

  return {
    setData,
    autoFill,
    setOrientation,
    setSelectionMode,
    sendToTubes,
    sendToPlates,
    getLayout: _serialize,
    resetView,
    destroy() {
      canvasEl.removeEventListener('pointerdown',  _onPointerDown)
      canvasEl.removeEventListener('pointermove',  _onPointerMove)
      canvasEl.removeEventListener('pointerup',    _onPointerUp)
      canvasEl.removeEventListener('pointerleave', _onPointerLeave)
      canvasEl.removeEventListener('contextmenu',  _contextMenuHandler)
      canvasEl.removeEventListener('wheel',        _onWheel)
      _resizeObs?.disconnect?.(); _resizeObs = null
      _contextMenu?.close(); _contextMenu = null
      _hideTooltip()
      if (_tooltipEl) { _tooltipEl.remove(); _tooltipEl = null }
    },
  }
}
