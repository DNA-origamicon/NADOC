/**
 * Sliceview — SVG lattice grid for helix activation/deactivation.
 *
 * Renders an HC or SQ lattice as SVG circles.  Pan/zoom is delegated entirely
 * to the svg-pan-zoom library.
 *
 * Left-click empty cell  → add helix
 * Left-click filled cell → remove helix
 * Scroll wheel           → zoom (svg-pan-zoom default)
 * Click+drag             → pan  (svg-pan-zoom default)
 *
 * Each occupied helix circle shows:
 *   • A numeric label (design.helices index — user-determined creation order)
 *   • A translucent phase arrow that rotates as the slice bar moves
 *     Phase is driven by setSliceBp(bp) called from pathview.
 */

// svg-pan-zoom is loaded as a UMD global via <script src="/svg-pan-zoom.js">
/* global svgPanZoom */

// ── Constants ─────────────────────────────────────────────────────────────────
// Orientation modes
//   NATIVE  — cadnano2 SVG convention: row 0 at top, Y increases downward.
//             Phase angles follow the cadnano2 Qt sliceview formula.
//   WORLD3D — true 3D XY-plane view from +Z: row 0 at bottom, Y increases upward.
//             Phase angles match backbone positions as seen in the 3D viewport.

const HC_R         = 1.125
const HC_COL_PITCH = HC_R * Math.sqrt(3)
const HC_ROW_PITCH = 3 * HC_R
const SQ_PITCH     = 2.25

const SCALE        = 50
const CELL_R_NM    = 0.35 * 2.25
const CELL_R       = CELL_R_NM * SCALE          // ≈ 39 px in SVG content space
const GRID_MARGIN  = 15

const DEFAULT_ROWS = [-2, 17]
const DEFAULT_COLS = [-2, 17]

// Phase constants (from backend/core/constants.py)
const HC_TWIST_PER_BP_DEG = 34.3     // BDNA_TWIST_PER_BP_DEG
const SQ_TWIST_PER_BP_DEG = 33.75   // SQUARE_TWIST_PER_BP_DEG
const MINOR_GROOVE_DEG    = 150      // caDNAno convention

// Half-bp-twist Holliday Junction correction applied to the 3D backbone but NOT
// to the cadnano-native view (which follows cadnano2 exactly).
const HC_HALF_TWIST_DEG   = HC_TWIST_PER_BP_DEG / 2   // 17.15°
const SQ_HALF_TWIST_DEG   = SQ_TWIST_PER_BP_DEG / 2   // 16.875°

// Phase arrow colours — match pathview strand colours
const CLR_ARROW_SCAFFOLD = '#0070bb'   // scaffold blue (matches pathview CLR_SCAFFOLD)
const CLR_ARROW_STAPLE   = '#c62828'   // staple red (matches reverse cell family)

// Arrow geometry — line + arrowhead, pointing toward -y (upward in SVG)
const ARW_LEN_SCAF = CELL_R * 0.62
const ARW_LEN_STPL = CELL_R * 0.50
const ARW_STROKE_W = CELL_R * 0.065

// ── Colours ───────────────────────────────────────────────────────────────────

const CLR_FORWARD_FILL   = 'rgba(41, 182, 246, 0.35)'   // translucent blue
const CLR_FORWARD_STROKE = '#29b6f6'
const CLR_REVERSE_FILL   = 'rgba(239, 83, 80, 0.35)'    // translucent red
const CLR_REVERSE_STROKE = '#ef5350'
const CLR_EMPTY_FILL     = '#141c24'
const CLR_EMPTY_STROKE   = '#2d3f50'

// ── Lattice math ──────────────────────────────────────────────────────────────

function hcIsForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }  // even parity = FORWARD (cadnano2)
function sqIsForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }

function hcCellNm(row, col) {
  const odd = (((row + col) % 2) + 2) % 2
  // Matches cadnano2 latticeCoordToPositionXY: x = col*r*sqrt(3), y = row*r*3 [+r if odd].
  // SVG y increases downward → row 0 at top, matching cadnano2 Qt convention.
  return { x: col * HC_COL_PITCH, y: row * HC_ROW_PITCH + (odd ? HC_R : 0) }
}
function sqCellNm(row, col) {
  return { x: col * SQ_PITCH, y: row * SQ_PITCH }
}

