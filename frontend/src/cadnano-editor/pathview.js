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

// ── Extension geometry (inspired by scadnano defaults) ────────────────────────
const EXT_LEN_PX    = 18                    // arm length in world-space px
const EXT_ANGLE_RAD = 145 * Math.PI / 180  // 145° — arm points back toward strand body

// Modification dot colours — CSS hex strings matching helix_renderer.js
const EXT_MOD_COLORS = {
  cy3: '#ff8c00', cy5: '#cc0000', fam: '#00cc00', tamra: '#cc00cc',
  bhq1: '#444444', bhq2: '#666666', atto488: '#00ffcc', atto550: '#ffaa00', biotin: '#eeeeee',
}
const EXT_MOD_NAMES = {
  cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA',
  bhq1: 'BHQ-1', bhq2: 'BHQ-2', atto488: 'ATTO488', atto550: 'ATTO550', biotin: 'Biotin',
}

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
function strandPassesScafStapFilter(strand, filter) {
  if (!filter) return true
  if (strand.strand_type === 'scaffold') return !!filter.scaf
  // Linker strands are selectable/editable on the non-scaffold side, matching
  // the 3D view where every non-scaffold strand follows the staple filter.
  return !!filter.stap
}

// ── Main init ─────────────────────────────────────────────────────────────────

