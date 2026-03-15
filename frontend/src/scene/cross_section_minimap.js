/**
 * Cross-section minimap — 2D canvas overlay shown in the upper-right corner
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

export function initCrossSectionMinimap(viewportContainer) {
  // ── DOM setup ─────────────────────────────────────────────────────────────

  const cv = document.createElement('canvas')
  cv.width  = SIZE
  cv.height = SIZE
  Object.assign(cv.style, {
    position:     'absolute',
    top:          '8px',
    right:        '8px',
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
    ctx.fillStyle    = DIM_CLR
    ctx.font         = '9px monospace'
    ctx.textAlign    = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText(TITLE, 8, 7)

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

        if (sx < -helixR - 2 || sx > SIZE + helixR + 2 ||
            sy < -helixR - 2 || sy > SIZE + helixR + 2) continue

        // Glow for highlighted helices
        if (hl) {
          ctx.save()
          ctx.shadowColor = RING_HL
          ctx.shadowBlur  = 10
        }

        ctx.beginPath()
        ctx.arc(sx, sy, helixR, 0, Math.PI * 2)
        ctx.fillStyle   = hl ? FILL_HL   : FILL_CLR
        ctx.fill()
        ctx.strokeStyle = hl ? RING_HL   : RING_CLR
        ctx.lineWidth   = hl ? 2.0 : 1.5
        ctx.stroke()

        if (hl) ctx.restore()

        // Number label — font size scales with circle, clamped for readability
        const num = String(i + 1)
        const fsz = Math.min(12, Math.max(7, helixR * 0.9)) * (num.length > 2 ? 0.75 : 1)
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
        cv.style.display = 'none'
      }
    } else if (newState.unfoldActive && (designChanged || selChanged)) {
      _draw()
    }
  })

  // ── Dispose ───────────────────────────────────────────────────────────────

  return {
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
