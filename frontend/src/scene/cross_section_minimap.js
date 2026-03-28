/**
 * Cross-section minimap — 2D canvas overlay shown in the lower-right corner
 * of the viewport whenever the 2D unfold view is active.
 *
 * Displays the helical cross-section at bp=0 (axis_start positions) as a
 * top-down XY view.  Each helix is drawn as a numbered circle sized so that
 * adjacent helices in the honeycomb lattice nearly touch (radius = 1.125 nm
 * in world space, which is exactly the honeycomb lattice radius).
 *
 * Helices touched by the currently selected strand or nucleotide are
 * highlighted in amber.
 *
 * Interaction:
 *   - Auto-zooms to fit all helices with padding on first display.
 *   - Drag to pan within the minimap.
 *   - Double-click to reset pan.
 *   - All pointer events are consumed so they don't reach OrbitControls.
 *
 * Usage:
 *   const minimap = initCrossSectionMinimap(viewportContainerEl)
 *   // self-manages visibility via store subscription
 *   minimap.dispose()
 */

import { store } from '../state/store.js'

// World-space helix radius (nm).  Honeycomb lattice radius = 1.125 nm, so
// circles at adjacent helices will nearly touch.
const HELIX_WORLD_R  = 1.125

const SIZE           = 224          // px — square canvas side length
const PADDING        = 24           // px — inner margin so edge circles aren't clipped
const SCALE_MAX      = 48           // px/nm — cap so single-helix fills at most ~48px
const BG_COLOR       = 'rgba(13, 17, 23, 0.90)'
const BORDER_CLR     = '#30363d'
const RING_CLR       = '#29b6f6'    // sky blue — matches scaffold colour
const FILL_CLR       = '#0d1f2d'
const RING_HL        = '#ffa726'    // amber — highlighted helix ring
const FILL_HL        = '#2d1800'    // dark amber fill for highlighted helices
const LABEL_CLR      = '#c9d1d9'
const LABEL_HL       = '#ffe082'    // bright amber label for highlighted helices
const DIM_CLR        = '#484f58'
const TITLE          = 'CROSS SECTION · bp 0'
const RISE_NM           = 0.334
const RING_CLR_DIM      = '#1a3a4a'            // dimmed ring when slice active but no scaffold
const FILL_CLR_DIM      = '#0a1318'            // dimmed fill when slice active but no scaffold
const SCAFFOLD_RING_CLR = '#fcba03'            // gold — matches free-cell colour in extrusion lattice
const SCAFFOLD_FILL_CLR = 'rgba(252,186,3,0.13)'  // semi-transparent gold fill
const SCAFFOLD_ARROW_CLR = '#58a6ff'           // blue — matches selection colour


