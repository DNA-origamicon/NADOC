/**
 * Zoom scope — circular magnifier lens for the cadnano editor.
 *
 * Mirrors the UX of `frontend/src/scene/zoom_scope.js` (the main 3D app's
 * Space-held magnifier): a 240 px circular overlay tracking the cursor that
 * shows the cell region around the cursor at higher zoom for fine-grained
 * selection.
 *
 * Implementation: native re-render via `pathview.drawToLens(...)`. The lens
 * gets a sharp magnified image because the world geometry is re-rasterized
 * at the lens transform onto the lens canvas, rather than upscaling pixels
 * from the main canvas (which would be capped at the source's resolution).
 *
 * The lens is purely visual — clicks pass through (`pointer-events:none`)
 * to the underlying canvas, so selection logic is unchanged. The crosshair
 * SVG inside the lens marks the click point.
 */

const LENS_SIZE  = 240
const ZOOM       = 3.5            // magnification factor — matches the 3D scope
const R          = LENS_SIZE / 2
const CL         = 22
// Internal lens-canvas pixel ratio — render at this multiple of the CSS size
// for crisp lines on high-DPI displays. The lens canvas is purely-internal,
// so we can pick a high ratio without affecting the main view.
const LENS_DPR   = Math.max(2, Math.round(window.devicePixelRatio || 1) * 2)

export function initZoomScope(canvas, pathview) {
  // ── Lens DOM ────────────────────────────────────────────────────────────
  const lens = document.createElement('div')
  lens.style.cssText = [
    'position:fixed',
    `width:${LENS_SIZE}px`,
    `height:${LENS_SIZE}px`,
    'border-radius:50%',
    'border:1.5px solid rgba(255,255,255,0.25)',
    'box-shadow:0 0 0 1px rgba(0,0,0,0.6),0 6px 28px rgba(0,0,0,0.55)',
    'overflow:hidden',
    'pointer-events:none',
    'display:none',
    'z-index:9999',
    'transform:translate(-50%,-50%)',
    'will-change:transform',
  ].join(';')

  const lensCanvas = document.createElement('canvas')
  lensCanvas.width  = LENS_SIZE * LENS_DPR
  lensCanvas.height = LENS_SIZE * LENS_DPR
  lensCanvas.style.cssText = `position:absolute;top:0;left:0;width:${LENS_SIZE}px;height:${LENS_SIZE}px;`
  lens.appendChild(lensCanvas)

  // Crosshair overlay
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', `0 0 ${LENS_SIZE} ${LENS_SIZE}`)
  svg.style.cssText = `position:absolute;top:0;left:0;width:${LENS_SIZE}px;height:${LENS_SIZE}px;pointer-events:none;`
  svg.innerHTML = `
    <line x1="${R}" y1="${R - CL}" x2="${R}" y2="${R + CL}" stroke="rgba(0,0,0,0.85)" stroke-width="1.25"/>
    <line x1="${R - CL}" y1="${R}" x2="${R + CL}" y2="${R}" stroke="rgba(0,0,0,0.85)" stroke-width="1.25"/>
    <circle cx="${R}" cy="${R}" r="3.5" stroke="rgba(0,0,0,0.75)" stroke-width="1.25" fill="none"/>
  `
  lens.appendChild(svg)
  document.body.appendChild(lens)

  // ── State ───────────────────────────────────────────────────────────────
  let _active = false
  let _rafId  = null
  let _cx = 0, _cy = 0
  let _dirty  = true   // redraw needed on next frame

  // ── Lens redraw loop ────────────────────────────────────────────────────
  function _drawFrame() {
    if (!_active) return
    _rafId = requestAnimationFrame(_drawFrame)

    const rect = canvas.getBoundingClientRect()
    const localX = _cx - rect.left
    const localY = _cy - rect.top
    if (localX < 0 || localX > rect.width || localY < 0 || localY > rect.height) {
      lens.style.display = 'none'
      return
    }
    if (lens.style.display !== 'block') lens.style.display = 'block'
    if (!_dirty) return
    _dirty = false

    // Pull the main view's current zoom/pan from pathview so we can compute
    // the world-space point under the cursor and produce a lens transform
    // that places it at the lens canvas centre at lens magnification.
    const mainZoom = pathview.getZoom()
    const mainPanX = pathview.getPanX()
    const mainPanY = pathview.getPanY()
    // Local cursor coords are in the canvas's CSS pixels. The canvas's
    // pixel buffer matches its CSS size (no DPR), so:
    const wx = (localX - mainPanX) / mainZoom
    const wy = (localY - mainPanY) / mainZoom

    const lensZoom = mainZoom * ZOOM * LENS_DPR
    // Lens canvas centre is at (LENS_SIZE/2 * LENS_DPR, LENS_SIZE/2 * LENS_DPR)
    // in lens-pixel space; we want world point (wx, wy) to land there.
    const lensCenterPx = (LENS_SIZE / 2) * LENS_DPR
    const lensPanX = lensCenterPx - wx * lensZoom
    const lensPanY = lensCenterPx - wy * lensZoom

    pathview.drawToLens(lensCanvas, lensZoom, lensPanX, lensPanY)
  }

  function _positionLens() {
    lens.style.left = _cx + 'px'
    lens.style.top  = _cy + 'px'
    _dirty = true
  }

  function _activate() {
    if (_active) return
    _active = true
    _dirty = true
    canvas.style.cursor = 'none'
    _positionLens()
    _rafId = requestAnimationFrame(_drawFrame)
  }

  function _deactivate() {
    if (!_active) return
    _active = false
    canvas.style.cursor = ''
    lens.style.display = 'none'
    if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null }
  }

  // ── Input ───────────────────────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (e.repeat || e.key !== ' ') return
    const t = e.target
    const inEditable = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
    if (inEditable) return
    e.preventDefault()
    _activate()
  })
  document.addEventListener('keyup', e => {
    if (e.key !== ' ') return
    _deactivate()
  })
  window.addEventListener('blur', _deactivate)
  document.addEventListener('mousemove', e => {
    _cx = e.clientX
    _cy = e.clientY
    if (_active) _positionLens()
  })

  return { isActive: () => _active }
}
