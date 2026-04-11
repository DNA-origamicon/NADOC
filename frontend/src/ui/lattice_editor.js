/**
 * Honeycomb lattice editor — 2D cross-section view.
 *
 * Renders an interactive hex grid on a <canvas>.  Users click cells to
 * toggle them on/off.  Selected cells are passed to the extrude action.
 *
 * caDNAno parity colouring:
 *   even parity → scaffold FORWARD → teal  (#00bcd4)
 *   odd  parity → scaffold REVERSE → coral (#ff7043)
 *
 * Returns { getSelectedCells, setSelectedCells, resize }.
 */

const ROWS = 10
const COLS = 16
const HEX_SIZE = 16          // px — apothem (center to edge midpoint)
const COL_PITCH_PX = HEX_SIZE * Math.sqrt(3)
const ROW_PITCH_PX = HEX_SIZE * 3
const OFFSET_X = 32
const OFFSET_Y = 32

const COLOR_EVEN   = '#00bcd4'   // teal  — FORWARD scaffold
const COLOR_ODD    = '#ff7043'   // coral — REVERSE scaffold
const COLOR_EMPTY  = '#21262d'
const COLOR_BORDER = '#30363d'
const COLOR_HOVER  = '#58a6ff44'
const COLOR_AXIS_LABEL = '#8b949e'

/**
 * Return pixel centre of hex cell (row, col).
 * Matches backend honeycomb_position() convention (Y-down / caDNAno):
 *   odd-parity cells ((row+col)%2==1) offset +HEX_SIZE in y (lower on canvas).
 */
function cellCenter(row, col) {
  const x = OFFSET_X + col * COL_PITCH_PX
  const yBase = OFFSET_Y + row * ROW_PITCH_PX
  const y = ((row + col) % 2 === 1) ? yBase + HEX_SIZE : yBase
  return { x, y }
}

/** Return hex corner vertices (flat-top hexagon). */
function hexCorners(cx, cy, r) {
  const pts = []
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 180) * (60 * i - 30)
    pts.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) })
  }
  return pts
}

/** Hit-test: return { row, col } or null.  Checks a 3×3 neighbourhood. */
function cellAtPoint(px, py) {
  // Estimate nearest col/row and check ±1.
  const approxCol = Math.round((px - OFFSET_X) / COL_PITCH_PX)
  const approxRow = Math.round((py - OFFSET_Y) / ROW_PITCH_PX)

  let best = null
  let bestDist = Infinity

  for (let dr = -1; dr <= 1; dr++) {
    for (let dc = -1; dc <= 1; dc++) {
      const row = approxRow + dr
      const col = approxCol + dc
      if (row < 0 || row >= ROWS || col < 0 || col >= COLS) continue
      const { x, y } = cellCenter(row, col)
      const dist = Math.hypot(px - x, py - y)
      if (dist < bestDist) { bestDist = dist; best = { row, col } }
    }
  }
  // Accept only if within the apothem of the cell
  return best && bestDist <= HEX_SIZE ? best : null
}

function isEvenParity(row, col) { return (row % 2) === (col % 2) }

export function initLatticeEditor(canvas, { onChange } = {}) {
  const ctx = canvas.getContext('2d')

  const _selected = new Set()  // keys: `${row},${col}`
  let _hover = null

  function _key(row, col) { return `${row},${col}` }
  function _isSelected(row, col) { return _selected.has(_key(row, col)) }

  function _draw() {
    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width  = w * dpr
      canvas.height = h * dpr
    }
    ctx.save()
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, w, h)

    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const { x, y } = cellCenter(row, col)
        const corners = hexCorners(x, y, HEX_SIZE - 1)

        ctx.beginPath()
        ctx.moveTo(corners[0].x, corners[0].y)
        for (let i = 1; i < 6; i++) ctx.lineTo(corners[i].x, corners[i].y)
        ctx.closePath()

        // Fill
        if (_isSelected(row, col)) {
          ctx.fillStyle = isEvenParity(row, col) ? COLOR_EVEN : COLOR_ODD
        } else {
          ctx.fillStyle = COLOR_EMPTY
        }
        ctx.fill()

        // Hover overlay
        if (_hover && _hover.row === row && _hover.col === col && !_isSelected(row, col)) {
          ctx.fillStyle = COLOR_HOVER
          ctx.fill()
        }

        // Border
        ctx.strokeStyle = COLOR_BORDER
        ctx.lineWidth = 0.5
        ctx.stroke()

        // Row/col label on cell (0,0) corner cells only — show coordinates every 2
        if (row % 2 === 0 && col % 2 === 0) {
          ctx.fillStyle = COLOR_AXIS_LABEL
          ctx.font = '7px Courier New'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(`${col},${row}`, x, y)
        }
      }
    }
    ctx.restore()
  }

  function _toggle(row, col) {
    const k = _key(row, col)
    if (_selected.has(k)) _selected.delete(k)
    else _selected.add(k)
    _draw()
    onChange?.(_getSelected())
  }

  function _getSelected() {
    return [..._selected].map(k => {
      const [r, c] = k.split(',').map(Number)
      return [r, c]
    })
  }

  canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect()
    const cell = cellAtPoint(e.clientX - rect.left, e.clientY - rect.top)
    if (cell) _toggle(cell.row, cell.col)
  })

  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect()
    const cell = cellAtPoint(e.clientX - rect.left, e.clientY - rect.top)
    const changed = JSON.stringify(cell) !== JSON.stringify(_hover)
    _hover = cell
    if (changed) _draw()
  })

  canvas.addEventListener('mouseleave', () => {
    _hover = null
    _draw()
  })

  _draw()
  window.addEventListener('resize', _draw)

  return {
    getSelectedCells: _getSelected,
    setSelectedCells(cells) {
      _selected.clear()
      cells.forEach(([r, c]) => _selected.add(_key(r, c)))
      _draw()
    },
    redraw: _draw,
  }
}