function hcNmToCell(x, y) {
  // Backend: x = col × COL_PITCH, y = row × ROW_PITCH + stagger
  const col = Math.round(x / HC_COL_PITCH)
  const odd = (((col) % 2) + 2) % 2
  return { row: Math.round((y - (odd ? HC_R : 0)) / HC_ROW_PITCH), col }
}
function sqNmToCell(x, y) {
  return { row: Math.round(y / SQ_PITCH), col: Math.round(x / SQ_PITCH) }
}

// ── Main init ─────────────────────────────────────────────────────────────────

export function initSliceview(svgEl, containerEl, { onAddHelix, onRemoveHelix }) {
  const NS = 'http://www.w3.org/2000/svg'

  let _design   = null
  let _panZoom  = null
  let _fitDone  = false

  // Orientation mode.
  // true  → cadnano native: row 0 at top, Y-down, cadnano2 phase convention.
  // false → 3D world: row 0 at bottom, Y-up, phase angles match the 3D viewport.
  let _nativeOrientation = true

  // Slice bar state — updated by setSliceBp() from pathview
  let _sliceBp    = 0
  let _arrowEls   = new Map()   // helix.id → { scaf: SVGGElement, stpl: SVGGElement }
  let _helixCells = new Map()   // helix.id → { row, col }

  // Build a line+arrowhead <g> pointing toward -y (upward in SVG), with black border.
  function _makeArrowGroup(len, color) {
    const g = document.createElementNS(NS, 'g')
    g.setAttribute('class', 'sv-phase-arrow')

    const headLen = len * 0.36
    const headW   = len * 0.22
    const tipY    = -len
    const baseY   = tipY + headLen   // stem ends here, arrowhead begins

    // Stem — black underline then colored line on top
    const lineBg = document.createElementNS(NS, 'line')
    lineBg.setAttribute('x1', '0'); lineBg.setAttribute('y1', '0')
    lineBg.setAttribute('x2', '0'); lineBg.setAttribute('y2', baseY.toFixed(1))
    lineBg.setAttribute('stroke', 'rgba(0,0,0,0.55)')
    lineBg.setAttribute('stroke-width', (ARW_STROKE_W + 1.8).toFixed(2))
    lineBg.setAttribute('stroke-linecap', 'round')
    g.appendChild(lineBg)

    const line = document.createElementNS(NS, 'line')
    line.setAttribute('x1', '0'); line.setAttribute('y1', '0')
    line.setAttribute('x2', '0'); line.setAttribute('y2', baseY.toFixed(1))
    line.setAttribute('stroke', color)
    line.setAttribute('stroke-width', ARW_STROKE_W.toFixed(2))
    line.setAttribute('stroke-linecap', 'round')
    g.appendChild(line)

    // Arrowhead with black border
    const poly = document.createElementNS(NS, 'polygon')
    poly.setAttribute('points',
      `0,${tipY.toFixed(1)} ${headW.toFixed(1)},${baseY.toFixed(1)} ${(-headW).toFixed(1)},${baseY.toFixed(1)}`)
    poly.setAttribute('fill', color)
    poly.setAttribute('stroke', 'rgba(0,0,0,0.55)')
    poly.setAttribute('stroke-width', '1.2')
    poly.setAttribute('stroke-linejoin', 'round')
    g.appendChild(poly)

    return g
  }

  // ── Build SVG structure ───────────────────────────────────────────────────

  const styleEl = document.createElementNS(NS, 'style')
  styleEl.textContent = `
    .sv-cell              { cursor: pointer; }
    .sv-cell circle       { transition: opacity 0.08s; }
    .sv-cell:hover circle { stroke: #ffffff !important; stroke-width: 3 !important; }
    .sv-cell.occupied:hover circle { opacity: 0.72; }
    .sv-cell.empty:hover circle    { fill: #1e2d3d !important; }
    .sv-label       { pointer-events: none; user-select: none; }
    .sv-phase-arrow { pointer-events: none; }
  `
  svgEl.appendChild(styleEl)

  const viewport = document.createElementNS(NS, 'g')
  viewport.setAttribute('id', 'sv-viewport')
  svgEl.appendChild(viewport)

  // ── View-direction legend ─────────────────────────────────────────────────
  // Fixed overlay in the bottom-left corner (outside the pan-zoom viewport).
  // Shows which world axes correspond to the SVG col (→) and row (↓) directions,
  // and which axis is pointing toward the viewer.
  //
  // Axis layout per design plane (inferred from helix ID format h_PLANE_row_col):
  //   XY (helices along Z): col→ = +X, row↓ = −Y, view = +Z
  //   XZ (helices along Y): col→ = +X, row↓ = −Z, view = +Y
  //   YZ (helices along X): col→ = +Y, row↓ = −Z, view = +X

  // rowDir: 1 = row axis points downward (cadnano native, SVG y-down)
  //        -1 = row axis points upward (3D world, Y-up)
  const LEGEND_AXES = {
    XY:      { col: '+X', row: '−Y', view: '+Z', rowDir:  1 },
    XZ:      { col: '+X', row: '−Z', view: '+Y', rowDir:  1 },
    YZ:      { col: '+Y', row: '−Z', view: '+X', rowDir:  1 },
    'XY-3D': { col: '+X', row: '+Y', view: '+Z', rowDir: -1 },
  }

  const legendG = document.createElementNS(NS, 'g')
  legendG.setAttribute('class', 'sv-legend')
  legendG.setAttribute('pointer-events', 'none')
  svgEl.appendChild(legendG)   // appended after viewport so it renders on top

  function _buildLegend(axes) {
    while (legendG.firstChild) legendG.removeChild(legendG.firstChild)

    const dim  = 14    // arrow length
    const ox   = 14    // cross origin x (inside the bg box)
    const oy   = 14    // cross origin y (inside the bg box)
    const fs   = 10    // font size
    const pad  = 4
    const boxW = 70
    const boxH = 62

    // Background
    const bg = document.createElementNS(NS, 'rect')
    bg.setAttribute('x', '0'); bg.setAttribute('y', '0')
    bg.setAttribute('width', boxW); bg.setAttribute('height', boxH)
    bg.setAttribute('rx', '4')
    bg.setAttribute('fill', 'rgba(13,17,23,0.78)')
    bg.setAttribute('stroke', '#2d3f50')
    bg.setAttribute('stroke-width', '1')
    legendG.appendChild(bg)

    function _arrow(x1, y1, x2, y2, label, lx, ly, color) {
      const line = document.createElementNS(NS, 'line')
      line.setAttribute('x1', x1); line.setAttribute('y1', y1)
      line.setAttribute('x2', x2); line.setAttribute('y2', y2)
      line.setAttribute('stroke', color)
      line.setAttribute('stroke-width', '1.5')
      line.setAttribute('stroke-linecap', 'round')
      legendG.appendChild(line)

      // Small arrowhead
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.hypot(dx, dy)
      const ux = dx / len, uy = dy / len
      const hw = 3.5, hl = 5
      const bx = x2 - ux * hl, by = y2 - uy * hl
      const nx = -uy, ny = ux
      const head = document.createElementNS(NS, 'polygon')
      head.setAttribute('points',
        `${x2},${y2} ${(bx + nx * hw).toFixed(1)},${(by + ny * hw).toFixed(1)} ${(bx - nx * hw).toFixed(1)},${(by - ny * hw).toFixed(1)}`)
      head.setAttribute('fill', color)
      legendG.appendChild(head)

      const txt = document.createElementNS(NS, 'text')
      txt.setAttribute('x', lx); txt.setAttribute('y', ly)
      txt.setAttribute('font-size', fs)
      txt.setAttribute('font-family', 'monospace')
      txt.setAttribute('fill', color)
      txt.setAttribute('dominant-baseline', 'central')
      txt.textContent = label
      legendG.appendChild(txt)
    }

    // Col axis: rightward arrow
    _arrow(ox, oy, ox + dim, oy, axes.col, ox + dim + pad, oy, '#8b949e')

    // Row axis: downward (native) or upward (3D) arrow
    const rowDir = axes.rowDir ?? 1
    const rowEndY = oy + rowDir * dim
    // Label 6px past the endpoint — always inside the box regardless of row direction.
    _arrow(ox, oy, ox, rowEndY, axes.row, ox + pad, rowEndY + 6, '#8b949e')

    // View direction: circle with dot (axis toward viewer) — always below the cross origin
    const vcy = oy + dim + pad + fs + 6
    const vcx = ox
    const viewCircle = document.createElementNS(NS, 'circle')
    viewCircle.setAttribute('cx', vcx); viewCircle.setAttribute('cy', vcy)
    viewCircle.setAttribute('r', '5')
    viewCircle.setAttribute('fill', 'none')
    viewCircle.setAttribute('stroke', '#79c0ff')
    viewCircle.setAttribute('stroke-width', '1.2')
    legendG.appendChild(viewCircle)
    const viewDot = document.createElementNS(NS, 'circle')
    viewDot.setAttribute('cx', vcx); viewDot.setAttribute('cy', vcy)
    viewDot.setAttribute('r', '1.8')
    viewDot.setAttribute('fill', '#79c0ff')
    legendG.appendChild(viewDot)
    const viewTxt = document.createElementNS(NS, 'text')
    viewTxt.setAttribute('x', vcx + 9); viewTxt.setAttribute('y', vcy)
    viewTxt.setAttribute('font-size', fs)
    viewTxt.setAttribute('font-family', 'monospace')
    viewTxt.setAttribute('fill', '#79c0ff')
    viewTxt.setAttribute('dominant-baseline', 'central')
    viewTxt.textContent = axes.view
    legendG.appendChild(viewTxt)
  }

  function _repositionLegend() {
    const h = svgEl.clientHeight || 220
    legendG.setAttribute('transform', `translate(8, ${h - 70})`)
  }

  // Initial build (default XY axes until a design loads)
  _buildLegend(LEGEND_AXES.XY)
  _repositionLegend()

  // Reposition when the container resizes
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(_repositionLegend).observe(containerEl)
  }

  // ── svg-pan-zoom ──────────────────────────────────────────────────────────

  function _initPanZoom() {
    if (_panZoom) return
    _panZoom = svgPanZoom(svgEl, {
      viewportSelector:     '#sv-viewport',
      zoomScaleSensitivity: 0.25,
      minZoom:              0.05,
      maxZoom:              25,
      fit:                  false,
      center:               false,
      dblClickZoomEnabled:  false,
      preventMouseEventsDefault: false,
    })

    // Right-click + middle-click drag to pan (svg-pan-zoom only handles left by default).
    let _rpDragging = false, _rpLastX = 0, _rpLastY = 0
    svgEl.addEventListener('pointerdown', (e) => {
      if (e.button !== 1 && e.button !== 2) return
      e.preventDefault()
      _rpDragging = true
      _rpLastX = e.clientX
      _rpLastY = e.clientY
      svgEl.setPointerCapture(e.pointerId)
    })
    svgEl.addEventListener('pointermove', (e) => {
      if (!_rpDragging) return
      _panZoom.panBy({ x: e.clientX - _rpLastX, y: e.clientY - _rpLastY })
      _rpLastX = e.clientX
      _rpLastY = e.clientY
    })
    svgEl.addEventListener('pointerup',    () => { _rpDragging = false })
    svgEl.addEventListener('pointercancel', () => { _rpDragging = false })
    svgEl.addEventListener('contextmenu',  (e) => e.preventDefault())
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function _activeMap() {
    const map = new Map()
    if (!_design?.helices) return map
    const isHC = _design.lattice_type === 'HONEYCOMB'
    for (const h of _design.helices) {
      const cell = h.grid_pos
        ? { row: h.grid_pos[0], col: h.grid_pos[1] }
        : isHC ? hcNmToCell(h.axis_start.x, h.axis_start.y)
               : sqNmToCell(h.axis_start.x, h.axis_start.y)
      map.set(`${cell.row}:${cell.col}`, { cell, helix: h })
    }
    return map
  }

  // Compute phase rotation (SVG degrees, clockwise from up) matching cadnano2.
  //
  // cadnano2 arrow convention (twistOffset applied at bp=0, then bp×twistPerBase CW rotation):
  //   HC  twistOffset=0°:       even (fwd) → right (SVG 90°),   odd (rev) → left (SVG 270°)
  //   SQ  twistOffset=196.875°: even (fwd) → SVG 90°+196.875°,  odd (rev) → SVG 270°+196.875°
  //
  // View direction: +Z toward -Z, matching cadnano2's Qt sliceview (row 0 at top, CW rotation).
  function _phaseDeg(row, col, bp, isHC) {
    const isFwd = isHC ? hcIsForward(row, col) : sqIsForward(row, col)
    if (isHC) {
      const base = isFwd ? 90 : 270
      return (base + bp * HC_TWIST_PER_BP_DEG) % 360
    } else {
      const SQ_TWIST_OFFSET = 196.875
      const base = isFwd ? 90 + SQ_TWIST_OFFSET : 270 + SQ_TWIST_OFFSET
      return (base + bp * SQ_TWIST_PER_BP_DEG) % 360
    }
  }

  // Convert cadnano SVG phase angle → scaffold and staple SVG rotate() angles
  // for the current orientation mode.
  //
  // Native (cadnano Y-down): arrows follow cadnano2 convention directly.
  //
  // World 3D (Y-up from +Z): the view Y-axis is flipped relative to cadnano.
  //   The helix_frame angle θ maps to world (sin θ, −cos θ).  When drawn on a
  //   Y-down canvas from the +Z direction, the required SVG rotate angle is
  //   (180° − θ), because sin(180°−θ) = sin θ and −cos(180°−θ) = cos θ = −(−cos θ).
  //   For the staple: (180° − cadnano_staple) = (180° − θ − 150°) = (30° − θ).
  function _arrowDegs(cadDeg) {
    if (_nativeOrientation) {
      return {
        scaf: cadDeg % 360,
        stpl: (cadDeg + MINOR_GROOVE_DEG) % 360,
      }
    }
    // 3D world mode: convert cadnano SVG angle → 3D display angle (180° − θ),
    // then subtract the half-bp Holliday Junction correction that was added to
    // the backend phase offsets (so the sliceview matches the 3D backbone positions).
    const isHC   = !_design || _design.lattice_type === 'HONEYCOMB'
    const halfBp = isHC ? HC_HALF_TWIST_DEG : SQ_HALF_TWIST_DEG
    const scaf   = (180 - cadDeg - halfBp + 720) % 360
    const stpl   = (180 - cadDeg - halfBp - MINOR_GROOVE_DEG + 720) % 360
    return { scaf, stpl }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function _render() {
    while (viewport.firstChild) viewport.removeChild(viewport.firstChild)

    // Rebuild arrow/cell reference maps
    _arrowEls.clear()
    _helixCells.clear()

    const isHC   = !_design || _design.lattice_type === 'HONEYCOMB'
    const cellNm = isHC ? hcCellNm  : sqCellNm
    const isFwd  = isHC ? hcIsForward : sqIsForward
    const active = _activeMap()

    // Helix display label — use h.label when set (e.g. scadnano index), else positional index.
    const helixIdx = new Map((_design?.helices ?? []).map((h, i) => [h.id, h.label ?? i]))

    // Grid extent
    const activeCells = [...active.values()].map(v => v.cell)
    let rMin, rMax, cMin, cMax
    if (activeCells.length === 0) {
      ;[rMin, rMax] = DEFAULT_ROWS
      ;[cMin, cMax] = DEFAULT_COLS
    } else {
      rMin = Math.min(...activeCells.map(c => c.row)) - GRID_MARGIN
      rMax = Math.max(...activeCells.map(c => c.row)) + GRID_MARGIN
      cMin = Math.min(...activeCells.map(c => c.col)) - GRID_MARGIN
      cMax = Math.max(...activeCells.map(c => c.col)) + GRID_MARGIN
    }

    const cells = []
    for (let r = rMin; r <= rMax; r++)
      for (let c = cMin; c <= cMax; c++)
        cells.push({ row: r, col: c, ...cellNm(r, c) })
    if (cells.length === 0) return

    for (const cell of cells) {
      const key   = `${cell.row}:${cell.col}`
      const entry = active.get(key)
      const fwd   = isFwd(cell.row, cell.col)
      // Absolute coordinates: cell positions never shift when bounds change
      // (e.g. when adding a helix at the lattice edge), so the visible lattice
      // stays put within the pan-zoom viewport on click.
      const px    = cell.x * SCALE
      // Native: row 0 at top (cadnano2 y-down).  3D world: row 0 at bottom (y-up).
      const py    = _nativeOrientation ? cell.y * SCALE : -cell.y * SCALE

      const g = document.createElementNS(NS, 'g')
      g.setAttribute('class', `sv-cell ${entry ? 'occupied' : 'empty'}`)
      g.setAttribute('transform', `translate(${px.toFixed(1)},${py.toFixed(1)})`)

      // Tooltip
      const title = document.createElementNS(NS, 'title')
      title.textContent = entry
        ? `[${cell.row}, ${cell.col}] — ${entry.helix.id.slice(0, 8)}`
        : `[${cell.row}, ${cell.col}]`
      g.appendChild(title)

      // Background circle
      const circle = document.createElementNS(NS, 'circle')
      circle.setAttribute('r', CELL_R)
      circle.setAttribute('vector-effect', 'non-scaling-stroke')
      if (entry) {
        circle.setAttribute('fill',         fwd ? CLR_FORWARD_FILL   : CLR_REVERSE_FILL)
        circle.setAttribute('stroke',       fwd ? CLR_FORWARD_STROKE : CLR_REVERSE_STROKE)
        circle.setAttribute('stroke-width', '2')
      } else {
        circle.setAttribute('fill',         CLR_EMPTY_FILL)
        circle.setAttribute('stroke',       CLR_EMPTY_STROKE)
        circle.setAttribute('stroke-width', '1.5')
      }
      g.appendChild(circle)

      if (entry) {
        // ── Phase arrows: scaffold (blue) + staple (red) ───────────────────
        const deg         = _phaseDeg(cell.row, cell.col, _sliceBp, isHC)
        const { scaf: scafDeg, stpl: stplDeg } = _arrowDegs(deg)
        const scafArrow   = _makeArrowGroup(ARW_LEN_SCAF, CLR_ARROW_SCAFFOLD)
        const stplArrow   = _makeArrowGroup(ARW_LEN_STPL, CLR_ARROW_STAPLE)
        scafArrow.setAttribute('transform', `rotate(${scafDeg.toFixed(1)})`)
        stplArrow.setAttribute('transform', `rotate(${stplDeg.toFixed(1)})`)
        g.appendChild(scafArrow)
        g.appendChild(stplArrow)

        // ── Helix index label (appended last so it renders over arrows) ─────
        const idx   = helixIdx.get(entry.helix.id) ?? '?'
        const label = document.createElementNS(NS, 'text')
        label.setAttribute('class', 'sv-label')
        label.setAttribute('text-anchor', 'middle')
        label.setAttribute('dominant-baseline', 'central')
        label.setAttribute('font-size',   (CELL_R * 0.70).toFixed(1))
        label.setAttribute('font-weight', 'bold')
        label.setAttribute('font-family', 'sans-serif')
        label.setAttribute('fill',        '#ffffff')
        label.textContent = String(idx)
        g.appendChild(label)

        // Store for slice-bar updates
        _arrowEls.set(entry.helix.id,   { scaf: scafArrow, stpl: stplArrow })
        _helixCells.set(entry.helix.id, { row: cell.row, col: cell.col })
      }

      // Click — add or remove helix
      g.addEventListener('click', (e) => {
        if (e._svgPanZoomDragged) return
        e.stopPropagation()
        entry ? onRemoveHelix(entry.helix.id) : onAddHelix({ row: cell.row, col: cell.col })
      })

      viewport.appendChild(g)
    }

    _initPanZoom()

    // Defer the initial fit/center until there's at least one active helix
    // to fit to — fitting an empty grid leaves a useless centered view that
    // doesn't move when a design loads (because _fitDone was already set).
    if (!_fitDone && activeCells.length > 0) {
      _fitDone = true
      // Two rAFs: layout + svg-pan-zoom internal viewport sizing both need to
      // settle before getSizes() returns sensible values. One rAF is sometimes
      // too early on the first render of the page.
      requestAnimationFrame(() => requestAnimationFrame(() => _fitToActiveCells()))
    }
  }

  /** Zoom + pan so the active-helix bounding box fills the viewport with a
   *  small margin. Replaces svg-pan-zoom's native fit() (which would zoom out
   *  to encompass the full GRID_MARGIN-padded lattice, leaving the helices
   *  small and lost in a sea of empty cells). */
  function _fitToActiveCells() {
    if (!_panZoom || !_helixCells.size) return
    const isHC   = !_design || _design.lattice_type === 'HONEYCOMB'
    const cellNm = isHC ? hcCellNm : sqCellNm
    const padCells = 1.5   // extra cells of breathing room around the active set
    let minX =  Infinity, minY =  Infinity
    let maxX = -Infinity, maxY = -Infinity
    for (const { row, col } of _helixCells.values()) {
      const xy = cellNm(row, col)
      const x  = xy.x * SCALE
      const y  = (_nativeOrientation ? xy.y : -xy.y) * SCALE
      if (x < minX) minX = x; if (x > maxX) maxX = x
      if (y < minY) minY = y; if (y > maxY) maxY = y
    }
    // Cell radius padding so circles aren't clipped at the edge.
    const pad = CELL_R * (1 + padCells * 2)
    const bx = minX - pad, by = minY - pad
    const bw = (maxX - minX) + 2 * pad
    const bh = (maxY - minY) + 2 * pad

    _panZoom.resize()
    const sizes = _panZoom.getSizes()
    const Vw = sizes.width
    const Vh = sizes.height
    if (Vw <= 0 || Vh <= 0 || bw <= 0 || bh <= 0) {
      _panZoom.fit(); _panZoom.center(); return
    }
    // Compute desired effective zoom (pixels per SVG unit) for the bbox to fit
    // in the viewport, then scale the *current* zoom by the appropriate factor
    // via zoomBy() — avoids the absolute-zoom path's NaN trap when the SVG
    // viewBox/zoom relationship hasn't fully settled yet.
    const currentReal = sizes.realZoom
    const targetReal  = Math.min(Vw / bw, Vh / bh)
    if (!isFinite(currentReal) || currentReal <= 0 ||
        !isFinite(targetReal)  || targetReal  <= 0) {
      _panZoom.fit(); _panZoom.center(); return
    }
    _panZoom.zoomBy(targetReal / currentReal)

    // After zoom, recompute and pan so the bbox centre lands on the viewport
    // centre. pixel = (svg − viewBox.x) * realZoom + pan.
    const newSizes = _panZoom.getSizes()
    const realZ    = newSizes.realZoom
    const vbx      = newSizes.viewBox?.x ?? 0
    const vby      = newSizes.viewBox?.y ?? 0
    const cx = bx + bw / 2
    const cy = by + bh / 2
    const panX = Vw / 2 - (cx - vbx) * realZ
    const panY = Vh / 2 - (cy - vby) * realZ
    if (isFinite(panX) && isFinite(panY)) {
      _panZoom.pan({ x: panX, y: panY })
    }
  }

  // Initial render (empty grid)
  _render()

  // ── Public interface ──────────────────────────────────────────────────────

  return {
    /**
     * Redraw for the given design.  Pan/zoom state is preserved across updates.
     */
    update(design) {
      _design = design
      _render()
      // Update legend axes from design plane (inferred from helix ID format h_PLANE_row_col).
      const plane = design?.helices?.[0]?.id?.split('_')[1]
      const key   = _nativeOrientation ? (plane ?? 'XY') : 'XY-3D'
      _buildLegend(LEGEND_AXES[key] ?? LEGEND_AXES.XY)
    },

    /** Reset zoom/pan so the active helices fill the viewport (F-key handler). */
    fitToContent() { _fitToActiveCells() },

    /**
     * Called by pathview whenever the slice bar moves.
     * Efficiently updates only the arrow `transform` attributes — no full re-render.
     */
    setSliceBp(bp) {
      _sliceBp = bp
      const isHC = !_design || _design.lattice_type === 'HONEYCOMB'
      for (const [hid, arrows] of _arrowEls) {
        const cell = _helixCells.get(hid)
        if (!cell) continue
        const deg = _phaseDeg(cell.row, cell.col, bp, isHC)
        const { scaf: scafDeg, stpl: stplDeg } = _arrowDegs(deg)
        arrows.scaf.setAttribute('transform', `rotate(${scafDeg.toFixed(1)})`)
        arrows.stpl.setAttribute('transform', `rotate(${stplDeg.toFixed(1)})`)
      }
    },

    /**
     * Set the orientation mode and re-render.
     * @param {boolean} native  true = cadnano native (default), false = 3D world (Y-up).
     */
    setNativeOrientation(native) {
      if (_nativeOrientation === native) return
      _nativeOrientation = native
      _fitDone = false   // re-fit after flip so content stays centered
      _render()
      // Rebuild legend: pick the 3D variant when not native, otherwise use design plane.
      const plane = _design?.helices?.[0]?.id?.split('_')[1]
      const key   = native ? (plane ?? 'XY') : 'XY-3D'
      _buildLegend(LEGEND_AXES[key] ?? LEGEND_AXES.XY)
    },
  }
}
