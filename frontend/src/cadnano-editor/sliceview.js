/**
 * Sliceview — SVG lattice grid for helix activation/deactivation.
 *
 * Renders an HC or SQ lattice grid.  Occupied cells (active helices) are
 * filled; empty cells are hollow.  Clicking an empty cell adds a helix;
 * clicking an occupied cell removes it.
 *
 * Coordinate math (mirrors backend/core/lattice.py exactly):
 *
 *   HC:
 *     x_nm = col * COL_PITCH               (COL_PITCH = 1.125 * sqrt(3))
 *     y_nm = row * ROW_PITCH + (col%2==0 ? R : 0)  (R=1.125, ROW_PITCH=2.25)
 *     Valid cell: honeycomb_cell_value(row,col) != 2
 *     Cell value: (row + col%2) % 3 — 0=FORWARD, 1=REVERSE, 2=HOLE
 *
 *   SQ:
 *     x_nm = col * 2.25
 *     y_nm = row * 2.25
 *     All cells valid.
 *     Direction: (row+col)%2==0 → FORWARD, else REVERSE
 *
 * SVG layout:
 *   - Y axis is INVERTED (SVG Y increases downward, row 0 at top)
 *   - Scale: SCALE px per nm
 *   - Each cell rendered as a circle (cadnano2 style)
 *   - FORWARD cells: sky blue filled when occupied, hollow when empty
 *   - REVERSE cells: orange filled when occupied, hollow when empty
 *   - HOLE cells (HC only): not rendered
 */

// ── Constants (mirrors constants.js and backend/core/constants.py) ───────────

const HC_R         = 1.125                     // nm — hex lattice radius
const HC_COL_PITCH = HC_R * Math.sqrt(3)       // ≈ 1.9486 nm
const HC_ROW_PITCH = 2.25                      // nm
const SQ_PITCH     = 2.25                      // nm (col and row pitch)

const SCALE        = 13    // pixels per nm
const CELL_RADIUS  = Math.round(HC_R * SCALE * 0.82)  // ≈ 12 px — slightly inside cell boundary
const PAD          = CELL_RADIUS + 4           // SVG padding (pixels)

const GRID_MARGIN  = 2   // extra rows/cols of empty cells to show around active helices

// Default grid viewport when no helices present (0-indexed, inclusive)
const DEFAULT_HC_ROWS = [0, 3]    // rows 0..3
const DEFAULT_HC_COLS = [0, 7]    // cols 0..7
const DEFAULT_SQ_ROWS = [0, 3]
const DEFAULT_SQ_COLS = [0, 7]

// Colours
const CLR_FORWARD_OCCUPIED  = '#29b6f6'   // sky blue  — scaffold
const CLR_REVERSE_OCCUPIED  = '#ff8c00'   // orange
const CLR_EMPTY_STROKE      = '#2d3f50'
const CLR_EMPTY_FILL        = '#141c24'
const CLR_HOVER             = '#ffffff'
const CLR_HOVER_EMPTY_FILL  = '#1e2d3d'

// ── HC cell rule ──────────────────────────────────────────────────────────────

function hcCellValue(row, col) {
  return (row + (col % 2 + 2) % 2) % 3   // safe modulo for negative cols
}
function hcIsValid(row, col) { return hcCellValue(row, col) !== 2 }
function hcIsForward(row, col) { return hcCellValue(row, col) === 0 }

function sqIsForward(row, col) { return (((row + col) % 2) + 2) % 2 === 0 }

// ── Physical nm position for cell ────────────────────────────────────────────

function hcCellNm(row, col) {
  const x = col * HC_COL_PITCH
  const y = row * HC_ROW_PITCH + ((col % 2 + 2) % 2 === 0 ? HC_R : 0)
  return { x, y }
}

function sqCellNm(row, col) {
  return { x: col * SQ_PITCH, y: row * SQ_PITCH }
}

// ── Reverse map: nm position → (row, col) ────────────────────────────────────

function hcNmToCell(x_nm, y_nm) {
  const col = Math.round(x_nm / HC_COL_PITCH)
  const rowOff = ((col % 2 + 2) % 2 === 0) ? HC_R : 0
  const row = Math.round((y_nm - rowOff) / HC_ROW_PITCH)
  return { row, col }
}

function sqNmToCell(x_nm, y_nm) {
  return { row: Math.round(y_nm / SQ_PITCH), col: Math.round(x_nm / SQ_PITCH) }
}

// ── nm → SVG screen position (Y inverted, bounding box applied later) ────────

function nmToScreen(x_nm, y_nm, minX_nm, maxY_nm) {
  return {
    sx: PAD + (x_nm - minX_nm) * SCALE,
    sy: PAD + (maxY_nm - y_nm) * SCALE,   // invert Y so row 0 is at top
  }
}

// ── Build set of cells to render ─────────────────────────────────────────────

function _buildViewport(isHC, activeCells) {
  let rMin, rMax, cMin, cMax
  if (activeCells.length === 0) {
    const [rDef, cDef] = isHC
      ? [DEFAULT_HC_ROWS, DEFAULT_HC_COLS]
      : [DEFAULT_SQ_ROWS, DEFAULT_SQ_COLS]
    ;[rMin, rMax, cMin, cMax] = [rDef[0], rDef[1], cDef[0], cDef[1]]
  } else {
    rMin = Math.min(...activeCells.map(c => c.row)) - GRID_MARGIN
    rMax = Math.max(...activeCells.map(c => c.row)) + GRID_MARGIN
    cMin = Math.min(...activeCells.map(c => c.col)) - GRID_MARGIN
    cMax = Math.max(...activeCells.map(c => c.col)) + GRID_MARGIN
  }
  return { rMin, rMax, cMin, cMax }
}

