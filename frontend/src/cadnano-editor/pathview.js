/**
 * Pathview — Canvas 2D strand editor.
 *
 * Renders each helix as a double-track row (FORWARD top, REVERSE bottom).
 * Scaffold and staple strands are painted as filled rectangles.
 * The pencil tool allows click+drag to draw scaffold domain segments.
 *
 * Phase 1 stub — renders the canvas container and wires up the design.
 * Full rendering and interaction is implemented in Commit 4.
 */

export function initPathview(canvasEl, containerEl, { onPaintScaffold, onStrandHover }) {
  const ctx = canvasEl.getContext('2d')

  // Size the canvas to the container
  function _resize() {
    canvasEl.width  = containerEl.clientWidth  || 800
    canvasEl.height = containerEl.clientHeight || 400
    _draw()
  }
  new ResizeObserver(_resize).observe(containerEl)
  _resize()

  let _design = null

  function _draw() {
    ctx.clearRect(0, 0, canvasEl.width, canvasEl.height)
    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, canvasEl.width, canvasEl.height)

    if (!_design?.helices?.length) {
      ctx.fillStyle = '#444'
      ctx.font = '11px Courier New, monospace'
      ctx.textAlign = 'center'
      ctx.fillText('No helices — add helices in the Slice View', canvasEl.width / 2, 60)
      return
    }

    // Placeholder — real rendering implemented in Commit 4
    ctx.fillStyle = '#444'
    ctx.font = '11px Courier New, monospace'
    ctx.textAlign = 'left'
    ctx.fillText(`${_design.helices.length} helix(es) — pathview rendering coming in Commit 4`, 12, 30)
  }

  return {
    /**
     * Redraw the pathview for the given design.
     * @param {object|null} design
     */
    update(design) {
      _design = design
      _draw()
    },
  }
}