export function initCrossSectionMinimap(viewportContainer) {
  // ── DOM setup ─────────────────────────────────────────────────────────────

  const cv = document.createElement('canvas')
  cv.width  = SIZE
  cv.height = SIZE
  Object.assign(cv.style, {
    position:     'absolute',
    bottom:       '8px',
    left:         '8px',
    width:        `${SIZE}px`,
    height:       `${SIZE}px`,
    display:      'none',
    border:       `1px solid ${BORDER_CLR}`,
    borderRadius: '6px',
    cursor:       'grab',
    zIndex:       '20',
    userSelect:   'none',
  })
  viewportContainer.appendChild(cv)

  const ctx = cv.getContext('2d')

  // ── State ─────────────────────────────────────────────────────────────────

  let _design           = null
  let _panX             = 0
  let _panY             = 0
  let _fitCx            = 0     // world-space centre used by current fit
  let _fitCy            = 0
  let _fitScale         = 1     // px per nm
  let _highlightedIds   = new Set()  // helix IDs to highlight
  let _sliceOffsetNm    = null       // nm — set when slice plane is active; null = inactive
  let _slicePlane       = null       // 'XY' | 'XZ' | 'YZ'
  // TODO(physics): entry.pos is kept live by helix_renderer (updated by physics/deform passes),
  // so these arrows will follow physically-relaxed positions once we wire up physics redraw here.
  let _backboneEntries  = []         // backbone entries from designRenderer — used for phase arrows

  // ── Highlight computation ─────────────────────────────────────────────────

  /**
   * Given the current selectedObject and design, return a Set of helix IDs
   * that belong to the selected strand (all its domains' helices).
   */
  function _computeHighlights(sel, design) {
    if (!sel || !design) return new Set()

    let strandId = null
    if (sel.type === 'strand' || sel.type === 'cone') {
      strandId = sel.data?.strand_id ?? null
    } else if (sel.type === 'nucleotide') {
      strandId = sel.data?.strand_id ?? null
    }

    if (!strandId) {
      // Nucleotide selection may not carry strand_id — fall back to single helix
      if (sel.type === 'nucleotide' && sel.data?.helix_id) {
        return new Set([sel.data.helix_id])
      }
      return new Set()
    }

    const strand = design.strands?.find(s => s.id === strandId)
    if (!strand) return new Set()
    return new Set(strand.domains.map(d => d.helix_id))
  }

  // ── Slice data ────────────────────────────────────────────────────────────

  /**
   * For each helix, determine if scaffold / staples pass through it at the
   * current slice offset, and compute the backbone phase angle (radians) at
   * that cross-section.  Returns a map of helix_id → { hasScaffold,
   * scaffoldPhase, staples: [{phase, color}] }.
   */
  function _getSliceData() {
    if (_sliceOffsetNm === null || !_design) return {}
    const normalAxis = { XY: 'z', XZ: 'y', YZ: 'x' }[_slicePlane] ?? 'z'

    // Build lookup: "helixId::bpIndex" → backbone entry, keyed by nuc.direction so we can
    // find both FORWARD and REVERSE beads at the same bp independently.
    const entryMap = new Map()  // key → { FORWARD: entry, REVERSE: entry }
    for (const entry of _backboneEntries) {
      const key = `${entry.nuc.helix_id}::${entry.nuc.bp_index}`
      if (!entryMap.has(key)) entryMap.set(key, {})
      entryMap.get(key)[entry.nuc.direction] = entry
    }

    const result = {}

    for (const helix of (_design.helices ?? [])) {
      const z0 = helix.axis_start[normalAxis]
      const bp = Math.round(helix.bp_start + (_sliceOffsetNm - z0) / RISE_NM)
      if (bp < helix.bp_start || bp >= helix.bp_start + helix.length_bp) continue

      // Walk the topology to find which strands are present at this helix+bp,
      // and which DNA-strand position (FORWARD/REVERSE) each domain occupies.
      // Phase is then read directly from the 3D backbone bead position.
      const dominated = {}   // 'FORWARD' | 'REVERSE' → { strand_type, defaultColor }
      for (const strand of (_design.strands ?? [])) {
        for (const domain of (strand.domains ?? [])) {
          if (domain.helix_id !== helix.id) continue
          const lo = Math.min(domain.start_bp, domain.end_bp)
          const hi = Math.max(domain.start_bp, domain.end_bp)
          if (bp < lo || bp > hi) continue
          // Traversal direction determines which DNA-strand position this domain occupies.
          // start_bp < end_bp → FORWARD position; start_bp > end_bp → REVERSE position.
          const dnaPos = domain.start_bp <= domain.end_bp ? 'FORWARD' : 'REVERSE'
          dominated[dnaPos] = { strand_type: strand.strand_type }
        }
      }

      const bpEntries = entryMap.get(`${helix.id}::${bp}`)
      if (!bpEntries) continue

      const data = { hasScaffold: false, scaffoldPhase: 0, staples: [] }

      // The minimap always lays out helices in world XY regardless of _slicePlane.
      const axisX = helix.axis_start.x
      const axisY = helix.axis_start.y

      for (const dnaPos of ['FORWARD', 'REVERSE']) {
        const info  = dominated[dnaPos]
        const entry = bpEntries[dnaPos]
        if (!info || !entry) continue

        // Arrow direction: vector from helix axis centre to the 3D backbone bead,
        // projected into the XY plane.  Use the geometry-build-time position
        // (nuc.backbone_position) rather than entry.pos so that unfold-view
        // offsets (which translate every helix to x=0) don't corrupt the angle.
        const phase = Math.atan2(
          entry.nuc.backbone_position[1] - axisY,
          entry.nuc.backbone_position[0] - axisX,
        )

        if (info.strand_type === 'scaffold') {
          data.hasScaffold   = true
          data.scaffoldPhase = phase
        } else {
          const color = '#' + entry.defaultColor.toString(16).padStart(6, '0')
          data.staples.push({ phase, color })
        }
      }

      if (data.hasScaffold || data.staples.length > 0) result[helix.id] = data
    }
    return result
  }

  // ── Fit ───────────────────────────────────────────────────────────────────

  function _resetFit(helices) {
    if (!helices?.length) return
    let minX = Infinity, maxX = -Infinity
    let minY = Infinity, maxY = -Infinity
    for (const h of helices) {
      const x = h.axis_start.x
      const y = h.axis_start.y
      if (x < minX) minX = x; if (x > maxX) maxX = x
      if (y < minY) minY = y; if (y > maxY) maxY = y
    }
    const drawArea = SIZE - PADDING * 2
    const rangeX   = maxX - minX || 1
    const rangeY   = maxY - minY || 1
    _fitScale = Math.min(drawArea / rangeX, drawArea / rangeY, SCALE_MAX)
    _fitCx    = (minX + maxX) / 2
    _fitCy    = (minY + maxY) / 2
    _panX     = 0
    _panY     = 0
  }

  // ── Draw ──────────────────────────────────────────────────────────────────

  function _draw() {
    ctx.clearRect(0, 0, SIZE, SIZE)

    // Background panel
    ctx.fillStyle = BG_COLOR
    _roundRect(ctx, 0, 0, SIZE, SIZE, 6)
    ctx.fill()

    // Title
    const titleText = _sliceOffsetNm !== null
      ? `CROSS SECTION · bp ${Math.round(_sliceOffsetNm / RISE_NM)}`
      : TITLE
    ctx.fillStyle    = DIM_CLR
    ctx.font         = '9px monospace'
    ctx.textAlign    = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText(titleText, 8, 7)

    const helices = _design?.helices
    if (!helices?.length) {
      ctx.fillStyle    = DIM_CLR
      ctx.font         = '10px monospace'
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('no design', SIZE / 2, SIZE / 2)
      return
    }

    const s       = _fitScale
    const helixR  = Math.max(6, s * HELIX_WORLD_R)  // px
    const originX = SIZE / 2 + _panX
    const originY = SIZE / 2 + _panY

    // Faint cross-hairs at the world origin
    ctx.strokeStyle = 'rgba(48,54,61,0.5)'
    ctx.lineWidth   = 0.5
    ctx.beginPath()
    ctx.moveTo(originX, 0); ctx.lineTo(originX, SIZE)
    ctx.moveTo(0, originY); ctx.lineTo(SIZE, originY)
    ctx.stroke()

    const sliceActive = _sliceOffsetNm !== null
    const sliceData   = sliceActive ? _getSliceData() : {}

    // Draw normal helices first, then highlighted ones on top
    const normal     = []
    const highlighted = []
    for (let i = 0; i < helices.length; i++) {
      (_highlightedIds.has(helices[i].id) ? highlighted : normal).push(i)
    }

    for (const pass of [normal, highlighted]) {
      for (const i of pass) {
        const h   = helices[i]
        const wx  = h.axis_start.x
        const wy  = h.axis_start.y
        const sx  = originX + (wx - _fitCx) * s
        const sy  = originY - (wy - _fitCy) * s  // flip Y
        const hl  = _highlightedIds.has(h.id)
        const sd  = sliceData[h.id]

        if (sx < -helixR - 2 || sx > SIZE + helixR + 2 ||
            sy < -helixR - 2 || sy > SIZE + helixR + 2) continue

        // Glow for highlighted helices
        if (hl) {
          ctx.save()
          ctx.shadowColor = RING_HL
          ctx.shadowBlur  = 10
        }

        const fillClr = hl ? FILL_HL
          : (sd?.hasScaffold ? SCAFFOLD_FILL_CLR : (sliceActive ? FILL_CLR_DIM : FILL_CLR))
        const ringClr = hl ? RING_HL
          : (sd?.hasScaffold ? SCAFFOLD_RING_CLR : (sliceActive ? RING_CLR_DIM : RING_CLR))

        ctx.beginPath()
        ctx.arc(sx, sy, helixR, 0, Math.PI * 2)
        ctx.fillStyle   = fillClr
        ctx.fill()
        ctx.strokeStyle = ringClr
        ctx.lineWidth   = (hl || sd?.hasScaffold) ? 2.0 : 1.5
        ctx.stroke()

        if (hl) ctx.restore()
      }
    }

    // Phase arrow pass — drawn on top of all circles
    if (sliceActive) {
      const arrowLen = Math.max(4, helixR * 0.75)
      for (const h of helices) {
        const sd = sliceData[h.id]
        if (!sd) continue
        const sx = originX + (h.axis_start.x - _fitCx) * s
        const sy = originY - (h.axis_start.y - _fitCy) * s
        if (sx < -helixR - 4 || sx > SIZE + helixR + 4 ||
            sy < -helixR - 4 || sy > SIZE + helixR + 4) continue
        if (sd.hasScaffold) {
          _drawPhaseArrow(sx, sy, sd.scaffoldPhase, arrowLen, SCAFFOLD_ARROW_CLR, 1.5)
        }
        for (const st of sd.staples) {
          _drawPhaseArrow(sx, sy, st.phase, arrowLen * 0.85, st.color, 1.5)
        }
      }
    }

    // Number label pass — drawn last so labels appear over arrows
    for (const pass of [normal, highlighted]) {
      for (const i of pass) {
        const h  = helices[i]
        const sx = originX + (h.axis_start.x - _fitCx) * s
        const sy = originY - (h.axis_start.y - _fitCy) * s
        if (sx < -helixR - 2 || sx > SIZE + helixR + 2 ||
            sy < -helixR - 2 || sy > SIZE + helixR + 2) continue
        const hl  = _highlightedIds.has(h.id)
        const num = String(i)
        const fsz = Math.min(14, Math.max(9, helixR * 1.1)) * (num.length > 2 ? 0.75 : 1)
        ctx.fillStyle    = hl ? LABEL_HL : LABEL_CLR
        ctx.font         = `bold ${fsz.toFixed(1)}px monospace`
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(num, sx, sy)
      }
    }

    // Scale bar — 1 nm width
    const barPx = s
    if (barPx >= 4) {
      const bx = 8
      const by = SIZE - 10
      ctx.strokeStyle = '#58a6ff'
      ctx.lineWidth   = 1.5
      ctx.beginPath()
      ctx.moveTo(bx, by); ctx.lineTo(bx + barPx, by)
      ctx.moveTo(bx, by - 3); ctx.lineTo(bx, by + 3)
      ctx.moveTo(bx + barPx, by - 3); ctx.lineTo(bx + barPx, by + 3)
      ctx.stroke()
      ctx.fillStyle    = DIM_CLR
      ctx.font         = '8px monospace'
      ctx.textAlign    = 'left'
      ctx.textBaseline = 'bottom'
      ctx.fillText('1 nm', bx + barPx + 4, by + 4)
    }
  }

  // ── Phase arrow ───────────────────────────────────────────────────────────

  function _drawPhaseArrow(cx, cy, phase, len, color, lineWidth) {
    const dx =  Math.cos(phase) * len
    const dy = -Math.sin(phase) * len   // flip Y: world +Y → canvas -Y
    const ex = cx + dx
    const ey = cy + dy
    ctx.save()
    ctx.strokeStyle = color
    ctx.fillStyle   = color
    ctx.lineWidth   = lineWidth
    ctx.lineCap     = 'round'
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(ex, ey)
    ctx.stroke()
    const angle   = Math.atan2(dy, dx)
    const headLen = Math.max(3, len * 0.32)
    ctx.beginPath()
    ctx.moveTo(ex, ey)
    ctx.lineTo(ex - headLen * Math.cos(angle - Math.PI / 6), ey - headLen * Math.sin(angle - Math.PI / 6))
    ctx.lineTo(ex - headLen * Math.cos(angle + Math.PI / 6), ey - headLen * Math.sin(angle + Math.PI / 6))
    ctx.closePath()
    ctx.fill()
    ctx.restore()
  }

  // ── Pan interaction ───────────────────────────────────────────────────────

  let _dragging = false
  let _dragX    = 0
  let _dragY    = 0

  function _onPointerDown(e) {
    e.stopPropagation()
    e.preventDefault()
    _dragging = true
    _dragX    = e.clientX
    _dragY    = e.clientY
    cv.style.cursor = 'grabbing'
    cv.setPointerCapture(e.pointerId)
  }

  function _onPointerMove(e) {
    if (!_dragging) return
    e.stopPropagation()
    _panX += e.clientX - _dragX
    _panY += e.clientY - _dragY
    _dragX = e.clientX
    _dragY = e.clientY
    _draw()
  }

  function _onPointerUp(e) {
    if (!_dragging) return
    e.stopPropagation()
    _dragging = false
    cv.style.cursor = 'grab'
  }

  function _onDblClick(e) {
    e.stopPropagation()
    _panX = 0
    _panY = 0
    _draw()
  }

  function _onWheel(e) {
    e.stopPropagation()
    e.preventDefault()
    const rect   = cv.getBoundingClientRect()
    const mouseX = e.clientX - rect.left   // px relative to canvas
    const mouseY = e.clientY - rect.top
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
    // Keep the world point under the cursor fixed: adjust pan so that point
    // stays at the same screen position after the scale change.
    _panX = mouseX - (mouseX - _panX) * factor
    _panY = mouseY - (mouseY - _panY) * factor
    _fitScale = Math.min(Math.max(_fitScale * factor, 2), 300)
    _draw()
  }

  cv.addEventListener('pointerdown',   _onPointerDown)
  cv.addEventListener('pointermove',   _onPointerMove)
  cv.addEventListener('pointerup',     _onPointerUp)
  cv.addEventListener('pointercancel', _onPointerUp)
  cv.addEventListener('dblclick',      _onDblClick)
  cv.addEventListener('wheel',         _onWheel, { passive: false })

  // ── Store subscription ────────────────────────────────────────────────────

  const _unsub = store.subscribe((newState, prevState) => {
    const activeChanged  = newState.unfoldActive    !== prevState.unfoldActive
    const designChanged  = newState.currentDesign   !== prevState.currentDesign
    const selChanged     = newState.selectedObject  !== prevState.selectedObject

    if (designChanged) {
      _design = newState.currentDesign
      _resetFit(_design?.helices)
    }

    if (selChanged || designChanged) {
      _highlightedIds = _computeHighlights(newState.selectedObject, newState.currentDesign)
    }

    if (activeChanged) {
      if (newState.unfoldActive) {
        if (!designChanged) {
          _design = newState.currentDesign
          _resetFit(_design?.helices)
        }
        if (!selChanged && !designChanged) {
          _highlightedIds = _computeHighlights(newState.selectedObject, newState.currentDesign)
        }
        cv.style.display = 'block'
        _draw()
      } else {
        // Only hide if the slice plane is also inactive.  When the user exits
        // unfold while a slice volume is still shown, the minimap should stay.
        if (_sliceOffsetNm === null) cv.style.display = 'none'
      }
    } else if ((newState.unfoldActive || _sliceOffsetNm !== null) && (designChanged || selChanged)) {
      _draw()
    }
  })

  // ── Dispose ───────────────────────────────────────────────────────────────

  return {
    show() {
      _design = store.getState().currentDesign
      _resetFit(_design?.helices)
      _highlightedIds = _computeHighlights(store.getState().selectedObject, _design)
      cv.style.display = 'block'
      _draw()
    },
    hide() {
      _sliceOffsetNm = null
      _slicePlane    = null
      cv.style.display = 'none'
    },
    /** Called by the slice plane on every offset change (read-only mode). */
    update(offsetNm, plane, backboneEntries) {
      _sliceOffsetNm   = offsetNm
      _slicePlane      = plane
      _design          = store.getState().currentDesign
      _backboneEntries = backboneEntries ?? []
      _draw()
    },
    /** Clear slice state and redraw (called when slice plane is hidden). */
    clearSlice() {
      _sliceOffsetNm   = null
      _slicePlane      = null
      _backboneEntries = []
      if (cv.style.display !== 'none') _draw()
    },
    dispose() {
      _unsub()
      cv.removeEventListener('pointerdown',   _onPointerDown)
      cv.removeEventListener('pointermove',   _onPointerMove)
      cv.removeEventListener('pointerup',     _onPointerUp)
      cv.removeEventListener('pointercancel', _onPointerUp)
      cv.removeEventListener('dblclick',      _onDblClick)
      cv.removeEventListener('wheel',         _onWheel)
      viewportContainer.removeChild(cv)
    },
  }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _roundRect(ctx, x, y, w, h, r) {
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(x, y, w, h, r)
  } else {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.lineTo(x + w - r, y)
    ctx.quadraticCurveTo(x + w, y, x + w, y + r)
    ctx.lineTo(x + w, y + h - r)
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
    ctx.lineTo(x + r, y + h)
    ctx.quadraticCurveTo(x, y + h, x, y + h - r)
    ctx.lineTo(x, y + r)
    ctx.quadraticCurveTo(x, y, x + r, y)
    ctx.closePath()
  }
}
