/**
 * Pathview — Canvas 2D strand editor, cadnano2-style.
 *
 * Tools
 * ─────
 *  Select (S)  — hover strands; click staple → onStrandClick (color picker)
 *  Pencil (P)  — drag scaffold track → onPaintScaffold
 *                drag staple track   → onPaintStaple
 *  Erase  (E)  — click domain → onEraseDomain
 *  Nick   (N)  — click on strand → onNickStrand
 *
 * Pan/zoom  (free, no clamping — matches sliceview svg-pan-zoom model)
 * ────────────────────────────────────────────────────────────────────
 *  Right-click or middle-click drag → pan
 *  Scroll wheel                     → zoom centred on cursor
 */

// ── Layout constants (world-space pixels) ─────────────────────────────────────

const GUTTER     = 40
const RULER_H    = 26
const TOP_PAD    = 18
const BP_W       = 10
const LABEL_R    = 16
const EXTEND_BPS = 56
const MIN_ZOOM   = 0.06
const MAX_ZOOM   = 10

const CELL_H  = 12        // height of each track cell (strand fills this)
const PAIR_Y  = CELL_H   // distance between fwdY and revY — adjacent cells
const ROW_H   = 40        // total row height: 2×CELL_H cells + 16 px inter-helix gap
const GROUP_GAP = 28      // extra vertical gap between disconnected helix groups


// ── Colours ───────────────────────────────────────────────────────────────────

const CLR_BG           = '#f0f2f5'
const CLR_TRACK        = '#b0bac4'
const CLR_TICK_MINOR   = '#cdd5dc'
const CLR_TICK_MAJOR   = '#7a8fa0'
const CLR_RULER_BG     = '#e4e8ed'
const CLR_RULER_TEXT   = '#3a4a58'
// Gutter helix labels — forward cell = blue family, reverse cell = red family
const CLR_LABEL_FWD_FILL   = 'rgba(41, 182, 246, 0.82)'
const CLR_LABEL_FWD_STROKE = '#1976d2'
const CLR_LABEL_REV_FILL   = 'rgba(239, 83, 80, 0.82)'
const CLR_LABEL_REV_STROKE = '#c62828'
const CLR_LABEL_TEXT       = '#ffffff'
const CLR_SCAFFOLD     = '#0070bb'
const CLR_GHOST_SCAF   = 'rgba(0, 100, 220, 0.32)'
const CLR_GHOST_STPL   = 'rgba(200, 60, 0, 0.32)'
const CLR_SLICE_FILL   = 'rgba(245, 166, 35, 0.22)'
const CLR_SLICE_EDGE   = '#d08800'
const CLR_SLICE_NUM    = '#b03000'
const CLR_SEL_RING     = '#e53935'   // selected strand highlight
const CLR_SEL_END      = 'rgba(229, 57, 53, 0.40)'  // end-cap overlay when selected

// Crossover indicator geometry
const XOVER_R = 4            // sprite circle radius (world-space px)

// Crossover indicator colours — staple (non-scaffold side)
const CLR_XOVER_FILL   = 'rgba(120, 210, 255, 0.88)'
const CLR_XOVER_STROKE = '#1a88ee'
const CLR_XOVER_GLOW   = 'rgba(60, 160, 255, 0.65)'
const CLR_XOVER_TEXT   = '#0a1a2a'

// Crossover indicator colours — scaffold (scaffold side)
const CLR_SCAF_XOVER_FILL   = 'rgba(0, 112, 187, 0.90)'
const CLR_SCAF_XOVER_STROKE = '#004f99'
const CLR_SCAF_XOVER_GLOW   = 'rgba(0, 80, 180, 0.60)'
const CLR_SCAF_XOVER_TEXT   = '#cce8ff'

// Cell grid colours
const CLR_CELL_BG    = 'rgba(195, 208, 220, 0.38)'  // empty track cell fill
const CLR_CELL_GRID  = '#c4cdd5'                    // minor column separator lines

// Canonical palette — must match backend/core/constants.py STAPLE_PALETTE
// and frontend/src/scene/helix_renderer.js STAPLE_PALETTE exactly.
const STAPLE_PALETTE = [
  '#ff6b6b', '#ffd93d', '#6bcb77', '#f9844a',
  '#a29bfe', '#ff9ff3', '#00cec9', '#e17055',
  '#74b9ff', '#55efc4', '#fdcb6e', '#d63031',
]


// ── HC/SQ helpers ─────────────────────────────────────────────────────────────

const HC_R         = 1.125
const HC_COL_PITCH = HC_R * Math.sqrt(3)
const HC_ROW_PITCH = 3 * HC_R
const SQ_PITCH     = 2.25

function hcIsForward(row, col)  { return (((row + col) % 2) + 2) % 2 === 0 }  // even parity = FORWARD (cadnano2)
function sqIsForward(row, col)  { return (((row + col) % 2) + 2) % 2 === 0 }

// ── Crossover neighbor lookup (mirrors backend crossover offset tables) ───────

const HC_XOVER_PERIOD = 21
// Staple crossover offsets — cadnano2 _stapL/_stapH (HC_CROSSOVER_OFFSETS)
const HC_XOVER_MAP = {
  // Forward cell (even parity: scaffold FORWARD) — cadnano2 canonical
  // Even neighbors: [(r,c+1),(r-1,c),(r,c-1)] → bp6,7→(0,+1); bp13,14→(-1,0); bp0,20→(0,-1)
  '1_0':  [ 0, -1],  '1_6':  [ 0, +1],  '1_7':  [ 0, +1],
  '1_13': [-1,  0],  '1_14': [-1,  0],  '1_20': [ 0, -1],
  // Reverse cell (odd parity: scaffold REVERSE) — cadnano2 canonical
  // Odd neighbors: [(r,c-1),(r+1,c),(r,c+1)] → bp6,7→(0,-1); bp13,14→(+1,0); bp0,20→(0,+1)
  '0_0':  [ 0, +1],  '0_6':  [ 0, -1],  '0_7':  [ 0, -1],
  '0_13': [+1,  0],  '0_14': [+1,  0],  '0_20': [ 0, +1],
}
// Scaffold crossover offsets — cadnano2 _scafL/_scafH (HC_SCAFFOLD_CROSSOVER_OFFSETS)
// _scafL=[[1,11],[8,18],[4,15]], _scafH=[[2,12],[9,19],[5,16]]
// Even neighbors: p0=(r,c+1):{1,2,11,12}; p1=(r-1,c):{8,9,18,19}; p2=(r,c-1):{4,5,15,16}
const HC_SCAF_XOVER_MAP = {
  '1_1':  [ 0, +1],  '1_2':  [ 0, +1],  '1_11': [ 0, +1],  '1_12': [ 0, +1],
  '1_8':  [-1,  0],  '1_9':  [-1,  0],  '1_18': [-1,  0],  '1_19': [-1,  0],
  '1_4':  [ 0, -1],  '1_5':  [ 0, -1],  '1_15': [ 0, -1],  '1_16': [ 0, -1],
  '0_1':  [ 0, -1],  '0_2':  [ 0, -1],  '0_11': [ 0, -1],  '0_12': [ 0, -1],
  '0_8':  [+1,  0],  '0_9':  [+1,  0],  '0_18': [+1,  0],  '0_19': [+1,  0],
  '0_4':  [ 0, +1],  '0_5':  [ 0, +1],  '0_15': [ 0, +1],  '0_16': [ 0, +1],
}

const SQ_XOVER_PERIOD = 32
// Staple crossover offsets — cadnano2 _stapL/_stapH (SQ_CROSSOVER_OFFSETS)
const SQ_XOVER_MAP = {
  // Forward cell (even parity: scaffold FORWARD) — cadnano2 squarepart.py
  // Even neighbors: [(r,c+1),(r+1,c),(r,c-1),(r-1,c)] → bp0,31→(0,+1); bp23,24→(+1,0); bp15,16→(0,-1); bp7,8→(-1,0)
  '1_0':  [ 0, +1],  '1_31': [ 0, +1],
  '1_23': [+1,  0],  '1_24': [+1,  0],
  '1_15': [ 0, -1],  '1_16': [ 0, -1],
  '1_7':  [-1,  0],  '1_8':  [-1,  0],
  // Reverse cell (odd parity: scaffold REVERSE) — cadnano2 squarepart.py
  // Odd neighbors: [(r,c-1),(r-1,c),(r,c+1),(r+1,c)] → bp0,31→(0,-1); bp23,24→(-1,0); bp15,16→(0,+1); bp7,8→(+1,0)
  '0_0':  [ 0, -1],  '0_31': [ 0, -1],
  '0_23': [-1,  0],  '0_24': [-1,  0],
  '0_15': [ 0, +1],  '0_16': [ 0, +1],
  '0_7':  [+1,  0],  '0_8':  [+1,  0],
}
// Scaffold crossover offsets — cadnano2 squareScafLow/High (SQ_SCAFFOLD_CROSSOVER_OFFSETS)
// squareScafLow=[[4,26,15],[18,28,7],[10,20,31],[2,12,23]]
// squareScafHigh=[[5,27,16],[19,29,8],[11,21,0],[3,13,24]]
// Even neighbors: p0=(r,c+1):{4,5,15,16,26,27}; p1=(r+1,c):{7,8,18,19,28,29};
//                 p2=(r,c-1):{0,10,11,20,21,31}; p3=(r-1,c):{2,3,12,13,23,24}
const SQ_SCAF_XOVER_MAP = {
  '1_4':  [ 0, +1],  '1_5':  [ 0, +1],  '1_15': [ 0, +1],  '1_16': [ 0, +1],  '1_26': [ 0, +1],  '1_27': [ 0, +1],
  '1_7':  [+1,  0],  '1_8':  [+1,  0],  '1_18': [+1,  0],  '1_19': [+1,  0],  '1_28': [+1,  0],  '1_29': [+1,  0],
  '1_0':  [ 0, -1],  '1_10': [ 0, -1],  '1_11': [ 0, -1],  '1_20': [ 0, -1],  '1_21': [ 0, -1],  '1_31': [ 0, -1],
  '1_2':  [-1,  0],  '1_3':  [-1,  0],  '1_12': [-1,  0],  '1_13': [-1,  0],  '1_23': [-1,  0],  '1_24': [-1,  0],
  '0_4':  [ 0, -1],  '0_5':  [ 0, -1],  '0_15': [ 0, -1],  '0_16': [ 0, -1],  '0_26': [ 0, -1],  '0_27': [ 0, -1],
  '0_7':  [-1,  0],  '0_8':  [-1,  0],  '0_18': [-1,  0],  '0_19': [-1,  0],  '0_28': [-1,  0],  '0_29': [-1,  0],
  '0_0':  [ 0, +1],  '0_10': [ 0, +1],  '0_11': [ 0, +1],  '0_20': [ 0, +1],  '0_21': [ 0, +1],  '0_31': [ 0, +1],
  '0_2':  [+1,  0],  '0_3':  [+1,  0],  '0_12': [+1,  0],  '0_13': [+1,  0],  '0_23': [+1,  0],  '0_24': [+1,  0],
}

/** Return [neighborRow, neighborCol] for a staple crossover at (row,col) at global bp index, or null. */
function _xoverNeighborCell(row, col, bp, isHC) {
  if (isHC) {
    const fwd = hcIsForward(row, col)
    const key = `${fwd ? 1 : 0}_${((bp % HC_XOVER_PERIOD) + HC_XOVER_PERIOD) % HC_XOVER_PERIOD}`
    const d   = HC_XOVER_MAP[key]
    return d ? [row + d[0], col + d[1]] : null
  } else {
    const fwd = sqIsForward(row, col)
    const key = `${fwd ? 1 : 0}_${((bp % SQ_XOVER_PERIOD) + SQ_XOVER_PERIOD) % SQ_XOVER_PERIOD}`
    const d   = SQ_XOVER_MAP[key]
    return d ? [row + d[0], col + d[1]] : null
  }
}