export function initPathview(canvasEl, containerEl, {
  onPaintScaffold,
  onPaintStaple,
  onEraseDomain,
  onNickStrand,
  onLigateStrand,
  onAddCrossover,
  onForcedLigation,
  onResizeEnds,
  onShiftDomains,
  onMoveCrossover,
  onBatchMoveCrossovers,
  onInsertLoopSkip,
  onPaintStrands,
  onStrandClick,
  onStrandHover,
  onSliceChange,
  onSelectionChange,
  onDeleteElements,
  onCrossoverContextMenu,
  onOverhangContextMenu,
  onStrandContextMenu,
}) {
  // `ctx` is mutable so `drawToCanvas()` can swap it to an offscreen target
  // (the zoom_scope lens) for a native re-render at lens transform, then
  // restore. All helpers read this closure variable directly.
  let ctx = canvasEl.getContext('2d')

  // ── Drag tooltip (DOM overlay, mirrors 3D extrude tooltip) ──────────────────
  const _dragTooltip = document.createElement('div')
  Object.assign(_dragTooltip.style, {
    position:        'fixed',
    display:         'none',
    padding:         '3px 8px',
    background:      'rgba(0,0,0,0.75)',
    color:           '#fff',
    fontFamily:      'monospace',
    fontSize:        '13px',
    borderRadius:    '4px',
    pointerEvents:   'none',
    userSelect:      'none',
    whiteSpace:      'nowrap',
    zIndex:          '9999',
    transform:       'translate(14px, -50%)',
  })
  document.body.appendChild(_dragTooltip)

  function _showDragTooltip(clientX, clientY, delta) {
    _dragTooltip.textContent = delta > 0 ? `[+${delta}]` : `[${delta}]`
    _dragTooltip.style.left  = `${clientX}px`
    _dragTooltip.style.top   = `${clientY}px`
    _dragTooltip.style.display = ''
    _dragTooltip.style.color = delta >= 0 ? '#00e5ff' : '#ff6633'
  }

  function _hideDragTooltip() { _dragTooltip.style.display = 'none' }

  // ── Design state ─────────────────────────────────────────────────────────────
  let _design  = null
  let _helices = []
  // IDs of crossovers the backend left unligated to avoid circularizing a
  // strand. Painted with an amber ⚠ next to each arc. Set on every design
  // sync via setUnligatedCrossoverIds; auto-clears when topology changes
  // (backend recomputes per-response).
  let _unligatedCrossoverIds = new Set()
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

  function _forcedLigKey(fl) {
    return `fl:${fl.id}`
  }

  /** True if the domain transition (domA→domB) matches a forced ligation record. */
  function _isForcedLigTransition(domA, domB) {
    for (const fl of (_design?.forced_ligations ?? [])) {
      if (fl.three_prime_helix_id === domA.helix_id
          && fl.three_prime_bp === domA.end_bp
          && fl.three_prime_direction === domA.direction
          && fl.five_prime_helix_id === domB.helix_id
          && fl.five_prime_bp === domB.start_bp
          && fl.five_prime_direction === domB.direction) return true
    }
    return false
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
    if (!_design?.strands) { onSelectionChange([]); return }
    const strandIds = new Set()
    for (const strand of _design.strands) {
      for (const dom of strand.domains) {
        if (_selectedElements.has(_domainLineKey(dom)) ||
            _selectedElements.has(_domainEndKey(dom, '5p')) ||
            _selectedElements.has(_domainEndKey(dom, '3p'))) {
          strandIds.add(strand.id)
          break
        }
      }
    }
    for (const xo of (_design.crossovers ?? [])) {
      if (_selectedElements.has(_xoverKey(xo))) {
        const sA = _findStrandIdxAt(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        if (sA >= 0) strandIds.add(_design.strands[sA].id)
      }
    }
    for (const fl of (_design.forced_ligations ?? [])) {
      if (_selectedElements.has(_forcedLigKey(fl))) {
        const sIdx = _findStrandIdxAt(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction)
        if (sIdx >= 0) strandIds.add(_design.strands[sIdx].id)
      }
    }
    const expanded = new Set()
    for (const sid of strandIds) {
      for (const memberId of _components.membersOf(sid)) expanded.add(memberId)
    }
    onSelectionChange([...expanded])
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

  // ── Paint state (pencil tool �� scaffold + staple) ───────────────���─────────────
  let _painting       = false
  let _paintH         = null
  let _paintAnchor    = 0
  let _paintLo        = 0
  let _paintHi        = 0
  let _paintIsScaffold = true
  let _paintDirection  = 'FORWARD'

  // ── Forced ligation state (pencil tool — click 3' end → drag → click 5' end) ─
  // Manual user feature only — NOT for autocrossover or automated pipelines.
  let _forcedLigActive  = false     // true while dragging an arc from a 3' end
  let _forcedLigStrand  = null      // source strand (has the 3' end we clicked)
  let _forcedLigDom     = null      // source domain (terminal domain with the 3' end)
  let _forcedLigStartX  = 0         // world-space X of the 3' end anchor
  let _forcedLigStartY  = 0         // world-space Y of the 3' end anchor
  let _forcedLigCursorX = 0         // world-space X of current cursor position
  let _forcedLigCursorY = 0         // world-space Y of current cursor position

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

  // ── Domain-drag (move whole domain by N bp, length unchanged) ──────────────────
  let _domDragActive   = false
  let _domDragEntries  = []   // [{ strandId, domainIndex, helixId, direction, domLo, domHi, info }]
  let _domDragDeltaBp  = 0
  let _domDragMinDelta = -Infinity
  let _domDragMaxDelta = +Infinity
  let _domDragStartWX  = 0

  // ── Crossover drag-to-move ──────────────────────────────────────────────────
  let _xoverDragActive    = false
  let _xoverDragXover     = null    // the PRIMARY crossover (the one the user clicked)
  let _xoverDragOrigIdx   = 0      // primary crossover's original bp index
  let _xoverDragSnapBp    = null   // current snap target for primary (null = no valid snap nearby)
  let _xoverDragCursorBp  = null   // fractional bp at cursor (always updated during drag)
  let _xoverDragValidDeltas = []   // precomputed valid delta values (intersection across group)
  let _xoverDragStartWX   = 0      // world-x at drag start
  let _xoverDragOrigBow   = 0      // +1 (right) or -1 (left) bow direction of the primary
  let _xoverDragIsScaf    = false   // whether the primary is a scaffold crossover
  let _xoverDragD0        = null    // primary: domain before crossover
  let _xoverDragD1        = null    // primary: domain after crossover
  // Multi-crossover group: array of { xo, origIdx, d0, d1, isScaf, origBow }
  let _xoverDragGroup     = []
  const XOVER_SNAP_DIST   = 7      // snap threshold in bp units

  let _dbgLastEvent = '—'
  let _dbgDetail    = []   // extra lines appended to the debug overlay after each nick
  let _dbgShowSprites = false   // toggle with 'D' key — draws sprite hit-radius circles

  // ── Nick hover ghost ──────────────────────────────────────────────────────────
  // Null when not hovering a strand with the nick tool active.
  // { threeEndBp, fiveEndBp, y, hasNick } — world-space Y of the hovered track.
  let _nickHover = null
  let _shiftHeld = false
  let _hoverHelixId = null   // helix ID under cursor (for scaffold sprite filtering)

  // ── Coordinate helpers ────────────────────────────────────────────────────────

  // Return the helix ID whose row band contains world-space Y, or null.
  function _helixAtWY(wy) {
    const half = ROW_H / 2
    for (const [hid, info] of _rowMap) {
      const midY = (info.fwdY + info.revY) / 2
      if (wy >= midY - half && wy <= midY + half) return hid
    }
    return null
  }

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
    // Stable label index per helix — based on native (top-to-bottom) order so that
    // gutter labels reflect the helix's identity, not its current display position.
    const nativeIdx = new Map(_helices.map((h, i) => [h.id, i]))
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
        cell, idx: nativeIdx.get(h.id),
        label: h.label ?? null,
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
            if (!strandPassesScafStapFilter(strand, filter)) return null
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
      if (!strandPassesScafStapFilter(strand, _selectFilter)) continue
      const doms = strand.domains
      for (let di = 0; di < doms.length; di++) {
        const dom = doms[di]
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const lo   = Math.min(dom.start_bp, dom.end_bp)
        const hi   = Math.max(dom.start_bp, dom.end_bp)
        const isFwd = dom.direction === 'FORWARD'
        const dxL  = _bpToX(lo), dxR = _bpToX(hi + 1)
        const dyC  = isFwd ? info.fwdY : info.revY
        // Quick reject — entire domain outside lasso
        if (dxR <= lx0 || dxL >= lx1 || dyC + CELL_H / 2 <= ly0 || dyC - CELL_H / 2 >= ly1) continue

        // Only strand-level terminals are selectable as ends, not internal
        // domain junctions (e.g. after a forced ligation merges two strands).
        const isFirstDom = di === 0
        const isLastDom  = di === doms.length - 1
        const has5p = isFirstDom   // strand 5' lives on the first domain
        const has3p = isLastDom    // strand 3' lives on the last domain

        if (lo === hi) {
          // Single-bp domain: the whole cell is an end cap
          if (_selectFilter.ends && has5p) result.add(_domainEndKey(dom, '5p'))
        } else {
          // Left end-cap cell (lo bp): 5′ for FORWARD, 3′ for REVERSE
          const leftIs5p = isFwd
          if (_selectFilter.ends && lx1 > dxL && lx0 < dxL + BP_W) {
            if (leftIs5p ? has5p : has3p)
              result.add(_domainEndKey(dom, isFwd ? '5p' : '3p'))
          }
          // Right end-cap cell (hi bp): 3′ for FORWARD, 5′ for REVERSE
          if (_selectFilter.ends && lx1 > _bpToX(hi) && lx0 < dxR) {
            if (leftIs5p ? has3p : has5p)
              result.add(_domainEndKey(dom, isFwd ? '3p' : '5p'))
          }
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
        if (isScafXo && !_selectFilter.scaf) continue
        if (!isScafXo && !_selectFilter.stap) continue
        const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
        const axMin  = Math.min(x, x + bowDir * bowAmt) - BP_W * 0.5
        const axMax  = Math.max(x, x + bowDir * bowAmt) + BP_W * 0.5
        const ayMin  = Math.min(y0, y1), ayMax = Math.max(y0, y1)
        if (axMax <= lx0 || axMin >= lx1 || ayMax <= ly0 || ayMin >= ly1) continue
        result.add(_xoverKey(xo))
      }
      // Forced ligation arcs — same geometry as strand-transition arcs
      for (const fl of (_design?.forced_ligations ?? [])) {
        const infoA = _rowMap.get(fl.three_prime_helix_id)
        const infoB = _rowMap.get(fl.five_prime_helix_id)
        if (!infoA || !infoB) continue
        const xA   = _bpCenterX(fl.three_prime_bp)
        const xB   = _bpCenterX(fl.five_prime_bp)
        const yA   = fl.three_prime_direction === 'FORWARD' ? infoA.fwdY : infoA.revY
        const yB   = fl.five_prime_direction  === 'FORWARD' ? infoB.fwdY : infoB.revY
        const midX = (xA + xB) / 2
        const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
        const axMin = Math.min(xA, xB, midX + bowAmt) - BP_W * 0.5
        const axMax = Math.max(xA, xB, midX + bowAmt) + BP_W * 0.5
        const ayMin = Math.min(yA, yB), ayMax = Math.max(yA, yB)
        if (axMax <= lx0 || axMin >= lx1 || ayMax <= ly0 || ayMin >= ly1) continue
        result.add(_forcedLigKey(fl))
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

  // Click tolerance for arc hit-testing — squared, in world units.
  // ~half a bp-cell width: tight enough that diagonal forced-ligation arcs
  // don't claim a huge rectangular hit-box, loose enough to forgive a small
  // miss on the actual stroked curve.
  const _ARC_HIT_TOLERANCE = BP_W * 0.5
  const _ARC_HIT_TOL_SQ    = _ARC_HIT_TOLERANCE * _ARC_HIT_TOLERANCE

  // Sample-and-segment min squared distance from (wx, wy) to a quadratic
  // Bezier. Treats the curve as a `samples`-segment polyline (24 segments
  // tracks the visual stroke to within a fraction of a pixel at typical
  // zoom levels) and returns the smallest squared distance from the point
  // to any segment.
  function _quadBezierMinDistSq(wx, wy, x0, y0, cx, cy, x1, y1, samples = 24) {
    let best = Infinity
    let prevX = x0, prevY = y0
    for (let i = 1; i <= samples; i++) {
      const t  = i / samples
      const mt = 1 - t
      const bx = mt * mt * x0 + 2 * mt * t * cx + t * t * x1
      const by = mt * mt * y0 + 2 * mt * t * cy + t * t * y1
      const dx = bx - prevX, dy = by - prevY
      const segLenSq = dx * dx + dy * dy
      let projT = 0
      if (segLenSq > 1e-9) {
        projT = ((wx - prevX) * dx + (wy - prevY) * dy) / segLenSq
        if (projT < 0) projT = 0; else if (projT > 1) projT = 1
      }
      const ex = wx - (prevX + projT * dx)
      const ey = wy - (prevY + projT * dy)
      const dSq = ex * ex + ey * ey
      if (dSq < best) best = dSq
      prevX = bx; prevY = by
    }
    return best
  }

  /**
   * Hit-test a world-space point against all registered crossover and
   * forced-ligation arcs. Returns the CLOSEST hit (`{ xo }` or `{ fl }`)
   * within `_ARC_HIT_TOLERANCE` world units of the actual stroked curve,
   * or null when no arc is close enough or the xover filter is off.
   *
   * Uses an AABB pre-filter (expanded by the tolerance) for cheap rejection
   * of distant arcs, then a sampled-Bezier distance check for arcs that
   * pass the pre-filter. The previous AABB-only hit-test gave diagonal
   * forced-ligation arcs an inflated rectangular hit-box that swallowed
   * clicks on neighbouring crossovers.
   */
  function _hitTestArc(wx, wy) {
    if (!_selectFilter.xover) return null
    let best = null
    let bestDistSq = _ARC_HIT_TOL_SQ
    const tol = _ARC_HIT_TOLERANCE

    // ── Crossover arcs ──────────────────────────────────────────────────────
    for (const xo of (_design?.crossovers ?? [])) {
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue
      const isScafXo = infoA.scaffoldFwd ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
      if (isScafXo && !_selectFilter.scaf) continue
      if (!isScafXo && !_selectFilter.stap) continue
      const x   = _bpCenterX(xo.half_a.index)
      const y0  = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1  = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
      const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const cx = x + bowDir * bowAmt
      const cy = (y0 + y1) / 2
      // Cheap AABB pre-filter (expanded by tolerance).
      const xMin = Math.min(x, cx) - tol
      const xMax = Math.max(x, cx) + tol
      const yMin = Math.min(y0, y1) - tol
      const yMax = Math.max(y0, y1) + tol
      if (wx < xMin || wx > xMax || wy < yMin || wy > yMax) continue
      // Precise check against the sampled Bezier.
      const dSq = _quadBezierMinDistSq(wx, wy, x, y0, cx, cy, x, y1)
      if (dSq < bestDistSq) { bestDistSq = dSq; best = { xo } }
    }

    // ── Forced ligation arcs ───────────────────────────────────────────────
    for (const fl of (_design?.forced_ligations ?? [])) {
      const infoA = _rowMap.get(fl.three_prime_helix_id)
      const infoB = _rowMap.get(fl.five_prime_helix_id)
      if (!infoA || !infoB) continue
      const xA   = _bpCenterX(fl.three_prime_bp)
      const xB   = _bpCenterX(fl.five_prime_bp)
      const yA   = fl.three_prime_direction === 'FORWARD' ? infoA.fwdY : infoA.revY
      const yB   = fl.five_prime_direction  === 'FORWARD' ? infoB.fwdY : infoB.revY
      const midX = (xA + xB) / 2
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
      const cx = midX + bowAmt
      const cy = (yA + yB) / 2
      const xMin = Math.min(xA, xB, cx) - tol
      const xMax = Math.max(xA, xB, cx) + tol
      const yMin = Math.min(yA, yB) - tol
      const yMax = Math.max(yA, yB) + tol
      if (wx < xMin || wx > xMax || wy < yMin || wy > yMax) continue
      const dSq = _quadBezierMinDistSq(wx, wy, xA, yA, cx, cy, xB, yB)
      if (dSq < bestDistSq) { bestDistSq = dSq; best = { fl } }
    }

    return best
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
  /**
   * Find a ligateable nick near cursorBp on the hovered domain's helix/direction.
   *
   * A nick is ligateable when a strand's 3' terminal end and another strand's
   * 5' terminal end sit on the same helix, same direction, with a bp index
   * difference of exactly 1.  That's the whole computation — no other checks.
   *
   * NOTE: This is regular ligation (shift+click with nick tool), NOT forced
   * ligation (pencil tool).  Forced ligation connects arbitrary 3'/5' ends
   * across helices; regular ligation only repairs same-helix nicks.
   */
  function _findLigation(dom, cursorBp) {
    if (!_design?.strands) return null
    const helixId = dom.helix_id
    const dir     = dom.direction

    // Collect all strand-terminal 3' and 5' ends on this helix+direction.
    const threeEnds = []  // bp values of 3' strand termini
    const fiveEnds  = []  // bp values of 5' strand termini
    for (const s of _design.strands) {
      if (!s.domains.length) continue
      const last  = s.domains[s.domains.length - 1]
      if (last.helix_id === helixId && last.direction === dir)
        threeEnds.push(last.end_bp)
      const first = s.domains[0]
      if (first.helix_id === helixId && first.direction === dir)
        fiveEnds.push(first.start_bp)
    }

    // Find pairs where |3'bp - 5'bp| === 1 (adjacent on the helix).
    const candidates = []
    for (const t of threeEnds) {
      for (const f of fiveEnds) {
        if (Math.abs(t - f) !== 1) continue
        // bpIndex sent to backend is the 3' end bp (same convention as nick).
        candidates.push({
          threeEndBp: t, fiveEndBp: f, bpIndex: t,
          dist: Math.abs(cursorBp - (t + f) / 2),
        })
      }
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

      if (_viewTools.grid) {
        // ── Cell backgrounds ──────────────────────────────────────────────────
        ctx.fillStyle = CLR_CELL_BG
        ctx.fillRect(startX, topY, endX - startX, pairH)

        // ── Horizontal divider between the two tracks ─────────────────────────
        ctx.strokeStyle = CLR_TRACK
        ctx.lineWidth   = 0.5 / _zoom
        _line(startX, fwdY + half, endX, fwdY + half)

        // ── Vertical column separators ────────────────────────────────────────
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

        // ── Outer border around the 2-cell pair ───────────────────────────────
        ctx.strokeStyle = CLR_TRACK
        ctx.lineWidth   = 1 / _zoom
        ctx.strokeRect(startX, topY, endX - startX, pairH)
      }
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
    const linkerMembers = new Map()
    for (const conn of (_design?.overhang_connections ?? [])) {
      if (conn.linker_type !== 'ss') continue
      const ids = [`__lnk__${conn.id}__a`, `__lnk__${conn.id}__b`]
      for (const id of ids) linkerMembers.set(id, ids)
    }

    // Crossover slot set — "helixId_bp_direction" for every registered half.
    // Used to suppress end caps on domains that terminate at a crossover.
    const xoverSlots = new Set()
    for (const xo of (_design?.crossovers ?? [])) {
      xoverSlots.add(`${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`)
      xoverSlots.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
    }

    return {
      colorOf:     (si) => strandColor(strands[si], si),
      // ss overhang linkers are stored as two complement strands plus one
      // connection record. Expand either side to both sides so clicking one
      // linker domain highlights the whole logical linker in cadnano and 3D.
      membersOf:   (strandId) => new Set(linkerMembers.get(strandId) ?? [strandId]),
      isXoverSlot: (hid, bp, dir) => xoverSlots.has(`${hid}_${bp}_${dir}`),
    }
  }

  // Frame-cached result of _buildComponents() — rebuilt at the top of _draw().
  let _components = { colorOf: (si) => strandColor((_design?.strands ?? [])[si], si), membersOf: () => new Set(), isXoverSlot: () => false }

  // ── View tools state ──────────────────────────────────────────────────────
  let _viewTools = { lengthHeatmap: false, overhangNames: false, grid: true }

  // Length heat map: maps nucleotide count to a blue→red colour.
  // Range 14–60 bp linearly interpolated; below 14 = pure blue, above 60 = pure red.
  const HEATMAP_MIN = 14
  const HEATMAP_MAX = 60
  function _lengthHeatmapColor(ntCount) {
    const t = Math.max(0, Math.min(1, (ntCount - HEATMAP_MIN) / (HEATMAP_MAX - HEATMAP_MIN)))
    // HSL hue: 240 (blue) → 0 (red)
    const hue = 240 * (1 - t)
    return `hsl(${hue}, 90%, 50%)`
  }
  // Thickness multiplier for out-of-range strands
  function _lengthHeatmapThickMul(ntCount) {
    return (ntCount < HEATMAP_MIN || ntCount > HEATMAP_MAX) ? 1.8 : 1.0
  }
  // Per-frame cache: strand index → { color, thickMul }
  let _heatmapCache = new Map()
  function _rebuildHeatmapCache() {
    _heatmapCache = new Map()
    if (!_viewTools.lengthHeatmap || !_design?.strands) return
    for (let si = 0; si < _design.strands.length; si++) {
      const strand = _design.strands[si]
      if (strand.strand_type === 'scaffold') continue   // scaffold keeps its own colour
      const nt = strandNtCount(strand)
      _heatmapCache.set(si, { color: _lengthHeatmapColor(nt), thickMul: _lengthHeatmapThickMul(nt) })
    }
  }

  // ── Heat map legend (screen-space overlay, right-centre of canvas) ────────
  function _drawHeatmapLegend() {
    if (!_viewTools.lengthHeatmap) return
    const W = canvasEl.width, H = canvasEl.height

    const barW    = 14
    const barH    = 120
    const pad     = 10
    const margin  = 16
    const titleH  = 14
    const labelH  = 11
    const boxW    = barW + pad * 2 + 24   // extra space for tick labels
    const boxH    = barH + pad * 2 + titleH + 8

    const x0 = W - boxW - margin
    const y0 = Math.round((H - boxH) / 2)

    // Background panel
    ctx.fillStyle = 'rgba(13, 17, 23, 0.85)'
    ctx.strokeStyle = '#30363d'
    ctx.lineWidth = 1
    const r = 4
    ctx.beginPath()
    ctx.moveTo(x0 + r, y0)
    ctx.lineTo(x0 + boxW - r, y0)
    ctx.arcTo(x0 + boxW, y0, x0 + boxW, y0 + r, r)
    ctx.lineTo(x0 + boxW, y0 + boxH - r)
    ctx.arcTo(x0 + boxW, y0 + boxH, x0 + boxW - r, y0 + boxH, r)
    ctx.lineTo(x0 + r, y0 + boxH)
    ctx.arcTo(x0, y0 + boxH, x0, y0 + boxH - r, r)
    ctx.lineTo(x0, y0 + r)
    ctx.arcTo(x0, y0, x0 + r, y0, r)
    ctx.closePath()
    ctx.fill()
    ctx.stroke()

    // Title
    ctx.fillStyle = '#c9d1d9'
    ctx.font = '10px Courier New, monospace'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText('Length', x0 + boxW / 2, y0 + 6)

    // Gradient bar (top = red/hot/long, bottom = blue/cold/short)
    const barX = x0 + pad
    const barY = y0 + titleH + pad
    for (let i = 0; i < barH; i++) {
      const t = 1 - i / (barH - 1)   // t=1 at top (red), t=0 at bottom (blue)
      const nt = HEATMAP_MIN + t * (HEATMAP_MAX - HEATMAP_MIN)
      ctx.fillStyle = _lengthHeatmapColor(nt)
      ctx.fillRect(barX, barY + i, barW, 1)
    }
    // Bar border
    ctx.strokeStyle = '#484f58'
    ctx.lineWidth = 1
    ctx.strokeRect(barX, barY, barW, barH)

    // Tick labels (right of bar)
    ctx.fillStyle = '#8b949e'
    ctx.font = '9px Courier New, monospace'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    const tickX = barX + barW + 5
    // Top label
    ctx.fillText(`${HEATMAP_MAX}+`, tickX, barY + 1)
    // Middle label
    const midNt = Math.round((HEATMAP_MIN + HEATMAP_MAX) / 2)
    ctx.fillText(`${midNt}`, tickX, barY + barH / 2)
    // Bottom label
    ctx.fillText(`≤${HEATMAP_MIN}`, tickX, barY + barH - 1)
  }

  // ── Sequence / undefined-base view tool constants ──────────────────────────
  const CLR_SEQ_TEXT = '#000000'
  const CLR_UNDEF_FILL = 'rgba(251, 191, 36, 0.30)'
  const CLR_UNDEF_BORDER = '#d97706'
  const VALID_BASES = new Set(['A', 'T', 'G', 'C'])

  // Build overhang_id → sequence lookup from design.overhangs.
  // Used when a strand has no sequence yet but an overhang has a user-assigned one.
  function _overhangSeqMap() {
    const m = new Map()
    for (const o of (_design?.overhangs ?? [])) {
      if (o.sequence) m.set(o.id, o.sequence.toUpperCase())
    }
    return m
  }

  // Resolve the sequence character at position `i` within a domain.
  // Checks strand.sequence first, then falls back to the overhang spec.
  function _seqCharAt(strand, seqIdx, i, dom, ovhMap) {
    if (strand.sequence) {
      const ch = strand.sequence[seqIdx + i]?.toUpperCase()
      if (ch) return ch
    }
    // Fallback: overhang domain with its own sequence
    if (dom.overhang_id) {
      const ovhSeq = ovhMap.get(dom.overhang_id)
      if (ovhSeq) return ovhSeq[i]?.toUpperCase() ?? null
    }
    return null
  }

  // ── Draw: sequence letters on strand domains (world-space) ────────────────
  function _drawSequences() {
    if (!_viewTools.sequences || !_design?.strands) return
    // Only draw letters when zoomed in enough to read them
    if (BP_W * _zoom < 6) return
    const ovhMap = _overhangSeqMap()
    const fontSize = Math.min(BP_W * 0.85, CELL_H * 0.65)
    ctx.font = `bold ${fontSize}px Courier New, monospace`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = CLR_SEQ_TEXT
    for (const strand of _design.strands) {
      const hasSeq = !!strand.sequence
      const hasOvh = !hasSeq && strand.domains.some(d => d.overhang_id && ovhMap.has(d.overhang_id))
      if (!hasSeq && !hasOvh) continue
      let seqIdx = 0
      for (const dom of strand.domains) {
        const info = _rowMap.get(dom.helix_id)
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const count = hi - lo + 1
        if (!info) { seqIdx += count; continue }
        const isFwd = dom.direction === 'FORWARD'
        const y = isFwd ? info.fwdY : info.revY
        for (let i = 0; i < count; i++) {
          const ch = _seqCharAt(strand, seqIdx, i, dom, ovhMap)
          if (!ch || !VALID_BASES.has(ch)) continue
          const bp = isFwd ? lo + i : hi - i
          const cx = _bpCenterX(bp)
          const sx = cx * _zoom + _panX
          if (sx < -BP_W * _zoom || sx > canvasEl.width + BP_W * _zoom) continue
          ctx.fillText(ch, cx, y)
        }
        seqIdx += count
      }
    }
  }

  // ── Draw: undefined base highlights (world-space) ─────────────────────────
  function _drawUndefinedBases() {
    if (!_viewTools.undefinedBases || !_design?.strands) return
    const ovhMap = _overhangSeqMap()
    ctx.fillStyle = CLR_UNDEF_FILL
    ctx.strokeStyle = CLR_UNDEF_BORDER
    ctx.lineWidth = 1 / _zoom
    for (const strand of _design.strands) {
      let seqIdx = 0
      for (const dom of strand.domains) {
        const info = _rowMap.get(dom.helix_id)
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const count = hi - lo + 1
        if (!info) { seqIdx += count; continue }
        const isFwd = dom.direction === 'FORWARD'
        const y = isFwd ? info.fwdY : info.revY
        const half = CELL_H / 2
        for (let i = 0; i < count; i++) {
          const ch = _seqCharAt(strand, seqIdx, i, dom, ovhMap)
          if (ch && VALID_BASES.has(ch)) continue
          const bp = isFwd ? lo + i : hi - i
          const x = _bpToX(bp)
          const sx = x * _zoom + _panX
          if (sx + BP_W * _zoom < 0 || sx > canvasEl.width) continue
          ctx.fillRect(x, y - half, BP_W, CELL_H)
          ctx.strokeRect(x, y - half, BP_W, CELL_H)
        }
        seqIdx += count
      }
    }
  }

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
    thickMul = 1.0,
  ) {
    const isFwd   = dom.direction === 'FORWARD'
    const y       = isFwd ? info.fwdY : info.revY
    const lo      = Math.min(dom.start_bp, dom.end_bp)
    const hi      = Math.max(dom.start_bp, dom.end_bp)
    const x1      = _bpToX(lo)
    const x2      = _bpToX(hi + 1)
    const half    = CELL_H / 2
    const sThick  = CELL_H * 0.20 * thickMul
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
    // Build a set of strand-end positions that have an extension arm so end caps
    // can be moved to the arm tip instead of the domain terminus.
    const extEndSet = new Set((_design.extensions ?? []).map(e => `${e.strand_id}:${e.end}`))
    for (let si = 0; si < _design.strands.length; si++) {
      const strand   = _design.strands[si]
      const isGlow   = _strandSelectedIds.has(strand.id)
      const hm       = _heatmapCache.get(si)
      const color    = isGlow ? CLR_STRAND_GLOW : (hm ? hm.color : _components.colorOf(si))
      const thickMul = hm ? hm.thickMul : 1.0
      const n        = strand.domains.length
      for (let di = 0; di < n; di++) {
        const dom  = strand.domains[di]
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const sTop = (info.fwdY - CELL_H / 2) * _zoom + _panY
        if ((info.revY + CELL_H / 2) * _zoom + _panY < 0 || sTop > canvasEl.height) continue

        // Suppress the end cap (square or triangle) and use a half-line wherever
        // an arc attaches — either a registered crossover or a cross-helix
        // domain continuation (coaxial, scaffold routing, forced ligation).
        const dir     = dom.direction
        const lo      = Math.min(dom.start_bp, dom.end_bp)
        const hi      = Math.max(dom.start_bp, dom.end_bp)
        const fiveBp  = dir === 'FORWARD' ? lo : hi
        const threeBp = dir === 'FORWARD' ? hi : lo
        const prev = di > 0     ? strand.domains[di - 1] : null
        const next = di < n - 1 ? strand.domains[di + 1] : null
        // Registered crossover: body stops at cell centre (visualises the gap at N|N+1).
        const xoverSlot5 = _components.isXoverSlot(dom.helix_id, fiveBp,  dir)
        const xoverSlot3 = _components.isXoverSlot(dom.helix_id, threeBp, dir)
        // Cross-helix continuation within the same strand: body stops at cell
        // centre (half a line) and end cap is suppressed — same visual as a
        // registered crossover.  Consecutive domains in a strand's domain list
        // are always connected (3' of domain[i] → 5' of domain[i+1]).  This
        // covers coaxial, scaffold routing, and forced ligation (manual
        // cross-helix ligation at any bp offset).
        const continuationAt5 = !!(prev && prev.helix_id !== dom.helix_id)
        const continuationAt3 = !!(next && next.helix_id !== dom.helix_id)
        const xoverAt5 = xoverSlot5 || continuationAt5
        const xoverAt3 = xoverSlot3 || continuationAt3
        // Same-helix continuation: two adjacent domains on the same helix &
        // direction (e.g. scaffold-part + overhang split).  Suppress end caps
        // so the strand appears continuous, but do NOT set xoverAt* (body
        // should extend fully, not stop at cell centre).
        const sameHelixAt5 = !!(prev && prev.helix_id === dom.helix_id && prev.direction === dir)
        const sameHelixAt3 = !!(next && next.helix_id === dom.helix_id && next.direction === dir)
        // Extension arm: suppress domain end cap — it will be drawn at the arm tip instead.
        const extAt5 = di === 0       && extEndSet.has(`${strand.id}:five_prime`)
        const extAt3 = di === n - 1   && extEndSet.has(`${strand.id}:three_prime`)
        const suppress5 = xoverAt5 || sameHelixAt5 || extAt5
        const suppress3 = xoverAt3 || sameHelixAt3 || extAt3

        _drawDomain(dom, info, color, suppress5, suppress3, xoverAt5 || extAt5, xoverAt3 || extAt3, isGlow, thickMul)
      }
    }
  }

  // ── Draw: strand extensions (5′/3′ tails with optional sequence/modification) ─

  function _drawExtensions() {
    if (!_design?.extensions?.length || !_design?.strands) return
    const strandMap = new Map(_design.strands.map((s, i) => [s.id, { strand: s, idx: i }]))
    const lineW = CELL_H * 0.20
    const dotR  = CELL_H * 0.30
    const sqSz  = Math.min(BP_W, CELL_H) * 0.80
    const half  = CELL_H / 2

    ctx.save()
    ctx.lineCap = 'round'

    for (const ext of _design.extensions) {
      const entry = strandMap.get(ext.strand_id)
      if (!entry) continue
      const { strand, idx } = entry

      const dom = ext.end === 'five_prime'
        ? strand.domains[0]
        : strand.domains[strand.domains.length - 1]
      if (!dom) continue

      const info = _rowMap.get(dom.helix_id)
      if (!info) continue

      // Screen-space cull
      const rowSY = info.fwdY * _zoom + _panY
      if (rowSY + ROW_H * _zoom < 0 || rowSY - ROW_H * _zoom > canvasEl.height) continue

      const isFwd = dom.direction === 'FORWARD'
      const lo    = Math.min(dom.start_bp, dom.end_bp)
      const hi    = Math.max(dom.start_bp, dom.end_bp)
      const ay    = isFwd ? info.fwdY : info.revY

      // Attached end: centre of terminal bp cell (arm originates from bp centre, matching crossover convention)
      let termBp
      if      (isFwd  && ext.end === 'five_prime')  termBp = lo
      else if (isFwd  && ext.end === 'three_prime') termBp = hi
      else if (!isFwd && ext.end === 'five_prime')  termBp = hi
      else                                           termBp = lo
      const ax = _bpToX(termBp) + BP_W / 2

      // Free end — scadnano sign convention adapted to our coordinate system
      const dx = EXT_LEN_PX * Math.cos(EXT_ANGLE_RAD)
      const dy = EXT_LEN_PX * Math.sin(EXT_ANGLE_RAD)
      let fx, fy
      if      (isFwd  && ext.end === 'five_prime')  { fx = ax - dx; fy = ay - dy }
      else if (isFwd  && ext.end === 'three_prime') { fx = ax + dx; fy = ay - dy }
      else if (!isFwd && ext.end === 'five_prime')  { fx = ax + dx; fy = ay + dy }
      else                                           { fx = ax - dx; fy = ay + dy }

      // Arm unit vector and perpendicular (used for end cap and sequence positioning)
      const ux  = (fx - ax) / EXT_LEN_PX
      const uy  = (fy - ay) / EXT_LEN_PX
      const pvx = -uy
      const pvy =  ux

      // Strand colour (same lookup as _drawAllDomains)
      const hm    = _heatmapCache.get(idx)
      const color = hm ? hm.color : _components.colorOf(idx)

      // ── Arm line ────────────────────────────────────────────────────────────
      ctx.strokeStyle = color
      ctx.lineWidth   = lineW
      ctx.shadowBlur  = 0
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(fx, fy)
      ctx.stroke()

      // ── End cap or modification dot at free end ─────────────────────────────
      if (ext.modification) {
        // Modification: coloured dot (replaces the end cap)
        const dotColor = EXT_MOD_COLORS[ext.modification] ?? '#ffffff'
        ctx.fillStyle   = dotColor
        ctx.strokeStyle = '#000000'
        ctx.lineWidth   = 0.5
        ctx.beginPath()
        ctx.arc(fx, fy, dotR, 0, 2 * Math.PI)
        ctx.fill()
        ctx.stroke()
      } else if (ext.end === 'five_prime') {
        // 5′ square at arm tip
        ctx.fillStyle = color
        ctx.fillRect(fx - sqSz / 2, fy - sqSz / 2, sqSz, sqSz)
      } else {
        // 3′ triangle at arm tip, pointing along the arm direction
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.moveTo(fx - ux * BP_W + pvx * half, fy - uy * BP_W + pvy * half)
        ctx.lineTo(fx, fy)
        ctx.lineTo(fx - ux * BP_W - pvx * half, fy - uy * BP_W - pvy * half)
        ctx.closePath()
        ctx.fill()
      }

      // ── Sequence — interpolated along arm, gated on sequence view tool ──────
      if (_viewTools.sequences && ext.sequence && BP_W * _zoom >= 6) {
        const seq      = ext.sequence.toUpperCase()
        const n        = seq.length
        const fontSize = Math.min(BP_W * 0.85, CELL_H * 0.65)
        ctx.font         = `bold ${fontSize}px Courier New, monospace`
        ctx.fillStyle    = '#222222'
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'middle'
        for (let i = 0; i < n; i++) {
          const t  = (i + 1) / (n + 1)
          const bx = ax + t * (fx - ax)
          const by = ay + t * (fy - ay)
          ctx.fillText(seq[i], bx, by)
        }
      }

      // ── Label — modification name or extension label, gated on overhang tool ─
      if (_viewTools.overhangNames && BP_W * _zoom >= 3) {
        const label = ext.modification
          ? (EXT_MOD_NAMES[ext.modification] ?? ext.modification)
          : (ext.label ?? null)
        if (label) {
          const fontSize = Math.max(6, Math.min(CELL_H * 0.65, BP_W * 0.85))
          ctx.font         = `${fontSize}px sans-serif`
          ctx.fillStyle    = '#333333'
          ctx.textBaseline = 'middle'
          ctx.textAlign    = fx > ax ? 'left' : 'right'
          const gap  = ext.modification ? dotR + 2 : sqSz / 2 + 2
          const xOff = fx > ax ? gap : -gap
          ctx.fillText(label, fx + xOff, fy)
        }
      }
    }
    ctx.restore()
  }

  // ── Draw: coaxial continuation arcs ───────────────────────────────────────────
  //
  // When two adjacent domains in the same strand are on different helices at
  // consecutive bp (coaxial ligation), draw a connecting arc so the user sees
  // that the strand is continuous.

  function _drawCoaxialArcs() {
    if (!_design?.strands) return
    const baseThick = CELL_H * 0.20
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = baseThick
    ctx.shadowBlur = 0
    for (let si = 0; si < _design.strands.length; si++) {
      const strand = _design.strands[si]
      const strandGlow = _strandSelectedIds.has(strand.id)
      const hm = _heatmapCache.get(si)
      const color  = strandGlow ? CLR_STRAND_GLOW : (hm ? hm.color : _components.colorOf(si))
      ctx.strokeStyle = color
      ctx.lineWidth = baseThick * (hm ? hm.thickMul : 1.0)
      if (strandGlow) { ctx.shadowColor = CLR_STRAND_GLOW; ctx.shadowBlur = 10 / _zoom }
      else            { ctx.shadowBlur = 0 }
      for (let di = 0; di < strand.domains.length - 1; di++) {
        const domA = strand.domains[di]
        const domB = strand.domains[di + 1]
        if (domA.helix_id === domB.helix_id) continue  // same helix — no arc needed
        // Skip if this transition is a registered crossover — _drawCrossoverArcs handles those.
        if (_components.isXoverSlot(domA.helix_id, domA.end_bp, domA.direction)) continue
        // Skip if this transition is a forced ligation — _drawCrossoverArcs handles those too.
        if (_isForcedLigTransition(domA, domB)) continue
        const infoA = _rowMap.get(domA.helix_id)
        const infoB = _rowMap.get(domB.helix_id)
        if (!infoA || !infoB) continue
        // Arc from 3' end of domA to 5' end of domB — use each domain's
        // own direction for its Y track (overhangs may be antiparallel).
        // Handles coaxial adjacency (bp ±1), forced ligation (any bp), and overhangs.
        const isFwdA = domA.direction === 'FORWARD'
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
    const hasXovers = _design?.crossovers?.length > 0
    const hasForcedLigs = _design?.forced_ligations?.length > 0
    if (!hasXovers && !hasForcedLigs) return
    const baseThick = CELL_H * 0.20
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = baseThick
    for (const xo of (_design?.crossovers ?? [])) {
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue
      const sA      = _findStrandIdxAt(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
      const sB      = _findStrandIdxAt(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
      const strandGlow = (sA >= 0 && _strandSelectedIds.has(_design.strands[sA].id)) ||
                         (sB >= 0 && _strandSelectedIds.has(_design.strands[sB].id))
      const arcSel  = _selectedElements.has(_xoverKey(xo))
      const hmA = sA >= 0 ? _heatmapCache.get(sA) : null
      if (arcSel) {
        ctx.strokeStyle  = CLR_SEL_RING
        ctx.lineWidth    = baseThick * 2.5
        ctx.shadowColor  = CLR_SEL_RING
        ctx.shadowBlur   = 8 / _zoom
      } else if (strandGlow) {
        ctx.strokeStyle  = CLR_STRAND_GLOW
        ctx.lineWidth    = baseThick * (hmA ? hmA.thickMul : 1.0)
        ctx.shadowColor  = CLR_STRAND_GLOW
        ctx.shadowBlur   = 10 / _zoom
      } else {
        ctx.strokeStyle  = hmA ? hmA.color : (sA >= 0 ? _components.colorOf(sA) : CLR_SCAFFOLD)
        ctx.lineWidth    = baseThick * (hmA ? hmA.thickMul : 1.0)
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

      // ⚠ marker for unligated (would-circularize) crossovers — drawn at the
      // arc's bow apex (peak of the quadratic Bézier, t=0.5) so it sits at
      // the visually most-distant point from the helix tracks. Auto-clears
      // when the user nicks the strand to break the cycle (backend recomputes
      // unligated_crossover_ids on the next response).
      if (_unligatedCrossoverIds.has(xo.id)) {
        const apexX = x + 0.5 * bowDir * bowAmt
        const apexY = midY
        ctx.save()
        ctx.shadowBlur = 0
        ctx.fillStyle    = '#f5a623'   // amber — same as feature-log broken-delta marker
        ctx.strokeStyle  = '#000'
        ctx.lineWidth    = 0.5 / _zoom
        ctx.font         = `bold ${Math.max(BP_W * 1.4, 7)}px sans-serif`
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'middle'
        ctx.strokeText('⚠', apexX, apexY)
        ctx.fillText  ('⚠', apexX, apexY)
        ctx.restore()
      }

      // Extra-base tick marks — one bar per extra base, sampled evenly along
      // the quadratic Bézier arc, each extending from the arc toward the bow centre.
      if (xo.extra_bases?.length > 0) {
        const n     = xo.extra_bases.length
        const tickW = BP_W * 0.7   // length of each bar
        ctx.save()
        ctx.strokeStyle = arcSel ? CLR_SEL_RING : (hmA ? hmA.color : (sA >= 0 ? _components.colorOf(sA) : CLR_SCAFFOLD))
        ctx.lineWidth   = baseThick * 0.7
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
    // Forced ligation arcs — drawn with the same selection highlighting as crossovers.
    // Uses the strand-transition arc geometry (asymmetric endpoints).
    for (const fl of (_design?.forced_ligations ?? [])) {
      const infoA = _rowMap.get(fl.three_prime_helix_id)
      const infoB = _rowMap.get(fl.five_prime_helix_id)
      if (!infoA || !infoB) continue
      const sIdx     = _findStrandIdxAt(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction)
      const strandGlow = sIdx >= 0 && _strandSelectedIds.has(_design.strands[sIdx].id)
      const arcSel   = _selectedElements.has(_forcedLigKey(fl))
      const hmFL = sIdx >= 0 ? _heatmapCache.get(sIdx) : null
      if (arcSel) {
        ctx.strokeStyle  = CLR_SEL_RING
        ctx.lineWidth    = baseThick * 2.5
        ctx.shadowColor  = CLR_SEL_RING
        ctx.shadowBlur   = 8 / _zoom
      } else if (strandGlow) {
        ctx.strokeStyle  = CLR_STRAND_GLOW
        ctx.lineWidth    = baseThick * (hmFL ? hmFL.thickMul : 1.0)
        ctx.shadowColor  = CLR_STRAND_GLOW
        ctx.shadowBlur   = 10 / _zoom
      } else {
        ctx.strokeStyle  = hmFL ? hmFL.color : (sIdx >= 0 ? _components.colorOf(sIdx) : CLR_SCAFFOLD)
        ctx.lineWidth    = baseThick * (hmFL ? hmFL.thickMul : 1.0)
        ctx.shadowBlur   = 0
      }
      const xA   = _bpCenterX(fl.three_prime_bp)
      const xB   = _bpCenterX(fl.five_prime_bp)
      const yA   = fl.three_prime_direction === 'FORWARD' ? infoA.fwdY : infoA.revY
      const yB   = fl.five_prime_direction  === 'FORWARD' ? infoB.fwdY : infoB.revY
      const midX = (xA + xB) / 2
      const midY = (yA + yB) / 2
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
      const ctrlX = midX + bowAmt
      const ctrlY = midY
      ctx.beginPath()
      ctx.moveTo(xA, yA)
      ctx.quadraticCurveTo(ctrlX, ctrlY, xB, yB)
      ctx.stroke()

      // Extra-base tick marks — one bar per extra base, sampled evenly along the arc,
      // each extending perpendicularly toward the bow interior.
      if (fl.extra_bases?.length > 0) {
        const n     = fl.extra_bases.length
        const tickW = BP_W * 0.7
        ctx.save()
        ctx.strokeStyle = arcSel ? CLR_SEL_RING : (hmFL ? hmFL.color : (sIdx >= 0 ? _components.colorOf(sIdx) : CLR_SCAFFOLD))
        ctx.lineWidth   = baseThick * 0.7
        ctx.lineCap     = 'butt'
        ctx.shadowBlur  = 0
        for (let i = 1; i <= n; i++) {
          const t  = i / (n + 1)
          const mt = 1 - t
          const bx = mt * mt * xA + 2 * mt * t * ctrlX + t * t * xB
          const by = mt * mt * yA + 2 * mt * t * ctrlY + t * t * yB
          // Tangent at t; normal points toward control-point (bow) side
          const tdx = 2 * (mt * (ctrlX - xA) + t * (xB - ctrlX))
          const tdy = 2 * (mt * (ctrlY - yA) + t * (yB - ctrlY))
          const len = Math.hypot(tdx, tdy) || 1
          let nx = -tdy / len
          let ny =  tdx / len
          // Flip normal to always point toward bow (control point side)
          if (nx * (ctrlX - bx) + ny * (ctrlY - by) < 0) { nx = -nx; ny = -ny }
          ctx.beginPath()
          ctx.moveTo(bx, by)
          ctx.lineTo(bx + nx * tickW, by + ny * tickW)
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

  // ── Draw: overhang names ─────────────────────────────────────────────────────

  function _drawOverhangNames() {
    if (!_viewTools.overhangNames || !_design?.strands) return
    const labelMap = new Map()
    for (const ovhg of (_design.overhangs ?? [])) {
      if (ovhg.label) labelMap.set(ovhg.id, ovhg.label)
    }
    if (!labelMap.size) return

    const fontSize = Math.max(7, Math.min(CELL_H * 0.75, BP_W * 2))
    ctx.font = `bold ${fontSize}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'bottom'
    ctx.fillStyle = '#fb923c'

    for (const strand of _design.strands) {
      for (const dom of strand.domains) {
        if (!dom.overhang_id) continue
        const label = labelMap.get(dom.overhang_id)
        if (!label) continue
        const info = _rowMap.get(dom.helix_id)
        if (!info) continue
        const lo  = Math.min(dom.start_bp, dom.end_bp)
        const hi  = Math.max(dom.start_bp, dom.end_bp)
        const mid = (lo + hi) / 2
        const x   = _bpCenterX(mid)
        const y   = (dom.direction === 'FORWARD' ? info.fwdY : info.revY) - CELL_H * 0.55
        ctx.fillText(label, x, y)
      }
    }
    ctx.textBaseline = 'alphabetic'
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

    // Pre-compute scaffold crossover neighbor helix IDs for the hovered helix.
    // These are the helices that could receive a scaffold crossover from the
    // hovered helix at any bp — we show sprites on both sides.
    const _scafNeighborHids = new Set()
    if (_shiftHeld && _hoverHelixId != null) {
      const hInfo = _rowMap.get(_hoverHelixId)
      const hHelix = hInfo && _helices.find(h => h.id === _hoverHelixId)
      if (hInfo && hHelix) {
        const hMinBp = minDomainBpByHelix.get(_hoverHelixId) ?? hHelix.bp_start
        const hBpStart = Math.max(bpL, hMinBp)
        const hBpEnd   = Math.min(bpR, hHelix.bp_start + hHelix.length_bp - 1)
        for (let bp = hBpStart; bp <= hBpEnd; bp++) {
          const nb = _xoverNeighborCellScaffold(hInfo.cell.row, hInfo.cell.col, bp, isHC)
          if (nb) {
            const t = cellMap.get(`${nb[0]}_${nb[1]}`)
            if (t) _scafNeighborHids.add(t.hid)
          }
        }
      }
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
        // Only show for the hovered helix and its crossover neighbor to avoid
        // overwhelming the view on large designs.
        if (_shiftHeld && _hoverHelixId != null &&
            (hid === _hoverHelixId || _scafNeighborHids.has(hid))) {
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

  // ── Domain-drag helpers (move whole domain) ────────────────────────────────

  // Build domain-drag entries from all `line:` keys in _selectedElements.
  function _resolveDomainDragEntries() {
    const entries = []
    for (const key of _selectedElements) {
      if (!key.startsWith('line:')) continue
      const m = key.match(/^line:(.+)_(\d+)_(\d+)_(FORWARD|REVERSE)$/)
      if (!m) continue
      const [, helix_id, loStr, hiStr, direction] = m
      const lo = parseInt(loStr), hi = parseInt(hiStr)
      let found = false
      for (const strand of (_design?.strands ?? [])) {
        for (let di = 0; di < strand.domains.length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== helix_id || dom.direction !== direction) continue
          const dLo = Math.min(dom.start_bp, dom.end_bp)
          const dHi = Math.max(dom.start_bp, dom.end_bp)
          if (dLo !== lo || dHi !== hi) continue
          entries.push({
            strandId:    strand.id,
            domainIndex: di,
            helixId:     helix_id,
            direction,
            domLo:       lo,
            domHi:       hi,
            info:        _rowMap.get(helix_id),
          })
          found = true; break
        }
        if (found) break
      }
    }
    return entries
  }

  // Compute shared [minDelta, maxDelta] across all dragged domains.
  // Rules (intersected across entries):
  //   - Plain Crossover at domLo or domHi on (helix, direction) → entry clamps to [0, 0].
  //     ForcedLigation records do NOT clamp; their bp is shifted by the same delta on commit.
  //   - Plain Crossover strictly inside (domLo, domHi) on (helix, direction) → clamp to [0, 0].
  //   - Other-domain endpoints on the same (helix, direction) bound the slide
  //     direction (no overlap allowed; gaps are allowed). Endpoints belonging
  //     to OTHER co-selected domains in `entries` are excluded — they shift
  //     by the same shared delta so they can never collide with us.
  //   - Helix bp 0 floor: minDelta ≥ -domLo. Backend auto-grows on the upper end.
  function _computeDomainDragLimits(entries) {
    let minDelta = -Infinity, maxDelta = +Infinity

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

    // Set of (strand_id, domain_index) keys identifying co-selected domains —
    // these don't act as blockers for each other since they all shift by the
    // same delta.
    const coSelected = new Set(entries.map(en => `${en.strandId}\x00${en.domainIndex}`))

    const otherEndpoints = (helixId, direction, domLo, domHi) => {
      const lefts = []   // endpoints with hi < domLo
      const rights = []  // endpoints with lo > domHi
      for (const strand of (_design?.strands ?? [])) {
        for (let di = 0; di < strand.domains.length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== helixId || dom.direction !== direction) continue
          if (coSelected.has(`${strand.id}\x00${di}`)) continue   // co-moving — skip
          const lo = Math.min(dom.start_bp, dom.end_bp)
          const hi = Math.max(dom.start_bp, dom.end_bp)
          if (lo === domLo && hi === domHi) continue   // same domain — skip
          if (hi < domLo) lefts.push(hi)
          else if (lo > domHi) rights.push(lo)
          else {
            // Some other domain already overlaps — pre-existing inconsistency,
            // bail out by clamping this entry to zero.
            lefts.push(domLo)   // forces minDelta = 0
            rights.push(domHi)  // forces maxDelta = 0
          }
        }
      }
      return { lefts, rights }
    }

    for (const entry of entries) {
      const { helixId, direction, domLo, domHi } = entry
      const xoPos = xoverPositions(helixId, direction)

      // Plain crossover at either endpoint OR strictly inside → cannot move.
      let blocked = xoPos.has(domLo) || xoPos.has(domHi)
      if (!blocked) {
        for (const bp of xoPos) {
          if (bp > domLo && bp < domHi) { blocked = true; break }
        }
      }
      if (blocked) {
        minDelta = Math.max(minDelta, 0)
        maxDelta = Math.min(maxDelta, 0)
        continue
      }

      const { lefts, rights } = otherEndpoints(helixId, direction, domLo, domHi)
      // Left blocker bounds how far we can shift down (-).
      const leftBlocker = lefts.length ? Math.max(...lefts) : -Infinity
      const minByLeft = leftBlocker === -Infinity ? -Infinity : -(domLo - leftBlocker - 1)
      // bp 0 floor: minDelta ≥ -domLo.
      minDelta = Math.max(minDelta, minByLeft, -domLo)

      // Right blocker bounds how far we can shift up (+).
      const rightBlocker = rights.length ? Math.min(...rights) : Infinity
      const maxByRight = rightBlocker === Infinity ? Infinity : (rightBlocker - domHi - 1)
      maxDelta = Math.min(maxDelta, maxByRight)
    }

    if (minDelta > maxDelta) { minDelta = 0; maxDelta = 0 }
    return { minDelta, maxDelta }
  }

  // Draw a 55%-opacity ghost rectangle for each dragged domain at its shifted
  // bp range. Spans the full domain length so the user sees the whole move.
  function _drawDomainDragGhost() {
    if (!_domDragActive || _domDragDeltaBp === 0) return
    ctx.save()
    ctx.fillStyle = 'rgba(229, 57, 53, 0.55)'
    for (const entry of _domDragEntries) {
      const { info, domLo, domHi, direction } = entry
      if (!info) continue
      const isFwd = direction === 'FORWARD'
      const y     = isFwd ? info.fwdY : info.revY
      const half  = CELL_H / 2
      const newLo = domLo + _domDragDeltaBp
      const newHi = domHi + _domDragDeltaBp
      ctx.fillRect(_bpToX(newLo), y - half, BP_W * (newHi - newLo + 1), CELL_H)
    }
    ctx.restore()
  }

  // ── Crossover drag helpers ──────────────────────────────────────────────────

  /**
   * Find the two consecutive domains connected by a crossover (d0 → xover → d1).
   * Returns { strand, domIdx, d0, d1 } or null.
   */
  function _findXoverDomains(xover) {
    const oldIdx = xover.half_a.index
    for (const [ha, hb] of [[xover.half_a, xover.half_b], [xover.half_b, xover.half_a]]) {
      for (const strand of (_design?.strands ?? [])) {
        for (let di = 0; di < strand.domains.length - 1; di++) {
          const d0 = strand.domains[di]
          const d1 = strand.domains[di + 1]
          if (d0.helix_id === ha.helix_id && d0.direction === ha.strand && d0.end_bp === oldIdx &&
              d1.helix_id === hb.helix_id && d1.direction === hb.strand && d1.start_bp === oldIdx) {
            return { strand, domIdx: di, d0, d1 }
          }
        }
      }
    }
    return null
  }

  /**
   * Compute min/max bp range for a crossover move.
   *
   * Only enforces the hard constraint that each domain must remain ≥ 1 bp
   * (the moving end can't pass its fixed end).  Overlap with other domains
   * is validated by the backend on commit; the frontend allows the full
   * range so the user can drag past unoccupied regions.
   *
   * Returns { minBp, maxBp }.
   */
  function _computeXoverDragLimits(xover) {
    // No domain-size constraint — the backend grows helices as needed and
    // resizes domains in both directions.  Return -/+Infinity so the only
    // real clamp comes from _getValidXoverBps (helix-bounds + padding).
    return { minBp: -Infinity, maxBp: +Infinity }
  }

  /**
   * Compute valid crossover bp indices for the given crossover's helix pair,
   * within [minBp, maxBp], excluding positions occupied by other crossovers.
   */
  function _getValidXoverBps(xover, minBp, maxBp, origBowDir, isScaf) {
    const isHC = _design?.lattice_type === 'HONEYCOMB'
    const infoA = _rowMap.get(xover.half_a.helix_id)
    const infoB = _rowMap.get(xover.half_b.helix_id)
    if (!infoA || !infoB) return []

    // Clamp to helix bp bounds so we never iterate an unbounded range
    const hA = _helices.find(h => h.id === xover.half_a.helix_id)
    const hB = _helices.find(h => h.id === xover.half_b.helix_id)
    if (!hA || !hB) return []
    // Allow dragging well beyond current helix bounds — the backend will grow
    // helices as needed.  Pad by several lattice periods so the user can reach
    // positions past existing strands.
    const PAD = isHC ? 21 * 6 : 32 * 4   // ~126 bp HC, ~128 bp SQ
    const loClamp = Math.max(minBp, Math.min(hA.bp_start, hB.bp_start) - PAD)
    const hiClamp = Math.min(maxBp,
      Math.max(hA.bp_start + hA.length_bp - 1, hB.bp_start + hB.length_bp - 1) + PAD)

    const cellA = infoA.cell
    const targetRow = infoB.cell.row
    const targetCol = infoB.cell.col

    const neighborFn = isScaf ? _xoverNeighborCellScaffold : _xoverNeighborCell

    // Occupied crossover positions (excluding the one being dragged)
    const xoverOccupied = new Set()
    for (const xo of (_design?.crossovers ?? [])) {
      if (xo.id === xover.id) continue
      xoverOccupied.add(`${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`)
      xoverOccupied.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
    }

    // Other domain ranges on each helix+direction (excluding the two dragged domains)
    const doms = _findXoverDomains(xover)
    const d0 = doms?.d0, d1 = doms?.d1, xoStrand = doms?.strand, xoDomIdx = doms?.domIdx
    const otherRangesOn = (helixId, direction, excludeDomIdx) => {
      const ranges = []
      for (const s of (_design?.strands ?? [])) {
        for (let dj = 0; dj < s.domains.length; dj++) {
          if (s.id === xoStrand?.id && dj === excludeDomIdx) continue
          const dom = s.domains[dj]
          if (dom.helix_id !== helixId || dom.direction !== direction) continue
          ranges.push([Math.min(dom.start_bp, dom.end_bp), Math.max(dom.start_bp, dom.end_bp)])
        }
      }
      return ranges
    }
    const d0Others = d0 ? otherRangesOn(d0.helix_id, d0.direction, xoDomIdx) : []
    const d1Others = d1 ? otherRangesOn(d1.helix_id, d1.direction, xoDomIdx != null ? xoDomIdx + 1 : -1) : []

    const valid = []
    for (let bp = loClamp; bp <= hiClamp; bp++) {
      // Bow direction must match the original (left→left, right→right)
      if (_xoverBowDir(bp, isScaf) !== origBowDir) continue
      const nb = neighborFn(cellA.row, cellA.col, bp, isHC)
      if (!nb || nb[0] !== targetRow || nb[1] !== targetCol) continue
      // Check not occupied by another crossover
      if (xoverOccupied.has(`${xover.half_a.helix_id}_${bp}_${xover.half_a.strand}`)) continue
      if (xoverOccupied.has(`${xover.half_b.helix_id}_${bp}_${xover.half_b.strand}`)) continue
      // Check resized domains would not overlap other domains
      if (d0) {
        const newLo = Math.min(d0.start_bp, bp), newHi = Math.max(d0.start_bp, bp)
        if (d0Others.some(([lo, hi]) => newLo <= hi && lo <= newHi)) continue
      }
      if (d1) {
        const newLo = Math.min(d1.end_bp, bp), newHi = Math.max(d1.end_bp, bp)
        if (d1Others.some(([lo, hi]) => newLo <= hi && lo <= newHi)) continue
      }
      valid.push(bp)
    }
    return valid
  }

  /**
   * Draw ghost crossover arc + attached strand bodies during drag.
   *
   * Shows a continuous preview at the cursor's current bp:
   *  - Dim grey when not at a valid snap position (feedback that drag is working)
   *  - Bright cyan when snapped to a valid target
   * The two strand bodies extend/shrink from their fixed ends to the ghost bp.
   */
  function _drawXoverDragGhost() {
    if (!_xoverDragActive || _xoverDragCursorBp == null) return
    if (_xoverDragGroup.length === 0) return

    const isSnapped = _xoverDragSnapBp != null
    const primaryDelta = isSnapped
      ? _xoverDragSnapBp - _xoverDragOrigIdx
      : _xoverDragCursorBp - _xoverDragOrigIdx

    // Colors
    const arcColor    = isSnapped ? '#00e5ff' : 'rgba(150, 160, 170, 0.7)'
    const bodyColor   = isSnapped ? 'rgba(0, 229, 255, 0.35)' : 'rgba(150, 160, 170, 0.25)'
    const cellHiColor = isSnapped ? 'rgba(0, 229, 255, 0.5)' : 'rgba(150, 160, 170, 0.35)'
    const alpha       = isSnapped ? 0.65 : 0.45
    const sThick      = CELL_H * 0.20
    const half        = CELL_H / 2

    ctx.save()
    ctx.globalAlpha = alpha

    for (const g of _xoverDragGroup) {
      const { xo, origIdx, d0, d1, isScaf } = g
      if (!d0 || !d1) continue
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue

      const ghostBp = origIdx + primaryDelta

      const y0 = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1 = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY

      // ── Ghost strand body on helix A (d0: fixed end → ghostBp) ──────
      {
        const fixedBp = d0.start_bp
        const lo = Math.min(fixedBp, ghostBp)
        const hi = Math.max(fixedBp, ghostBp)
        const x1 = _bpToX(lo)
        const x2 = _bpToX(hi + 1)
        ctx.fillStyle = bodyColor
        ctx.fillRect(x1, y0 - sThick / 2, x2 - x1, sThick)
        ctx.fillStyle = cellHiColor
        ctx.fillRect(_bpToX(ghostBp), y0 - half, BP_W, CELL_H)
      }

      // ── Ghost strand body on helix B (d1: ghostBp → fixed end) ──────
      {
        const fixedBp = d1.end_bp
        const lo = Math.min(fixedBp, ghostBp)
        const hi = Math.max(fixedBp, ghostBp)
        const x1 = _bpToX(lo)
        const x2 = _bpToX(hi + 1)
        ctx.fillStyle = bodyColor
        ctx.fillRect(x1, y1 - sThick / 2, x2 - x1, sThick)
        ctx.fillStyle = cellHiColor
        ctx.fillRect(_bpToX(ghostBp), y1 - half, BP_W, CELL_H)
      }

      // ── Ghost crossover arc ─────────────────────────────────────────
      const arcX   = _bpCenterX(ghostBp)
      const bowDir = _xoverBowDir(ghostBp, isScaf)
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const midY   = (y0 + y1) / 2
      ctx.strokeStyle = arcColor
      ctx.lineWidth   = CELL_H * 0.25
      ctx.lineCap     = 'round'
      ctx.beginPath()
      ctx.moveTo(arcX, y0)
      ctx.quadraticCurveTo(arcX + bowDir * bowAmt, midY, arcX, y1)
      ctx.stroke()
    }

    ctx.restore()
  }

  // ── Draw: pencil ghost ────────────────────────────────────────────────────────

  // ── Draw: forced ligation arc (pencil tool drag from 3' end to cursor) ──────

  const CLR_FORCED_LIG_ARC    = 'rgba(180, 50, 220, 0.75)'   // purple arc
  const CLR_FORCED_LIG_ANCHOR = 'rgba(220, 40, 40, 0.85)'    // red 3' anchor dot
  const CLR_FORCED_LIG_TARGET = 'rgba(30, 160, 60, 0.85)'    // green 5' target dot

  function _drawForcedLigationArc() {
    if (!_forcedLigActive) return
    const x0 = _forcedLigStartX, y0 = _forcedLigStartY
    const x1 = _forcedLigCursorX, y1 = _forcedLigCursorY
    const sThick = CELL_H * 0.20
    const midX = (x0 + x1) / 2
    const midY = (y0 + y1) / 2
    const bowAmt = Math.max(BP_W * 0.5, Math.abs(y1 - y0) * 0.10)
    // Arc
    ctx.save()
    ctx.strokeStyle = CLR_FORCED_LIG_ARC
    ctx.lineWidth   = sThick * 1.5
    ctx.lineCap     = 'round'
    ctx.setLineDash([4 / _zoom, 4 / _zoom])
    ctx.beginPath()
    ctx.moveTo(x0, y0)
    ctx.quadraticCurveTo(midX + bowAmt, midY, x1, y1)
    ctx.stroke()
    ctx.setLineDash([])
    // 3' anchor dot (red)
    ctx.fillStyle = CLR_FORCED_LIG_ANCHOR
    ctx.beginPath()
    ctx.arc(x0, y0, 3 / _zoom, 0, Math.PI * 2)
    ctx.fill()
    // Cursor dot (green when hovering a valid 5' target, purple otherwise)
    const hoverHit = _forcedLigHoverTarget
    ctx.fillStyle = hoverHit ? CLR_FORCED_LIG_TARGET : CLR_FORCED_LIG_ARC
    ctx.beginPath()
    ctx.arc(x1, y1, 3 / _zoom, 0, Math.PI * 2)
    ctx.fill()
    // Highlight the hovered 5' end cell in green
    if (hoverHit) {
      const info = _rowMap.get(hoverHit.dom.helix_id)
      if (info) {
        const isFwd = hoverHit.dom.direction === 'FORWARD'
        const cy = isFwd ? info.fwdY : info.revY
        const lo = Math.min(hoverHit.dom.start_bp, hoverHit.dom.end_bp)
        const hi = Math.max(hoverHit.dom.start_bp, hoverHit.dom.end_bp)
        const fivePrimeBp = isFwd ? lo : hi
        ctx.fillStyle = 'rgba(30, 160, 60, 0.40)'
        ctx.fillRect(_bpToX(fivePrimeBp), cy - CELL_H / 2, BP_W, CELL_H)
      }
    }
    ctx.restore()
  }

  // Cached hover target for forced ligation — updated in pointermove
  let _forcedLigHoverTarget = null   // { strand, dom } or null

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
      ctx.fillText(info.label ?? info.idx, cx, screenY)
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
    const baseMajor = isHC ? 7 : 8
    const bpL    = Math.floor(_xToBp(wLeft))
    const bpR    = Math.ceil(_xToBp(wRight))

    ctx.save()
    // Clip labels to the content region (right of frozen gutter, inside ruler height).
    ctx.beginPath(); ctx.rect(GUTTER, 0, W - GUTTER, RULER_H); ctx.clip()

    ctx.fillStyle = CLR_RULER_TEXT
    ctx.font = '9px Courier New, monospace'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'

    // Adaptive label spacing: when zoomed out, the natural 7/8-bp grid puts
    // labels too close together to read. Pick the smallest k×baseMajor (k a
    // power of 2) that keeps adjacent labels at least maxLabelW + GAP apart.
    // 9px Courier monospace → digits ≈ 5.4 px wide; pad for the largest bp
    // that will appear in the visible window.
    const DIGIT_W   = 5.4
    const LABEL_GAP = 6
    const maxBpAbs  = Math.max(Math.abs(bpL), Math.abs(bpR), 1)
    const digits    = Math.ceil(Math.log10(maxBpAbs + 1)) + (bpL < 0 ? 1 : 0)
    const minPxStep = digits * DIGIT_W + LABEL_GAP
    const stepPx    = baseMajor * BP_W * _zoom
    let kPow = 1
    while (stepPx * kPow < minPxStep) kPow *= 2
    const major = baseMajor * kPow

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

  // World-space drawing helpers in the order the main draw uses them.
  // Extracted so `_draw` and `_drawToCanvas` (lens render) can share it.
  function _drawWorldContent() {
    _drawAllTracks()
    _drawUndefinedBases()
    _drawCrossoverIndicators()
    _drawAllDomains()
    _drawExtensions()
    _drawCoaxialArcs()
    _drawCrossoverArcs()
    _drawSequences()
    _drawLoopSkips()
    _drawOverhangNames()
  }

  function _draw() {
    _components = _buildComponents()   // rebuild once per frame
    _rebuildStrandSelection()          // rebuild strand glow set
    _rebuildHeatmapCache()             // rebuild heat map colours
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
    _drawWorldContent()
    _drawEndDragGhost()
    _drawDomainDragGhost()
    _drawXoverDragGhost()
    _drawNickHover()
    _drawPencilGhost()
    _drawForcedLigationArc()
    _drawSliceBar()
    _drawLasso()
    _drawSpriteDebug()     // magenta hit-radius circles when D key is held
    // ── Frozen screen-space overlays (drawn on top of scrolling content) ───────
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    _drawGutter()          // frozen left panel
    _drawRuler()           // frozen top ruler (painted after gutter to cover corner)
    _drawHeatmapLegend()   // heat map legend (right-centre)
    _drawDebug()
  }

  // Render the world content to a different canvas at a different
  // transform — used by the zoom-scope lens for a sharp native-resolution
  // re-render. Skips screen-space chrome (gutter, ruler, debug) and
  // cursor-driven overlays (ghosts, lasso, hovers) that don't apply to
  // the lens. Restores ctx + transform state on return so the main view
  // is unaffected.
  function _drawToCanvas(targetCanvas, lensZoom, lensPanX, lensPanY) {
    if (!_design?.helices?.length) {
      const tctx = targetCanvas.getContext('2d')
      tctx.setTransform(1, 0, 0, 1, 0, 0)
      tctx.fillStyle = CLR_BG
      tctx.fillRect(0, 0, targetCanvas.width, targetCanvas.height)
      return
    }
    const savedCtx  = ctx
    const savedZoom = _zoom
    const savedPanX = _panX
    const savedPanY = _panY
    try {
      _components = _buildComponents()
      _rebuildStrandSelection()
      _rebuildHeatmapCache()
      ctx   = targetCanvas.getContext('2d')
      _zoom = lensZoom
      _panX = lensPanX
      _panY = lensPanY
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.fillStyle = CLR_BG
      ctx.fillRect(0, 0, targetCanvas.width, targetCanvas.height)
      ctx.setTransform(_zoom, 0, 0, _zoom, _panX, _panY)
      _drawWorldContent()
      _drawForcedLigationArc()   // pencil ghost — harmless when inactive
    } finally {
      ctx   = savedCtx
      _zoom = savedZoom
      _panX = savedPanX
      _panY = savedPanY
    }
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

    // ── Select tool: crossover arc drag (move existing crossover) ─────────────
    if (_activeTool === 'select') {
      const arcHit = _hitTestArc(wx, wy)
      if (arcHit?.xo) {
        const xo = arcHit.xo
        const infoA = _rowMap.get(xo.half_a.helix_id)
        const isScaf = infoA?.scaffoldFwd
          ? xo.half_a.strand === 'FORWARD'
          : xo.half_a.strand === 'REVERSE'
        const origBow = _xoverBowDir(xo.half_a.index, isScaf)
        const doms = _findXoverDomains(xo)
        if (!doms) { /* can't drag */ }
        else {
          // Build drag group from all selected crossovers (including the clicked one)
          const clickedKey = _xoverKey(xo)
          const group = []
          // Gather selected xover keys
          const selXoKeys = new Set()
          for (const k of _selectedElements) { if (k.startsWith('xo:')) selXoKeys.add(k) }
          // If the clicked crossover is already selected, drag all selected crossovers
          // Otherwise, just drag the clicked one (and select it)
          const dragAll = selXoKeys.has(clickedKey) && selXoKeys.size > 1
          const xoversToDrag = []
          if (dragAll) {
            for (const dxo of (_design?.crossovers ?? [])) {
              if (selXoKeys.has(_xoverKey(dxo))) xoversToDrag.push(dxo)
            }
          } else {
            xoversToDrag.push(xo)
          }
          // Build per-crossover info and compute valid deltas (intersection)
          let validDeltaSets = null
          let allDomsOk = true
          for (const gxo of xoversToDrag) {
            const gInfoA = _rowMap.get(gxo.half_a.helix_id)
            const gIsScaf = gInfoA?.scaffoldFwd
              ? gxo.half_a.strand === 'FORWARD'
              : gxo.half_a.strand === 'REVERSE'
            const gOrigBow = _xoverBowDir(gxo.half_a.index, gIsScaf)
            const gDoms = _findXoverDomains(gxo)
            if (!gDoms) { allDomsOk = false; break }
            const limits = _computeXoverDragLimits(gxo)
            const validBps = _getValidXoverBps(gxo, limits.minBp, limits.maxBp, gOrigBow, gIsScaf)
            const gOrigIdx = gxo.half_a.index
            const deltaSet = new Set(validBps.map(bp => bp - gOrigIdx))
            if (validDeltaSets === null) validDeltaSets = deltaSet
            else {
              // Intersect
              for (const d of validDeltaSets) { if (!deltaSet.has(d)) validDeltaSets.delete(d) }
            }
            group.push({ xo: gxo, origIdx: gOrigIdx, d0: gDoms.d0, d1: gDoms.d1, isScaf: gIsScaf, origBow: gOrigBow })
          }
          const validDeltas = allDomsOk && validDeltaSets ? [...validDeltaSets].sort((a, b) => a - b) : []
          if (validDeltas.length > 0) {
            _xoverDragXover    = xo
            _xoverDragOrigIdx  = xo.half_a.index
            _xoverDragSnapBp   = null
            _xoverDragCursorBp = null
            _xoverDragValidDeltas = validDeltas
            _xoverDragStartWX  = wx
            _xoverDragOrigBow  = origBow
            _xoverDragIsScaf   = isScaf
            _xoverDragD0       = doms.d0
            _xoverDragD1       = doms.d1
            _xoverDragGroup    = group
            _xoverDragActive   = true
            // Select the crossover arc(s)
            if (!dragAll) {
              if (!(e.ctrlKey || e.metaKey)) _selectedElements = new Set([clickedKey])
              else _selectedElements.add(clickedKey)
            }
            canvasEl.style.cursor = 'grabbing'
            canvasEl.setPointerCapture(e.pointerId)
            _draw(); _notifySelectionChange(); e.preventDefault(); return
          }
        }
      }
    }

    // ── Select tool: domain-body drag (move whole domain by N bp) ─────────────
    if (_activeTool === 'select') {
      const hit = _hitTest(e.offsetX, e.offsetY, _selectFilter)
      if (hit?.elementType === 'line') {
        const lineKey = _hitElementKey(hit)
        const wasSelected = _selectedElements.has(lineKey)
        if (!wasSelected) {
          if (!(e.ctrlKey || e.metaKey)) _selectedElements = new Set([lineKey])
          else _selectedElements.add(lineKey)
        }
        const entries = _resolveDomainDragEntries()
        if (entries.length > 0) {
          const { minDelta, maxDelta } = _computeDomainDragLimits(entries)
          if (minDelta !== 0 || maxDelta !== 0) {
            _domDragEntries  = entries
            _domDragMinDelta = minDelta
            _domDragMaxDelta = maxDelta
            _domDragDeltaBp  = 0
            _domDragStartWX  = wx
            _domDragActive   = true
            canvasEl.style.cursor = 'grabbing'
            canvasEl.setPointerCapture(e.pointerId)
            _draw()
            if (!wasSelected) _notifySelectionChange()
            e.preventDefault()
            return
          }
        }
        // Limits all-zero (e.g. crossover anchored): undo the speculative
        // selection mutation if we made one — let pointerup handle as a click.
        if (!wasSelected) _selectedElements.delete(lineKey)
      }
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

    // ── Forced ligation: second click (complete or cancel) ────────────────────
    // Click-then-click model: first click on 3' starts the arc, second click
    // on a valid 5' end completes the ligation, any other click cancels.
    if (_forcedLigActive && _activeTool === 'pencil') {
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit && hit.endWhich === '5p' && hit.strand.id !== _forcedLigStrand.id) {
        const sourceStrand = _forcedLigStrand
        _forcedLigActive      = false
        _forcedLigStrand      = null
        _forcedLigDom         = null
        _forcedLigHoverTarget = null
        _dbgLastEvent = `pencil: forced-lig 3'=${sourceStrand.id.slice(0,8)} → 5'=${hit.strand.id.slice(0,8)}`
        console.log('[FORCED LIG] complete', {
          from_3prime: sourceStrand.id.slice(0, 12),
          to_5prime:   hit.strand.id.slice(0, 12),
        })
        _draw()
        ;(async () => {
          await onForcedLigation?.(sourceStrand.id, hit.strand.id)
        })()
      } else {
        // Clicked somewhere other than a valid 5' end — cancel
        _forcedLigActive      = false
        _forcedLigStrand      = null
        _forcedLigDom         = null
        _forcedLigHoverTarget = null
        _dbgLastEvent = 'pencil: forced-lig cancelled'
        console.log('[FORCED LIG] cancelled — clicked non-5\' target')
        _draw()
      }
      return
    }

    // ── Pencil tool ─────────────────────────────────────────────────────────────
    if (_activeTool === 'pencil') {
      // Priority: if clicking on a 3' end, start forced ligation mode.
      // Forced ligation is a manual user feature only — NOT for autocrossover.
      // Click-then-click: first click activates, second click completes.
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit && hit.endWhich === '3p') {
        const info = _rowMap.get(hit.dom.helix_id)
        if (info) {
          const isFwd = hit.dom.direction === 'FORWARD'
          const trackY = isFwd ? info.fwdY : info.revY
          _forcedLigActive   = true
          _forcedLigStrand   = hit.strand
          _forcedLigDom      = hit.dom
          _forcedLigStartX   = _bpCenterX(hit.dom.end_bp)
          _forcedLigStartY   = trackY
          _forcedLigCursorX  = wx
          _forcedLigCursorY  = wy
          _forcedLigHoverTarget = null
          _dbgLastEvent = `pencil: forced-lig start 3'=${hit.strand.id.slice(0,8)}`
          console.log('[FORCED LIG] start from 3\' end', {
            strand: hit.strand.id.slice(0, 12),
            helix: hit.dom.helix_id.slice(0, 8),
            end_bp: hit.dom.end_bp,
            direction: hit.dom.direction,
          })
          _draw()
          return
        }
      }

      // Default pencil: paint scaffold/staple domain
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
    // ── Forced ligation — update arc endpoint + check 5' hover target ────────
    // Click-then-click: arc follows cursor between first click (3') and second click (5').
    if (_forcedLigActive) {
      const { wx, wy } = _c2w(e.offsetX, e.offsetY)
      _forcedLigCursorX = wx
      _forcedLigCursorY = wy
      // Check if cursor is over a 5' end (valid ligation target)
      const hit = _hitTest(e.offsetX, e.offsetY)
      if (hit && hit.endWhich === '5p' && hit.strand.id !== _forcedLigStrand.id) {
        _forcedLigHoverTarget = { strand: hit.strand, dom: hit.dom }
        canvasEl.style.cursor = 'pointer'
      } else {
        _forcedLigHoverTarget = null
        canvasEl.style.cursor = 'crosshair'
      }
      _draw(); return
    }
    if (_endDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const rawDelta = Math.round((wx - _endDragStartWX) / BP_W)
      _endDragDeltaBp = Math.max(_endDragMinDelta, Math.min(_endDragMaxDelta, rawDelta))
      if (_endDragDeltaBp !== 0) _showDragTooltip(e.clientX, e.clientY, _endDragDeltaBp)
      else _hideDragTooltip()
      _draw(); return
    }
    if (_domDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const rawDelta = Math.round((wx - _domDragStartWX) / BP_W)
      _domDragDeltaBp = Math.max(_domDragMinDelta, Math.min(_domDragMaxDelta, rawDelta))
      if (_domDragDeltaBp !== 0) _showDragTooltip(e.clientX, e.clientY, _domDragDeltaBp)
      else _hideDragTooltip()
      _draw(); return
    }
    if (_xoverDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const curBpFrac = (wx - GUTTER) / BP_W   // fractional for accurate snap distance
      // Always track cursor position (clamped to integer bp within helix bounds)
      _xoverDragCursorBp = Math.round(curBpFrac)
      // Find nearest valid delta within snap distance (delta-based for multi-xover)
      const curDelta = curBpFrac - _xoverDragOrigIdx
      let bestDelta = null, bestDist = Infinity
      for (const vd of _xoverDragValidDeltas) {
        const dist = Math.abs(vd - curDelta)
        if (dist < bestDist) { bestDist = dist; bestDelta = vd }
      }
      _xoverDragSnapBp = (bestDelta !== null && bestDist <= XOVER_SNAP_DIST)
        ? _xoverDragOrigIdx + bestDelta : null
      if (_xoverDragSnapBp != null && _xoverDragSnapBp !== _xoverDragOrigIdx) {
        const delta = _xoverDragSnapBp - _xoverDragOrigIdx
        _showDragTooltip(e.clientX, e.clientY, delta)
      } else {
        _hideDragTooltip()
      }
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
    // Track which helix the cursor is over (for scaffold sprite filtering)
    {
      const { wy } = _c2w(e.offsetX, e.offsetY)
      const prev = _hoverHelixId
      _hoverHelixId = _helixAtWY(wy)
      if (_shiftHeld && _hoverHelixId !== prev) _draw()
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
    } else if (_activeTool === 'select' && _selectFilter.xover) {
      // Grab cursor when hovering over an existing crossover arc (draggable)
      const { wx: hx, wy: hy } = _c2w(e.offsetX, e.offsetY)
      const arcH = _hitTestArc(hx, hy)
      canvasEl.style.cursor = arcH?.xo ? 'grab' : 'default'
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
        if (!info) { _nickHover = null; _draw(); return }
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
    if (_xoverDragActive && e.button === 0) {
      _xoverDragActive = false
      const snapBp = _xoverDragSnapBp
      const group  = _xoverDragGroup
      _xoverDragSnapBp = null
      _xoverDragCursorBp = null
      _xoverDragGroup = []
      _hideDragTooltip()
      _draw()
      if (snapBp != null && snapBp !== _xoverDragOrigIdx) {
        const delta = snapBp - _xoverDragOrigIdx
        if (group.length > 1) {
          // Batch move all crossovers in the group
          const moves = group.map(g => ({
            crossover_id: g.xo.id,
            new_index: g.origIdx + delta,
          }))
          console.group(`%c[XOVER BATCH MOVE] pointerup  delta=${delta}  count=${moves.length}`, 'color:lime;font-weight:bold')
          console.log('moves:', JSON.stringify(moves))
          console.groupEnd()
          onBatchMoveCrossovers?.(moves)
        } else {
          console.group(`%c[XOVER MOVE] pointerup  ${_xoverDragOrigIdx} → ${snapBp}`, 'color:lime;font-weight:bold')
          console.log('crossover:', _xoverDragXover.id)
          console.groupEnd()
          onMoveCrossover?.(_xoverDragXover.id, snapBp)
        }
      }
      return
    }
    if (_endDragActive && e.button === 0) {
      _endDragActive = false
      const delta    = _endDragDeltaBp
      _endDragDeltaBp = 0
      _hideDragTooltip()
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
    if (_domDragActive && e.button === 0) {
      _domDragActive = false
      const delta = _domDragDeltaBp
      _domDragDeltaBp = 0
      _hideDragTooltip()
      _draw()
      if (delta !== 0) {
        const apiEntries = _domDragEntries.map(en => ({
          strand_id:    en.strandId,
          domain_index: en.domainIndex,
          delta_bp:     delta,
        }))
        console.group(`%c[DOMAIN-SHIFT] pointerup  delta=${delta}`, 'color:lime;font-weight:bold')
        console.log('apiEntries:', JSON.stringify(apiEntries, null, 2))
        console.groupEnd()
        onShiftDomains?.(apiEntries)
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
            if (!strandPassesScafStapFilter(strand, _selectFilter)) continue
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
      const key    = hit ? _hitElementKey(hit)
                   : arcHit ? (arcHit.xo ? _xoverKey(arcHit.xo) : _forcedLigKey(arcHit.fl))
                   : lsKey
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
    if (_domDragActive)                { _domDragActive = false; _domDragDeltaBp = 0; _hideDragTooltip(); needDraw = true }
    if (_xoverDragActive)              { _xoverDragActive = false; _xoverDragSnapBp = null; _xoverDragCursorBp = null; _xoverDragGroup = []; _hideDragTooltip(); needDraw = true }
    if (_forcedLigActive)              { _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null; needDraw = true }
    if (_lassoStarted || _lassoActive) { _lassoStarted = false; _lassoActive = false; needDraw = true }
    if (_painting)                     { _painting = false; _paintH = null; needDraw = true }
    if (_nickHover !== null)           { _nickHover = null; _dbgDetail = []; needDraw = true }
    if (_hoverHelixId !== null)       { _hoverHelixId = null; needDraw = true }
    if (needDraw) _draw()
  })

  canvasEl.addEventListener('pointercancel', () => {
    if (_endDragActive)   { _endDragActive = false; _endDragDeltaBp = 0; _draw() }
    if (_domDragActive)   { _domDragActive = false; _domDragDeltaBp = 0; _hideDragTooltip(); _draw() }
    if (_xoverDragActive) { _xoverDragActive = false; _xoverDragSnapBp = null; _xoverDragCursorBp = null; _xoverDragGroup = []; _hideDragTooltip(); _draw() }
    if (_forcedLigActive) { _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null; _draw() }
    if (_panActive)       { _panActive = false; _draw() }
    if (_sliceDragging)   { _sliceDragging = false; _draw() }
  })

  canvasEl.addEventListener('contextmenu', (e) => {
    e.preventDefault()
    const { wx, wy } = _c2w(e.offsetX, e.offsetY)
    const arcHit = _hitTestArc(wx, wy)
    if (arcHit) {
      onCrossoverContextMenu?.({
        xo: arcHit.xo ?? null,
        fl: arcHit.fl ?? null,
        selectedXoKeys: Array.from(_selectedElements).filter(k => k.startsWith('xo:') || k.startsWith('fl:')),
        clientX: e.clientX,
        clientY: e.clientY,
      })
      return
    }
    const domHit = _hitTest(e.offsetX, e.offsetY)
    if (domHit?.dom?.overhang_id) {
      onOverhangContextMenu?.({
        overhangId: domHit.dom.overhang_id,
        strandId:   domHit.strand.id,
        clientX:    e.clientX,
        clientY:    e.clientY,
      })
    } else if (domHit?.strand) {
      onStrandContextMenu?.({ strand: domHit.strand, clientX: e.clientX, clientY: e.clientY })
    }
  })

  // ── Shift key — update nick hover ghost for ligation mode ────────────────────
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _forcedLigActive) {
      _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null
      _dbgLastEvent = 'pencil: forced-lig cancelled (Escape)'
      console.log('[FORCED LIG] cancelled via Escape')
      _draw(); return
    }
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
    /**
     * Render the world (strands, crossovers, arcs, sequences, loop/skips, etc.)
     * to *targetCanvas* at the given zoom/pan transform. Used by the
     * zoom-scope lens to produce a native-resolution magnified view rather
     * than upscaling pixels from the main canvas. Main canvas is unaffected.
     */
    drawToLens(targetCanvas, lensZoom, lensPanX, lensPanY) {
      _drawToCanvas(targetCanvas, lensZoom, lensPanX, lensPanY)
    },

    /** Current view transform — read by the zoom-scope lens to compute its centre. */
    getZoom() { return _zoom },
    getPanX() { return _panX },
    getPanY() { return _panY },

    /** Reset zoom/pan so all content fits the canvas (F-key handler). */
    fitToContent() { _fitToContent(); _draw() },

    setTool(tool) {
      _activeTool = tool
      _lassoStarted = false; _lassoActive = false
      if (_forcedLigActive) { _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null }
      if (_painting)        { _painting = false; _paintH = null }
      if (_endDragActive)   { _endDragActive = false; _endDragDeltaBp = 0; _hideDragTooltip() }
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

    setViewTools(vt) {
      _viewTools = vt
      _draw()
    },

    /** Programmatically set selected strand IDs (e.g. from 3D cross-window broadcast).
     *  Translates strand IDs to all element keys for those strands' domains and arcs.
     *  Does NOT emit onSelectionChange — caller responsible for loop prevention. */
    setSelection(strandIds) {
      _selectedElements = new Set()
      if (!strandIds?.length || !_design) { _draw(); return }
      const idSet = new Set()
      for (const sid of strandIds) {
        for (const memberId of _components.membersOf(sid)) idSet.add(memberId)
      }
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

    /** Replace the unligated-crossover marker set + redraw. Accepts Set,
     *  Array, or null. Called by main.js whenever the editor store's
     *  unligatedCrossoverIds slot changes. */
    setUnligatedCrossoverIds(ids) {
      const next = ids instanceof Set ? ids : new Set(ids ?? [])
      // Cheap reference-only no-op detection — the response always builds a
      // new Set so reference inequality also implies set inequality here.
      _unligatedCrossoverIds = next
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