// ── Main init function ────────────────────────────────────────────────────────

export function initSliceview(svgEl, containerEl, { onAddHelix, onRemoveHelix }) {
  const NS = 'http://www.w3.org/2000/svg'

  // State
  let _design = null
  let _hoveredKey = null   // "row:col" of hovered cell

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _cellKey(row, col) { return `${row}:${col}` }

  function _isForward(isHC, row, col) {
    return isHC ? hcIsForward(row, col) : sqIsForward(row, col)
  }

  // Build Map<"row:col", helix> for the current design
  function _activeMap(design) {
    const map = new Map()
    if (!design?.helices) return map
    const isHC = design.lattice_type === 'HONEYCOMB'
    for (const h of design.helices) {
      let cell
      if (h.grid_pos) {
        cell = { row: h.grid_pos[0], col: h.grid_pos[1] }
      } else {
        // Fallback: compute from axis_start
        cell = isHC
          ? hcNmToCell(h.axis_start.x, h.axis_start.y)
          : sqNmToCell(h.axis_start.x, h.axis_start.y)
      }
      map.set(_cellKey(cell.row, cell.col), { ...cell, helix: h })
    }
    return map
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  function _render() {
    // Remove all children
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild)

    const design = _design
    const isHC   = !design || design.lattice_type === 'HONEYCOMB'
    const cellNm = isHC ? hcCellNm : sqCellNm
    const active = _activeMap(design)

    const activeCells = [...active.values()]
    const { rMin, rMax, cMin, cMax } = _buildViewport(isHC, activeCells)

    // Collect all valid cells in viewport and their nm positions
    const cells = []
    for (let r = rMin; r <= rMax; r++) {
      for (let c = cMin; c <= cMax; c++) {
        if (isHC && !hcIsValid(r, c)) continue
        const { x, y } = cellNm(r, c)
        cells.push({ row: r, col: c, x, y })
      }
    }

    if (cells.length === 0) {
      svgEl.setAttribute('width', '200')
      svgEl.setAttribute('height', '100')
      return
    }

    // Bounding box of cell centres
    const xs    = cells.map(c => c.x)
    const ys    = cells.map(c => c.y)
    const minX  = Math.min(...xs)
    const maxY  = Math.max(...ys)
    const maxX  = Math.max(...xs)
    const minY  = Math.min(...ys)

    const svgW = Math.ceil(PAD * 2 + (maxX - minX) * SCALE) + CELL_RADIUS
    const svgH = Math.ceil(PAD * 2 + (maxY - minY) * SCALE) + CELL_RADIUS

    svgEl.setAttribute('width',  svgW)
    svgEl.setAttribute('height', svgH)

    for (const cell of cells) {
      const key   = _cellKey(cell.row, cell.col)
      const entry = active.get(key)
      const fwd   = _isForward(isHC, cell.row, cell.col)
      const { sx, sy } = nmToScreen(cell.x, cell.y, minX, maxY)

      const isHovered   = key === _hoveredKey
      const isOccupied  = !!entry

      const circle = document.createElementNS(NS, 'circle')
      circle.setAttribute('cx', sx)
      circle.setAttribute('cy', sy)
      circle.setAttribute('r',  CELL_RADIUS)
      circle.style.cursor = 'pointer'

      if (isOccupied) {
        circle.setAttribute('fill',         isHovered ? CLR_HOVER : (fwd ? CLR_FORWARD_OCCUPIED : CLR_REVERSE_OCCUPIED))
        circle.setAttribute('stroke',       isHovered ? CLR_HOVER : (fwd ? CLR_FORWARD_OCCUPIED : CLR_REVERSE_OCCUPIED))
        circle.setAttribute('stroke-width', '1.5')
        circle.setAttribute('opacity',      isHovered ? '0.75' : '1')
      } else {
        circle.setAttribute('fill',         isHovered ? CLR_HOVER_EMPTY_FILL : CLR_EMPTY_FILL)
        circle.setAttribute('stroke',       isHovered ? CLR_HOVER : CLR_EMPTY_STROKE)
        circle.setAttribute('stroke-width', isHovered ? '1.5' : '1')
      }

      // Hover
      circle.addEventListener('mouseenter', () => {
        _hoveredKey = key
        _render()
      })
      circle.addEventListener('mouseleave', () => {
        if (_hoveredKey === key) { _hoveredKey = null; _render() }
      })

      // Click
      circle.addEventListener('click', () => {
        if (entry) {
          onRemoveHelix(entry.helix.id)
        } else {
          onAddHelix({ row: cell.row, col: cell.col })
        }
      })

      // Tooltip: show row/col label
      const title = document.createElementNS(NS, 'title')
      title.textContent = `[${cell.row}, ${cell.col}]${entry ? ` — ${entry.helix.id.slice(0, 8)}` : ''}`
      circle.appendChild(title)

      svgEl.appendChild(circle)
    }
  }

  // Initial render (empty)
  _render()

  return {
    /**
     * Redraw the sliceview for the given design.
     * @param {object|null} design
     */
    update(design) {
      _design = design
      _render()
    },
  }
}