/** Return [neighborRow, neighborCol] for a scaffold crossover at (row,col) at global bp index, or null. */
function _xoverNeighborCellScaffold(row, col, bp, isHC) {
  if (isHC) {
    const fwd = hcIsForward(row, col)
    const key = `${fwd ? 1 : 0}_${((bp % HC_XOVER_PERIOD) + HC_XOVER_PERIOD) % HC_XOVER_PERIOD}`
    const d   = HC_SCAF_XOVER_MAP[key]
    return d ? [row + d[0], col + d[1]] : null
  } else {
    const fwd = sqIsForward(row, col)
    const key = `${fwd ? 1 : 0}_${((bp % SQ_XOVER_PERIOD) + SQ_XOVER_PERIOD) % SQ_XOVER_PERIOD}`
    const d   = SQ_SCAF_XOVER_MAP[key]
    return d ? [row + d[0], col + d[1]] : null
  }
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

function helixCell(helix, isHC) {
  if (helix.grid_pos) return { row: helix.grid_pos[0], col: helix.grid_pos[1] }
  return isHC
    ? hcNmToCell(helix.axis_start.x, helix.axis_start.y)
    : sqNmToCell(helix.axis_start.x, helix.axis_start.y)
}
function helixIsForward(helix, isHC, cell) {
  return isHC ? hcIsForward(cell.row, cell.col) : sqIsForward(cell.row, cell.col)
}
// Helix track order = design.helices order (user-determined creation order, no sorting).
function sortedHelices(design) {
  return [...(design?.helices ?? [])]
}

// ── Strand utilities ──────────────────────────────────────────────────────────

function strandNtCount(strand) {
  return strand.domains.reduce((sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0)
}
function strandColor(strand, idx) {
  if (strand.strand_type === 'scaffold') return CLR_SCAFFOLD
  if (strand.color) return strand.color
  return STAPLE_PALETTE[idx % STAPLE_PALETTE.length]
}

// ── Main init ─────────────────────────────────────────────────────────────────

export function initPathview(canvasEl, containerEl, {
  onPaintScaffold,
  onPaintStaple,
  onEraseDomain,
  onNickStrand,
  onLigateStrand,
  onAddCrossover,
  onResizeEnds,
  onInsertLoopSkip,
  onPaintStrands,
  onStrandClick,
  onStrandHover,
  onSliceChange,
  onSelectionChange,
  onDeleteElements,
  onCrossoverContextMenu,
}) {
  const ctx = canvasEl.getContext('2d')

  // ── Design state ─────────────────────────────────────────────────────────────
  let _design  = null
  let _helices = []
  let _rowMap  = new Map()   // helix.id → { fwdY, revY, scaffoldFwd, cell, idx }
  let _totalBp = 0   // max bp end across all helices
  let _minBp   = 0   // min bp_start across all helices (may be negative)
  let _fitDone = false
  let _nativeOrientation = true   // cadnano native: helix order top-to-bottom as-is

  // ── Selection state ───────────────────────────────────────────────────────────
  // Each element (domain body, individual end cap, crossover arc) is selected
  // independently. Selection is editor-local — no outgoing 3D broadcast.
  //
  // Key formats:
  //   line:{helix_id}_{lo}_{hi}_{direction}   — domain body segment
  //   end:{helix_id}_{bp}_{direction}          — individual 5′ or 3′ end cap
  //   xo:{helix_id}_{index}_{strand}           — crossover arc (keyed on half_a)
  let _selectedElements = new Set()

  function _domainLineKey(dom) {
    const lo = Math.min(dom.start_bp, dom.end_bp)
    const hi = Math.max(dom.start_bp, dom.end_bp)
    return `line:${dom.helix_id}_${lo}_${hi}_${dom.direction}`
  }

  function _domainEndKey(dom, which) {   // which = '5p' | '3p'
    const lo  = Math.min(dom.start_bp, dom.end_bp)
    const hi  = Math.max(dom.start_bp, dom.end_bp)
    const isFwd = dom.direction === 'FORWARD'
    const bp  = which === '5p' ? (isFwd ? lo : hi) : (isFwd ? hi : lo)
    return `end:${dom.helix_id}_${bp}_${dom.direction}`
  }

  function _xoverKey(xo) {
    return `xo:${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`
  }

  // Compute the element key from a _hitTest result.
  function _hitElementKey(hit) {
    return hit.elementType === 'line'
      ? _domainLineKey(hit.dom)
      : _domainEndKey(hit.dom, hit.endWhich)
  }

  /** Return all element keys (line + end) for every domain in *strand*. */
  function _strandElementKeys(strand) {
    const keys = []
    for (const dom of strand.domains) {
      keys.push(_domainLineKey(dom))
      keys.push(_domainEndKey(dom, '5p'))
      keys.push(_domainEndKey(dom, '3p'))
    }
    return keys
  }

  function _loopSkipKey(helixId, bpIndex, delta) {
    return `ls:${helixId}_${bpIndex}_${delta > 0 ? 'loop' : 'skip'}`
  }

  /**
   * Hit-test loop/skip markers at a world-space point.
   * Returns { helixId, bpIndex, delta, key } or null.
   */
  function _hitTestLoopSkip(wx, wy) {
    if (!_design?.helices?.length) return null
    for (const helix of _design.helices) {
      if (!helix.loop_skips?.length) continue
      const info = _rowMap.get(helix.id)
      if (!info) continue
      for (const ls of helix.loop_skips) {
        const cx = _bpCenterX(ls.bp_index)
        const midY = (info.fwdY + info.revY) / 2
        const r = Math.min(BP_W, CELL_H) * 0.45
        if (Math.abs(wx - cx) <= r && Math.abs(wy - midY) <= r) {
          return { helixId: helix.id, bpIndex: ls.bp_index, delta: ls.delta,
                   key: _loopSkipKey(helix.id, ls.bp_index, ls.delta) }
        }
      }
    }
    return null
  }

  function _notifySelectionChange() {
    // Selection is editor-local; no outgoing 3D broadcast.
  }

  // ── Crossover sprite hit areas (rebuilt each frame in _drawCrossoverIndicators) ──
  let _xoverSprites = []   // [{ hid, bp, targetHid, cx, indY, halfAStrand, halfBStrand }]

  // ── Pan/zoom ──────────────────────────────────────────────────────────────────
  let _zoom = 1, _panX = 0, _panY = 0

  let _panActive    = false
  let _panStartCX   = 0, _panStartCY   = 0
  let _panStartPanX = 0, _panStartPanY = 0

  // ── Slice bar ─────────────────────────────────────────────────────────────────
  let _sliceBp       = 0
  let _sliceDragging = false

  // ── Paint state (pencil tool — scaffold + staple) ─────────────────────────────
  let _painting       = false
  let _paintH         = null
  let _paintAnchor    = 0
  let _paintLo        = 0
  let _paintHi        = 0
  let _paintIsScaffold = true
  let _paintDirection  = 'FORWARD'

  let _activeTool     = 'select'
  let _selectFilter   = { strand: true, scaf: true, stap: true, ends: true, xover: true, line: true }
  let _paintToolColor = STAPLE_PALETTE[0]

  // ── Lasso selection ───────────────────────────────────────────────────────────
  const DRAG_THRESHOLD = 4      // px — below this treat as click, not lasso drag
  let _lassoStarted = false     // true from pointerdown until pointerup/leave
  let _lassoActive  = false     // true once pointer moved > DRAG_THRESHOLD
  let _lassoCtrl    = false     // ctrl/meta held at lasso start
  let _lassoSX0 = 0, _lassoSY0 = 0   // screen start (threshold test)
  let _lassoWX0 = 0, _lassoWY0 = 0   // world start
  let _lassoWX1 = 0, _lassoWY1 = 0   // world current end (updated in pointermove)

  // ── End-drag resize ───────────────────────────────────────────────────────────
  let _endDragActive   = false
  let _endDragEntries  = []   // [{ strandId, helixId, end, origBp, direction, domLo, domHi, info }]
  let _endDragDeltaBp  = 0    // current clamped delta (shared across all dragged ends)
  let _endDragMinDelta = -Infinity
  let _endDragMaxDelta = +Infinity
  let _endDragStartWX  = 0    // world-x at drag start

  let _dbgLastEvent = '—'
  let _dbgDetail    = []   // extra lines appended to the debug overlay after each nick
  let _dbgShowSprites = false   // toggle with 'D' key — draws sprite hit-radius circles

  // ── Nick hover ghost ──────────────────────────────────────────────────────────
  // Null when not hovering a strand with the nick tool active.
  // { threeEndBp, fiveEndBp, y, hasNick } — world-space Y of the hovered track.
  let _nickHover = null
  let _shiftHeld = false

  // ── Coordinate helpers ────────────────────────────────────────────────────────

  function _c2w(cx, cy) {
    return { wx: (cx - _panX) / _zoom, wy: (cy - _panY) / _zoom }
  }
  // bp index N corresponds to the Nth cell (square).
  // Cell N occupies world x ∈ [_bpToX(N), _bpToX(N+1)]; its centre is _bpCenterX(N).
  // Tick marks (column-separator lines) are drawn at _bpToX(bp) = left boundary of cell bp.
  // Nick/crossover gaps also land at _bpToX(N) boundaries — NOT at cell centres.
  function _bpToX(bp)      { return GUTTER + bp * BP_W }
  function _bpCenterX(bp)  { return GUTTER + (bp + 0.5) * BP_W }
  function _xToBp(worldX)  { return Math.floor((worldX - GUTTER) / BP_W) }

  // ── Slice position helper ─────────────────────────────────────────────────────
  function _updateSliceBp(bp) {
    _sliceBp = bp
    onSliceChange?.(bp)
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  function _rebuildLayout() {
    _helices = sortedHelices(_design)
    // When not in native (cadnano) orientation, reverse the vertical helix order
    // so that the pathview matches the slice view's Y-up arrangement.
    if (!_nativeOrientation) _helices.reverse()
    _rowMap  = new Map()
    const isHC = _design?.lattice_type === 'HONEYCOMB'

    // Compute cells for each helix
    const cells = _helices.map(h => helixCell(h, isHC))

    // Detect disconnected groups via flood-fill on occupied grid cells.
    // Two cells are connected if Chebyshev distance ≤ 1 (adjacent row/col).
    const groupOf = new Int32Array(_helices.length)  // group id per helix
    groupOf.fill(-1)
    let gid = 0
    for (let seed = 0; seed < _helices.length; seed++) {
      if (groupOf[seed] !== -1) continue
      const queue = [seed]
      groupOf[seed] = gid
      while (queue.length) {
        const ci = queue.shift()
        const cr = cells[ci].row, cc = cells[ci].col
        for (let j = 0; j < _helices.length; j++) {
          if (groupOf[j] !== -1) continue
          if (Math.abs(cells[j].row - cr) <= 1 && Math.abs(cells[j].col - cc) <= 1) {
            groupOf[j] = gid
            queue.push(j)
          }
        }
      }
      gid++
    }

    let fwdY = RULER_H + TOP_PAD
    for (let i = 0; i < _helices.length; i++) {
      // Insert a gap when the group changes
      if (i > 0 && groupOf[i] !== groupOf[i - 1]) fwdY += GROUP_GAP
      const h    = _helices[i]
      const cell = cells[i]
      _rowMap.set(h.id, {
        fwdY, revY: fwdY + PAIR_Y,
        scaffoldFwd: helixIsForward(h, isHC, cell),
        cell, idx: i,
      })
      fwdY += ROW_H
    }
    _totalBp = _helices.length === 0 ? 0
      : Math.max(..._helices.map(h => h.bp_start + h.length_bp))
    _minBp   = _helices.length === 0 ? 0
      : Math.min(..._helices.map(h => h.bp_start))
    _sliceBp = Math.max(_minBp, Math.min(_sliceBp, _totalBp))
  }

  function _fitToContent() {
    const W = canvasEl.width, H = canvasEl.height
    if (!W || !H || !_helices.length) return
    // Include negative bp range: bp0 is the leftmost bp that must be visible.
    // For designs with no negative-bp helices this equals the original formula.
    const bp0 = Math.min(0, _minBp)
    const span = (_totalBp - bp0) + EXTEND_BPS
    const cW = GUTTER + span * BP_W
    // Use actual bottom of last row (accounts for group gaps)
    const lastInfo = _rowMap.get(_helices[_helices.length - 1].id)
    const cH = (lastInfo ? lastInfo.revY + CELL_H / 2 : RULER_H + TOP_PAD) + 20
    _zoom = Math.max(MIN_ZOOM, Math.min(1, W / cW, H / cH))
    _panX = Math.max(0, (W - cW * _zoom) / 2)
    _panY = Math.max(0, (H - cH * _zoom) / 2)
  }

  function _resize() {
    canvasEl.width  = containerEl.clientWidth  || 800
    canvasEl.height = containerEl.clientHeight || 400
    _draw()
  }
  new ResizeObserver(_resize).observe(containerEl)


  // ── Hit tests ─────────────────────────────────────────────────────────────────

  /**
   * Returns { strand, strandIdx, dom, domainIdx, elementType, endWhich } or null.
   *   elementType = 'end' | 'line'
   *   endWhich    = '5p' | '3p' | null  (set when elementType === 'end')
   * @param {object|null} filter — selectFilter object; when non-null, gates by
   *   strand type (scaf/stap) and cell position (ends = first/last bp, line = body).
   */
  function _hitTest(cx, cy, filter = null) {
    if (!_design?.strands) return null
    const { wx, wy } = _c2w(cx, cy)
    const HIT = PAIR_Y / 2
    for (const [hid, info] of _rowMap) {
      const dF = Math.abs(wy - info.fwdY)
      const dR = Math.abs(wy - info.revY)
      if (dF > HIT && dR > HIT) continue
      const isFwdTrack = dF <= dR
      const bp = _xToBp(wx)
      for (let si = 0; si < _design.strands.length; si++) {
        const strand = _design.strands[si]
        for (let di = 0; di < strand.domains.length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== hid) continue
          if ((dom.direction === 'FORWARD') !== isFwdTrack) continue
          const lo = Math.min(dom.start_bp, dom.end_bp)
          const hi = Math.max(dom.start_bp, dom.end_bp)
          if (bp < lo || bp > hi) continue
          const isEnd = (bp === lo || bp === hi)
          if (filter) {
            if (strand.strand_type === 'scaffold' && !filter.scaf) return null
            if (strand.strand_type === 'staple'   && !filter.stap) return null
            if ( isEnd && !filter.ends) return null
            if (!isEnd && !filter.line) return null
          }
          const elementType = isEnd ? 'end' : 'line'
          const isFwd = dom.direction === 'FORWARD'
          const endWhich = isEnd
            ? ((isFwd && bp === lo) || (!isFwd && bp === hi) ? '5p' : '3p')
            : null
          return { strand, strandIdx: si, dom, domainIdx: di, elementType, endWhich }
        }
      }
      break
    }
    return null
  }

  /**
   * Returns a Set<elementKey> of all individual elements (line, end, xover arc)
   * whose visual extent intersects the current lasso world rect and pass the filter.
   * No component expansion — each element is captured independently.
   */
  function _hitTestLassoElements() {
    const result = new Set()
    const lx0 = Math.min(_lassoWX0, _lassoWX1), lx1 = Math.max(_lassoWX0, _lassoWX1)
    const ly0 = Math.min(_lassoWY0, _lassoWY1), ly1 = Math.max(_lassoWY0, _lassoWY1)

    for (const strand of (_design?.strands ?? [])) {
      if (strand.strand_type === 'scaffold' && !_selectFilter.scaf) continue
      if (strand.strand_type === 'staple'   && !_selectFilter.stap) continue
      for (const dom of strand.domains) {
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const lo   = Math.min(dom.start_bp, dom.end_bp)
        const hi   = Math.max(dom.start_bp, dom.end_bp)
        const isFwd = dom.direction === 'FORWARD'
        const dxL  = _bpToX(lo), dxR = _bpToX(hi + 1)
        const dyC  = isFwd ? info.fwdY : info.revY
        // Quick reject — entire domain outside lasso
        if (dxR <= lx0 || dxL >= lx1 || dyC + CELL_H / 2 <= ly0 || dyC - CELL_H / 2 >= ly1) continue

        if (lo === hi) {
          // Single-bp domain: the whole cell is an end cap
          if (_selectFilter.ends) result.add(_domainEndKey(dom, '5p'))
        } else {
          // Left end-cap cell (lo bp): 5′ for FORWARD, 3′ for REVERSE
          if (_selectFilter.ends && lx1 > dxL && lx0 < dxL + BP_W)
            result.add(_domainEndKey(dom, isFwd ? '5p' : '3p'))
          // Right end-cap cell (hi bp): 3′ for FORWARD, 5′ for REVERSE
          if (_selectFilter.ends && lx1 > _bpToX(hi) && lx0 < dxR)
            result.add(_domainEndKey(dom, isFwd ? '3p' : '5p'))
          // Body (lo+1 .. hi columns)
          if (_selectFilter.line && lx1 > _bpToX(lo + 1) && lx0 < _bpToX(hi))
            result.add(_domainLineKey(dom))
        }
      }
    }

    // Crossover arcs
    if (_selectFilter.xover) {
      for (const xo of (_design?.crossovers ?? [])) {
        const infoA = _rowMap.get(xo.half_a.helix_id)
        const infoB = _rowMap.get(xo.half_b.helix_id)
        if (!infoA || !infoB) continue
        const x      = _bpCenterX(xo.half_a.index)
        const y0     = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
        const y1     = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
        const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
        const isScafXo = infoA.scaffoldFwd ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
        const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
        const axMin  = Math.min(x, x + bowDir * bowAmt) - BP_W * 0.5
        const axMax  = Math.max(x, x + bowDir * bowAmt) + BP_W * 0.5
        const ayMin  = Math.min(y0, y1), ayMax = Math.max(y0, y1)
        if (axMax <= lx0 || axMin >= lx1 || ayMax <= ly0 || ayMin >= ly1) continue
        result.add(_xoverKey(xo))
      }
    }

    // Loop/skip markers
    if (_selectFilter.loop || _selectFilter.skip) {
      for (const helix of (_design?.helices ?? [])) {
        if (!helix.loop_skips?.length) continue
        const info = _rowMap.get(helix.id)
        if (!info) continue
        for (const ls of helix.loop_skips) {
          if (ls.delta > 0 && !_selectFilter.loop) continue
          if (ls.delta < 0 && !_selectFilter.skip) continue
          const cx = _bpCenterX(ls.bp_index)
          const midY = (info.fwdY + info.revY) / 2
          const r = Math.min(BP_W, CELL_H) * 0.35
          if (cx + r > lx0 && cx - r < lx1 && midY + r > ly0 && midY - r < ly1) {
            result.add(_loopSkipKey(helix.id, ls.bp_index, ls.delta))
          }
        }
      }
    }

    return result
  }

  /**
   * Returns a Set<strandId> of all staple strands that have at least one domain
   * intersecting the current lasso rect.  Scaffold strands are excluded.
   */
  function _hitTestLassoStrands() {
    const result = new Set()
    const lx0 = Math.min(_lassoWX0, _lassoWX1), lx1 = Math.max(_lassoWX0, _lassoWX1)
    const ly0 = Math.min(_lassoWY0, _lassoWY1), ly1 = Math.max(_lassoWY0, _lassoWY1)
    for (const strand of (_design?.strands ?? [])) {
      if (strand.strand_type === 'scaffold') continue
      for (const dom of strand.domains) {
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const lo   = Math.min(dom.start_bp, dom.end_bp)
        const hi   = Math.max(dom.start_bp, dom.end_bp)
        const isFwd = dom.direction === 'FORWARD'
        const dxL  = _bpToX(lo), dxR = _bpToX(hi + 1)
        const dyC  = isFwd ? info.fwdY : info.revY
        if (dxR <= lx0 || dxL >= lx1 || dyC + CELL_H / 2 <= ly0 || dyC - CELL_H / 2 >= ly1) continue
        result.add(strand.id)
        break   // one domain hit is enough — no need to check the rest of this strand
      }
    }
    return result
  }

  /**
   * Hit-test a world-space point against all registered crossover arcs.
   * Returns { xo } if hit, or null if no arc is hit or the xover filter is off.
   */
  function _hitTestArc(wx, wy) {
    if (!_selectFilter.xover) return null
    if (!_design?.crossovers?.length) return null
    for (const xo of _design.crossovers) {
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue
      const x   = _bpCenterX(xo.half_a.index)
      const y0  = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1  = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const isScafXo = infoA.scaffoldFwd ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
      const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
      const xMin = Math.min(x, x + bowDir * bowAmt) - BP_W * 0.5
      const xMax = Math.max(x, x + bowDir * bowAmt) + BP_W * 0.5
      const yMin = Math.min(y0, y1) - CELL_H * 0.5
      const yMax = Math.max(y0, y1) + CELL_H * 0.5
      if (wx < xMin || wx > xMax || wy < yMin || wy > yMax) continue
      return { xo }
    }
    return null
  }

  function _isNearSliceBar(screenX) {
    // Slice bar highlights the entire cell (bp square), so hit-test against its screen extent.
    const sxLeft  = _bpToX(_sliceBp)     * _zoom + _panX
    const sxRight = _bpToX(_sliceBp + 1) * _zoom + _panX
    return screenX >= sxLeft && screenX <= sxRight
  }

  /**
   * Returns true if a nick is needed at nickBp on the given helix/direction strand.
   * A nick is needed when a domain of that direction covers nickBp but its 3' end
   * is not already at nickBp.
   *
   * FORWARD: 3' end of domain = max(start_bp, end_bp).  Nick needed if hi !== nickBp.
   * REVERSE: 3' end of domain = min(start_bp, end_bp).  Nick needed if lo !== nickBp.
   *
   * Returns false when no domain covers nickBp (nothing to nick).
   */
  function _needsNick(helixId, nickBp, direction) {
    if (!_design?.strands) return false
    for (const strand of _design.strands) {
      for (const dom of strand.domains) {
        if (dom.helix_id !== helixId || dom.direction !== direction) continue
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        if (nickBp < lo || nickBp > hi) continue
        // Domain covers nickBp. A valid nick requires at least one bp on each side
        // of the split — i.e. the domain must not start or end exactly at nickBp.
        //
        // FORWARD: 3' end = hi, 5' end = lo.
        //   Skip if hi == nickBp (3' already here) or lo == nickBp (5' at nick
        //   point — would produce a lone 1-bp left fragment).
        // REVERSE: 3' end = lo, 5' end = hi.
        //   Skip if lo == nickBp (3' already here) or hi == nickBp (5' at nick
        //   point — nothing to the right to form the right fragment).
        return lo !== nickBp && hi !== nickBp
      }
    }
    return false  // no domain covers this position — nothing to nick
  }

  /**
   * Returns true if a ligatable nick exists at nickBp on the given helix/direction.
   * A nick exists when one strand has its 3′ end (end_bp) at nickBp and a different
   * strand has its 5′ end (start_bp) at the adjacent bp.
   */
  /**
   * Find a ligateable nick adjacent to a hovered domain.
   * Checks the domain's actual boundary cells (not the clipped nickBp) for
   * an adjacent strand terminus.  Returns { threeEndBp, fiveEndBp, bpIndex }
   * where bpIndex is the 3′-end convention used by /design/ligate, or null.
   * cursorBp is used to pick the nearer end when both boundaries have nicks.
   */
  function _findLigation(dom, cursorBp) {
    if (!_design?.strands) return null
    const isFwd = dom.direction === 'FORWARD'
    const lo = Math.min(dom.start_bp, dom.end_bp)
    const hi = Math.max(dom.start_bp, dom.end_bp)

    const candidates = []

    if (isFwd) {
      // Right end: this domain's 3′ is at hi. Nick exists if another FORWARD domain
      // on this helix starts at hi+1 (its 5′ end = lo of that domain = hi+1).
      const rightOk = _design.strands.some(s =>
        s.domains.some(d => d.helix_id === dom.helix_id && d.direction === dom.direction
          && Math.min(d.start_bp, d.end_bp) === hi + 1))
      if (rightOk) candidates.push({ threeEndBp: hi, fiveEndBp: hi + 1, bpIndex: hi, dist: Math.abs(cursorBp - hi) })

      // Left end: this domain's 5′ is at lo. Nick exists if another FORWARD domain
      // ends at lo-1 (its 3′ end = hi of that domain = lo-1).
      const leftOk = _design.strands.some(s =>
        s.domains.some(d => d.helix_id === dom.helix_id && d.direction === dom.direction
          && Math.max(d.start_bp, d.end_bp) === lo - 1))
      if (leftOk) candidates.push({ threeEndBp: lo - 1, fiveEndBp: lo, bpIndex: lo - 1, dist: Math.abs(cursorBp - lo) })
    } else {
      // REVERSE: 3′ is at lo (left end), 5′ is at hi (right end).
      // Left end: nick exists if another REVERSE domain's 5′ (hi of that domain) = lo-1.
      const leftOk = _design.strands.some(s =>
        s.domains.some(d => d.helix_id === dom.helix_id && d.direction === dom.direction
          && Math.max(d.start_bp, d.end_bp) === lo - 1))
      if (leftOk) candidates.push({ threeEndBp: lo, fiveEndBp: lo - 1, bpIndex: lo, dist: Math.abs(cursorBp - lo) })

      // Right end: nick exists if another REVERSE domain's 3′ (lo of that domain) = hi+1.
      const rightOk = _design.strands.some(s =>
        s.domains.some(d => d.helix_id === dom.helix_id && d.direction === dom.direction
          && Math.min(d.start_bp, d.end_bp) === hi + 1))
      if (rightOk) candidates.push({ threeEndBp: hi + 1, fiveEndBp: hi, bpIndex: hi + 1, dist: Math.abs(cursorBp - hi) })
    }

    if (candidates.length === 0) return null
    candidates.sort((a, b) => a.dist - b.dist)
    return candidates[0]
  }

  // ── Draw utilities ────────────────────────────────────────────────────────────

  function _line(x1, y1, x2, y2) {
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke()
  }

  // ── Draw: track grid (2×N cell model) ────────────────────────────────────────

  function _drawAllTracks() {
    const isHC  = _design?.lattice_type === 'HONEYCOMB'
    const major = isHC ? 7 : 8

    // Viewport in world-space — extend one bp beyond each edge so partial
    // columns at the boundary are always fully drawn.
    const wLeft  = (-_panX) / _zoom
    const wRight = (canvasEl.width - _panX) / _zoom
    const bpL = Math.floor(_xToBp(wLeft)) - 1
    const bpR = Math.ceil(_xToBp(wRight)) + 1

    // Track backgrounds span the full visible viewport width (no fixed left/right
    // boundary) — the frozen gutter panel covers any content left of the label area.
    const startX = _bpToX(bpL)
    const endX   = _bpToX(bpR + 1)

    const half = CELL_H / 2

    for (const [, info] of _rowMap) {
      const { fwdY, revY } = info
      const topY = fwdY - half
      const botY = revY + half
      const sTop = topY * _zoom + _panY
      const sBot = botY * _zoom + _panY
      if (sBot < 0 || sTop > canvasEl.height) continue

      const pairH = CELL_H * 2   // total height of both cells

      // ── Cell backgrounds ────────────────────────────────────────────────────
      ctx.fillStyle = CLR_CELL_BG
      ctx.fillRect(startX, topY, endX - startX, pairH)

      // ── Horizontal divider between the two tracks ───────────────────────────
      ctx.strokeStyle = CLR_TRACK
      ctx.lineWidth   = 0.5 / _zoom
      _line(startX, fwdY + half, endX, fwdY + half)

      // ── Vertical column separators ──────────────────────────────────────────
      for (let bp = bpL; bp <= bpR; bp++) {
        const x = _bpToX(bp)
        if (bp % major === 0) {
          ctx.strokeStyle = CLR_TICK_MAJOR
          ctx.lineWidth   = 1 / _zoom
          _line(x, topY - 3, x, botY + 3)
        } else {
          ctx.strokeStyle = CLR_CELL_GRID
          ctx.lineWidth   = 0.5 / _zoom
          _line(x, topY, x, botY)
        }
      }

      // ── Outer border around the 2-cell pair ────────────────────────────────
      ctx.strokeStyle = CLR_TRACK
      ctx.lineWidth   = 1 / _zoom
      ctx.strokeRect(startX, topY, endX - startX, pairH)
    }
  }

  // ── Strand coloring + crossover slot tracking ───────────────────────────────
  //
  // Each strand IS the complete oligo — crossover ligation is done server-side.
  // colorOf returns the per-strand color directly; isXoverSlot suppresses end
  // caps at crossover boundaries.

  function _findStrandIdxAt(helixId, bp, direction) {
    if (!_design?.strands) return -1
    for (let si = 0; si < _design.strands.length; si++) {
      for (const dom of _design.strands[si].domains) {
        if (dom.helix_id !== helixId || dom.direction !== direction) continue
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        if (lo <= bp && bp <= hi) return si
      }
    }
    return -1
  }

  // Build per-frame helpers: colorOf (direct strand color) and isXoverSlot
  // (suppresses end caps at crossover boundaries).  No union-find needed —
  // crossover ligation is done server-side, so each strand IS the complete oligo.
  function _buildComponents() {
    const strands = _design?.strands ?? []

    // Crossover slot set — "helixId_bp_direction" for every registered half.
    // Used to suppress end caps on domains that terminate at a crossover.
    const xoverSlots = new Set()
    for (const xo of (_design?.crossovers ?? [])) {
      xoverSlots.add(`${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`)
      xoverSlots.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
    }

    return {
      colorOf:     (si) => strandColor(strands[si], si),
      membersOf:   (strandId) => new Set([strandId]),
      isXoverSlot: (hid, bp, dir) => xoverSlots.has(`${hid}_${bp}_${dir}`),
    }
  }

  // Frame-cached result of _buildComponents() — rebuilt at the top of _draw().
  let _components = { colorOf: (si) => strandColor((_design?.strands ?? [])[si], si), membersOf: () => new Set(), isXoverSlot: () => false }

  // Strand-level selection glow — rebuilt per frame in _draw().
  const CLR_STRAND_GLOW = '#ff3333'
  let _strandSelectedIds = new Set()   // strand IDs that are "whole-strand selected"

  /** Rebuild _strandSelectedIds from _selectedElements when strand filter is on.
   *  Expands to the full crossover-connected component so that strands linked
   *  by registered crossovers all glow together.  */
  function _rebuildStrandSelection() {
    _strandSelectedIds = new Set()
    if (!_selectFilter.strand || !_selectedElements.size || !_design?.strands) return
    // Collect directly-selected strand IDs
    const directIds = new Set()
    for (const strand of _design.strands) {
      for (const dom of strand.domains) {
        if (_selectedElements.has(_domainLineKey(dom)) ||
            _selectedElements.has(_domainEndKey(dom, '5p')) ||
            _selectedElements.has(_domainEndKey(dom, '3p'))) {
          directIds.add(strand.id)
          break
        }
      }
    }
    // Expand each directly-selected strand to its full crossover component
    for (const sid of directIds) {
      for (const memberId of _components.membersOf(sid)) {
        _strandSelectedIds.add(memberId)
      }
    }
  }

  // ── Draw: strand domains ──────────────────────────────────────────────────────
  //
  // Layout (FORWARD example, cells indexed by bp):
  //
  //   cell  lo   lo+1  …  hi-1   hi
  //         ┌────┬────┬──┬────┬──────┐
  //   fwd   │ ───┼────┼──┼────│  ▶  │   ← 3′ triangle fills cell hi
  //         └────┴────┴──┴────┴──────┘
  //
  //  x1 = _bpToX(lo)      — left edge of first cell  (5′ for FORWARD)
  //  x2 = _bpToX(hi + 1)  — right edge of last cell
  //  The 3′ triangle occupies [x2-BP_W … x2]; body covers [x1 … x2-BP_W].
  //  For a 1-bp domain the body has zero width and only the triangle is drawn.

  /** Draw a single domain.
   *
   * suppress5prime / suppress3prime — skip the end cap (square/triangle):
   *   xoverAt5 / xoverAt3   = true  → registered crossover: body stops at cell centre
   *   routing suppress only  = true  → scaffold routing: body extends to the N|N+1 border
   *
   * "Cell centre" rule: when a crossover arc attaches at an end, the body
   * stops halfway through the terminal cell (BP_W/2 from the border).  This
   * leaves the half-cell between the centre and the N|N+1 border empty, making
   * it visually clear that the two sides of the boundary are not connected.
   */
  function _drawDomain(dom, info, color,
    suppress5prime = false, suppress3prime = false,
    xoverAt5 = false, xoverAt3 = false,
    glowStrand = false,
  ) {
    const isFwd   = dom.direction === 'FORWARD'
    const y       = isFwd ? info.fwdY : info.revY
    const lo      = Math.min(dom.start_bp, dom.end_bp)
    const hi      = Math.max(dom.start_bp, dom.end_bp)
    const x1      = _bpToX(lo)
    const x2      = _bpToX(hi + 1)
    const half    = CELL_H / 2
    const sThick  = CELL_H * 0.20
    const sqSz    = Math.min(BP_W, CELL_H) * 0.80

    if (glowStrand) {
      ctx.shadowColor = CLR_STRAND_GLOW
      ctx.shadowBlur  = 10 / _zoom
    }

    // Per-element selection — each element highlighted independently.
    const lineSelected = _selectedElements.has(_domainLineKey(dom))
    const fiveSel      = _selectedElements.has(_domainEndKey(dom, '5p'))
    const threeSel     = _selectedElements.has(_domainEndKey(dom, '3p'))

    // Body ring
    if (lineSelected) {
      const pad = 2 / _zoom
      ctx.strokeStyle = CLR_SEL_RING
      ctx.lineWidth   = 2 / _zoom
      ctx.strokeRect(x1 - pad, y - half - pad, (x2 - x1) + 2 * pad, CELL_H + 2 * pad)
    }
    // End-cap overlays (semi-transparent fill behind the shape)
    if (fiveSel && !suppress5prime) {
      ctx.fillStyle = CLR_SEL_END
      const fiveX = isFwd ? x1 : _bpToX(hi)
      ctx.fillRect(fiveX, y - half, BP_W, CELL_H)
    }
    if (threeSel && !suppress3prime) {
      ctx.fillStyle = CLR_SEL_END
      const threeX = isFwd ? _bpToX(hi) : x1
      ctx.fillRect(threeX, y - half, BP_W, CELL_H)
    }

    // End-cap shape colors (independent for 5′ and 3′)
    const cap5Color = fiveSel  ? CLR_SEL_RING : color
    const cap3Color = threeSel ? CLR_SEL_RING : color

    if (isFwd) {
      // FORWARD — 5′ at LEFT (lo), 3′ at RIGHT (hi)
      const bodyStart = xoverAt5      ? x1 + BP_W / 2
                      : suppress5prime ? x1
                      :                  x1 + sqSz / 2
      const bodyEnd   = xoverAt3      ? x2 - BP_W / 2
                      : suppress3prime ? x2
                      :                  x2 - BP_W

      if (!suppress5prime) {
        ctx.fillStyle = cap5Color
        ctx.fillRect(x1, y - sqSz / 2, sqSz, sqSz)   // 5′ square
      }
      ctx.fillStyle = color
      if (bodyEnd > bodyStart) {
        ctx.fillRect(bodyStart, y - sThick / 2, bodyEnd - bodyStart, sThick)
      }
      if (!suppress3prime) {
        ctx.fillStyle = cap3Color
        const triStart = x2 - BP_W
        ctx.beginPath()
        ctx.moveTo(triStart, y - half)
        ctx.lineTo(x2,       y)
        ctx.lineTo(triStart, y + half)
        ctx.closePath(); ctx.fill()
      }
    } else {
      // REVERSE — 5′ at RIGHT (hi), 3′ at LEFT (lo)
      const bodyEnd   = xoverAt5      ? x2 - BP_W / 2
                      : suppress5prime ? x2
                      :                  x2 - sqSz / 2
      const bodyStart = xoverAt3      ? x1 + BP_W / 2
                      : suppress3prime ? x1
                      :                  x1 + BP_W

      if (!suppress5prime) {
        ctx.fillStyle = cap5Color
        ctx.fillRect(x2 - sqSz, y - sqSz / 2, sqSz, sqSz)   // 5′ square
      }
      ctx.fillStyle = color
      if (bodyEnd > bodyStart) {
        ctx.fillRect(bodyStart, y - sThick / 2, bodyEnd - bodyStart, sThick)
      }
      if (!suppress3prime) {
        ctx.fillStyle = cap3Color
        const triEnd = x1 + BP_W
        ctx.beginPath()
        ctx.moveTo(triEnd, y - half)
        ctx.lineTo(x1,     y)
        ctx.lineTo(triEnd, y + half)
        ctx.closePath(); ctx.fill()
      }
    }
    if (glowStrand) { ctx.shadowBlur = 0 }
  }

  function _drawAllDomains() {
    if (!_design?.strands) return
    for (let si = 0; si < _design.strands.length; si++) {
      const strand   = _design.strands[si]
      const isGlow   = _strandSelectedIds.has(strand.id)
      const color    = isGlow ? CLR_STRAND_GLOW : _components.colorOf(si)
      const n        = strand.domains.length
      for (let di = 0; di < n; di++) {
        const dom  = strand.domains[di]
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const sTop = (info.fwdY - CELL_H / 2) * _zoom + _panY
        if ((info.revY + CELL_H / 2) * _zoom + _panY < 0 || sTop > canvasEl.height) continue

        // Suppress the end cap (square or triangle) wherever a crossover arc attaches.
        //
        // Two cases:
        //   1. Registered crossover (separate strands linked via _design.crossovers) —
        //      check _components.isXoverSlot at the domain's 5'/3' bp.
        //   2. Scaffold routing crossover (multi-helix domains within the same strand) —
        //      keep the existing adjacent-domain check.
        const dir     = dom.direction
        const lo      = Math.min(dom.start_bp, dom.end_bp)
        const hi      = Math.max(dom.start_bp, dom.end_bp)
        const fiveBp  = dir === 'FORWARD' ? lo : hi
        const threeBp = dir === 'FORWARD' ? hi : lo
        const prev = di > 0     ? strand.domains[di - 1] : null
        const next = di < n - 1 ? strand.domains[di + 1] : null
        // Registered crossover: body stops at cell centre (visualises the gap at N|N+1).
        const xoverAt5 = _components.isXoverSlot(dom.helix_id, fiveBp,  dir)
        const xoverAt3 = _components.isXoverSlot(dom.helix_id, threeBp, dir)
        // Scaffold routing / coaxial continuation: body extends to the border
        // (strand continues on another helix).  Exact-bp match handles scaffold
        // routing crossovers; ±1 match handles coaxial helix ligation where
        // adjacent domains are on different helix IDs but consecutive bp.
        const adj5 = dir === 'FORWARD' ? -1 : 1   // prev.end_bp + adj5 === dom.start_bp
        const adj3 = dir === 'FORWARD' ?  1 : -1   // dom.end_bp + adj3 === next.start_bp
        const routingSuppress5 = !!(prev && prev.helix_id !== dom.helix_id
          && (prev.end_bp === dom.start_bp || prev.end_bp + adj5 === dom.start_bp))
        const routingSuppress3 = !!(next && next.helix_id !== dom.helix_id
          && (next.start_bp === dom.end_bp || dom.end_bp + adj3 === next.start_bp))
        const suppress5prime = xoverAt5 || routingSuppress5
        const suppress3prime = xoverAt3 || routingSuppress3

        _drawDomain(dom, info, color, suppress5prime, suppress3prime, xoverAt5, xoverAt3, isGlow)
      }
    }
  }

  // ── Draw: coaxial continuation arcs ───────────────────────────────────────────
  //
  // When two adjacent domains in the same strand are on different helices at
  // consecutive bp (coaxial ligation), draw a connecting arc so the user sees
  // that the strand is continuous.

  function _drawCoaxialArcs() {
    if (!_design?.strands) return
    const sThick = CELL_H * 0.20
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = sThick
    ctx.shadowBlur = 0
    for (let si = 0; si < _design.strands.length; si++) {
      const strand = _design.strands[si]
      const strandGlow = _strandSelectedIds.has(strand.id)
      const color  = strandGlow ? CLR_STRAND_GLOW : _components.colorOf(si)
      ctx.strokeStyle = color
      if (strandGlow) { ctx.shadowColor = CLR_STRAND_GLOW; ctx.shadowBlur = 10 / _zoom }
      else            { ctx.shadowBlur = 0 }
      for (let di = 0; di < strand.domains.length - 1; di++) {
        const domA = strand.domains[di]
        const domB = strand.domains[di + 1]
        if (domA.helix_id === domB.helix_id) continue  // same helix — no arc needed
        // Skip if this transition is a registered crossover — _drawCrossoverArcs handles those.
        if (_components.isXoverSlot(domA.helix_id, domA.end_bp, domA.direction)) continue
        // Check for coaxial / overhang adjacency: domA.end_bp ±1 === domB.start_bp
        const isFwdA = domA.direction === 'FORWARD'
        const adj    = isFwdA ? 1 : -1
        // Overhang domains may also match exactly (end_bp === start_bp)
        if (domA.end_bp + adj !== domB.start_bp && domA.end_bp !== domB.start_bp) continue
        const infoA = _rowMap.get(domA.helix_id)
        const infoB = _rowMap.get(domB.helix_id)
        if (!infoA || !infoB) continue
        // Arc from 3' end of domA to 5' end of domB — use each domain's
        // own direction for its Y track (overhangs may be antiparallel).
        const xA = _bpCenterX(domA.end_bp)
        const xB = _bpCenterX(domB.start_bp)
        const yA = isFwdA                          ? infoA.fwdY : infoA.revY
        const yB = domB.direction === 'FORWARD'    ? infoB.fwdY : infoB.revY
        const midX = (xA + xB) / 2
        const midY = (yA + yB) / 2
        const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
        ctx.beginPath()
        ctx.moveTo(xA, yA)
        ctx.quadraticCurveTo(midX + bowAmt, midY, xB, yB)
        ctx.stroke()
      }
    }
    ctx.restore()
  }

  // ── Draw: placed crossover arcs ───────────────────────────────────────────────
  //
  // For each crossover in _design.crossovers, draw a quadratic bezier arc from
  // the center of cell half_a.index on helix A's track to the same column on
  // helix B's track. The bow direction follows the cadnano2 _stapH convention:
  // HC period 21: _stapH=[7,14,0] → bow right; SQ period 32: _stapH=[0,8,16,24] → bow right.

  const _XOVER_BOW_RIGHT_HC      = new Set([0, 7, 14])             // HC period 21 (_stapH)
  const _XOVER_BOW_RIGHT_SQ      = new Set([0, 8, 16, 24])         // SQ period 32 (_stapH)
  const _XOVER_BOW_RIGHT_HC_SCAF = new Set([2, 5, 9, 12, 16, 19])  // HC period 21 (_scafH)
  const _XOVER_BOW_RIGHT_SQ_SCAF = new Set([0, 3, 5, 8, 11, 13, 16, 19, 21, 24, 27, 29]) // SQ period 32 (squareScafHigh)

  /** Return +1 (right) or -1 (left) bow direction for the given global bp index.
   *  isScaffold selects the scaffold offset table instead of the staple one. */
  function _xoverBowDir(bpIndex, isScaffold = false) {
    const isHC = !_design || _design.lattice_type === 'HONEYCOMB'
    if (isHC) {
      const m = ((bpIndex % HC_XOVER_PERIOD) + HC_XOVER_PERIOD) % HC_XOVER_PERIOD
      return (isScaffold ? _XOVER_BOW_RIGHT_HC_SCAF : _XOVER_BOW_RIGHT_HC).has(m) ? +1 : -1
    } else {
      const m = ((bpIndex % SQ_XOVER_PERIOD) + SQ_XOVER_PERIOD) % SQ_XOVER_PERIOD
      return (isScaffold ? _XOVER_BOW_RIGHT_SQ_SCAF : _XOVER_BOW_RIGHT_SQ).has(m) ? +1 : -1
    }
  }

  function _drawCrossoverArcs() {
    if (!_design?.crossovers?.length) return
    const sThick = CELL_H * 0.20
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = sThick
    for (const xo of _design.crossovers) {
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue
      const sA      = _findStrandIdxAt(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
      const sB      = _findStrandIdxAt(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
      const strandGlow = (sA >= 0 && _strandSelectedIds.has(_design.strands[sA].id)) ||
                         (sB >= 0 && _strandSelectedIds.has(_design.strands[sB].id))
      const arcSel  = _selectedElements.has(_xoverKey(xo))
      if (arcSel) {
        ctx.strokeStyle  = CLR_SEL_RING
        ctx.lineWidth    = sThick * 2.5
        ctx.shadowColor  = CLR_SEL_RING
        ctx.shadowBlur   = 8 / _zoom
      } else if (strandGlow) {
        ctx.strokeStyle  = CLR_STRAND_GLOW
        ctx.lineWidth    = sThick
        ctx.shadowColor  = CLR_STRAND_GLOW
        ctx.shadowBlur   = 10 / _zoom
      } else {
        ctx.strokeStyle  = sA >= 0 ? _components.colorOf(sA) : CLR_SCAFFOLD  // normal arc color
        ctx.lineWidth    = sThick
        ctx.shadowBlur   = 0
      }
      const x  = _bpCenterX(xo.half_a.index)
      const y0 = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1 = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
      const isScafXo = infoA.scaffoldFwd ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
      const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const midY   = (y0 + y1) / 2
      ctx.beginPath()
      ctx.moveTo(x, y0)
      ctx.quadraticCurveTo(x + bowDir * bowAmt, midY, x, y1)
      ctx.stroke()

      // Extra-base tick marks — one bar per extra base, sampled evenly along
      // the quadratic Bézier arc, each extending from the arc toward the bow centre.
      if (xo.extra_bases?.length > 0) {
        const n     = xo.extra_bases.length
        const tickW = BP_W * 0.7   // length of each bar
        ctx.save()
        ctx.strokeStyle = arcSel ? CLR_SEL_RING : (sA >= 0 ? _components.colorOf(sA) : CLR_SCAFFOLD)
        ctx.lineWidth   = sThick * 0.7
        ctx.lineCap     = 'butt'
        ctx.shadowBlur  = 0
        for (let i = 1; i <= n; i++) {
          const t  = i / (n + 1)
          const mt = 1 - t
          // P(t) = (1-t)²P0 + 2t(1-t)P1 + t²P2; P0.x=P2.x=x so bx simplifies
          const bx = x + 2 * mt * t * bowDir * bowAmt
          const by = mt * mt * y0 + 2 * mt * t * midY + t * t * y1
          // Bar starts at the arc point and extends toward the bow direction (inward)
          ctx.beginPath()
          ctx.moveTo(bx, by)
          ctx.lineTo(bx + bowDir * tickW, by)
          ctx.stroke()
        }
        ctx.restore()
      }
    }
    ctx.restore()
    ctx.shadowBlur = 0   // ensure shadow doesn't leak into subsequent draws
  }

  // ── Draw: loop / skip markers ──────────────────────────────────────────────
  //
  // For each helix, iterate its loop_skips array and draw visual markers:
  //   skip  (delta < 0): red ✕ at the bp column, spanning both fwd and rev tracks
  //   loop  (delta > 0): blue circle at the bp column, spanning both fwd and rev tracks

  const CLR_SKIP = '#dd4444'
  const CLR_LOOP = '#4488dd'

  function _drawLoopSkips() {
    if (!_design?.helices?.length) return
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'

    for (const helix of _design.helices) {
      if (!helix.loop_skips?.length) continue
      const info = _rowMap.get(helix.id)
      if (!info) continue

      for (const ls of helix.loop_skips) {
        const cx = _bpCenterX(ls.bp_index)
        const midY = (info.fwdY + info.revY) / 2
        const r = Math.min(BP_W, CELL_H) * 0.35
        const isSel = _selectedElements.has(_loopSkipKey(helix.id, ls.bp_index, ls.delta))

        // Selection highlight ring
        if (isSel) {
          const pad = 3 / _zoom
          ctx.strokeStyle = CLR_SEL_RING
          ctx.lineWidth   = 2 / _zoom
          ctx.beginPath()
          ctx.arc(cx, midY, r + pad, 0, Math.PI * 2)
          ctx.stroke()
        }

        if (ls.delta < 0) {
          // Skip — draw ✕
          ctx.strokeStyle = isSel ? CLR_SEL_RING : CLR_SKIP
          ctx.lineWidth   = 2 / _zoom
          ctx.beginPath()
          ctx.moveTo(cx - r, midY - r)
          ctx.lineTo(cx + r, midY + r)
          ctx.moveTo(cx + r, midY - r)
          ctx.lineTo(cx - r, midY + r)
          ctx.stroke()
        } else if (ls.delta > 0) {
          // Loop — draw circle (one per extra base)
          ctx.strokeStyle = isSel ? CLR_SEL_RING : CLR_LOOP
          ctx.lineWidth   = 2 / _zoom
          for (let i = 0; i < ls.delta; i++) {
            const offset = (i - (ls.delta - 1) / 2) * r * 1.8
            ctx.beginPath()
            ctx.arc(cx + offset, midY, r * 0.7, 0, Math.PI * 2)
            ctx.stroke()
          }
        }
      }
    }
    ctx.restore()
  }

  // ── Draw: valid crossover site indicators ────────────────────────────────────
  //
  // A small circle appears in the whitespace on the non-scaffold side of each
  // helix, at every bp column that has a valid (unoccupied) crossover site.
  // The target helix's display index is printed inside the circle.
  //
  // "Non-scaffold side":
  //   forward cell (scaffold on top/FORWARD) → indicator below, in gap under revY
  //   reverse cell (scaffold on bottom/REVERSE) → indicator above, in gap over fwdY

  function _drawCrossoverIndicators() {
    _xoverSprites = []   // rebuild hit areas each frame
    if (!_design?.helices?.length) return
    if (_zoom < 0.55) return              // too far out — hide entirely
    const simplified = _zoom < 1       // far out — plain blue dots, no text/glow
    const isHC = _design.lattice_type === 'HONEYCOMB'

    // Visible bp window (world-space)
    const wLeft  = (-_panX) / _zoom
    const wRight = (canvasEl.width - _panX) / _zoom
    const bpL = Math.floor(_xToBp(wLeft)) - 1   // allow negative (ss-scaffold loops)
    const bpR = Math.ceil(_xToBp(wRight)) + 1

    // Track-aware occupied set: "helix_id_bp_DIRECTION"
    // Staple and scaffold crossovers occupy different tracks at the same bp,
    // so we track them independently.
    const occupied = new Set()
    for (const xo of (_design.crossovers ?? [])) {
      occupied.add(`${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`)
      occupied.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
    }

    // Pre-build strand coverage: "helix_id_DIRECTION" → [[lo, hi], ...]
    // Used to gate indicators — only show where both strand slots are occupied.
    const strandRanges = new Map()
    for (const strand of (_design.strands ?? [])) {
      for (const dom of strand.domains) {
        const key = `${dom.helix_id}_${dom.direction}`
        let list = strandRanges.get(key)
        if (!list) { list = []; strandRanges.set(key, list) }
        list.push([Math.min(dom.start_bp, dom.end_bp), Math.max(dom.start_bp, dom.end_bp)])
      }
    }
    const _slotOccupied = (helixId, bp, direction) => {
      const ranges = strandRanges.get(`${helixId}_${direction}`) ?? []
      return ranges.some(([lo, hi]) => lo <= bp && bp <= hi)
    }

    // cell key "row_col" → { hid, info }
    const cellMap = new Map()
    for (const [hid, info] of _rowMap) {
      cellMap.set(`${info.cell.row}_${info.cell.col}`, { hid, info })
    }

    // Minimum bp referenced by strand domains per helix (may be < helix.bp_start for ss loops).
    const minDomainBpByHelix = new Map()
    for (const strand of (_design.strands ?? [])) {
      for (const dom of strand.domains) {
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const cur = minDomainBpByHelix.get(dom.helix_id) ?? Infinity
        if (lo < cur) minDomainBpByHelix.set(dom.helix_id, lo)
      }
    }

    const indGap = CELL_H / 2 + 3   // = 9 px from track centre
    const fs = Math.max(4, XOVER_R * 1.5)

    // Helper: draw one indicator circle
    const _drawSprite = (cx, indY, label, isScaffold) => {
      if (simplified) {
        // Plain filled dot — no glow, stroke, or text
        ctx.beginPath()
        ctx.arc(cx, indY, XOVER_R * 0.7, 0, 2 * Math.PI)
        ctx.fillStyle = isScaffold ? '#005fa0' : '#3399dd'
        ctx.fill()
        return
      }
      ctx.shadowColor = isScaffold ? CLR_SCAF_XOVER_GLOW : CLR_XOVER_GLOW
      ctx.shadowBlur  = 6
      ctx.beginPath()
      ctx.arc(cx, indY, XOVER_R, 0, 2 * Math.PI)
      ctx.fillStyle   = isScaffold ? CLR_SCAF_XOVER_FILL   : CLR_XOVER_FILL
      ctx.fill()
      ctx.strokeStyle = isScaffold ? CLR_SCAF_XOVER_STROKE : CLR_XOVER_STROKE
      ctx.lineWidth   = 1.5 / _zoom
      ctx.stroke()
      ctx.shadowBlur  = 0
      ctx.fillStyle   = isScaffold ? CLR_SCAF_XOVER_TEXT   : CLR_XOVER_TEXT
      ctx.fillText(label, cx, indY)
    }

    ctx.save()
    ctx.textAlign    = 'center'
    ctx.textBaseline = 'middle'
    ctx.font         = `bold ${fs}px sans-serif`

    for (const [hid, info] of _rowMap) {
      const { cell, scaffoldFwd, fwdY, revY } = info
      const helix = _helices.find(h => h.id === hid)
      if (!helix) continue

      const helixMinBp = minDomainBpByHelix.get(hid) ?? helix.bp_start
      const bpStart = Math.max(bpL, helixMinBp)
      const bpEnd   = Math.min(bpR, helix.bp_start + helix.length_bp - 1)

      for (let bp = bpStart; bp <= bpEnd; bp++) {
        const cx = _bpCenterX(bp)

        const stapIndY = scaffoldFwd ? revY + indGap : fwdY - indGap
        const scafIndY = scaffoldFwd ? fwdY - indGap : revY + indGap

        // ── Staple indicator (non-scaffold side) — always visible ─────────────
        const stapNb = _xoverNeighborCell(cell.row, cell.col, bp, isHC)
        if (stapNb) {
          const target = cellMap.get(`${stapNb[0]}_${stapNb[1]}`)
          if (target) {
            const stapA = scaffoldFwd ? 'REVERSE' : 'FORWARD'
            const stapB = scaffoldFwd ? 'FORWARD' : 'REVERSE'
            if (!occupied.has(`${hid}_${bp}_${stapA}`) &&
                _slotOccupied(hid, bp, stapA) &&
                _slotOccupied(target.hid, bp, stapB)) {
              _xoverSprites.push({ hid, bp, targetHid: target.hid, cx, indY: stapIndY, halfAStrand: stapA, halfBStrand: stapB, isScaffold: false })
              _drawSprite(cx, stapIndY, target.info.idx, false)
            }
          }
        }

        // ── Scaffold indicator (scaffold side) — visible only while Shift held ─
        if (_shiftHeld) {
          const scafNb = _xoverNeighborCellScaffold(cell.row, cell.col, bp, isHC)
          if (scafNb) {
            const target = cellMap.get(`${scafNb[0]}_${scafNb[1]}`)
            if (target) {
              const scafA = scaffoldFwd ? 'FORWARD' : 'REVERSE'
              const scafB = scaffoldFwd ? 'REVERSE' : 'FORWARD'
              if (!occupied.has(`${hid}_${bp}_${scafA}`) &&
                  _slotOccupied(hid, bp, scafA) &&
                  _slotOccupied(target.hid, bp, scafB)) {
                _xoverSprites.push({ hid, bp, targetHid: target.hid, cx, indY: scafIndY, halfAStrand: scafA, halfBStrand: scafB, isScaffold: true })
                _drawSprite(cx, scafIndY, target.info.idx, true)
              }
            }
          }
        }
      }
    }

    ctx.textBaseline = 'alphabetic'
    ctx.restore()
  }

  function _hitTestCrossoverSprite(screenX, screenY) {
    const { wx, wy } = _c2w(screenX, screenY)
    const hitR = (XOVER_R + 4) / _zoom
    for (const sp of _xoverSprites) {
      const dx = wx - sp.cx, dy = wy - sp.indY
      if (dx * dx + dy * dy <= hitR * hitR) return sp
    }
    return null
  }

  // ── End-drag helpers ──────────────────────────────────────────────────────────

  // Build entry list from all `end:` keys in _selectedElements.
  function _resolveEndDragEntries() {
    const entries = []
    for (const key of _selectedElements) {
      if (!key.startsWith('end:')) continue
      const m = key.match(/^end:(.+)_(\d+)_(FORWARD|REVERSE)$/)
      if (!m) continue
      const [, helix_id, bpStr, direction] = m
      const bp = parseInt(bpStr)
      for (const strand of (_design?.strands ?? [])) {
        let found = false
        for (const dom of strand.domains) {
          if (dom.helix_id !== helix_id || dom.direction !== direction) continue
          const lo    = Math.min(dom.start_bp, dom.end_bp)
          const hi    = Math.max(dom.start_bp, dom.end_bp)
          if (bp !== lo && bp !== hi) continue
          const isFwd = direction === 'FORWARD'
          const is5p  = isFwd ? bp === lo : bp === hi
          const helix = _design.helices.find(h => h.id === helix_id)
          entries.push({
            strandId: strand.id,
            helixId:  helix_id,
            end:      is5p ? '5p' : '3p',
            origBp:   bp,
            direction,
            domLo:    lo,
            domHi:    hi,
            info:     _rowMap.get(helix_id),
          })
          found = true; break
        }
        if (found) break
      }
    }
    return entries
  }

  // Compute shared [minDelta, maxDelta] across all entries.
  function _computeEndDragLimits(entries) {
    let minDelta = -Infinity, maxDelta = +Infinity

    // Helper: crossover positions on a specific helix+direction
    const xoverPositions = (helixId, direction) => {
      const positions = new Set()
      for (const xo of (_design?.crossovers ?? [])) {
        for (const half of [xo.half_a, xo.half_b]) {
          if (half.helix_id === helixId && half.strand === direction)
            positions.add(half.index)
        }
      }
      return positions
    }

    // Helper: other domain endpoints on the same helix+direction (excluding this domain)
    const otherEndpoints = (helixId, direction, domLo, domHi) => {
      const pts = []
      for (const strand of (_design?.strands ?? [])) {
        for (const dom of strand.domains) {
          if (dom.helix_id !== helixId || dom.direction !== direction) continue
          const lo = Math.min(dom.start_bp, dom.end_bp)
          const hi = Math.max(dom.start_bp, dom.end_bp)
          if (lo === domLo && hi === domHi) continue   // same domain — skip
          pts.push(lo, hi)
        }
      }
      return pts
    }

    for (const entry of entries) {
      const { helixId, direction, end, origBp, domLo, domHi } = entry
      const isFwd = direction === 'FORWARD'
      const xoPos = xoverPositions(helixId, direction)
      const others = otherEndpoints(helixId, direction, domLo, domHi)

      // If the end itself is a crossover attachment point, it cannot move.
      if (xoPos.has(origBp)) {
        minDelta = Math.max(minDelta, 0)
        maxDelta = Math.min(maxDelta, 0)
        continue
      }

      // Positions of crossovers strictly inside the domain [domLo, domHi]
      const innerXovers = [...xoPos].filter(p => p > domLo && p < domHi)

      if (end === '5p') {
        if (isFwd) {
          // 5′ FORWARD is at domLo — moving left extends, right shrinks
          // Shrink limit: first inner crossover, or hi (keep ≥ 1 bp)
          const shrinkBlock = innerXovers.length
            ? Math.min(...innerXovers) - domLo
            : domHi - domLo
          maxDelta = Math.min(maxDelta, shrinkBlock)
          // Extend limit: nearest other endpoint to the left (helix grows if none)
          const leftBlocks = others.filter(p => p < domLo)
          const extendBlock = leftBlocks.length
            ? domLo - Math.max(...leftBlocks) - 1
            : Infinity
          minDelta = Math.max(minDelta, -extendBlock)
        } else {
          // 5′ REVERSE is at domHi — moving right extends, left shrinks
          const shrinkBlock = innerXovers.length
            ? domHi - Math.max(...innerXovers)
            : domHi - domLo
          minDelta = Math.max(minDelta, -shrinkBlock)
          const rightBlocks = others.filter(p => p > domHi)
          const extendBlock = rightBlocks.length
            ? Math.min(...rightBlocks) - domHi - 1
            : Infinity
          maxDelta = Math.min(maxDelta, extendBlock)
        }
      } else {
        // end === '3p'
        if (isFwd) {
          // 3′ FORWARD is at domHi — moving right extends, left shrinks
          const shrinkBlock = innerXovers.length
            ? domHi - Math.max(...innerXovers)
            : domHi - domLo
          minDelta = Math.max(minDelta, -shrinkBlock)
          const rightBlocks = others.filter(p => p > domHi)
          const extendBlock = rightBlocks.length
            ? Math.min(...rightBlocks) - domHi - 1
            : Infinity
          maxDelta = Math.min(maxDelta, extendBlock)
        } else {
          // 3′ REVERSE is at domLo — moving left extends, right shrinks
          const shrinkBlock = innerXovers.length
            ? Math.min(...innerXovers) - domLo
            : domHi - domLo
          maxDelta = Math.min(maxDelta, shrinkBlock)
          const leftBlocks = others.filter(p => p < domLo)
          const extendBlock = leftBlocks.length
            ? domLo - Math.max(...leftBlocks) - 1
            : Infinity
          minDelta = Math.max(minDelta, -extendBlock)
        }
      }
    }

    // Clamp to zero if the limits crossed (conflicting constraints)
    if (minDelta > maxDelta) { minDelta = 0; maxDelta = 0 }
    return { minDelta, maxDelta }
  }

  // Draw ghost rectangles at the dragged-to positions.
  function _drawEndDragGhost() {
    if (!_endDragActive || _endDragDeltaBp === 0) return
    ctx.save()
    ctx.fillStyle = 'rgba(229, 57, 53, 0.55)'
    for (const entry of _endDragEntries) {
      const { info, origBp, direction } = entry
      if (!info) continue
      const isFwd = direction === 'FORWARD'
      const y     = isFwd ? info.fwdY : info.revY
      const half  = CELL_H / 2
      const newBp = origBp + _endDragDeltaBp
      ctx.fillRect(_bpToX(newBp), y - half, BP_W, CELL_H)
    }
    ctx.restore()
  }

  // ── Draw: pencil ghost ────────────────────────────────────────────────────────

  function _drawPencilGhost() {
    if (!_painting || !_paintH) return
    const info = _rowMap.get(_paintH.id)
    if (!info) return
    const y = _paintIsScaffold
      ? (info.scaffoldFwd ? info.fwdY : info.revY)
      : (_paintDirection === 'FORWARD' ? info.fwdY : info.revY)
    const ghostThick = CELL_H * 0.20
    ctx.fillStyle = _paintIsScaffold ? CLR_GHOST_SCAF : CLR_GHOST_STPL
    ctx.fillRect(_bpToX(_paintLo), y - ghostThick / 2, _bpToX(_paintHi + 1) - _bpToX(_paintLo), ghostThick)
  }

  // ── Draw: nick hover ghost ────────────────────────────────────────────────────
  // When nick tool is active and cursor is over a strand, highlight where the
  // new 3' end (RED) and new 5' end (GREEN) would land if the user clicked now.

  function _drawNickHover() {
    if (!_nickHover) return
    const { threeEndBp, fiveEndBp, y, ligation } = _nickHover
    const half = CELL_H / 2
    if (_shiftHeld && ligation) {
      // Ligation mode — blue highlight on both boundary cells of the nick
      ctx.fillStyle = 'rgba(50, 130, 255, 0.65)'
      ctx.fillRect(_bpToX(ligation.threeEndBp), y - half, BP_W, CELL_H)
      ctx.fillRect(_bpToX(ligation.fiveEndBp),  y - half, BP_W, CELL_H)
    } else {
      // Normal nick mode — red 3' end, green 5' end
      ctx.fillStyle = 'rgba(220, 40, 40, 0.55)'
      ctx.fillRect(_bpToX(threeEndBp), y - half, BP_W, CELL_H)
      ctx.fillStyle = 'rgba(30, 160, 60, 0.55)'
      ctx.fillRect(_bpToX(fiveEndBp),  y - half, BP_W, CELL_H)
    }
  }

  // ── Draw: slice bar ───────────────────────────────────────────────────────────

  function _drawSliceBar() {
    if (!_helices.length) return
    // Highlight the full cell (bp square) for the current slice position.
    const x0    = _bpToX(_sliceBp)        // left boundary of cell
    const x1    = _bpToX(_sliceBp + 1)    // right boundary of cell
    const topY  = (-_panY) / _zoom
    const botY  = (canvasEl.height - _panY) / _zoom
    ctx.fillStyle = CLR_SLICE_FILL
    ctx.fillRect(x0, topY, BP_W, botY - topY)
    ctx.strokeStyle = CLR_SLICE_EDGE
    ctx.lineWidth   = 1 / _zoom
    _line(x0, topY, x0, botY)
    _line(x1, topY, x1, botY)
  }

  // ── Draw: lasso rect ─────────────────────────────────────────────────────────

  function _drawLasso() {
    if (!_lassoActive) return
    const x0 = Math.min(_lassoWX0, _lassoWX1)
    const y0 = Math.min(_lassoWY0, _lassoWY1)
    const w  = Math.abs(_lassoWX1 - _lassoWX0)
    const h  = Math.abs(_lassoWY1 - _lassoWY0)
    ctx.save()
    ctx.setLineDash([4 / _zoom, 4 / _zoom])
    ctx.strokeStyle = '#388bfd'
    ctx.lineWidth   = 1.5 / _zoom
    ctx.strokeRect(x0, y0, w, h)
    ctx.fillStyle   = 'rgba(56, 139, 253, 0.08)'
    ctx.fillRect(x0, y0, w, h)
    ctx.restore()
  }

  // ── Draw: gutter (frozen — screen space) ─────────────────────────────────────

  function _drawGutter() {
    // Screen-space: fixed left panel regardless of horizontal pan/zoom.
    const H = canvasEl.height
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, GUTTER, H)
    ctx.strokeStyle = '#c0c8d0'
    ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(GUTTER, 0); ctx.lineTo(GUTTER, H); ctx.stroke()

    ctx.save()
    // Clip circles below the frozen ruler band so they don't bleed into it.
    ctx.beginPath(); ctx.rect(0, RULER_H, GUTTER, H - RULER_H); ctx.clip()
    for (const [, info] of _rowMap) {
      const cy      = (info.fwdY + info.revY) / 2
      const screenY = cy * _zoom + _panY
      if (screenY + LABEL_R < RULER_H || screenY - LABEL_R > H) continue
      const cx = GUTTER / 2
      ctx.beginPath(); ctx.arc(cx, screenY, LABEL_R, 0, 2 * Math.PI)
      ctx.fillStyle   = info.scaffoldFwd ? CLR_LABEL_FWD_FILL   : CLR_LABEL_REV_FILL
      ctx.fill()
      ctx.strokeStyle = info.scaffoldFwd ? CLR_LABEL_FWD_STROKE : CLR_LABEL_REV_STROKE
      ctx.lineWidth = 1.5; ctx.stroke()
      // Circle radius is LABEL_R screen pixels (fixed, doesn't scale with zoom).
      ctx.font = `bold ${LABEL_R * 1.15}px sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillStyle = CLR_LABEL_TEXT
      ctx.fillText(info.idx, cx, screenY)
    }
    ctx.textBaseline = 'alphabetic'
    ctx.restore()
  }

  // ── Draw: ruler ───────────────────────────────────────────────────────────────

  function _drawRuler() {
    // Screen-space: fixed top ruler regardless of vertical pan/zoom.
    const W = canvasEl.width
    ctx.fillStyle = CLR_RULER_BG
    ctx.fillRect(0, 0, W, RULER_H)
    ctx.strokeStyle = '#b0bac4'; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(0, RULER_H); ctx.lineTo(W, RULER_H); ctx.stroke()

    const wLeft  = (-_panX) / _zoom
    const wRight = (W - _panX) / _zoom
    const isHC   = _design?.lattice_type === 'HONEYCOMB'
    const major  = isHC ? 7 : 8
    const bpL    = Math.floor(_xToBp(wLeft))
    const bpR    = Math.ceil(_xToBp(wRight))

    ctx.save()
    // Clip labels to the content region (right of frozen gutter, inside ruler height).
    ctx.beginPath(); ctx.rect(GUTTER, 0, W - GUTTER, RULER_H); ctx.clip()

    ctx.fillStyle = CLR_RULER_TEXT
    ctx.font = '9px Courier New, monospace'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    // Labels centred inside cell N (not at the boundary tick).
    for (let bp = Math.ceil(bpL / major) * major; bp <= bpR; bp += major) {
      const sx = _bpCenterX(bp) * _zoom + _panX
      ctx.fillText(bp, sx, RULER_H / 2)
    }
    if (_helices.length) {
      const sx = _bpCenterX(_sliceBp) * _zoom + _panX
      if (sx >= GUTTER && sx <= W) {
        ctx.font = 'bold 11px Courier New, monospace'
        ctx.fillStyle = CLR_SLICE_NUM
        ctx.fillText(_sliceBp, sx, RULER_H / 2)
      }
    }
    ctx.textBaseline = 'alphabetic'
    ctx.restore()
  }

  // ── Draw: debug overlay ───────────────────────────────────────────────────────

  function _drawDebug() {
    const dragState = _endDragActive
      ? `ACTIVE  δ=${_endDragDeltaBp}  [${_endDragMinDelta === -Infinity ? '-∞' : _endDragMinDelta}, ${_endDragMaxDelta === Infinity ? '+∞' : _endDragMaxDelta}]`
      : `idle  entries=${_endDragEntries.length}`
    const lines = [
      `zoom: ${_zoom.toFixed(3)}  pan: ${_panX.toFixed(0)},${_panY.toFixed(0)}`,
      `helices: ${_helices.length}  totalBp: ${_totalBp}`,
      `slice: bp=${_sliceBp}`,
      `tool: ${_activeTool}  sel: ${_selectedElements.size ? `${_selectedElements.size} elements` : '—'}`,
      `drag: ${dragState}`,
      `sprites: ${_xoverSprites.length}  hitR=${((XOVER_R + 4) / _zoom).toFixed(1)}px  [D]=toggle`,
      `last: ${_dbgLastEvent}`,
      ..._dbgDetail,
    ]
    const pad = 4, lh = 14
    const bw  = 340, bh = lines.length * lh + pad * 2
    const bx  = canvasEl.width - bw - 4, by = 22
    ctx.save()
    ctx.globalAlpha = 0.9; ctx.fillStyle = '#111827'
    ctx.fillRect(bx, by, bw, bh)
    ctx.strokeStyle = '#388bfd'; ctx.lineWidth = 1; ctx.strokeRect(bx, by, bw, bh)
    ctx.globalAlpha = 1; ctx.font = '10px Courier New, monospace'
    ctx.textAlign = 'left'; ctx.fillStyle = '#60a5fa'
    for (let i = 0; i < lines.length; i++)
      ctx.fillText(lines[i], bx + pad, by + pad + lh * (i + 1) - 2)
    ctx.restore()
  }

  // Draw crossover sprite positions + hit-radius circles (toggled with D key).
  function _drawSpriteDebug() {
    if (!_dbgShowSprites || !_xoverSprites.length) return
    const hitR = (XOVER_R + 4) / _zoom
    ctx.save()
    ctx.setTransform(_zoom, 0, 0, _zoom, _panX, _panY)
    for (const sp of _xoverSprites) {
      // Hit-radius circle (magenta, semi-transparent)
      ctx.beginPath()
      ctx.arc(sp.cx, sp.indY, hitR, 0, 2 * Math.PI)
      ctx.strokeStyle = 'rgba(255, 0, 255, 0.7)'
      ctx.lineWidth   = 1 / _zoom
      ctx.stroke()
      ctx.fillStyle   = 'rgba(255, 0, 255, 0.10)'
      ctx.fill()
      // Cross-hair at sprite centre
      const t = 3 / _zoom
      ctx.strokeStyle = 'rgba(255,0,255,0.9)'
      ctx.lineWidth   = 0.5 / _zoom
      ctx.beginPath(); ctx.moveTo(sp.cx - t, sp.indY); ctx.lineTo(sp.cx + t, sp.indY); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(sp.cx, sp.indY - t); ctx.lineTo(sp.cx, sp.indY + t); ctx.stroke()
      // Label: bp number
      ctx.save()
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      const sx = sp.cx * _zoom + _panX, sy = sp.indY * _zoom + _panY
      ctx.font = '9px Courier New, monospace'
      ctx.fillStyle = 'magenta'; ctx.textAlign = 'center'
      ctx.fillText(`bp${sp.bp}`, sx, sy - hitR * _zoom - 3)
      ctx.restore()
    }
    ctx.restore()
  }

  // ── Main draw ─────────────────────────────────────────────────────────────────

  function _draw() {
    _components = _buildComponents()   // rebuild once per frame
    _rebuildStrandSelection()          // rebuild strand glow set
    const W = canvasEl.width, H = canvasEl.height
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = CLR_BG; ctx.fillRect(0, 0, W, H)
    if (!_design?.helices?.length) {
      ctx.fillStyle = '#556677'; ctx.font = '12px Courier New, monospace'
      ctx.textAlign = 'left'
      ctx.fillText('No helices — click lattice cells in the Slice View to add helices.', 16, 40)
      _drawDebug(); return
    }
    // ── World-space content ────────────────────────────────────────────────────
    ctx.setTransform(_zoom, 0, 0, _zoom, _panX, _panY)
    _drawAllTracks()
    _drawCrossoverIndicators()
    _drawAllDomains()
    _drawCoaxialArcs()
    _drawCrossoverArcs()
    _drawLoopSkips()
    _drawEndDragGhost()
    _drawNickHover()
    _drawPencilGhost()
    _drawSliceBar()
    _drawLasso()
    _drawSpriteDebug()     // magenta hit-radius circles when D key is held
    // ── Frozen screen-space overlays (drawn on top of scrolling content) ───────
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    _drawGutter()          // frozen left panel
    _drawRuler()           // frozen top ruler (painted after gutter to cover corner)
    _drawDebug()
  }

  // ── Event handlers ────────────────────────────────────────────────────────────

  canvasEl.addEventListener('pointerdown', (e) => {
    _dbgLastEvent = `pdown btn=${e.button} tool=${_activeTool}`

    // ── Pan (right / middle) ────────────────────────────────────────────────────
    if (e.button === 1 || e.button === 2) {
      _panActive    = true
      _panStartCX   = e.clientX; _panStartCY   = e.clientY
      _panStartPanX = _panX;    _panStartPanY = _panY
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); _draw(); return
    }

    if (e.button !== 0) return

    // ── Slice bar drag ──────────────────────────────────────────────────────────
    if (_isNearSliceBar(e.offsetX)) {
      _sliceDragging = true
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); return
    }

    const { wx, wy } = _c2w(e.offsetX, e.offsetY)

    // ── Select tool: end-cap drag (must precede xover sprite check) ─────────────
    // Crossover sprites sit near bp 0 / bp (maxBp) — the same positions as
    // strand end-caps.  We detect end-cap hits here before the sprite check so
    // resize-drag isn't stolen.  However, if a crossover sprite also occupies
    // that position, the crossover takes priority (its lattice position has no
    // alternative access point; the end-cap can be resized from the other end).
    if (_activeTool === 'select') {
      const hit = _hitTest(e.offsetX, e.offsetY, _selectFilter)
      console.group(`[PDOWN] select  bp=${_xToBp(wx)}  wx=${wx.toFixed(1)}  wy=${wy.toFixed(1)}  zoom=${_zoom.toFixed(3)}`)
      console.log('hitTest result:', hit ? `elementType=${hit.elementType} strand=${hit.strand.id.slice(0,12)} strandType=${hit.strand.strand_type} bp=${_xToBp(wx)}` : 'null')
      if (hit?.elementType === 'end') {
        // If a crossover sprite also lives at this position, prefer the
        // crossover — its lattice-dictated position has no alternative access.
        const xoverHere = _hitTestCrossoverSprite(e.offsetX, e.offsetY)
        if (xoverHere) {
          console.log('end-cap overlaps crossover sprite — deferring to xover handler')
          console.groupEnd()
          // Fall through to the crossover sprite click handler below.
        } else {
          const key = _hitElementKey(hit)
          if (!_selectedElements.has(key)) {
            if (!(e.ctrlKey || e.metaKey)) _selectedElements = new Set([key])
            else _selectedElements.add(key)
          }
          _endDragEntries = _resolveEndDragEntries()
          console.log('endDragEntries:', _endDragEntries.length, _endDragEntries.map(en => `${en.end}@${en.origBp} ${en.direction} ${en.helixId.slice(0,8)}`))
          if (_endDragEntries.length > 0) {
            const limits     = _computeEndDragLimits(_endDragEntries)
            _endDragMinDelta = limits.minDelta
            _endDragMaxDelta = limits.maxDelta
            console.log(`limits: [${limits.minDelta}, ${limits.maxDelta}]  → starting end-drag, returning early`)
            console.groupEnd()
            _endDragDeltaBp  = 0
            _endDragStartWX  = _c2w(e.offsetX, e.offsetY).wx
            _endDragActive   = true
            canvasEl.setPointerCapture(e.pointerId)
            _draw(); e.preventDefault(); return
          }
          console.log('endDragEntries empty — falling through to xover/lasso')
        }
      } else {
        console.log('not an end-cap — proceeding to xover sprite check')
      }
      console.groupEnd()
    }

    // ── Crossover sprite click ────────────────────────────────────────────────────
    //
    // RULE: apply these steps mechanically. Do not reason about geometry,
    // topology, strand polarity, or directionality — every such attempt has
    // produced wrong results. The rules below are correct as stated.
    //
    // Step 1 — find the lower bp of the clicked pair:
    //   HC: (6|7, 13|14, 20|0) — bpMod in _XOVER_BOW_RIGHT_HC → lowerBp = sprite.bp - 1
    //   SQ: (31|0, 7|8, 15|16, 23|24) — bpMod in _XOVER_BOW_RIGHT_SQ → lowerBp = sprite.bp - 1
    //   bow right (+1) means the sprite is at the upper bp of the pair → lowerBp = bp - 1.
    //   bow left (-1) means the sprite is at the lower bp → lowerBp = bp.
    //
    // Step 2 — nick each helix at the N|N+1 boundary:
    //   FORWARD strand → nickBp = lowerBp
    //   REVERSE strand → nickBp = lowerBp + 1
    //
    // Step 3 — register the crossover record using sprite.bp as-is (no adjustment).
    //
    // Backend: nick + ligate + record — one atomic operation.
    const xoverHit = _hitTestCrossoverSprite(e.offsetX, e.offsetY)
    if (xoverHit) {
      if (_activeTool === 'select') console.warn('[XOVER SPRITE] firing in SELECT mode — end-cap drag check did not intercept this click!')
      const bowDir  = _xoverBowDir(xoverHit.bp, xoverHit.isScaffold)
      const lowerBp = bowDir === +1 ? xoverHit.bp - 1 : xoverHit.bp
      const nickBpA = xoverHit.halfAStrand === 'FORWARD' ? lowerBp : lowerBp + 1
      const nickBpB = xoverHit.halfBStrand === 'FORWARD' ? lowerBp : lowerBp + 1
      const infoA = _rowMap.get(xoverHit.hid)
      const infoB = _rowMap.get(xoverHit.targetHid)
      const hitR  = (XOVER_R + 4) / _zoom
      const dxSp  = wx - xoverHit.cx, dySp = wy - xoverHit.indY
      console.group(`%c[XOVER SPRITE FIRED] bp=${xoverHit.bp}  bowDir=${bowDir>0?'+1':'-1'}  lowerBp=${lowerBp}`, 'color:orange;font-weight:bold')
      console.log(`  click world=(${wx.toFixed(1)}, ${wy.toFixed(1)})  sprite=(${xoverHit.cx.toFixed(1)}, ${xoverHit.indY.toFixed(1)})`)
      console.log(`  distance=${Math.hypot(dxSp,dySp).toFixed(2)}  hitR=${hitR.toFixed(2)}  zoom=${_zoom.toFixed(3)}`)
      console.log('helix A:', { helix_idx: infoA?.idx, helixId: xoverHit.hid.slice(0,8), dir: xoverHit.halfAStrand, nickBp: nickBpA })
      console.log('helix B:', { helix_idx: infoB?.idx, helixId: xoverHit.targetHid.slice(0,8), dir: xoverHit.halfBStrand, nickBp: nickBpB })
      console.groupEnd()
      ;(async () => {
        // nick + nick + register are a single atomic undo step via POST /design/crossovers/place
        await onAddCrossover?.(
          { helix_id: xoverHit.hid,       index: xoverHit.bp, strand: xoverHit.halfAStrand },
          { helix_id: xoverHit.targetHid, index: xoverHit.bp, strand: xoverHit.halfBStrand },
          nickBpA,
          nickBpB,
        )
      })()
      return
    }

    // ── Erase tool ──────────────────────────────────────────────────────────────
    if (_activeTool === 'erase') {
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit) {
        const { strand, domainIdx } = hit
        _dbgLastEvent = `erase strand=${strand.id.slice(0,8)} dom=${domainIdx}`
        if (strand.domains.length === 1) {
          onEraseDomain(strand.id, null)          // delete whole strand
        } else {
          onEraseDomain(strand.id, domainIdx)     // delete one domain
        }
      }
      return
    }

    // ── Nick tool ───────────────────────────────────────────────────────────────
    if (_activeTool === 'nick') {
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit) {
        const { dom } = hit
        const col = _xToBp(wx)   // cell index (= bp) the user clicked in
        // Cursor is always centred over the new 3' end cell.
        // FORWARD at bp=N → gap at right boundary of cell N (between N and N+1):
        //   new 3' = N,   new 5' = N+1
        // REVERSE at bp=N → gap at left boundary of cell N (between N-1 and N):
        //   new 3' = N,   new 5' = N-1
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const nickBp     = Math.max(lo, Math.min(hi - 1, col))
        const threeEndBp = nickBp
        const fiveEndBp  = dom.direction === 'FORWARD' ? nickBp + 1 : nickBp - 1
        const nickGapBoundary = dom.direction === 'FORWARD' ? nickBp + 1 : nickBp
        _nickHover = null   // clear ghost on click
        _dbgLastEvent = `nick cell=${col} bp=${nickBp} dir=${dom.direction}`
        _dbgDetail = [
          `  clicked cell=${col}  → nickBp=${nickBp}`,
          `  gap boundary=${nickGapBoundary}  x=${_bpToX(nickGapBoundary).toFixed(1)}px`,
          `  new 3' end at bp=${threeEndBp}  new 5' end at bp=${fiveEndBp}`,
        ]
        console.log('[NICK]', {
          helix: dom.helix_id.slice(0, 8), direction: dom.direction,
          clicked_cell: col, nickBp,
          gap_boundary: nickGapBoundary, gap_x: _bpToX(nickGapBoundary).toFixed(1),
          'new_3prime_bp': threeEndBp, 'new_5prime_bp': fiveEndBp,
        })
        if (e.shiftKey) {
          const lig = _findLigation(dom, col)
          if (lig) { onLigateStrand(dom.helix_id, lig.bpIndex, dom.direction); return }
        }
        onNickStrand(dom.helix_id, nickBp, dom.direction)
      }
      return
    }

    // ── Skip / Loop tools ─────────────────────────────────────────────────────
    if (_activeTool === 'skip' || _activeTool === 'loop') {
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit) {
        const bp    = _xToBp(wx)
        const lo    = Math.min(hit.dom.start_bp, hit.dom.end_bp)
        const hi    = Math.max(hit.dom.start_bp, hit.dom.end_bp)
        const clamp = Math.max(lo, Math.min(hi, bp))
        // delta: skip = -1, loop = +1; shift+click = remove (delta 0)
        const delta = e.shiftKey ? 0 : (_activeTool === 'skip' ? -1 : 1)
        _dbgLastEvent = `${_activeTool} bp=${clamp} delta=${delta} helix=${hit.dom.helix_id.slice(0,8)}`
        onInsertLoopSkip?.(hit.dom.helix_id, clamp, delta)
      }
      return
    }

    // ── Select tool — lasso start (end-cap drag already handled above) ──────────
    if (_activeTool === 'select') {
      console.log(`[PDOWN] select → lasso fallback (no end-cap hit, no xover sprite)`)
      _lassoStarted = true
      _lassoCtrl    = e.ctrlKey || e.metaKey
      _lassoActive  = false
      _lassoSX0 = e.offsetX; _lassoSY0 = e.offsetY
      const { wx: lx, wy: ly } = _c2w(e.offsetX, e.offsetY)
      _lassoWX0 = _lassoWX1 = lx
      _lassoWY0 = _lassoWY1 = ly
      canvasEl.setPointerCapture(e.pointerId)
      return
    }

    // ── Pencil tool ─────────────────────────────────────────────────────────────
    if (_activeTool === 'pencil') {
      const HIT = PAIR_Y / 2
      for (const [hid, info] of _rowMap) {
        const dF = Math.abs(wy - info.fwdY)
        const dR = Math.abs(wy - info.revY)
        if (dF > HIT && dR > HIT) continue
        const isFwdTrack = dF <= dR
        const direction  = isFwdTrack ? 'FORWARD' : 'REVERSE'
        const isScaffold = isFwdTrack === info.scaffoldFwd
        const bp = _xToBp(wx)
        _painting        = true
        _paintAnchor     = bp
        _paintLo         = bp
        _paintHi         = bp
        _paintIsScaffold = isScaffold
        _paintDirection  = direction
        _paintH          = _design.helices.find(h => h.id === hid) ?? null
        _draw()
        break
      }
    }

    // ── Paint tool ─────────────────────────────────────────────────────────────
    if (_activeTool === 'paint') {
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit && hit.strand.strand_type !== 'scaffold') {
        // Immediate click-paint — no lasso needed
        onPaintStrands?.([hit.strand.id])
        return
      }
      // No strand hit — start lasso so the user can drag a paint region
      _lassoStarted = true
      _lassoCtrl    = false
      _lassoActive  = false
      _lassoSX0 = e.offsetX; _lassoSY0 = e.offsetY
      const { wx: lx, wy: ly } = _c2w(e.offsetX, e.offsetY)
      _lassoWX0 = _lassoWX1 = lx
      _lassoWY0 = _lassoWY1 = ly
      canvasEl.setPointerCapture(e.pointerId)
    }
  })

  canvasEl.addEventListener('pointermove', (e) => {
    if (_endDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const rawDelta = Math.round((wx - _endDragStartWX) / BP_W)
      _endDragDeltaBp = Math.max(_endDragMinDelta, Math.min(_endDragMaxDelta, rawDelta))
      _draw(); return
    }
    if (_panActive) {
      _panX = _panStartPanX + (e.clientX - _panStartCX)
      _panY = _panStartPanY + (e.clientY - _panStartCY)
      _draw(); return
    }
    if (_sliceDragging) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      _updateSliceBp(Math.max(_minBp, Math.min(_totalBp, _xToBp(wx))))
      _draw(); return
    }
    if (_painting) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const bp = _xToBp(wx)
      _paintLo = Math.min(_paintAnchor, bp)
      _paintHi = Math.max(_paintAnchor, bp)
      _draw(); return
    }
    if (_lassoStarted) {
      const { wx, wy } = _c2w(e.offsetX, e.offsetY)
      _lassoWX1 = wx; _lassoWY1 = wy
      const dx = e.offsetX - _lassoSX0, dy = e.offsetY - _lassoSY0
      if (dx * dx + dy * dy > DRAG_THRESHOLD * DRAG_THRESHOLD) _lassoActive = true
      if (_lassoActive) _draw()
      return
    }
    // Cursor + hover
    if (_isNearSliceBar(e.offsetX)) {
      canvasEl.style.cursor = 'col-resize'
    } else if (_selectFilter.xover && _hitTestCrossoverSprite(e.offsetX, e.offsetY)) {
      canvasEl.style.cursor = 'pointer'
    } else if (_activeTool === 'pencil') {
      canvasEl.style.cursor = 'crosshair'
    } else if (_activeTool === 'nick') {
      canvasEl.style.cursor = 'cell'
    } else if (_activeTool === 'erase') {
      canvasEl.style.cursor = 'not-allowed'
    } else if (_activeTool === 'paint') {
      canvasEl.style.cursor = 'crosshair'
    } else {
      canvasEl.style.cursor = 'default'
    }
    const hit = _hitTest(e.offsetX, e.offsetY, _activeTool === 'select' ? _selectFilter : null)
    onStrandHover(hit ? {
      strandId:   hit.strand.id,
      strandType: hit.strand.strand_type,
      ntCount:    strandNtCount(hit.strand),
    } : null)

    // Nick tool hover ghost — compute potential 3'/5' end cells and redraw
    if (_activeTool === 'nick') {
      if (hit) {
        const { dom } = hit
        const info    = _rowMap.get(dom.helix_id)
        const { wx }  = _c2w(e.offsetX, e.offsetY)
        const col     = _xToBp(wx)
        const lo      = Math.min(dom.start_bp, dom.end_bp)
        const hi      = Math.max(dom.start_bp, dom.end_bp)
        const nickBp     = Math.max(lo, Math.min(hi - 1, col))
        const threeEndBp = nickBp
        const fiveEndBp  = dom.direction === 'FORWARD' ? nickBp + 1 : nickBp - 1
        const y = dom.direction === 'FORWARD' ? info.fwdY : info.revY
        _nickHover = { threeEndBp, fiveEndBp, y, ligation: _findLigation(dom, col) }
        _dbgDetail = [`  hover: new 3' at bp=${threeEndBp}  new 5' at bp=${fiveEndBp}`]
      } else {
        const hadHover = _nickHover !== null
        _nickHover = null
        if (hadHover) _dbgDetail = []
      }
      _draw()
    }
  })

  canvasEl.addEventListener('pointerup', (e) => {
    if (_endDragActive && e.button === 0) {
      _endDragActive = false
      const delta    = _endDragDeltaBp
      _endDragDeltaBp = 0
      _draw()
      if (delta !== 0) {
        const apiEntries = _endDragEntries.map(en => ({
          strand_id: en.strandId,
          helix_id:  en.helixId,
          end:       en.end,
          delta_bp:  delta,
        }))
        console.group(`%c[RESIZE] pointerup  delta=${delta}`, 'color:lime;font-weight:bold')
        console.log('apiEntries:', JSON.stringify(apiEntries, null, 2))
        console.groupEnd()
        onResizeEnds?.(apiEntries)
      } else {
        console.log('[RESIZE] pointerup: delta=0, no API call')
      }
      return
    }
    if (_panActive)     { _panActive = false; _draw(); return }
    if (_sliceDragging) { _sliceDragging = false; _draw(); return }

    // ── Select tool: lasso release or click ──────────────────────────────────────
    if (_lassoStarted && e.button === 0) {
      _lassoStarted = false
      if (_lassoActive) {
        // Lasso release ── branch on active tool
        _lassoActive = false
        if (_activeTool === 'paint') {
          const ids = _hitTestLassoStrands()
          if (ids.size > 0) onPaintStrands?.([...ids])
          _draw(); return
        }
        // Select lasso
        if (_selectFilter.strand) {
          // Strand-level: capture whole strands that intersect the lasso,
          // respecting scaf/stap type filters.
          const lx0 = Math.min(_lassoWX0, _lassoWX1), lx1 = Math.max(_lassoWX0, _lassoWX1)
          const ly0 = Math.min(_lassoWY0, _lassoWY1), ly1 = Math.max(_lassoWY0, _lassoWY1)
          const strandIds = new Set()
          for (const strand of (_design?.strands ?? [])) {
            if (strand.strand_type === 'scaffold' && !_selectFilter.scaf) continue
            if (strand.strand_type === 'staple'   && !_selectFilter.stap) continue
            for (const dom of strand.domains) {
              const info = _rowMap.get(dom.helix_id)
              if (!info) continue
              const lo = Math.min(dom.start_bp, dom.end_bp), hi = Math.max(dom.start_bp, dom.end_bp)
              const dyC = dom.direction === 'FORWARD' ? info.fwdY : info.revY
              if (_bpToX(hi + 1) > lx0 && _bpToX(lo) < lx1 && dyC + CELL_H / 2 > ly0 && dyC - CELL_H / 2 < ly1) {
                strandIds.add(strand.id); break
              }
            }
          }
          const keys = new Set()
          for (const strand of (_design?.strands ?? [])) {
            if (!strandIds.has(strand.id)) continue
            for (const k of _strandElementKeys(strand)) keys.add(k)
          }
          if (_lassoCtrl) { for (const k of keys) _selectedElements.add(k) }
          else            { _selectedElements = keys }
          _dbgLastEvent = `lasso strand=${strandIds.size}${_lassoCtrl ? ' +ctrl' : ''}`
        } else {
          // Element-level: capture individual elements
          const keys = _hitTestLassoElements()
          if (_lassoCtrl) { for (const k of keys) _selectedElements.add(k) }
          else            { _selectedElements = keys }
          _dbgLastEvent = `lasso sel=${keys.size}${_lassoCtrl ? ' +ctrl' : ''}`
        }
        _draw(); _notifySelectionChange(); return
      }
      // Short drag = click
      if (_activeTool === 'paint') {
        // Click was already handled in pointerdown; nothing to do here
        _draw(); return
      }
      // Select click — test domains first, then crossover arcs, then loop/skip
      const hit    = _hitTest(e.offsetX, e.offsetY, _selectFilter)
      const { wx: cwx, wy: cwy } = _c2w(e.offsetX, e.offsetY)
      const arcHit = !hit && _selectFilter.xover ? _hitTestArc(cwx, cwy) : null
      const lsHit  = !hit && !arcHit ? _hitTestLoopSkip(cwx, cwy) : null

      // Strand-level selection: clicking any part selects the whole strand
      if (_selectFilter.strand && hit) {
        const keys = _strandElementKeys(hit.strand)
        if (_lassoCtrl) {
          // Toggle: if any key already selected, remove all; else add all
          const anySelected = keys.some(k => _selectedElements.has(k))
          if (anySelected) keys.forEach(k => _selectedElements.delete(k))
          else             keys.forEach(k => _selectedElements.add(k))
        } else {
          _selectedElements = new Set(keys)
        }
        _dbgLastEvent = `select strand ${hit.strand.id.slice(0, 12)}`
        _draw(); _notifySelectionChange(); return
      }

      // Loop/skip click — gated by filter
      const lsKey  = lsHit && ((lsHit.delta > 0 && _selectFilter.loop) || (lsHit.delta < 0 && _selectFilter.skip))
                     ? lsHit.key : null
      const key    = hit ? _hitElementKey(hit) : arcHit ? _xoverKey(arcHit.xo) : lsKey
      if (key) {
        if (_lassoCtrl) {
          if (_selectedElements.has(key)) _selectedElements.delete(key)
          else                            _selectedElements.add(key)
        } else {
          _selectedElements = new Set([key])
        }
        _dbgLastEvent = `select ${key.slice(0, 24)}`
      } else if (!_lassoCtrl) {
        _selectedElements = new Set()
        _dbgLastEvent = 'deselect'
      }
      _draw(); _notifySelectionChange(); return
    }

    if (_painting && e.button === 0) {
      _painting = false
      if (_paintH && _paintLo <= _paintHi) {
        if (_paintIsScaffold) {
          onPaintScaffold(_paintH.id, _paintLo, _paintHi)
        } else {
          onPaintStaple(_paintH.id, _paintDirection, _paintLo, _paintHi)
        }
      }
      _paintH = null; _draw()
    }
  })

  canvasEl.addEventListener('pointerleave', () => {
    onStrandHover(null)
    let needDraw = false
    if (_endDragActive)                { _endDragActive = false; _endDragDeltaBp = 0; needDraw = true }
    if (_lassoStarted || _lassoActive) { _lassoStarted = false; _lassoActive = false; needDraw = true }
    if (_painting)                     { _painting = false; _paintH = null; needDraw = true }
    if (_nickHover !== null)           { _nickHover = null; _dbgDetail = []; needDraw = true }
    if (needDraw) _draw()
  })

  canvasEl.addEventListener('pointercancel', () => {
    if (_endDragActive) { _endDragActive = false; _endDragDeltaBp = 0; _draw() }
  })

  canvasEl.addEventListener('contextmenu', (e) => {
    e.preventDefault()
    const { wx, wy } = _c2w(e.offsetX, e.offsetY)
    const arcHit = _hitTestArc(wx, wy)
    if (arcHit) {
      onCrossoverContextMenu?.({
        xo: arcHit.xo,
        selectedXoKeys: Array.from(_selectedElements).filter(k => k.startsWith('xo:')),
        clientX: e.clientX,
        clientY: e.clientY,
      })
    }
  })

  // ── Shift key — update nick hover ghost for ligation mode ────────────────────
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Shift') { _shiftHeld = true; _draw() }
    // D key — toggle sprite hit-radius debug overlay
    if (e.key === 'd' || e.key === 'D') {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      _dbgShowSprites = !_dbgShowSprites
      console.log(`[DBG] sprite overlay ${_dbgShowSprites ? 'ON' : 'OFF'}  hitR=${((XOVER_R+4)/_zoom).toFixed(2)} world-px  sprites=${_xoverSprites.length}`)
      if (_dbgShowSprites) {
        console.table(_xoverSprites.map(s => ({
          bp: s.bp,
          hid: s.hid.slice(0,12),
          targetHid: s.targetHid.slice(0,12),
          halfAStrand: s.halfAStrand,
          halfBStrand: s.halfBStrand,
          indY_world: s.indY.toFixed(1),
        })))
      }
      _draw()
    }
  })
  window.addEventListener('keyup', (e) => {
    if (e.key === 'Shift') { _shiftHeld = false; _draw() }
  })

  // ── Delete key — remove selected elements ─────────────────────────────────────
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Delete' && e.key !== 'Backspace') return
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
    if (_activeTool !== 'select') return
    if (_selectedElements.size === 0) return
    e.preventDefault()
    const keys = Array.from(_selectedElements)
    _selectedElements = new Set()
    _draw()
    onDeleteElements?.(keys)
  })

  canvasEl.addEventListener('wheel', (e) => {
    e.preventDefault()
    const factor  = e.deltaY < 0 ? 1.15 : 0.87
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, _zoom * factor))
    if (newZoom !== _zoom) {
      const cx = e.offsetX, cy = e.offsetY
      _panX = cx - (cx - _panX) * (newZoom / _zoom)
      _panY = cy - (cy - _panY) * (newZoom / _zoom)
      _zoom = newZoom
      _dbgLastEvent = `zoom ${_zoom.toFixed(3)}`
    }
    _draw()
  }, { passive: false })

  // ── Public interface ──────────────────────────────────────────────────────────

  return {
    setTool(tool) {
      _activeTool = tool
      _lassoStarted = false; _lassoActive = false
      if (_nickHover !== null) { _nickHover = null; _dbgDetail = []; _draw() }
      const cursors = { pencil: 'crosshair', nick: 'cell', erase: 'not-allowed', paint: 'crosshair' }
      canvasEl.style.cursor = cursors[tool] ?? 'default'
    },

    setPaintColor(color) {
      _paintToolColor = color
    },

    setSelectFilter(filter) {
      _selectFilter = filter
    },

    /** Programmatically set selected strand IDs (e.g. from 3D cross-window broadcast).
     *  Translates strand IDs to all element keys for those strands' domains and arcs.
     *  Does NOT emit onSelectionChange — caller responsible for loop prevention. */
    setSelection(strandIds) {
      _selectedElements = new Set()
      if (!strandIds?.length || !_design) { _draw(); return }
      const idSet = new Set(strandIds)
      for (const strand of _design.strands) {
        if (!idSet.has(strand.id)) continue
        for (const dom of strand.domains) {
          _selectedElements.add(_domainLineKey(dom))
          _selectedElements.add(_domainEndKey(dom, '5p'))
          _selectedElements.add(_domainEndKey(dom, '3p'))
        }
      }
      for (const xo of (_design.crossovers ?? [])) {
        const sA = _findStrandIdxAt(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        if (sA >= 0 && idSet.has(_design.strands[sA].id)) {
          _selectedElements.add(_xoverKey(xo))
        }
      }
      _draw()
    },

    setNativeOrientation(native) {
      if (_nativeOrientation === native) return
      _nativeOrientation = native
      _rebuildLayout()
      _draw()
    },

    update(design) {
      // Log strand endpoints on every helix that changed — helps trace nicks.
      if (_design && design) {
        const changedHelixIds = new Set()
        for (const h of design.helices) {
          const old = _design.helices.find(oh => oh.id === h.id)
          if (!old || old.length_bp !== h.length_bp || old.bp_start !== h.bp_start)
            changedHelixIds.add(h.id)
        }
        if (changedHelixIds.size > 0) {
          console.group(`%c[DESIGN UPDATE] ${changedHelixIds.size} helix(es) changed`, 'color:cyan;font-weight:bold')
          for (const hid of changedHelixIds) {
            const h = design.helices.find(x => x.id === hid)
            console.log(`  helix ${hid}  bp_start=${h.bp_start}  length_bp=${h.length_bp}  → bp ${h.bp_start}..${h.bp_start + h.length_bp - 1}`)
            const domains = []
            for (const s of design.strands) {
              for (const d of s.domains) {
                if (d.helix_id !== hid) continue
                domains.push(`    ${s.strand_type} ${s.id.slice(0,14)} ${d.direction} [${Math.min(d.start_bp,d.end_bp)}..${Math.max(d.start_bp,d.end_bp)}]  start_bp=${d.start_bp}  end_bp=${d.end_bp}`)
              }
            }
            console.log(domains.join('\n') || '    (no domains)')
          }
          console.groupEnd()
        }
      }
      _design = design
      _selectedElements = new Set()   // clear selection on design change
      _rebuildLayout()
      _resize()
      if (!_fitDone && _helices.length > 0) {
        _fitDone = true
        _updateSliceBp(Math.floor(_totalBp / 3))
        requestAnimationFrame(() => { _fitToContent(); _draw() })
      }
    },
  }
}
