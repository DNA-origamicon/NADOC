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
// The drawing-grid geometry lives in ./pathview/layout.js because the 3D app's
// Domain Designer fork (ui/overhang_pathview.js) shares it — importing it from
// HERE dragged this whole 4977-LOC module into the main-app bundle (TD-14).
import {
  GUTTER, RULER_H, TOP_PAD, BP_W, LABEL_R,
  CELL_H, PAIR_Y, ROW_H, GROUP_GAP,
  connectedCellGroups,
} from './pathview/layout.js'

const EXTEND_BPS = 56
const MIN_ZOOM   = 0.06
const MAX_ZOOM   = 10

// ── Extension geometry (inspired by scadnano defaults) ────────────────────────
const EXT_LEN_PX    = 18                    // arm length in world-space px
const EXT_ANGLE_RAD = 145 * Math.PI / 180  // 145° — arm points back toward strand body

// ── Palette ───────────────────────────────────────────────────────────────────
// Named hex / rgba constants live in ./pathview/palette.js so this 4000-LOC
// drawing module isn't fronted by 60 lines of colour definitions.  Values are
// imported verbatim — do not change any colour without coordinated updates
// to backend/core/constants.py and frontend/src/scene/helix_renderer.js
// (canonical STAPLE_PALETTE must match across all three).
import {
  EXT_MOD_COLORS,
  EXT_MOD_NAMES,
  CLR_BG,
  CLR_TRACK,
  CLR_TICK_MINOR,
  CLR_TICK_MAJOR,
  CLR_RULER_BG,
  CLR_RULER_TEXT,
  CLR_LABEL_FWD_FILL,
  CLR_LABEL_FWD_STROKE,
  CLR_LABEL_REV_FILL,
  CLR_LABEL_REV_STROKE,
  CLR_LABEL_TEXT,
  CLR_SCAFFOLD,
  CLR_GHOST_SCAF,
  CLR_GHOST_STPL,
  CLR_SLICE_FILL,
  CLR_SLICE_EDGE,
  CLR_SLICE_NUM,
  CLR_PB_BAR,
  CLR_PB_BAR_FLASH,
  CLR_PB_HANDLE,
  CLR_PB_HANDLE_TXT,
  CLR_PB_BAND,
  CLR_PB_RULER,
  CLR_PB_GAP_OK,
  CLR_PB_GAP_BAD,
  CLR_SEL_RING,
  CLR_SEL_END,
  CLR_XOVER_FILL,
  CLR_XOVER_STROKE,
  CLR_XOVER_GLOW,
  CLR_XOVER_TEXT,
  CLR_SCAF_XOVER_FILL,
  CLR_SCAF_XOVER_STROKE,
  CLR_SCAF_XOVER_GLOW,
  CLR_SCAF_XOVER_TEXT,
  CLR_CELL_BG,
  CLR_CELL_GRID,
  STAPLE_PALETTE,
  ensureStapleColors,
  stapleColorOf,
} from './pathview/palette.js'
import {
  domainLineKey as _domainLineKey,
  domainEndKey as _domainEndKey,
  xoverKey as _xoverKey,
  forcedLigKey as _forcedLigKey,
  loopSkipKey as _loopSkipKey,
  crossoverJunctionSlots as _crossoverJunctionSlots,
  parseEndKey,
  parseLineKey,
} from './element_keys.js'
import { oneNtResizableEnd } from '../shared/strand_end_resize.js'
import { skipMapFromHelices, sequenceColumns } from './sequence_layout.js'

// Crossover indicator geometry
const XOVER_R = 4            // sprite circle radius (world-space px)

// ── Debug-log gate ────────────────────────────────────────────────────────────
// Module-local flag for verbose dev-debug console.log calls inside event
// handlers (NICK / XOVER / RESIZE / FORCED LIG / DESIGN UPDATE / sprite
// overlay).  Pattern mirrors Pass 2-A's main.js gating: flip to `true`
// while debugging, then revert before commit.  Out of scope for normal users.
const DBG = false


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
// Strand colour comes from the shared, stable resolver in palette.js (keyed on
// strand.id, not array index) so nick/ligation can't recolour untouched strands
// and the canvas always agrees with the strands spreadsheet. ensureStapleColors()
// is called once per frame in _buildComponents() before any colour is read.
const strandColor = stapleColorOf
function strandPassesScafStapFilter(strand, filter) {
  if (!filter) return true
  if (strand.strand_type === 'scaffold') return !!filter.scaf
  // Linker strands are selectable/editable on the non-scaffold side, matching
  // the 3D view where every non-scaffold strand follows the staple filter.
  return !!filter.stap
}

// (The Domain Designer fork used to import BP_W/CELL_H/PAIR_Y/GUTTER from here.
//  It now imports them from ./pathview/layout.js directly — see the import at
//  the top of this file. Don't re-add a constants re-export: it is what pulled
//  this module into the main-app bundle.)

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
  onReorderHelices,
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

  // ── Hover readout (upper-right HUD) ─────────────────────────────────────────
  // Shows "[helix label]:[bp index]" for the cell under the cursor, plus a
  // "Length: [nt]" second line while hovering over a strand. Anchored to the
  // (position:relative) path-view container so it stays put under pan/zoom.
  const _hoverReadout = document.createElement('div')
  _hoverReadout.id = 'pathview-hover-readout'
  Object.assign(_hoverReadout.style, {
    position:      'absolute',
    top:           '6px',
    right:         '8px',
    display:       'none',
    padding:       '4px 8px',
    background:    'rgba(13,17,23,0.78)',
    border:        '1px solid #30363d',
    borderRadius:  '4px',
    color:         '#c9d1d9',
    fontFamily:    'monospace',
    fontSize:      '12px',
    lineHeight:    '1.35',
    textAlign:     'right',
    whiteSpace:    'pre',
    pointerEvents: 'none',
    userSelect:    'none',
    zIndex:        '20',
  })
  containerEl.appendChild(_hoverReadout)

  function _updateHoverReadout(e) {
    const hid = _hoverHelixId
    if (hid == null) { _hoverReadout.style.display = 'none'; return }
    const info  = _rowMap.get(hid)
    const helix = _helixById.get(hid)
    if (!info || !helix) { _hoverReadout.style.display = 'none'; return }
    // REAL bp under cursor (folds the periodic-boundary mirror shift; no-op when off).
    const { wx } = _screenToRealWorld(e.offsetX, e.offsetY)
    const bp = _xToBp(wx)
    if (bp < helix.bp_start || bp >= helix.bp_start + helix.length_bp) {
      _hoverReadout.style.display = 'none'; return
    }
    let text = `${info.label ?? info.idx}[${bp}]`
    // Strand-length line — unfiltered hit so it shows over any strand type.
    const hit = _hitTest(e.offsetX, e.offsetY)
    if (hit) text += `\nLength: ${strandNtCount(hit.strand)}`
    _hoverReadout.textContent = text
    _hoverReadout.style.display = ''
  }

  function _hideHoverReadout() { _hoverReadout.style.display = 'none' }

  // ── Design state ─────────────────────────────────────────────────────────────
  let _design  = null
  let _helices = []
  // IDs of crossovers the backend left unligated to avoid circularizing a
  // strand. Painted with an amber ⚠ next to each arc. Set on every design
  // sync via setUnligatedCrossoverIds; auto-clears when topology changes
  // (backend recomputes per-response).
  let _unligatedCrossoverIds = new Set()
  let _rowMap  = new Map()   // helix.id → { fwdY, revY, scaffoldFwd, cell, idx }
  let _helixById = new Map() // helix.id → helix; rebuilt in _rebuildLayout. O(1) lookups
                             // in the hot crossover-draw loops (was O(helices) _helices.find).
  let _totalBp = 0   // max bp end across all helices
  let _minBp   = 0   // min bp_start across all helices (may be negative)
  let _fitDone = false
  let _nativeOrientation = true   // cadnano native: helix order top-to-bottom as-is
  let _layoutRevision = 0

  // ── Selection state ───────────────────────────────────────────────────────────
  // Each element (domain body, individual end cap, crossover arc) is selected
  // independently. Selection is editor-local — no outgoing 3D broadcast.
  //
  // Key formats:
  //   line:{helix_id}_{lo}_{hi}_{direction}   — domain body segment
  //   end:{helix_id}_{bp}_{direction}          — individual 5′ or 3′ end cap
  //   xo:{helix_id}_{index}_{strand}           — crossover arc (keyed on half_a)
  let _selectedElements = new Set()

  // ── Helix (gutter-circle) selection ──────────────────────────────────────────
  // Independent of _selectedElements (which tracks strand-level elements). These
  // are helix IDs selected by clicking / lasso-ing the numbered gutter circles,
  // used only by the drag-to-reorder interaction. Does NOT emit onSelectionChange.
  let _selectedHelices = new Set()

  // Element-key builders (_domainLineKey/_domainEndKey/_xoverKey/_forcedLigKey/
  // _loopSkipKey) + the negative-bp-safe parsers are imported from element_keys.js
  // (single source of truth; round-trip unit-tested). See top-of-file imports.

  /** True if the domain transition (domA→domB) matches a forced ligation record. */
  function _isForcedLigTransition(domA, domB) {
    _ensureStrandIndex()
    return _forcedLigTransitionKeys.has(_forcedLigTransitionKey(
      domA.helix_id, domA.end_bp, domA.direction,
      domB.helix_id, domB.start_bp, domB.direction))
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
  // True once a right/middle-button pan moves past DRAG_THRESHOLD. Right-button
  // pans end with a native `contextmenu` event; this flag lets that handler tell
  // a real right-click (show menu) from the tail of a pan drag (swallow it).
  let _rightDragMoved = false

  // ── Slice bar ─────────────────────────────────────────────────────────────────
  let _sliceBp       = 0
  let _sliceDragging = false

  // ── Periodic boundary (polymerization seam view) ───────────────────────────────
  // Mirrors the active design beyond two sliders so the far end can be viewed/edited
  // beside the near end. Pure 2D-editor view state — see project_periodic_boundary.
  let _pbActive       = false   // mirrors viewTools.periodicBoundary; cached for hot paths
  let _pbNearBp       = 0       // near slider bp (reads red P)
  let _pbFarBp        = 0       // far slider bp  (reads red 0)
  let _pbNearDragging = false
  let _pbFarDragging  = false
  let _pbInit         = false   // false until slider defaults are set for the current design
  let _pbLastExt      = null    // last-seen active-strand extent {lo,hi}; auto-shift fires only
                                // when an EDIT grows it past a slider, so a manually-placed slider
                                // inside the structure (puzzle-fit seam) doesn't reset on refresh
  let _pbFlashUntil   = 0       // performance.now() until which an auto-shifted bar pulses
  let _ghostPass      = 0       // 0 = real pass | +1 = right mirror (+P) | -1 = left mirror (-P)
  let _ghostShiftBp   = 0       // bp shift captured at pointerdown so a drag stays consistent across the seam

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
  let _forcedLigStartShift = 0      // periodic-boundary mirror shift at the 3' click (seam detection)

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

  // ── Gutter lasso (screen-space vertical rubber-band over the helix circles) ──
  let _gutterLassoStarted = false
  let _gutterLassoActive  = false
  let _gutterLassoCtrl    = false   // ctrl/meta held at start (additive)
  let _gutterLassoSY0     = 0       // screen-Y at start
  let _gutterLassoSY1     = 0       // current screen-Y

  // ── Helix drag-to-reorder (drag selected gutter circles to a new position) ───
  let _helixDragArmed     = false   // pointerdown on a selected circle, below threshold
  let _helixDragActive    = false   // past DRAG_THRESHOLD — drawing ghost + arrow
  let _helixDragStartSX   = 0
  let _helixDragStartSY   = 0
  let _helixDragCursorSY  = 0       // current cursor screen-Y (ghost follows)
  let _helixDragInsertIdx = 0       // gap index in display order (0.._helices.length)

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

  // ── Periodic-boundary helpers ──────────────────────────────────────────────────
  /** Period (bp) between the two sliders. Always derived live, never stored. */
  function _pbPeriod() { return _pbFarBp - _pbNearBp }
  /** Whether the mirror should render/respond (active + valid period + has helices). */
  function _pbOn() { return _pbActive && _pbPeriod() >= 1 && _helices.length > 0 }

  /** True when forced ligation `fl` should route THROUGH the periodic boundary: PB on,
   *  flagged is_periodic_seam, and the wrapped routing is shorter (endpoints more than
   *  half a period apart). DRAW (_drawCrossoverArcs) and HIT-TEST (_hitTestArc) both gate
   *  on this + _pbSeamFLArcs so the dashed arcs are clickable where they're drawn. */
  function _pbSeamFLThroughBoundary(fl) {
    return _pbOn() && !!fl.is_periodic_seam &&
           Math.abs(fl.three_prime_bp - fl.five_prime_bp) > _pbPeriod() / 2
  }

  /** The two seam-crossing arc segments for a through-boundary forced ligation: 3'→(5'
   *  image one period nearer) across one seam, and 5'→(3' image one period nearer) across
   *  the other. Each {x0,y0,cx,cy,x1,y1} is a bowed quadratic in world coords. */
  function _pbSeamFLArcs(fl, xA, yA, xB, yB) {
    const dx = (Math.sign(fl.five_prime_bp - fl.three_prime_bp) || 1) * _pbPeriod() * BP_W
    const seg = (x0, y0, x1, y1) => {
      const bAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      return { x0, y0, x1, y1, cx: (x0 + x1) / 2 + bAmt, cy: (y0 + y1) / 2 }
    }
    return [seg(xA, yA, xB - dx, yB), seg(xB, yB, xA + dx, yA)]
  }

  /** True when periodic-seam FL `fl` should render as TWO short fading stubs instead
   *  of the long straight arc across the structure. Triggers when the periodic boundary
   *  is OFF but the FL was flagged as a polymerization seam — the long connector across
   *  the part isn't meaningful in that mode (user choice). DRAW + HIT-TEST + LASSO all
   *  gate on this via _pbSeamFLStubs so the stubs are clickable where they're drawn. */
  function _pbSeamFLAsStubs(fl) {
    return !_pbOn() && !!fl.is_periodic_seam
  }

  /** The two short stub segments for a periodic-seam FL drawn in fading-stub mode.
   *  Each stub leaves its endpoint outward along x (away from the other endpoint),
   *  STUB_LEN world units long, at the same y as the endpoint. Returned in the same
   *  {x0,y0,cx,cy,x1,y1} shape as the arc segments — cx,cy is the midpoint so the
   *  quadratic collapses to the straight stub, letting hit-test reuse the Bezier code. */
  function _pbSeamFLStubs(fl, xA, yA, xB, yB) {
    const STUB_LEN = BP_W * 5
    const dirA = (Math.sign(fl.three_prime_bp - fl.five_prime_bp) || 1)
    const stub = (x0, y0, dir) => {
      const x1 = x0 + dir * STUB_LEN
      return { x0, y0, x1, y1: y0, cx: (x0 + x1) / 2, cy: y0 }
    }
    return [stub(xA, yA, dirA), stub(xB, yB, -dirA)]
  }

  /** {lo,hi} bp extent over ACTIVE (non-reference) strand domains, or null.
   *  Used for slider defaults + auto-shift. Excludes is_reference ALWAYS — distinct
   *  from _totalBp/_minBp which are helix-based and include reference strands. */
  function _activeStrandExtent() {
    let lo = Infinity, hi = -Infinity
    for (const s of (_design?.strands ?? [])) {
      if (s.is_reference) continue
      for (const d of s.domains) {
        const a = Math.min(d.start_bp, d.end_bp)
        const b = Math.max(d.start_bp, d.end_bp)
        if (a < lo) lo = a
        if (b > hi) hi = b
      }
    }
    return isFinite(lo) ? { lo, hi } : null
  }

  /** Set of helix IDs carrying ONLY reference strands (≥1 reference domain, 0
   *  active). Mirrors backend Design.reference_helix_ids(). Used to treat a
   *  helix's loop/skip markers as reference geometry (a mixed helix is NOT
   *  reference — its loop/skips affect the active strand too). */
  function _referenceOnlyHelixIds() {
    const ref = new Set(), active = new Set()
    for (const s of (_design?.strands ?? [])) {
      const target = s.is_reference ? ref : active
      for (const d of s.domains) target.add(d.helix_id)
    }
    for (const hid of active) ref.delete(hid)
    return ref
  }

  /** bp shift to add to a mirrored display position to reach the REAL bp:
   *  real_bp = display_bp - shift. +P in the right zone (shows near end),
   *  -P in the left zone (shows far end), 0 in the body / when off. */
  function _ghostShiftForWorldX(wx) {
    if (!_pbOn()) return 0
    const bp = _xToBp(wx)
    if (bp >= _pbFarBp)  return  _pbPeriod()
    if (bp <  _pbNearBp) return -_pbPeriod()
    return 0
  }

  /** Screen → REAL world coords for hit-testing/commit resolution. Folds the mirror
   *  shift so a cursor in a ghost zone resolves to the real strand. `shift` is
   *  returned so drag previews can render back at the mirror (display) location. */
  function _screenToRealWorld(cx, cy) {
    const { wx, wy } = _c2w(cx, cy)
    const shift = _ghostShiftForWorldX(wx)
    return { wx: wx - shift * BP_W, wy, shift }
  }

  /** Place the sliders at the active-strand extent. Does NOT move the camera: toggling
   *  the periodic boundary on/off preserves the user's current pan/zoom, so a zoomed-in
   *  area of interest stays put (the mirror simply appears beyond the sliders — pan to it
   *  if it's off-screen). Idempotent via _pbInit. */
  function _pbInitDefaults() {
    if (_pbInit) return
    const ext = _activeStrandExtent()
    if (!ext) return            // no active strands → leave _pbInit false; _pbOn() stays false
    // Domains occupy cells [lo..hi] inclusive (right edge = _bpToX(hi+1)); the far
    // slider sits at the boundary just past the last cell so P = cell count.
    _pbNearBp = ext.lo
    _pbFarBp  = ext.hi + 1
    _pbLastExt = ext            // baseline for auto-shift's "extent grew" check
    _pbInit   = true
  }

  /** Pulse the sliders briefly (e.g. after an auto-shift) so the jump isn't jarring. */
  function _pbFlash() { _pbFlashUntil = performance.now() + 700 }

  // ── Gutter-circle helpers (screen-space — the gutter is the frozen x<GUTTER strip)

  /** Screen-Y of a helix's gutter circle centre (matches _drawGutter). */
  function _gutterCircleSY(info) {
    return ((info.fwdY + info.revY) / 2) * _zoom + _panY
  }

  /** Helix ID whose gutter circle contains screen point (sx, sy), or null. */
  function _helixAtGutter(sx, sy) {
    if (sx > GUTTER || sy < RULER_H) return null
    for (const [hid, info] of _rowMap) {
      if (Math.hypot(sx - GUTTER / 2, sy - _gutterCircleSY(info)) <= LABEL_R) return hid
    }
    return null
  }

  /** Insertion gap index for a cursor screen-Y, in DISPLAY order (0.._helices.length).
   *  = the number of helix rows whose circle centre sits above the cursor. */
  function _gapIndexFromScreenY(sy) {
    let idx = 0
    for (const [, info] of _rowMap) {
      if (sy > _gutterCircleSY(info)) idx++
    }
    return idx
  }

  /** Compute the new helix-id order (in DESIGN-array order) after dropping the
   *  selected gutter circles as one contiguous block at display gap `gapIdx`.
   *  Returns null for a no-op (empty selection or dropped onto itself). */
  function _computeReorderedHelixIds(gapIdx) {
    const display = [..._rowMap.keys()]                      // display (post-reverse) order
    const sel  = display.filter(id => _selectedHelices.has(id))
    if (sel.length === 0) return null
    const rest = display.filter(id => !_selectedHelices.has(id))
    // Translate the display gap into an index within `rest` (count unselected rows above).
    let insertAt = 0
    for (let i = 0; i < gapIdx; i++) if (!_selectedHelices.has(display[i])) insertAt++
    const newDisplay = [...rest.slice(0, insertAt), ...sel, ...rest.slice(insertAt)]
    if (newDisplay.every((id, i) => id === display[i])) return null   // dropped onto itself
    // _rowMap/display is post-reverse; design.helices is native (pre-reverse) order.
    return _nativeOrientation ? newDisplay : [...newDisplay].reverse()
  }

  // ── Slice position helper ─────────────────────────────────────────────────────
  function _updateSliceBp(bp) {
    _sliceBp = bp
    onSliceChange?.(bp)
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  function _rebuildLayout() {
    _layoutRevision++
    _helices = sortedHelices(_design)
    // Stable label index per helix — based on native (top-to-bottom) order so that
    // gutter labels reflect the helix's identity, not its current display position.
    const nativeIdx = new Map(_helices.map((h, i) => [h.id, i]))
    // When not in native (cadnano) orientation, reverse the vertical helix order
    // so that the pathview matches the slice view's Y-up arrangement.
    if (!_nativeOrientation) _helices.reverse()
    _rowMap  = new Map()
    _helixById = new Map(_helices.map(h => [h.id, h]))   // O(1) id→helix for hot draw loops
    const isHC = _design?.lattice_type === 'HONEYCOMB'

    // Compute cells for each helix
    const cells = _helices.map(h => helixCell(h, isHC))

    const groupOf = connectedCellGroups(cells)

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
    // Leftmost world edge of all content: the gutter (world 0) OR — when helices
    // start at negative bp — the negative cells, which _bpToX draws LEFT of the
    // gutter at _bpToX(bp0) < 0.  _bpToX applies no bp0 shift, so the fit must
    // offset panX by worldLeft; otherwise negative-bp cells render off the left
    // edge and become unclickable (e.g. scaffold stubs living entirely in bp < 0
    // could not be erased in the 2D editor).
    const bp0        = Math.min(0, _minBp)
    const worldLeft  = Math.min(0, _bpToX(bp0))
    const worldRight = _bpToX(_totalBp + EXTEND_BPS)
    const cW         = worldRight - worldLeft
    // Use actual bottom of last row (accounts for group gaps)
    const lastInfo = _rowMap.get(_helices[_helices.length - 1].id)
    const cH = (lastInfo ? lastInfo.revY + CELL_H / 2 : RULER_H + TOP_PAD) + 20
    _zoom = Math.max(MIN_ZOOM, Math.min(1, W / cW, H / cH))
    const leftMargin = Math.max(0, (W - cW * _zoom) / 2)
    _panX = leftMargin - worldLeft * _zoom
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
    // _screenToRealWorld folds the periodic-boundary mirror shift so a cursor in a
    // mirror zone resolves to the REAL strand (no-op when the boundary is off).
    const { wx, wy } = _screenToRealWorld(cx, cy)
    const HIT = PAIR_Y / 2
    for (const [hid, info] of _rowMap) {
      const dF = Math.abs(wy - info.fwdY)
      const dR = Math.abs(wy - info.revY)
      if (dF > HIT && dR > HIT) continue
      const isFwdTrack = dF <= dR
      const bp = _xToBp(wx)
      _ensureStrandIndex()
      const direction = isFwdTrack ? 'FORWARD' : 'REVERSE'
      for (const entry of _strandIndexMap.get(`${hid}_${direction}`) ?? []) {
          const { lo, hi, si, di, dom } = entry
          if (bp < lo || bp > hi) continue
          const strand = _design.strands[si]
          const isEnd = (bp === lo || bp === hi)
          if (filter) {
            if (!strandPassesScafStapFilter(strand, filter)) return null
            if ( isEnd && !filter.ends) return null
            if (!isEnd && !filter.line) return null
          }
          const elementType = isEnd ? 'end' : 'line'
          const isFwd = dom.direction === 'FORWARD'
          let endWhich = null
          if (isEnd) {
            if (strand.domains.length === 1 && lo === hi) {
              // 1-nt strand: the bead is BOTH 5′ and 3′ → pick the end that can
              // actually be resized (free extension side), so a stub pinned by a
              // crossover on one side stays resizable on the other.
              endWhich = oneNtResizableEnd(
                { helix_id: dom.helix_id, direction: dom.direction, bp_index: bp, strand_id: strand.id },
                _design.strands,
              )
            } else {
              endWhich = (isFwd && bp === lo) || (!isFwd && bp === hi) ? '5p' : '3p'
            }
          }
          return { strand, strandIdx: si, dom, domainIdx: di, elementType, endWhich }
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
  function _lassoDomainEntries(lx0, lx1, ly0, ly1) {
    _ensureStrandIndex()
    const hits = []
    for (const [helixId, info] of _rowMap) {
      for (const [direction, y] of [['FORWARD', info.fwdY], ['REVERSE', info.revY]]) {
        if (y + CELL_H / 2 <= ly0 || y - CELL_H / 2 >= ly1) continue
        for (const entry of _strandIndexMap.get(`${helixId}_${direction}`) ?? []) {
          if (_bpToX(entry.hi + 1) <= lx0 || _bpToX(entry.lo) >= lx1) continue
          hits.push(entry)
        }
      }
    }
    return hits
  }

  function _hitTestLassoElements() {
    const result = new Set()
    const lx0 = Math.min(_lassoWX0, _lassoWX1), lx1 = Math.max(_lassoWX0, _lassoWX1)
    const ly0 = Math.min(_lassoWY0, _lassoWY1), ly1 = Math.max(_lassoWY0, _lassoWY1)

    for (const indexed of _lassoDomainEntries(lx0, lx1, ly0, ly1)) {
      const { strand, dom, di, lo, hi } = indexed
      if (!strandPassesScafStapFilter(strand, _selectFilter)) continue
      const doms = strand.domains
      const isFwd = dom.direction === 'FORWARD'
      const dxL  = _bpToX(lo), dxR = _bpToX(hi + 1)

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
        // Match the renderer: through-boundary routes as two seam arcs; PB-off periodic-
        // seam FLs render as two short stubs at each end (clickable along the stub line).
        const segs = _pbSeamFLAsStubs(fl)
          ? _pbSeamFLStubs(fl, xA, yA, xB, yB)
          : _pbSeamFLThroughBoundary(fl)
          ? _pbSeamFLArcs(fl, xA, yA, xB, yB)
          : [{ x0: xA, y0: yA, x1: xB, y1: yB,
               cx: (xA + xB) / 2 + Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07), cy: (yA + yB) / 2 }]
        let flHit = false
        for (const a of segs) {
          const axMin = Math.min(a.x0, a.x1, a.cx) - BP_W * 0.5
          const axMax = Math.max(a.x0, a.x1, a.cx) + BP_W * 0.5
          const ayMin = Math.min(a.y0, a.y1), ayMax = Math.max(a.y0, a.y1)
          if (!(axMax <= lx0 || axMin >= lx1 || ayMax <= ly0 || ayMin >= ly1)) { flHit = true; break }
        }
        if (flHit) result.add(_forcedLigKey(fl))
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
    for (const { strand } of _lassoDomainEntries(lx0, lx1, ly0, ly1)) {
      if (strand.strand_type === 'scaffold') continue
      result.add(strand.id)
    }
    return result
  }

  // Click tolerance for arc hit-testing — squared, in world units.
  // ~half a bp-cell width: tight enough that diagonal forced-ligation arcs
  // don't claim a huge rectangular hit-box, loose enough to forgive a small
  // miss on the actual stroked curve.
  const _ARC_HIT_TOLERANCE = BP_W * 0.5
  const _ARC_HIT_TOL_SQ    = _ARC_HIT_TOLERANCE * _ARC_HIT_TOLERANCE
  const _ARC_HIT_BUCKET_W  = BP_W * 8
  let _xoverArcHitDesign = null
  let _xoverArcHitLayoutRevision = -1
  let _xoverArcHitBins = new Map()

  function _ensureXoverArcHitIndex() {
    if (_xoverArcHitDesign === _design && _xoverArcHitLayoutRevision === _layoutRevision) return
    const bins = new Map()
    const tol = _ARC_HIT_TOLERANCE
    for (const xo of _design?.crossovers ?? []) {
      const infoA = _rowMap.get(xo.half_a.helix_id)
      const infoB = _rowMap.get(xo.half_b.helix_id)
      if (!infoA || !infoB) continue
      const isScafXo = infoA.scaffoldFwd
        ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
      const x = _bpCenterX(xo.half_a.index)
      const y0 = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1 = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
      const cx = x + _xoverBowDir(xo.half_a.index, isScafXo) *
        Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const descriptor = {
        xo, isScafXo, x, y0, y1, cx, cy: (y0 + y1) / 2,
        xMin: Math.min(x, cx) - tol, xMax: Math.max(x, cx) + tol,
        yMin: Math.min(y0, y1) - tol, yMax: Math.max(y0, y1) + tol,
      }
      const first = Math.floor(descriptor.xMin / _ARC_HIT_BUCKET_W)
      const last = Math.floor(descriptor.xMax / _ARC_HIT_BUCKET_W)
      for (let bucket = first; bucket <= last; bucket++) {
        let entries = bins.get(bucket)
        if (!entries) bins.set(bucket, entries = [])
        entries.push(descriptor)
      }
    }
    _xoverArcHitBins = bins
    _xoverArcHitDesign = _design
    _xoverArcHitLayoutRevision = _layoutRevision
  }

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
    _ensureXoverArcHitIndex()
    const bucket = Math.floor(wx / _ARC_HIT_BUCKET_W)
    for (const descriptor of _xoverArcHitBins.get(bucket) ?? []) {
      const { xo, isScafXo, x, y0, y1, cx, cy, xMin, xMax, yMin, yMax } = descriptor
      if (isScafXo && !_selectFilter.scaf) continue
      if (!isScafXo && !_selectFilter.stap) continue
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
      // Match the renderer: a seam FL routed through the boundary is two short arcs to
      // each endpoint's mirror image; with PB off + is_periodic_seam, two short stubs at
      // each end. Either case → hit-test against the segs (not the long straight arc).
      const segs = _pbSeamFLAsStubs(fl)
        ? _pbSeamFLStubs(fl, xA, yA, xB, yB)
        : _pbSeamFLThroughBoundary(fl)
        ? _pbSeamFLArcs(fl, xA, yA, xB, yB)
        : (() => { const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
                   return [{ x0: xA, y0: yA, x1: xB, y1: yB, cx: (xA + xB) / 2 + bowAmt, cy: (yA + yB) / 2 }] })()
      for (const a of segs) {
        const xMin = Math.min(a.x0, a.x1, a.cx) - tol
        const xMax = Math.max(a.x0, a.x1, a.cx) + tol
        const yMin = Math.min(a.y0, a.y1) - tol
        const yMax = Math.max(a.y0, a.y1) + tol
        if (wx < xMin || wx > xMax || wy < yMin || wy > yMax) continue
        const dSq = _quadBezierMinDistSq(wx, wy, a.x0, a.y0, a.cx, a.cy, a.x1, a.y1)
        if (dSq < bestDistSq) { bestDistSq = dSq; best = { fl } }
      }
    }

    return best
  }

  function _isNearSliceBar(screenX) {
    // Slice bar highlights the entire cell (bp square), so hit-test against its screen extent.
    const sxLeft  = _bpToX(_sliceBp)     * _zoom + _panX
    const sxRight = _bpToX(_sliceBp + 1) * _zoom + _panX
    return screenX >= sxLeft && screenX <= sxRight
  }

  /** Which periodic-boundary slider is near screen-x, or null. Grab tolerance is
   *  wider than the slice bar (the two are visually adjacent at the seam). */
  function _isNearPbSlider(screenX) {
    if (!_pbOn()) return null
    const TOL = 6
    const nearSX = _bpToX(_pbNearBp) * _zoom + _panX
    const farSX  = _bpToX(_pbFarBp)  * _zoom + _panX
    // Prefer whichever is closer when both are within tolerance.
    const dN = Math.abs(screenX - nearSX), dF = Math.abs(screenX - farSX)
    if (dN <= TOL && dN <= dF) return 'near'
    if (dF <= TOL) return 'far'
    return null
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
   * Clamp a clicked cell `col` to a valid nick bp within `dom`.
   *
   * Normally a nick can't land on the domain's own 3′ terminus (it'd leave a
   * 0-bp fragment). BUT when the strand CONTINUES collinearly past that terminus
   * — an inline overhang/duplex split: the next domain is the same helix &
   * direction, bp-adjacent, i.e. NOT a crossover (a crossover changes helix) —
   * nicking there splits the continuous strand into two real strands, so the
   * terminus is a legal nick point. (REVERSE already reaches its 3′ edge `lo`
   * via the lower clamp, so only the FORWARD upper clamp needs widening.)
   */
  function _nickBpForDomain(dom, col) {
    const lo = Math.min(dom.start_bp, dom.end_bp)
    const hi = Math.max(dom.start_bp, dom.end_bp)
    let hiClamp = hi - 1
    if (dom.direction === 'FORWARD') {
      const strand = (_design?.strands ?? []).find(s => s.domains.some(d =>
        d.helix_id === dom.helix_id && d.direction === dom.direction &&
        Math.min(d.start_bp, d.end_bp) === lo && Math.max(d.start_bp, d.end_bp) === hi))
      const di = strand ? strand.domains.findIndex(d =>
        d.helix_id === dom.helix_id && d.direction === dom.direction &&
        Math.min(d.start_bp, d.end_bp) === lo && Math.max(d.start_bp, d.end_bp) === hi) : -1
      const nxt = di >= 0 ? strand.domains[di + 1] : null
      if (nxt && nxt.helix_id === dom.helix_id && nxt.direction === 'FORWARD' &&
          Math.min(nxt.start_bp, nxt.end_bp) === hi + 1) {
        hiClamp = hi
      }
    }
    return Math.max(lo, Math.min(hiClamp, col))
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

  // Design-keyed index for _findStrandIdxAt. Without it, that fn is
  // O(strands × domains) and is called ~2× per crossover per frame — ~1M
  // iterations/frame on a large design (1252 crossovers), the dominant cost of
  // a post-mutation re-render. The index buckets domains by `${helix}_${dir}`
  // so a lookup scans only the handful of domains on that track. Rebuilt only
  // when `_design` changes (reference identity), so pan/zoom redraws reuse it.
  let _strandIndexMap = null      // Map: `${helixId}_${direction}` → [{lo, hi, si, di, dom}]
  let _strandIndexDesign = null   // the _design the index was built for
  let _strandById = new Map()
  let _extensionHostEntries = []
  let _forcedLigTransitionKeys = new Set()
  let _endEntryByKey = null
  let _lineEntryByKey = null
  let _xoverPositionsByTrack = null
  let _dragIndexDesign = null

  const _forcedLigTransitionKey = (aHelix, aBp, aDir, bHelix, bBp, bDir) =>
    `${aHelix}\0${aBp}\0${aDir}\0${bHelix}\0${bBp}\0${bDir}`

  function _ensureStrandIndex() {
    if (_strandIndexDesign === _design && _strandIndexMap) return
    const m = new Map()
    const strands = _design?.strands ?? []
    const strandById = new Map()
    const strandIndexById = new Map()
    for (let si = 0; si < strands.length; si++) {
      const strand = strands[si]
      strandById.set(strand.id, strand)
      strandIndexById.set(strand.id, si)
      for (let di = 0; di < strands[si].domains.length; di++) {
        const dom = strands[si].domains[di]
        const key = `${dom.helix_id}_${dom.direction}`
        let arr = m.get(key)
        if (!arr) m.set(key, arr = [])
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const entry = { lo, hi, si, di, dom, strand }
        arr.push(entry) // input order preserves the legacy first match
      }
    }
    const forcedLigTransitionKeys = new Set()
    for (const fl of _design?.forced_ligations ?? []) {
      forcedLigTransitionKeys.add(_forcedLigTransitionKey(
        fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction,
        fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction))
    }
    _strandIndexMap = m
    _strandById = strandById
    _extensionHostEntries = (_design?.extensions ?? []).flatMap(ext => {
      const strand = strandById.get(ext.strand_id)
      if (!strand) return []
      return [{ ext, strand, idx: strandIndexById.get(ext.strand_id) }]
    })
    _forcedLigTransitionKeys = forcedLigTransitionKeys
    _dragIndexDesign = null
    _endEntryByKey = null
    _lineEntryByKey = null
    _xoverPositionsByTrack = null
    _strandIndexDesign = _design
  }

  function _ensureDragIndex() {
    _ensureStrandIndex()
    if (_dragIndexDesign === _design) return
    const endEntryByKey = new Map()
    const lineEntryByKey = new Map()
    for (const entries of _strandIndexMap.values()) for (const entry of entries) {
      const lineKey = _domainLineKey(entry.dom)
      if (!lineEntryByKey.has(lineKey)) lineEntryByKey.set(lineKey, entry)
      for (const end of ['5p', '3p']) {
        const endKey = _domainEndKey(entry.dom, end)
        if (!endEntryByKey.has(endKey)) endEntryByKey.set(endKey, entry)
      }
    }
    const xoverPositionsByTrack = new Map()
    for (const xo of _design?.crossovers ?? []) for (const half of [xo.half_a, xo.half_b]) {
      const key = `${half.helix_id}_${half.strand}`
      let positions = xoverPositionsByTrack.get(key)
      if (!positions) xoverPositionsByTrack.set(key, positions = new Set())
      positions.add(half.index)
    }
    _endEntryByKey = endEntryByKey
    _lineEntryByKey = lineEntryByKey
    _xoverPositionsByTrack = xoverPositionsByTrack
    _dragIndexDesign = _design
  }

  function _findStrandIdxAt(helixId, bp, direction) {
    if (!_design?.strands) return -1
    _ensureStrandIndex()
    const arr = _strandIndexMap.get(`${helixId}_${direction}`)
    if (!arr) return -1
    for (let i = 0; i < arr.length; i++) {
      const e = arr[i]
      if (e.lo <= bp && bp <= e.hi) return e.si
    }
    return -1
  }

  // Build per-frame helpers: colorOf (direct strand color) and isXoverSlot
  // (suppresses end caps at crossover boundaries).  No union-find needed —
  // crossover ligation is done server-side, so each strand IS the complete oligo.
  function _buildComponents() {
    const strands = _design?.strands ?? []
    ensureStapleColors(_design)   // pin each staple's colour by id so edits don't reshuffle the palette
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
      colorOf:     (si) => strandColor(strands[si]),
      // ss overhang linkers are stored as two complement strands plus one
      // connection record. Expand either side to both sides so clicking one
      // linker domain highlights the whole logical linker in cadnano and 3D.
      membersOf:   (strandId) => new Set(linkerMembers.get(strandId) ?? [strandId]),
      isXoverSlot: (hid, bp, dir) => xoverSlots.has(`${hid}_${bp}_${dir}`),
    }
  }

  // Result of _buildComponents(). It depends ONLY on _design, so cache it keyed
  // on design identity and rebuild only when _design changes — pan/zoom redraws
  // (and the double-draw on a design change) reuse it instead of rebuilding the
  // 2504-entry crossover-slot set + re-pinning staple colours every frame.
  let _components = { colorOf: (si) => strandColor((_design?.strands ?? [])[si]), membersOf: () => new Set(), isXoverSlot: () => false }
  let _componentsDesign = null

  function _ensureComponents() {
    if (_componentsDesign !== _design) {
      _components = _buildComponents()
      _componentsDesign = _design
    }
    return _components
  }

  // ── View tools state ──────────────────────────────────────────────────────
  let _viewTools = { lengthHeatmap: false, overhangNames: false, grid: true, loopSkips: true }

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
  let _heatmapCacheDesign = null
  let _preparedHeatmapCache = new Map()
  function _rebuildHeatmapCache() {
    if (!_viewTools.lengthHeatmap || !_design?.strands) {
      _heatmapCache = new Map()
      return
    }
    if (_heatmapCacheDesign !== _design) {
      const prepared = new Map()
      for (let si = 0; si < _design.strands.length; si++) {
        const strand = _design.strands[si]
        if (strand.strand_type === 'scaffold') continue
        const nt = strandNtCount(strand)
        prepared.set(si, { color: _lengthHeatmapColor(nt), thickMul: _lengthHeatmapThickMul(nt) })
      }
      _preparedHeatmapCache = prepared
      _heatmapCacheDesign = _design
    }
    _heatmapCache = _preparedHeatmapCache
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

  // Sequence columns, loop/skip compression, and overhang fallbacks depend only
  // on the immutable design snapshot. Both sequence letters and undefined-base
  // highlighting consume the same walk, so cache it once instead of rebuilding
  // thousands of column records on every pan/zoom/drag redraw.
  let _sequenceRenderCacheDesign = null
  let _sequenceRenderCache = null
  function _ensureSequenceRenderCache() {
    if (_sequenceRenderCacheDesign === _design && _sequenceRenderCache) return _sequenceRenderCache
    const ovhMap = _overhangSeqMap()
    const skipMap = skipMapFromHelices(_design?.helices ?? [])
    const rows = (_design?.strands ?? []).map(strand => ({
      strand,
      columns: [...sequenceColumns(strand, skipMap)],
      hasSequence: !!strand.sequence || strand.domains.some(
        d => d.overhang_id && ovhMap.has(d.overhang_id)),
    }))
    _sequenceRenderCacheDesign = _design
    _sequenceRenderCache = { ovhMap, rows }
    return _sequenceRenderCache
  }

  // Resolve the sequence character for a column emitted by `sequenceColumns`.
  // `seqIndex` is the skip/loop-compressed index into strand.sequence; `domCol` is the
  // present-column index within the domain (used only for overhang strands, whose own
  // sequence is indexed per-domain).  Checks strand.sequence first, then the overhang.
  function _seqCharAt(strand, seqIndex, domCol, dom, ovhMap) {
    if (strand.sequence) {
      const ch = strand.sequence[seqIndex]?.toUpperCase()
      if (ch) return ch
    }
    // Fallback: overhang domain with its own sequence
    if (dom.overhang_id) {
      const ovhSeq = ovhMap.get(dom.overhang_id)
      if (ovhSeq) return ovhSeq[domCol]?.toUpperCase() ?? null
    }
    return null
  }

  // ── Draw: sequence letters on strand domains (world-space) ────────────────
  function _drawSequences() {
    if (!_viewTools.sequences || !_design?.strands) return
    // Only draw letters when zoomed in enough to read them
    if (BP_W * _zoom < 6) return
    const { ovhMap, rows } = _ensureSequenceRenderCache()
    const fontSize = Math.min(BP_W * 0.85, CELL_H * 0.65)
    ctx.font = `bold ${fontSize}px Courier New, monospace`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = CLR_SEQ_TEXT
    // In a mirror pass the canvas is translated ±P·BP_W, so the manual on-screen cull
    // below must add that shift — otherwise the mirrored sequence letters get culled.
    // (The chars still draw at `cx`; the ctx translate places them on the mirror side.)
    const ghostShiftX = _ghostPass * _pbPeriod() * BP_W
    // Skip-aware: `sequenceColumns` walks only PRESENT columns and carries the compressed
    // index into the (skip/loop-compressed) sequence string, so letters stay aligned with
    // the antiparallel strand across deletions (the old geometric index drifted after the
    // first skip).  Deleted columns are simply not yielded → nothing drawn there.
    // A loop column (nBases === 2) holds TWO inserted nucleotides in one geometric column;
    // draw both, squeezed side-by-side and 5'→3'-ordered along the strand direction (so the
    // reading order is left→right on a FORWARD strand, right→left on a REVERSE one), at a
    // reduced font so they fit within the single cell.
    const loopFontSize = fontSize * 0.66
    const baseFont = ctx.font
    const loopFont = `bold ${loopFontSize}px Courier New, monospace`
    for (const row of rows) {
      const { strand } = row
      if (!row.hasSequence) continue
      for (const col of row.columns) {
        const info = _rowMap.get(col.helixId)
        if (!info) continue
        const y = col.isFwd ? info.fwdY : info.revY
        const cx = _bpCenterX(col.bp)
        const sx = (cx + ghostShiftX) * _zoom + _panX
        if (sx < -BP_W * _zoom || sx > canvasEl.width + BP_W * _zoom) continue
        const n = col.nBases
        if (n > 1) ctx.font = loopFont
        for (let j = 0; j < n; j++) {
          const ch = _seqCharAt(strand, col.seqIndex + j, col.domCol, col.dom, ovhMap)
          if (!ch || !VALID_BASES.has(ch)) continue
          // 5'→3' along the strand: FORWARD reads left→right, REVERSE right→left
          const off = n > 1 ? (col.isFwd ? 1 : -1) * (j - (n - 1) / 2) * (BP_W * 0.5) : 0
          ctx.fillText(ch, cx + off, y)
        }
        if (n > 1) ctx.font = baseFont
      }
    }
  }

  // ── Draw: undefined base highlights (world-space) ─────────────────────────
  function _drawUndefinedBases() {
    if (!_viewTools.undefinedBases || !_design?.strands) return
    const { ovhMap, rows } = _ensureSequenceRenderCache()
    ctx.fillStyle = CLR_UNDEF_FILL
    ctx.strokeStyle = CLR_UNDEF_BORDER
    ctx.lineWidth = 1 / _zoom
    const ghostShiftX = _ghostPass * _pbPeriod() * BP_W   // mirror-pass translate (see _drawSequences)
    const half = CELL_H / 2
    // Skip-aware (mirrors _drawSequences): only PRESENT columns are candidates; a deleted
    // column is not "undefined", it simply has no nucleotide, so it must not be flagged.
    for (const { strand, columns } of rows) {
      for (const col of columns) {
        const info = _rowMap.get(col.helixId)
        if (!info) continue
        const ch = _seqCharAt(strand, col.seqIndex, col.domCol, col.dom, ovhMap)
        if (ch && VALID_BASES.has(ch)) continue
        const y = col.isFwd ? info.fwdY : info.revY
        const x = _bpToX(col.bp)
        const sx = (x + ghostShiftX) * _zoom + _panX
        if (sx + BP_W * _zoom < 0 || sx > canvasEl.width) continue
        ctx.fillRect(x, y - half, BP_W, CELL_H)
        ctx.strokeRect(x, y - half, BP_W, CELL_H)
      }
    }
  }

  // Strand-level selection glow — rebuilt per frame in _draw().
  const CLR_STRAND_GLOW = '#ff3333'
  let _strandSelectedIds = new Set()   // strand IDs that are "whole-strand selected"
  let _strandSelectionCacheDesign = null
  let _strandSelectionCacheEnabled = false
  let _strandSelectionCacheSignature = null

  /** Rebuild _strandSelectedIds from _selectedElements when strand filter is on.
   *  Expands to the full crossover-connected component so that strands linked
   *  by registered crossovers all glow together.  */
  function _rebuildStrandSelection() {
    // Selection changes far less often than pointer-driven redraws. A signature
    // over the usually tiny selected-key set avoids rescanning every domain on
    // every wheel/pan/drag frame while remaining correct for in-place Set edits.
    const enabled = !!_selectFilter.strand
    const signature = enabled && _selectedElements.size
      ? Array.from(_selectedElements).join('\u0000')
      : ''
    if (_strandSelectionCacheDesign === _design &&
        _strandSelectionCacheEnabled === enabled &&
        _strandSelectionCacheSignature === signature) return
    _strandSelectionCacheDesign = _design
    _strandSelectionCacheEnabled = enabled
    _strandSelectionCacheSignature = signature
    _strandSelectedIds = new Set()
    if (!enabled || !_selectedElements.size || !_design?.strands) return
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
    dashed = false,
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

    // Reference geometry draws as dashed hollow outlines instead of solid fills,
    // so it reads as an inactive backdrop at a glance. _DASH is in screen px
    // (÷_zoom under the scaled world transform).
    const _DASH  = dashed ? [5 / _zoom, 3.5 / _zoom] : null
    const _capLW = 1.6 / _zoom
    function _capRect(rx, ry, rw, rh, col) {
      if (dashed) {
        ctx.strokeStyle = col; ctx.lineWidth = _capLW
        ctx.setLineDash(_DASH); ctx.strokeRect(rx, ry, rw, rh); ctx.setLineDash([])
      } else { ctx.fillStyle = col; ctx.fillRect(rx, ry, rw, rh) }
    }
    function _bodyFill(bx0, bx1, by, thick, col) {
      if (bx1 <= bx0) return
      if (dashed) {
        ctx.strokeStyle = col; ctx.lineWidth = thick; ctx.lineCap = 'butt'
        ctx.setLineDash(_DASH)
        ctx.beginPath(); ctx.moveTo(bx0, by); ctx.lineTo(bx1, by); ctx.stroke()
        ctx.setLineDash([]); ctx.lineCap = 'round'
      } else { ctx.fillStyle = col; ctx.fillRect(bx0, by - thick / 2, bx1 - bx0, thick) }
    }
    function _capTri(pts, col) {
      ctx.beginPath()
      ctx.moveTo(pts[0][0], pts[0][1]); ctx.lineTo(pts[1][0], pts[1][1]); ctx.lineTo(pts[2][0], pts[2][1])
      ctx.closePath()
      if (dashed) {
        ctx.strokeStyle = col; ctx.lineWidth = _capLW; ctx.setLineDash(_DASH); ctx.stroke(); ctx.setLineDash([])
      } else { ctx.fillStyle = col; ctx.fill() }
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
        _capRect(x1, y - sqSz / 2, sqSz, sqSz, cap5Color)   // 5′ square
      }
      _bodyFill(bodyStart, bodyEnd, y, sThick, color)
      if (!suppress3prime) {
        const triStart = x2 - BP_W
        _capTri([[triStart, y - half], [x2, y], [triStart, y + half]], cap3Color)
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
        _capRect(x2 - sqSz, y - sqSz / 2, sqSz, sqSz, cap5Color)   // 5′ square
      }
      _bodyFill(bodyStart, bodyEnd, y, sThick, color)
      if (!suppress3prime) {
        const triEnd = x1 + BP_W
        _capTri([[triEnd, y - half], [x1, y], [triEnd, y + half]], cap3Color)
      }
    }
    if (glowStrand) { ctx.shadowBlur = 0 }
  }

  function _drawAllDomains() {
    if (!_design?.strands) return
    // Build a set of strand-end positions that have an extension arm so end caps
    // can be moved to the arm tip instead of the domain terminus.
    const extEndSet = new Set((_design.extensions ?? []).map(e => `${e.strand_id}:${e.end}`))
    const ghostShiftX = _ghostPass * _pbPeriod() * BP_W
    const screenMargin = Math.max(BP_W * _zoom, 16)
    for (let si = 0; si < _design.strands.length; si++) {
      const strand   = _design.strands[si]
      const isRef    = !!strand.is_reference
      // Reference geometry: hide when the view toggle is off, else draw dashed.
      if (isRef && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
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

        // Canvas clipping hides off-screen domains but still pays all of the
        // crossover, selection, colour, and cap-geometry work below. Reject by
        // the transformed horizontal bounds first. Include the periodic mirror
        // translation and a screen-space margin for glows/end caps.
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const sx1 = (_bpToX(lo) + ghostShiftX) * _zoom + _panX
        const sx2 = (_bpToX(hi + 1) + ghostShiftX) * _zoom + _panX
        if (sx2 < -screenMargin || sx1 > canvasEl.width + screenMargin) continue

        // Suppress the end cap (square or triangle) and use a half-line wherever
        // an arc attaches — either a registered crossover or a cross-helix
        // domain continuation (coaxial, scaffold routing, forced ligation).
        const dir     = dom.direction
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

        _drawDomain(dom, info, color, suppress5, suppress3, xoverAt5 || extAt5, xoverAt3 || extAt3, isGlow, thickMul, isRef)
      }
    }
  }

  // ── Draw: strand extensions (5′/3′ tails with optional sequence/modification) ─

  function _drawExtensions() {
    if (!_design?.extensions?.length || !_design?.strands) return
    _ensureStrandIndex()
    const lineW = CELL_H * 0.20
    const dotR  = CELL_H * 0.30
    const sqSz  = Math.min(BP_W, CELL_H) * 0.80
    const half  = CELL_H / 2

    ctx.save()
    ctx.lineCap = 'round'

    for (const { ext, strand, idx } of _extensionHostEntries) {
      const isRef = !!strand.is_reference
      if (isRef && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
      const _extDash = isRef ? [5 / _zoom, 3.5 / _zoom] : null

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

      const ghostShiftX = _ghostPass * _pbPeriod() * BP_W
      const sx0 = (Math.min(ax, fx) + ghostShiftX) * _zoom + _panX
      const sx1 = (Math.max(ax, fx) + ghostShiftX) * _zoom + _panX
      if (sx1 < -16 || sx0 > canvasEl.width + 16) continue

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
      if (_extDash) ctx.setLineDash(_extDash)
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(fx, fy)
      ctx.stroke()
      if (_extDash) ctx.setLineDash([])

      // ── End cap or modification dot at free end ─────────────────────────────
      if (ext.modification) {
        // Modification: coloured dot (replaces the end cap) — always solid.
        const dotColor = EXT_MOD_COLORS[ext.modification] ?? '#ffffff'
        ctx.fillStyle   = dotColor
        ctx.strokeStyle = '#000000'
        ctx.lineWidth   = 0.5
        ctx.beginPath()
        ctx.arc(fx, fy, dotR, 0, 2 * Math.PI)
        ctx.fill()
        ctx.stroke()
      } else if (ext.end === 'five_prime') {
        // 5′ square at arm tip (hollow dashed for reference geometry)
        if (isRef) {
          ctx.strokeStyle = color; ctx.lineWidth = 1.6 / _zoom; ctx.setLineDash(_extDash)
          ctx.strokeRect(fx - sqSz / 2, fy - sqSz / 2, sqSz, sqSz); ctx.setLineDash([])
        } else {
          ctx.fillStyle = color
          ctx.fillRect(fx - sqSz / 2, fy - sqSz / 2, sqSz, sqSz)
        }
      } else {
        // 3′ triangle at arm tip, pointing along the arm direction
        ctx.beginPath()
        ctx.moveTo(fx - ux * BP_W + pvx * half, fy - uy * BP_W + pvy * half)
        ctx.lineTo(fx, fy)
        ctx.lineTo(fx - ux * BP_W - pvx * half, fy - uy * BP_W - pvy * half)
        ctx.closePath()
        if (isRef) {
          ctx.strokeStyle = color; ctx.lineWidth = 1.6 / _zoom; ctx.setLineDash(_extDash)
          ctx.stroke(); ctx.setLineDash([])
        } else {
          ctx.fillStyle = color; ctx.fill()
        }
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

  let _coaxialArcDesign = null
  let _coaxialArcLayoutRevision = -1
  let _coaxialArcGroups = []

  function _ensureCoaxialArcIndex() {
    if (_coaxialArcDesign === _design && _coaxialArcLayoutRevision === _layoutRevision) return
    const groups = []
    for (let si = 0; si < (_design?.strands?.length ?? 0); si++) {
      const strand = _design.strands[si]
      const arcs = []
      for (let di = 0; di < strand.domains.length - 1; di++) {
        const domA = strand.domains[di]
        const domB = strand.domains[di + 1]
        if (domA.helix_id === domB.helix_id) continue
        if (_components.isXoverSlot(domA.helix_id, domA.end_bp, domA.direction)) continue
        if (_isForcedLigTransition(domA, domB)) continue
        const infoA = _rowMap.get(domA.helix_id)
        const infoB = _rowMap.get(domB.helix_id)
        if (!infoA || !infoB) continue
        const xA = _bpCenterX(domA.end_bp)
        const xB = _bpCenterX(domB.start_bp)
        const yA = domA.direction === 'FORWARD' ? infoA.fwdY : infoA.revY
        const yB = domB.direction === 'FORWARD' ? infoB.fwdY : infoB.revY
        arcs.push({
          xA, xB, yA, yB,
          cx: (xA + xB) / 2 + Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07),
          cy: (yA + yB) / 2,
        })
      }
      if (arcs.length) groups.push({ si, strand, arcs })
    }
    _coaxialArcGroups = groups
    _coaxialArcDesign = _design
    _coaxialArcLayoutRevision = _layoutRevision
  }

  function _drawCoaxialArcs() {
    if (!_design?.strands) return
    _ensureCoaxialArcIndex()
    const baseThick = CELL_H * 0.20
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = baseThick
    ctx.shadowBlur = 0
    for (const { si, strand, arcs } of _coaxialArcGroups) {
      const isRef  = !!strand.is_reference
      if (isRef && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
      const strandGlow = _strandSelectedIds.has(strand.id)
      const hm = _heatmapCache.get(si)
      const color  = strandGlow ? CLR_STRAND_GLOW : (hm ? hm.color : _components.colorOf(si))
      ctx.strokeStyle = color
      ctx.lineWidth = baseThick * (hm ? hm.thickMul : 1.0)
      // butt caps for reference dashes — round caps fill the gaps at working zoom.
      ctx.setLineDash(isRef ? [6 / _zoom, 5 / _zoom] : [])
      ctx.lineCap = isRef ? 'butt' : 'round'
      if (strandGlow) { ctx.shadowColor = CLR_STRAND_GLOW; ctx.shadowBlur = 10 / _zoom }
      else            { ctx.shadowBlur = 0 }
      const ghostShiftX = _ghostPass * _pbPeriod() * BP_W
      for (const arc of arcs) {
        const { xA, xB, yA, yB, cx, cy } = arc
        const sx0 = (Math.min(xA, xB, cx) + ghostShiftX) * _zoom + _panX
        const sx1 = (Math.max(xA, xB, cx) + ghostShiftX) * _zoom + _panX
        const sy0 = Math.min(yA, yB, cy) * _zoom + _panY
        const sy1 = Math.max(yA, yB, cy) * _zoom + _panY
        if (sx1 < -16 || sx0 > canvasEl.width + 16 ||
            sy1 < -16 || sy0 > canvasEl.height + 16) continue
        ctx.beginPath()
        ctx.moveTo(xA, yA)
        ctx.quadraticCurveTo(cx, cy, xB, yB)
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
      const x  = _bpCenterX(xo.half_a.index)
      const y0 = xo.half_a.strand === 'FORWARD' ? infoA.fwdY : infoA.revY
      const y1 = xo.half_b.strand === 'FORWARD' ? infoB.fwdY : infoB.revY
      const isScafXo = infoA.scaffoldFwd ? xo.half_a.strand === 'FORWARD' : xo.half_a.strand === 'REVERSE'
      const bowDir = _xoverBowDir(xo.half_a.index, isScafXo)
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(y1 - y0) * 0.07)
      const ghostShiftX = _ghostPass * _pbPeriod() * BP_W
      const screenMargin = 16
      const sx0 = (Math.min(x, x + bowDir * bowAmt) + ghostShiftX) * _zoom + _panX
      const sx1 = (Math.max(x, x + bowDir * bowAmt) + ghostShiftX) * _zoom + _panX
      const sy0 = Math.min(y0, y1) * _zoom + _panY
      const sy1 = Math.max(y0, y1) * _zoom + _panY
      if (sx1 < -screenMargin || sx0 > canvasEl.width + screenMargin ||
          sy1 < -screenMargin || sy0 > canvasEl.height + screenMargin) continue
      const sA      = _findStrandIdxAt(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
      const sB      = _findStrandIdxAt(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
      // A crossover is reference geometry when both halves sit on reference strands.
      const isRefXo = sA >= 0 && sB >= 0 &&
                      _design.strands[sA].is_reference && _design.strands[sB].is_reference
      if (isRefXo && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
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
      const midY   = (y0 + y1) / 2
      if (isRefXo) { ctx.setLineDash([6 / _zoom, 5 / _zoom]); ctx.lineCap = 'butt' }
      ctx.beginPath()
      ctx.moveTo(x, y0)
      ctx.quadraticCurveTo(x + bowDir * bowAmt, midY, x, y1)
      ctx.stroke()
      if (isRefXo) { ctx.setLineDash([]); ctx.lineCap = 'round' }

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
      const s5Idx    = _findStrandIdxAt(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)
      // A forced ligation is reference geometry when both ligated strands are reference.
      const isRefFL  = sIdx >= 0 && s5Idx >= 0 &&
                       _design.strands[sIdx].is_reference && _design.strands[s5Idx].is_reference
      if (isRefFL && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
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

      // Periodic-seam forced ligation: when the boundary is on and the connection is
      // shorter wrapped (endpoints > ½ period apart), route it the short way — a dashed
      // arc through EACH seam to the other endpoint's mirror image — instead of one long
      // straight arc across the structure. Drawn once (real pass); the straight arc is
      // skipped in every pass. Gated on is_periodic_seam (user choice). MUST stay in sync
      // with the matching block in _hitTestArc so the dashed arcs are clickable.
      if (_pbSeamFLThroughBoundary(fl)) {
        if (_ghostPass === 0) {
          ctx.save()
          ctx.setLineDash([6 / _zoom, 4 / _zoom]); ctx.lineCap = 'butt'
          for (const a of _pbSeamFLArcs(fl, xA, yA, xB, yB)) {
            ctx.beginPath()
            ctx.moveTo(a.x0, a.y0)
            ctx.quadraticCurveTo(a.cx, a.cy, a.x1, a.y1)
            ctx.stroke()
          }
          ctx.restore()
        }
        continue   // skip the long straight arc (and its ticks) in every pass
      }

      // Periodic-seam FL, periodic boundary OFF: the long across-the-structure arc isn't
      // meaningful here. Draw a SHORT dashed stub at each endpoint that fades to
      // transparent outward — a visual reminder that this end pairs with the other end
      // of the polymerization seam, without painting the whole length. MUST stay in sync
      // with the _pbSeamFLAsStubs branches in _hitTestArc + _hitTestLassoElements.
      if (_pbSeamFLAsStubs(fl)) {
        if (_ghostPass === 0) {
          const FADE_DASHES = 6
          const prevAlpha = ctx.globalAlpha
          ctx.save()
          ctx.lineCap = 'butt'
          for (const s of _pbSeamFLStubs(fl, xA, yA, xB, yB)) {
            const step = (s.x1 - s.x0) / FADE_DASHES
            for (let i = 0; i < FADE_DASHES; i++) {
              ctx.globalAlpha = prevAlpha * (1 - (i + 0.5) / FADE_DASHES)
              const xs = s.x0 + i * step
              ctx.beginPath()
              ctx.moveTo(xs, s.y0)
              ctx.lineTo(xs + step * 0.6, s.y0)
              ctx.stroke()
            }
          }
          ctx.globalAlpha = prevAlpha
          ctx.restore()
        }
        continue   // skip the long straight arc (and its ticks) in every pass
      }

      const midX = (xA + xB) / 2
      const midY = (yA + yB) / 2
      const bowAmt = Math.max(BP_W * 0.27, Math.abs(yB - yA) * 0.07)
      const ctrlX = midX + bowAmt
      const ctrlY = midY
      if (isRefFL) { ctx.setLineDash([6 / _zoom, 5 / _zoom]); ctx.lineCap = 'butt' }
      ctx.beginPath()
      ctx.moveTo(xA, yA)
      ctx.quadraticCurveTo(ctrlX, ctrlY, xB, yB)
      ctx.stroke()
      if (isRefFL) { ctx.setLineDash([]); ctx.lineCap = 'round' }

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
    if (_viewTools.loopSkips === false) return
    if (!_design?.helices?.length) return
    ctx.save()
    ctx.lineCap  = 'round'
    ctx.lineJoin = 'round'

    // Loop/skips on a reference-only helix are reference geometry: hide them
    // when the reference toggle is off AND in periodic-boundary mirror passes
    // (matches the 5 per-strand reference-skip sites above).
    const refHelixIds = _referenceOnlyHelixIds()

    for (const helix of _design.helices) {
      if (!helix.loop_skips?.length) continue
      if (refHelixIds.has(helix.id) &&
          (_ghostPass !== 0 || _viewTools.referenceGeometry === false)) continue
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

  let _xoverIndicatorIndexDesign = null
  let _xoverIndicatorIndex = null
  function _ensureXoverIndicatorIndex() {
    if (_xoverIndicatorIndexDesign === _design && _xoverIndicatorIndex) return _xoverIndicatorIndex

    // All four structures below depend only on the immutable design snapshot,
    // not pan/zoom/hover state. Building them per pointer-driven redraw made the
    // indicator overlay repeatedly traverse every strand and crossover.
    const occupied = new Set()
    for (const xo of (_design?.crossovers ?? [])) {
      occupied.add(`${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`)
      occupied.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
    }
    const strandRanges = new Map()
    const refRanges = new Map()
    const minDomainBpByHelix = new Map()
    for (const strand of (_design?.strands ?? [])) {
      for (const dom of strand.domains) {
        const key = `${dom.helix_id}_${dom.direction}`
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const range = [lo, Math.max(dom.start_bp, dom.end_bp)]
        let list = strandRanges.get(key)
        if (!list) { list = []; strandRanges.set(key, list) }
        list.push(range)
        if (strand.is_reference) {
          let rlist = refRanges.get(key)
          if (!rlist) { rlist = []; refRanges.set(key, rlist) }
          rlist.push(range)
        }
        const cur = minDomainBpByHelix.get(dom.helix_id) ?? Infinity
        if (lo < cur) minDomainBpByHelix.set(dom.helix_id, lo)
      }
    }
    _xoverIndicatorIndexDesign = _design
    _xoverIndicatorIndex = {
      occupied,
      strandRanges,
      refRanges,
      minDomainBpByHelix,
      junctionSlots: _crossoverJunctionSlots(_design),
    }
    return _xoverIndicatorIndex
  }

  function _drawCrossoverIndicators() {
    // No clickable crossover sprites in mirror zones — forced ligation (not lattice
    // crossover) is the seam tool. Return before touching _xoverSprites so the real
    // pass (drawn last) owns the hit areas.
    if (_ghostPass !== 0) return
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

    const { occupied, strandRanges, refRanges, junctionSlots, minDomainBpByHelix } =
      _ensureXoverIndicatorIndex()
    const _slotOccupied = (helixId, bp, direction) => {
      const ranges = strandRanges.get(`${helixId}_${direction}`) ?? []
      return ranges.some(([lo, hi]) => lo <= bp && bp <= hi)
    }
    // Slots already occupied by a crossover junction (a multi-domain strand's
    // turn). A new crossover must not land here — suppress its sprite. Mirrors
    // the backend rejection in _build_place_crossover.
    const _slotIsJunction = (helixId, bp, direction) =>
      junctionSlots.has(`${helixId}_${bp}_${direction}`)
    const _slotIsReference = (helixId, bp, direction) => {
      const ranges = refRanges.get(`${helixId}_${direction}`) ?? []
      return ranges.some(([lo, hi]) => lo <= bp && bp <= hi)
    }

    // cell key "row_col" → { hid, info }
    const cellMap = new Map()
    for (const [hid, info] of _rowMap) {
      cellMap.set(`${info.cell.row}_${info.cell.col}`, { hid, info })
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
      const hHelix = hInfo && _helixById.get(_hoverHelixId)
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
      const helix = _helixById.get(hid)
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
            // The crossover connects toward the bp its bow points at (bp+bowDir);
            // that bp must be covered on both helices, else it sits at the extreme
            // edge of coverage with nothing to connect (right/left-most bp).
            const stapReq = bp + _xoverBowDir(bp, false)
            if (!occupied.has(`${hid}_${bp}_${stapA}`) &&
                _slotOccupied(hid, bp, stapA) &&
                _slotOccupied(target.hid, bp, stapB) &&
                _slotOccupied(hid, stapReq, stapA) &&
                _slotOccupied(target.hid, stapReq, stapB) &&
                !_slotIsJunction(hid, bp, stapA) &&
                !_slotIsJunction(target.hid, bp, stapB) &&
                !_slotIsReference(hid, bp, stapA) &&
                !_slotIsReference(target.hid, bp, stapB)) {
              _xoverSprites.push({ hid, bp, targetHid: target.hid, cx, indY: stapIndY, halfAStrand: stapA, halfBStrand: stapB, isScaffold: false })
              // Show the destination helix's identity number (label), matching the
              // gutter; falls back to array index only when no label is frozen.
              _drawSprite(cx, stapIndY, target.info.label ?? target.info.idx, false)
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
              const scafReq = bp + _xoverBowDir(bp, true)
              if (!occupied.has(`${hid}_${bp}_${scafA}`) &&
                  _slotOccupied(hid, bp, scafA) &&
                  _slotOccupied(target.hid, bp, scafB) &&
                  _slotOccupied(hid, scafReq, scafA) &&
                  _slotOccupied(target.hid, scafReq, scafB) &&
                  !_slotIsJunction(hid, bp, scafA) &&
                  !_slotIsJunction(target.hid, bp, scafB) &&
                  !_slotIsReference(hid, bp, scafA) &&
                  !_slotIsReference(target.hid, bp, scafB)) {
                _xoverSprites.push({ hid, bp, targetHid: target.hid, cx, indY: scafIndY, halfAStrand: scafA, halfBStrand: scafB, isScaffold: true })
                _drawSprite(cx, scafIndY, target.info.label ?? target.info.idx, true)
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
    _ensureDragIndex()
    const entries = []
    for (const key of _selectedElements) {
      if (!key.startsWith('end:')) continue
      const parsed = parseEndKey(key)
      if (!parsed) continue
      const { helix_id, bp, direction } = parsed
      const indexed = _endEntryByKey.get(key)
      if (!indexed) continue
      const { strand, dom, lo, hi } = indexed
      const isFwd = direction === 'FORWARD'
      // 1-nt strand: both ends coincide at `bp`, so bp-position can't tell them
      // apart (it always reads 5′). Pick the resizable end instead so a stub
      // pinned by a crossover on its 5′ side is dragged from its free 3′ side.
      const end = (strand.domains.length === 1 && lo === hi)
        ? oneNtResizableEnd({ helix_id, direction, bp_index: bp, strand_id: strand.id }, _design.strands)
        : ((isFwd ? bp === lo : bp === hi) ? '5p' : '3p')
      entries.push({
        strandId: strand.id, helixId: helix_id, end, origBp: bp, direction,
        domLo: lo, domHi: hi, info: _rowMap.get(dom.helix_id),
      })
    }
    return entries
  }

  // Compute shared [minDelta, maxDelta] across all entries.
  function _computeEndDragLimits(entries) {
    _ensureDragIndex()
    let minDelta = -Infinity, maxDelta = +Infinity

    // Helper: crossover positions on a specific helix+direction
    const xoverPositions = (helixId, direction) => {
      return _xoverPositionsByTrack.get(`${helixId}_${direction}`) ?? new Set()
    }

    // Helper: other domain endpoints on the same helix+direction (excluding this domain)
    const otherEndpoints = (helixId, direction, domLo, domHi) => {
      const pts = []
      for (const entry of _strandIndexMap.get(`${helixId}_${direction}`) ?? []) {
        if (entry.lo === domLo && entry.hi === domHi) continue
        pts.push(entry.lo, entry.hi)
      }
      return pts
    }

    // Helper: extent of the contiguous collinear run the terminal domain belongs
    // to — adjacent domains of the SAME strand on the same helix+direction with
    // no bp gap. That pattern is an inline overhang/duplex split, never a
    // crossover (a crossover changes helix), so the run's far edge IS the nearest
    // crossover / strand boundary. Treating the run as one lets a terminal resize
    // move THROUGH the split; the backend re-classifies the overhang afterward.
    const collinearRun = (strandId, helixId, direction, domLo, domHi) => {
      const strand = _strandById.get(strandId)
      if (!strand) return { runLo: domLo, runHi: domHi }
      const doms = strand.domains
      const idx = doms.findIndex(d =>
        d.helix_id === helixId && d.direction === direction &&
        Math.min(d.start_bp, d.end_bp) === domLo && Math.max(d.start_bp, d.end_bp) === domHi)
      if (idx < 0) return { runLo: domLo, runHi: domHi }
      const adj = (a, b) => a.helix_id === b.helix_id && a.direction === b.direction &&
        (direction === 'FORWARD' ? a.end_bp + 1 === b.start_bp : a.end_bp - 1 === b.start_bp)
      let runLo = domLo, runHi = domHi
      const grow = (d) => { runLo = Math.min(runLo, d.start_bp, d.end_bp); runHi = Math.max(runHi, d.start_bp, d.end_bp) }
      for (let i = idx; i > 0 && adj(doms[i - 1], doms[i]); i--) grow(doms[i - 1])
      for (let i = idx; i < doms.length - 1 && adj(doms[i], doms[i + 1]); i++) grow(doms[i + 1])
      return { runLo, runHi }
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

      // Span the contiguous collinear run for the SHRINK limit so the end can
      // retract through an inline overhang/duplex split down to the run's far
      // edge (the nearest real crossover / strand boundary).
      const { runLo, runHi } = collinearRun(entry.strandId, helixId, direction, domLo, domHi)
      // Positions of crossovers strictly inside the run
      const innerXovers = [...xoPos].filter(p => p > runLo && p < runHi)

      if (end === '5p') {
        if (isFwd) {
          // 5′ FORWARD is at domLo — moving left extends, right shrinks
          // Shrink limit: first inner crossover, or hi (keep ≥ 1 bp)
          const shrinkBlock = innerXovers.length
            ? Math.min(...innerXovers) - domLo
            : runHi - runLo
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
            : runHi - runLo
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
            : runHi - runLo
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
            : runHi - runLo
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
      // Render back at the mirror (display) location when editing through a mirror.
      ctx.fillRect(_bpToX(newBp + _ghostShiftBp), y - half, BP_W, CELL_H)
    }
    ctx.restore()
  }

  // ── Domain-drag helpers (move whole domain) ────────────────────────────────

  // Build domain-drag entries from all `line:` keys in _selectedElements.
  function _resolveDomainDragEntries() {
    _ensureDragIndex()
    const entries = []
    for (const key of _selectedElements) {
      if (!key.startsWith('line:')) continue
      const parsed = parseLineKey(key)
      if (!parsed) continue
      const { helix_id, lo, hi, direction } = parsed
      const indexed = _lineEntryByKey.get(key)
      if (!indexed) continue
      entries.push({
        strandId: indexed.strand.id, domainIndex: indexed.di,
        helixId: helix_id, direction, domLo: lo, domHi: hi,
        info: _rowMap.get(helix_id),
      })
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
    _ensureDragIndex()
    let minDelta = -Infinity, maxDelta = +Infinity

    const xoverPositions = (helixId, direction) => {
      return _xoverPositionsByTrack.get(`${helixId}_${direction}`) ?? new Set()
    }

    // Set of (strand_id, domain_index) keys identifying co-selected domains —
    // these don't act as blockers for each other since they all shift by the
    // same delta.
    const coSelected = new Set(entries.map(en => `${en.strandId}\x00${en.domainIndex}`))

    const otherEndpoints = (helixId, direction, domLo, domHi) => {
      const lefts = []   // endpoints with hi < domLo
      const rights = []  // endpoints with lo > domHi
      for (const entry of _strandIndexMap.get(`${helixId}_${direction}`) ?? []) {
          if (coSelected.has(`${entry.strand.id}\x00${entry.di}`)) continue
          const { lo, hi } = entry
          if (lo === domLo && hi === domHi) continue
          if (hi < domLo) lefts.push(hi)
          else if (lo > domHi) rights.push(lo)
          else {
            // Some other domain already overlaps — pre-existing inconsistency,
            // bail out by clamping this entry to zero.
            lefts.push(domLo)   // forces minDelta = 0
            rights.push(domHi)  // forces maxDelta = 0
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
      ctx.fillRect(_bpToX(newLo + _ghostShiftBp), y - half, BP_W * (newHi - newLo + 1), CELL_H)
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
    const hA = _helixById.get(xover.half_a.helix_id)
    const hB = _helixById.get(xover.half_b.helix_id)
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
    // Render the drag preview back at the mirror (display) location when the
    // crossover is being dragged on the mirror side of a periodic boundary.
    if (_ghostShiftBp) ctx.translate(_ghostShiftBp * BP_W, 0)
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
        // Render back at the mirror location the cursor is hovering, if any.
        const s = _ghostShiftForWorldX(_forcedLigCursorX)
        ctx.fillStyle = 'rgba(30, 160, 60, 0.40)'
        ctx.fillRect(_bpToX(fivePrimeBp + s), cy - CELL_H / 2, BP_W, CELL_H)
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
    // _paintLo/_paintHi are REAL bp; render the preview back at the mirror location.
    const s = _ghostShiftBp
    ctx.fillStyle = _paintIsScaffold ? CLR_GHOST_SCAF : CLR_GHOST_STPL
    ctx.fillRect(_bpToX(_paintLo + s), y - ghostThick / 2, _bpToX(_paintHi + 1) - _bpToX(_paintLo), ghostThick)
  }

  // ── Draw: nick hover ghost ────────────────────────────────────────────────────
  // When nick tool is active and cursor is over a strand, highlight where the
  // new 3' end (RED) and new 5' end (GREEN) would land if the user clicked now.

  function _drawNickHover() {
    if (!_nickHover) return
    const { threeEndBp, fiveEndBp, y, ligation } = _nickHover
    const s = _nickHover.shift ?? 0   // render back at the mirror (display) location
    const half = CELL_H / 2
    if (_shiftHeld && ligation) {
      // Ligation mode — blue highlight on both boundary cells of the nick
      ctx.fillStyle = 'rgba(50, 130, 255, 0.65)'
      ctx.fillRect(_bpToX(ligation.threeEndBp + s), y - half, BP_W, CELL_H)
      ctx.fillRect(_bpToX(ligation.fiveEndBp + s),  y - half, BP_W, CELL_H)
    } else {
      // Normal nick mode — red 3' end, green 5' end
      ctx.fillStyle = 'rgba(220, 40, 40, 0.55)'
      ctx.fillRect(_bpToX(threeEndBp + s), y - half, BP_W, CELL_H)
      ctx.fillStyle = 'rgba(30, 160, 60, 0.55)'
      ctx.fillRect(_bpToX(fiveEndBp + s),  y - half, BP_W, CELL_H)
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

  // ── Draw: periodic-boundary mirror passes (world space) ──────────────────────
  // Re-renders the active design shifted ±P beyond each slider, clips real content
  // to the body, and tints the mirror zones. Replaces the single _drawWorldContent
  // call when _pbOn(). Reference geometry is force-skipped during mirror passes via
  // the _ghostPass flag (see the isRef checks in the draw helpers).
  function _drawPbContentPasses() {
    const P    = _pbPeriod()
    const dx   = P * BP_W
    const topY = (-_panY) / _zoom
    const botY = (canvasEl.height - _panY) / _zoom
    const wLeft  = (-_panX) / _zoom
    const wRight = (canvasEl.width - _panX) / _zoom
    const nearX  = _bpToX(_pbNearBp)
    const farX   = _bpToX(_pbFarBp)

    // Primary (real) strands: drawn FULL and unclipped at full opacity, so they stay
    // visible everywhere — including under a slider dragged into the body. The mirror
    // passes below draw translucent ON TOP, overlaying periodic onto primary (lets the
    // user slide a slider inward to superimpose far-vs-near and check the seam).
    _drawWorldContent()

    // Faint tint over each mirror zone (behind the mirror strands, over the primary)
    // so the periodic region still reads as distinct.
    ctx.fillStyle = CLR_PB_BAND
    if (nearX > wLeft)  ctx.fillRect(wLeft, topY, nearX - wLeft, botY - topY)
    if (farX  < wRight) ctx.fillRect(farX, topY, wRight - farX, botY - topY)

    // Left mirror: far-end content shifted -P, clipped to x ≤ nearX, translucent on top.
    if (nearX > wLeft) {
      ctx.save()
      ctx.beginPath(); ctx.rect(wLeft, topY, nearX - wLeft, botY - topY); ctx.clip()
      ctx.translate(-dx, 0)
      ctx.globalAlpha = 0.55
      _ghostPass = -1; _drawWorldContent(); _ghostPass = 0
      ctx.restore()
    }
    // Right mirror: near-end content shifted +P, clipped to x ≥ farX, translucent on top.
    if (farX < wRight) {
      ctx.save()
      ctx.beginPath(); ctx.rect(farX, topY, wRight - farX, botY - topY); ctx.clip()
      ctx.translate(dx, 0)
      ctx.globalAlpha = 0.55
      _ghostPass = 1; _drawWorldContent(); _ghostPass = 0
      ctx.restore()
    }
  }

  // ── Draw: periodic-boundary chrome (screen space) ────────────────────────────
  // Two red slider bars, grab handles in the ruler band, and the seam-gap readout.
  // Screen space so bars/handles are fixed-width and sit correctly under any zoom.
  function _drawPbChrome() {
    if (!_pbOn()) return
    const H = canvasEl.height, W = canvasEl.width
    const P = _pbPeriod()
    const now = performance.now()
    const flashing = now < _pbFlashUntil
    const bars = [
      { bp: _pbNearBp, role: 'near', red: _pbNearBp + P, dragging: _pbNearDragging },
      { bp: _pbFarBp,  role: 'far',  red: _pbFarBp  - P, dragging: _pbFarDragging  },
    ]
    ctx.save()
    ctx.textBaseline = 'alphabetic'
    for (const b of bars) {
      const sx = _bpToX(b.bp) * _zoom + _panX
      if (sx < GUTTER || sx > W) continue
      // Vertical bar from the ruler down.
      ctx.strokeStyle = flashing && b.dragging === false ? CLR_PB_BAR_FLASH : CLR_PB_BAR
      ctx.lineWidth = b.dragging ? 3 : 2
      ctx.beginPath(); ctx.moveTo(sx, RULER_H); ctx.lineTo(sx, H); ctx.stroke()
      // Grab handle + label inside the ruler band.
      const hw = 30, hh = RULER_H - 4
      const hx = b.role === 'near' ? sx : sx - hw   // near handle to the right, far handle to the left
      ctx.fillStyle = CLR_PB_HANDLE
      ctx.fillRect(hx, 2, hw, hh)
      ctx.fillStyle = CLR_PB_HANDLE_TXT
      ctx.font = 'bold 9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(`${b.role} ${b.red}`, hx + hw / 2, 2 + hh / 2 + 3)
    }
    // Seam-gap readout: period − active-strand cell span. 0 = copies tile flush.
    const ext = _activeStrandExtent()
    if (ext) {
      const span = (ext.hi + 1) - ext.lo
      const gap  = P - span
      ctx.font = 'bold 11px sans-serif'
      ctx.textAlign = 'left'
      ctx.fillStyle = gap === 0 ? CLR_PB_GAP_OK : CLR_PB_GAP_BAD
      const txt = gap === 0 ? 'seam: flush ✓'
                : gap > 0   ? `seam: +${gap} bp gap`
                :             `seam: ${gap} bp overlap`
      ctx.fillText(txt, GUTTER + 8, RULER_H + 16)
    }
    ctx.restore()
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
    for (const [hid, info] of _rowMap) {
      const cy      = (info.fwdY + info.revY) / 2
      const screenY = cy * _zoom + _panY
      if (screenY + LABEL_R < RULER_H || screenY - LABEL_R > H) continue
      const cx = GUTTER / 2
      ctx.beginPath(); ctx.arc(cx, screenY, LABEL_R, 0, 2 * Math.PI)
      ctx.fillStyle   = info.scaffoldFwd ? CLR_LABEL_FWD_FILL   : CLR_LABEL_REV_FILL
      ctx.fill()
      if (_selectedHelices.has(hid)) {
        // Selected for reordering — bright blue ring on top of the base stroke.
        ctx.strokeStyle = '#388bfd'; ctx.lineWidth = 3
      } else {
        ctx.strokeStyle = info.scaffoldFwd ? CLR_LABEL_FWD_STROKE : CLR_LABEL_REV_STROKE
        ctx.lineWidth = 1.5
      }
      ctx.stroke()
      // Circle radius is LABEL_R screen pixels (fixed, doesn't scale with zoom).
      ctx.font = `bold ${LABEL_R * 1.15}px sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillStyle = CLR_LABEL_TEXT
      ctx.fillText(info.label ?? info.idx, cx, screenY)
    }
    ctx.textBaseline = 'alphabetic'
    ctx.restore()
  }

  // ── Draw: gutter lasso (screen-space vertical rubber-band) ───────────────────
  function _drawGutterLasso() {
    if (!_gutterLassoActive) return
    const y0 = Math.min(_gutterLassoSY0, _gutterLassoSY1)
    const y1 = Math.max(_gutterLassoSY0, _gutterLassoSY1)
    ctx.save()
    ctx.setLineDash([4, 4])
    ctx.strokeStyle = '#388bfd'; ctx.lineWidth = 1.5
    ctx.strokeRect(1, y0, GUTTER - 2, y1 - y0)
    ctx.fillStyle = 'rgba(56, 139, 253, 0.10)'
    ctx.fillRect(1, y0, GUTTER - 2, y1 - y0)
    ctx.restore()
  }

  // ── Draw: helix drag-to-reorder ghost (screen-space) ─────────────────────────
  // Blue outline rectangle enclosing the dragged circles (follows the cursor) +
  // a red insertion arrow at the gap the cursor is nearest.
  function _drawHelixDragGhost() {
    if (!_helixDragActive) return
    const rows = [..._rowMap.values()]
    const n    = rows.length
    if (n === 0) return

    // ── Red insertion arrow at the current gap ────────────────────────────────
    const k  = Math.max(0, Math.min(n, _helixDragInsertIdx))
    const sy = rows.map(_gutterCircleSY)
    const span = ROW_H * _zoom / 2
    const arrowY = k === 0 ? sy[0] - span
                 : k >= n  ? sy[n - 1] + span
                 : (sy[k - 1] + sy[k]) / 2
    ctx.save()
    ctx.strokeStyle = '#e53935'; ctx.lineWidth = 2.5
    ctx.beginPath(); ctx.moveTo(2, arrowY); ctx.lineTo(GUTTER + 54, arrowY); ctx.stroke()
    ctx.fillStyle = '#e53935'
    ctx.beginPath()
    ctx.moveTo(GUTTER + 62, arrowY)
    ctx.lineTo(GUTTER + 50, arrowY - 7)
    ctx.lineTo(GUTTER + 50, arrowY + 7)
    ctx.closePath(); ctx.fill()

    // ── Blue outline around the selected circles, following the cursor ────────
    const selSY = []
    for (const [hid, info] of _rowMap) if (_selectedHelices.has(hid)) selSY.push(_gutterCircleSY(info))
    if (selSY.length > 0) {
      const blkH = (Math.max(...selSY) - Math.min(...selSY)) + 2 * LABEL_R + 6
      const top  = _helixDragCursorSY - blkH / 2
      ctx.setLineDash([])
      ctx.strokeStyle = '#388bfd'; ctx.lineWidth = 2
      ctx.strokeRect(2, top, GUTTER - 4, blkH)
      ctx.fillStyle = 'rgba(56, 139, 253, 0.12)'
      ctx.fillRect(2, top, GUTTER - 4, blkH)
    }
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

    // Labels centred inside cell N (not at the boundary tick). When the periodic
    // boundary is on, black labels show only between the sliders; the mirror zones
    // get RED labels reading the real bp of the mirrored content (display ∓ P).
    const pbOn = _pbOn()
    const P    = _pbPeriod()
    for (let bp = Math.ceil(bpL / major) * major; bp <= bpR; bp += major) {
      if (pbOn && (bp <= _pbNearBp || bp >= _pbFarBp)) continue
      const sx = _bpCenterX(bp) * _zoom + _panX
      ctx.fillText(bp, sx, RULER_H / 2)
    }
    if (pbOn) {
      ctx.fillStyle = CLR_PB_RULER
      for (let bp = Math.ceil(bpL / major) * major; bp <= bpR; bp += major) {
        let red
        if (bp >= _pbFarBp)       red = bp - P   // right mirror: near-end content
        else if (bp <= _pbNearBp) red = bp + P   // left mirror: far-end content
        else continue
        const sx = _bpCenterX(bp) * _zoom + _panX
        ctx.fillText(red, sx, RULER_H / 2)
      }
      ctx.fillStyle = CLR_RULER_TEXT
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

  let _drawFrame = null

  function _scheduleDraw() {
    if (_drawFrame !== null) return
    _drawFrame = requestAnimationFrame(() => {
      _drawFrame = null
      _draw()
    })
  }

  function _draw() {
    // An immediate draw (for example pointerup) supersedes a queued drag frame.
    if (_drawFrame !== null) {
      cancelAnimationFrame(_drawFrame)
      _drawFrame = null
    }
    _ensureComponents()                // build once per design change (cached)
    _rebuildStrandSelection()          // rebuild strand glow set
    _rebuildHeatmapCache()             // rebuild heat map colours
    const W = canvasEl.width, H = canvasEl.height
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = CLR_BG; ctx.fillRect(0, 0, W, H)
    if (!_design?.helices?.length) {
      ctx.fillStyle = '#556677'; ctx.font = '12px Courier New, monospace'
      ctx.textAlign = 'left'
      ctx.fillText('No helices — click lattice cells in the Slice View to add helices.', 16, 40)
      return
    }
    // ── World-space content ────────────────────────────────────────────────────
    ctx.setTransform(_zoom, 0, 0, _zoom, _panX, _panY)
    if (_pbOn()) _drawPbContentPasses()   // mirror passes + body clip + tint bands
    else         _drawWorldContent()
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
    _drawPbChrome()        // periodic-boundary sliders + handles + seam-gap readout
    _drawGutterLasso()     // gutter-circle rubber-band (over the frozen gutter)
    _drawHelixDragGhost()  // drag-to-reorder blue block + red insertion arrow
    _drawHeatmapLegend()   // heat map legend (right-centre)
    if (performance.now() < _pbFlashUntil) requestAnimationFrame(_draw)  // pulse the auto-shifted bar
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
      _ensureComponents()
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
      _panActive      = true
      _rightDragMoved = false   // fresh press: not yet a drag (reset stale flag from a prior pan)
      _panStartCX   = e.clientX; _panStartCY   = e.clientY
      _panStartPanX = _panX;    _panStartPanY = _panY
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); _draw(); return
    }

    if (e.button !== 0) return

    // ── Periodic-boundary slider drag (priority over the adjacent slice bar) ─────
    const pbHit = _isNearPbSlider(e.offsetX)
    if (pbHit) {
      if (pbHit === 'near') _pbNearDragging = true; else _pbFarDragging = true
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); _draw(); return
    }

    // ── Slice bar drag ──────────────────────────────────────────────────────────
    if (_isNearSliceBar(e.offsetX)) {
      _sliceDragging = true
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); return
    }

    // ── Gutter circles: select / lasso / arm reorder-drag ────────────────────────
    // The gutter is the frozen left strip (x < GUTTER); content lives at x ≥ GUTTER,
    // so this is handled before any content hit-test with no conflict.
    if (_activeTool === 'select' && e.offsetX < GUTTER && e.offsetY >= RULER_H) {
      const hid = _helixAtGutter(e.offsetX, e.offsetY)
      if (hid) {
        if (e.ctrlKey || e.metaKey) {
          if (_selectedHelices.has(hid)) _selectedHelices.delete(hid)
          else _selectedHelices.add(hid)
        } else if (!_selectedHelices.has(hid)) {
          _selectedHelices = new Set([hid])
        }
        // Arm a reorder drag (commits in pointerup only if it crosses the threshold).
        if (_selectedHelices.has(hid)) {
          _helixDragArmed   = true
          _helixDragActive  = false
          _helixDragStartSX = e.offsetX
          _helixDragStartSY = e.offsetY
          canvasEl.setPointerCapture(e.pointerId)
        }
        _draw(); e.preventDefault(); return
      }
      // Empty gutter → start a vertical lasso over the circles.
      _gutterLassoStarted = true
      _gutterLassoActive  = false
      _gutterLassoCtrl    = e.ctrlKey || e.metaKey
      _gutterLassoSY0     = e.offsetY
      _gutterLassoSY1     = e.offsetY
      canvasEl.setPointerCapture(e.pointerId); e.preventDefault(); return
    }

    const { wx, wy } = _c2w(e.offsetX, e.offsetY)
    // Mirror shift for this interaction: captured once so a drag stays consistent
    // even if the cursor crosses the seam mid-drag. Hit-tests resolve the REAL
    // strand (via _screenToRealWorld inside _hitTest); previews render back by +shift.
    _ghostShiftBp = _ghostShiftForWorldX(wx)

    // ── Select tool: end-cap drag (must precede xover sprite check) ─────────────
    // Crossover sprites sit near bp 0 / bp (maxBp) — the same positions as
    // strand end-caps.  We detect end-cap hits here before the sprite check so
    // resize-drag isn't stolen.  However, if a crossover sprite also occupies
    // that position, the crossover takes priority (its lattice position has no
    // alternative access point; the end-cap can be resized from the other end).
    if (_activeTool === 'select') {
      const hit = _hitTest(e.offsetX, e.offsetY, _selectFilter)
      if (DBG) console.group(`[PDOWN] select  bp=${_xToBp(wx)}  wx=${wx.toFixed(1)}  wy=${wy.toFixed(1)}  zoom=${_zoom.toFixed(3)}`)
      if (DBG) console.log('hitTest result:', hit ? `elementType=${hit.elementType} strand=${hit.strand.id.slice(0,12)} strandType=${hit.strand.strand_type} bp=${_xToBp(wx)}` : 'null')
      if (hit?.elementType === 'end') {
        // If a crossover sprite also lives at this position, prefer the
        // crossover — its lattice-dictated position has no alternative access.
        const xoverHere = _hitTestCrossoverSprite(e.offsetX, e.offsetY)
        if (xoverHere) {
          if (DBG) console.log('end-cap overlaps crossover sprite — deferring to xover handler')
          if (DBG) console.groupEnd()
          // Fall through to the crossover sprite click handler below.
        } else {
          const key = _hitElementKey(hit)
          if (!_selectedElements.has(key)) {
            if (!(e.ctrlKey || e.metaKey)) _selectedElements = new Set([key])
            else _selectedElements.add(key)
          }
          _endDragEntries = _resolveEndDragEntries()
          if (DBG) console.log('endDragEntries:', _endDragEntries.length, _endDragEntries.map(en => `${en.end}@${en.origBp} ${en.direction} ${en.helixId.slice(0,8)}`))
          if (_endDragEntries.length > 0) {
            const limits     = _computeEndDragLimits(_endDragEntries)
            _endDragMinDelta = limits.minDelta
            _endDragMaxDelta = limits.maxDelta
            if (DBG) console.log(`limits: [${limits.minDelta}, ${limits.maxDelta}]  → starting end-drag, returning early`)
            if (DBG) console.groupEnd()
            _endDragDeltaBp  = 0
            _endDragStartWX  = _c2w(e.offsetX, e.offsetY).wx
            _endDragActive   = true
            canvasEl.setPointerCapture(e.pointerId)
            _draw(); e.preventDefault(); return
          }
          if (DBG) console.log('endDragEntries empty — falling through to xover/lasso')
        }
      } else {
        if (DBG) console.log('not an end-cap — proceeding to xover sprite check')
      }
      if (DBG) console.groupEnd()
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
      if (DBG) console.group(`%c[XOVER SPRITE FIRED] bp=${xoverHit.bp}  bowDir=${bowDir>0?'+1':'-1'}  lowerBp=${lowerBp}`, 'color:orange;font-weight:bold')
      if (DBG) console.log(`  click world=(${wx.toFixed(1)}, ${wy.toFixed(1)})  sprite=(${xoverHit.cx.toFixed(1)}, ${xoverHit.indY.toFixed(1)})`)
      if (DBG) console.log(`  distance=${Math.hypot(dxSp,dySp).toFixed(2)}  hitR=${hitR.toFixed(2)}  zoom=${_zoom.toFixed(3)}`)
      if (DBG) console.log('helix A:', { helix_idx: infoA?.idx, helixId: xoverHit.hid.slice(0,8), dir: xoverHit.halfAStrand, nickBp: nickBpA })
      if (DBG) console.log('helix B:', { helix_idx: infoB?.idx, helixId: xoverHit.targetHid.slice(0,8), dir: xoverHit.halfBStrand, nickBp: nickBpB })
      if (DBG) console.groupEnd()
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
      // Resolve through the periodic-boundary mirror: a crossover arc shown in a
      // mirror zone maps to the real crossover (_ghostShiftBp captured above).
      const arcHit = _hitTestArc(wx - _ghostShiftBp * BP_W, wy)
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
        const nickBp     = _nickBpForDomain(dom, col)
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
        if (DBG) console.log('[NICK]', {
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
      if (DBG) console.log(`[PDOWN] select → lasso fallback (no end-cap hit, no xover sprite)`)
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
        // Seam crossing: the two ends were clicked in different periodic-boundary
        // zones (one body, one mirror — or opposite mirrors). Mechanical, no geometry.
        const endShift   = _ghostShiftForWorldX(_c2w(e.offsetX, e.offsetY).wx)
        const crossesSeam = _pbOn() && _forcedLigStartShift !== endShift
        _forcedLigActive      = false
        _forcedLigStrand      = null
        _forcedLigDom         = null
        _forcedLigHoverTarget = null
        _forcedLigStartShift  = 0
        _dbgLastEvent = `pencil: forced-lig 3'=${sourceStrand.id.slice(0,8)} → 5'=${hit.strand.id.slice(0,8)}${crossesSeam ? ' [seam]' : ''}`
        if (DBG) console.log('[FORCED LIG] complete', {
          from_3prime: sourceStrand.id.slice(0, 12),
          to_5prime:   hit.strand.id.slice(0, 12),
          periodic_seam: crossesSeam,
        })
        _draw()
        ;(async () => {
          await onForcedLigation?.(sourceStrand.id, hit.strand.id, crossesSeam)
        })()
      } else {
        // Clicked somewhere other than a valid 5' end — cancel
        _forcedLigActive      = false
        _forcedLigStrand      = null
        _forcedLigDom         = null
        _forcedLigHoverTarget = null
        _dbgLastEvent = 'pencil: forced-lig cancelled'
        if (DBG) console.log('[FORCED LIG] cancelled — clicked non-5\' target')
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
          // Anchor at the mirror (display) location so the arc starts under the cursor.
          _forcedLigStartX   = _bpCenterX(hit.dom.end_bp + _ghostShiftBp)
          _forcedLigStartY   = trackY
          _forcedLigCursorX  = wx
          _forcedLigCursorY  = wy
          _forcedLigStartShift = _ghostShiftBp   // which seam zone the 3' end was clicked in
          _forcedLigHoverTarget = null
          _dbgLastEvent = `pencil: forced-lig start 3'=${hit.strand.id.slice(0,8)}`
          if (DBG) console.log('[FORCED LIG] start from 3\' end', {
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
        const bp = _xToBp(wx) - _ghostShiftBp   // REAL bp when painting through a mirror
        _painting        = true
        _paintAnchor     = bp
        _paintLo         = bp
        _paintHi         = bp
        _paintIsScaffold = isScaffold
        _paintDirection  = direction
        _paintH          = _helixById.get(hid) ?? null
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
      _scheduleDraw(); return
    }
    if (_endDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const rawDelta = Math.round((wx - _endDragStartWX) / BP_W)
      _endDragDeltaBp = Math.max(_endDragMinDelta, Math.min(_endDragMaxDelta, rawDelta))
      if (_endDragDeltaBp !== 0) _showDragTooltip(e.clientX, e.clientY, _endDragDeltaBp)
      else _hideDragTooltip()
      _scheduleDraw(); return
    }
    if (_domDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const rawDelta = Math.round((wx - _domDragStartWX) / BP_W)
      _domDragDeltaBp = Math.max(_domDragMinDelta, Math.min(_domDragMaxDelta, rawDelta))
      if (_domDragDeltaBp !== 0) _showDragTooltip(e.clientX, e.clientY, _domDragDeltaBp)
      else _hideDragTooltip()
      _scheduleDraw(); return
    }
    if (_xoverDragActive) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      // Subtract the captured mirror shift so the bp is in REAL space when dragging
      // a crossover shown on the mirror side (no-op in the body / boundary off).
      const curBpFrac = (wx - GUTTER) / BP_W - _ghostShiftBp   // fractional for accurate snap distance
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
      _scheduleDraw(); return
    }
    if (_helixDragArmed || _helixDragActive) {
      const dx = e.offsetX - _helixDragStartSX, dy = e.offsetY - _helixDragStartSY
      if (!_helixDragActive && dx * dx + dy * dy > DRAG_THRESHOLD * DRAG_THRESHOLD) _helixDragActive = true
      if (_helixDragActive) {
        _helixDragCursorSY  = e.offsetY
        _helixDragInsertIdx = _gapIndexFromScreenY(e.offsetY)
        canvasEl.style.cursor = 'grabbing'
        _scheduleDraw()
      }
      return
    }
    if (_gutterLassoStarted) {
      _gutterLassoSY1 = e.offsetY
      if (Math.abs(e.offsetY - _gutterLassoSY0) > DRAG_THRESHOLD) _gutterLassoActive = true
      if (_gutterLassoActive) _scheduleDraw()
      return
    }
    if (_panActive) {
      _panX = _panStartPanX + (e.clientX - _panStartCX)
      _panY = _panStartPanY + (e.clientY - _panStartCY)
      if (Math.hypot(e.clientX - _panStartCX, e.clientY - _panStartCY) > DRAG_THRESHOLD) _rightDragMoved = true
      _scheduleDraw(); return
    }
    if (_pbNearDragging || _pbFarDragging) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const bp = _xToBp(wx)
      if (_pbNearDragging) _pbNearBp = Math.min(_pbFarBp - 1, bp)   // keep near ≤ far-1 (P ≥ 1)
      else                 _pbFarBp  = Math.max(_pbNearBp + 1, bp)  // keep far ≥ near+1
      _scheduleDraw(); return
    }
    if (_sliceDragging) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      _updateSliceBp(Math.max(_minBp, Math.min(_totalBp, _xToBp(wx))))
      _scheduleDraw(); return
    }
    if (_painting) {
      const { wx } = _c2w(e.offsetX, e.offsetY)
      const bp = _xToBp(wx) - _ghostShiftBp   // resolve to REAL bp when painting in a mirror zone
      _paintLo = Math.min(_paintAnchor, bp)
      _paintHi = Math.max(_paintAnchor, bp)
      _scheduleDraw(); return
    }
    if (_lassoStarted) {
      const { wx, wy } = _c2w(e.offsetX, e.offsetY)
      _lassoWX1 = wx; _lassoWY1 = wy
      const dx = e.offsetX - _lassoSX0, dy = e.offsetY - _lassoSY0
      if (dx * dx + dy * dy > DRAG_THRESHOLD * DRAG_THRESHOLD) _lassoActive = true
      if (_lassoActive) _scheduleDraw()
      return
    }
    // Track which helix the cursor is over (for scaffold sprite filtering)
    {
      const { wy } = _c2w(e.offsetX, e.offsetY)
      const prev = _hoverHelixId
      _hoverHelixId = _helixAtWY(wy)
      if (_shiftHeld && _hoverHelixId !== prev) _scheduleDraw()
    }
    // Cursor + hover
    if (_activeTool === 'select' && _helixAtGutter(e.offsetX, e.offsetY)) {
      canvasEl.style.cursor = 'grab'
    } else if (_isNearPbSlider(e.offsetX)) {
      canvasEl.style.cursor = 'col-resize'
    } else if (_isNearSliceBar(e.offsetX)) {
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
      // Grab cursor when hovering over an existing crossover arc (draggable),
      // including arcs shown on the mirror side (_screenToRealWorld folds the shift).
      const { wx: hx, wy: hy } = _screenToRealWorld(e.offsetX, e.offsetY)
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
    _updateHoverReadout(e)

    // Nick tool hover ghost — compute potential 3'/5' end cells and redraw
    if (_activeTool === 'nick') {
      if (hit) {
        const { dom } = hit
        const info    = _rowMap.get(dom.helix_id)
        if (!info) { _nickHover = null; _scheduleDraw(); return }
        const { wx }  = _c2w(e.offsetX, e.offsetY)
        const shift   = _ghostShiftForWorldX(wx)   // live shift (hover, not a captured drag)
        const col     = _xToBp(wx) - shift          // REAL bp under cursor
        const nickBp     = _nickBpForDomain(dom, col)
        const threeEndBp = nickBp
        const fiveEndBp  = dom.direction === 'FORWARD' ? nickBp + 1 : nickBp - 1
        const y = dom.direction === 'FORWARD' ? info.fwdY : info.revY
        // shift stored so the hover ghost renders back at the mirror (display) location.
        _nickHover = { threeEndBp, fiveEndBp, y, shift, ligation: _findLigation(dom, col) }
        _dbgDetail = [`  hover: new 3' at bp=${threeEndBp}  new 5' at bp=${fiveEndBp}`]
      } else {
        const hadHover = _nickHover !== null
        _nickHover = null
        if (hadHover) _dbgDetail = []
      }
      _scheduleDraw()
    }
  })

  canvasEl.addEventListener('pointerup', (e) => {
    if ((_pbNearDragging || _pbFarDragging) && e.button === 0) {
      _pbNearDragging = false; _pbFarDragging = false
      _draw(); return
    }
    if ((_helixDragArmed || _helixDragActive) && e.button === 0) {
      const wasActive = _helixDragActive
      _helixDragArmed  = false
      _helixDragActive = false
      canvasEl.style.cursor = 'default'
      if (!wasActive) { _draw(); return }   // pure click — selection set in pointerdown
      const orderedIds = _computeReorderedHelixIds(_helixDragInsertIdx)
      _draw()
      if (orderedIds) onReorderHelices?.(orderedIds)
      return
    }
    if (_gutterLassoStarted && e.button === 0) {
      _gutterLassoStarted = false
      if (_gutterLassoActive) {
        _gutterLassoActive = false
        const y0 = Math.min(_gutterLassoSY0, _gutterLassoSY1)
        const y1 = Math.max(_gutterLassoSY0, _gutterLassoSY1)
        const hits = new Set()
        for (const [hid, info] of _rowMap) {
          const sy = _gutterCircleSY(info)
          if (sy >= y0 && sy <= y1) hits.add(hid)
        }
        if (_gutterLassoCtrl) { for (const h of hits) _selectedHelices.add(h) }
        else                  { _selectedHelices = hits }
      } else if (!_gutterLassoCtrl) {
        // Empty-gutter click (no drag, no ctrl) → clear helix selection.
        _selectedHelices = new Set()
      }
      _draw(); return
    }
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
          if (DBG) console.group(`%c[XOVER BATCH MOVE] pointerup  delta=${delta}  count=${moves.length}`, 'color:lime;font-weight:bold')
          if (DBG) console.log('moves:', JSON.stringify(moves))
          if (DBG) console.groupEnd()
          onBatchMoveCrossovers?.(moves)
        } else {
          if (DBG) console.group(`%c[XOVER MOVE] pointerup  ${_xoverDragOrigIdx} → ${snapBp}`, 'color:lime;font-weight:bold')
          if (DBG) console.log('crossover:', _xoverDragXover.id)
          if (DBG) console.groupEnd()
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
        if (DBG) console.group(`%c[RESIZE] pointerup  delta=${delta}`, 'color:lime;font-weight:bold')
        if (DBG) console.log('apiEntries:', JSON.stringify(apiEntries, null, 2))
        if (DBG) console.groupEnd()
        onResizeEnds?.(apiEntries)
      } else {
        if (DBG) console.log('[RESIZE] pointerup: delta=0, no API call')
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
        if (DBG) console.group(`%c[DOMAIN-SHIFT] pointerup  delta=${delta}`, 'color:lime;font-weight:bold')
        if (DBG) console.log('apiEntries:', JSON.stringify(apiEntries, null, 2))
        if (DBG) console.groupEnd()
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
      // Select click — test domains first, then crossover arcs, then loop/skip.
      // _screenToRealWorld folds the mirror shift so arcs/markers shown on the
      // mirror side select the real crossover/loop-skip.
      const hit    = _hitTest(e.offsetX, e.offsetY, _selectFilter)
      const { wx: cwx, wy: cwy } = _screenToRealWorld(e.offsetX, e.offsetY)
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
    _hideHoverReadout()
    let needDraw = false
    if (_endDragActive)                { _endDragActive = false; _endDragDeltaBp = 0; needDraw = true }
    if (_domDragActive)                { _domDragActive = false; _domDragDeltaBp = 0; _hideDragTooltip(); needDraw = true }
    if (_xoverDragActive)              { _xoverDragActive = false; _xoverDragSnapBp = null; _xoverDragCursorBp = null; _xoverDragGroup = []; _hideDragTooltip(); needDraw = true }
    if (_forcedLigActive)              { _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null; needDraw = true }
    if (_lassoStarted || _lassoActive) { _lassoStarted = false; _lassoActive = false; needDraw = true }
    if (_helixDragArmed || _helixDragActive)      { _helixDragArmed = false; _helixDragActive = false; canvasEl.style.cursor = 'default'; needDraw = true }
    if (_gutterLassoStarted || _gutterLassoActive){ _gutterLassoStarted = false; _gutterLassoActive = false; needDraw = true }
    if (_painting)                     { _painting = false; _paintH = null; needDraw = true }
    if (_pbNearDragging || _pbFarDragging) { _pbNearDragging = false; _pbFarDragging = false; needDraw = true }
    if (_nickHover !== null)           { _nickHover = null; _dbgDetail = []; needDraw = true }
    if (_hoverHelixId !== null)       { _hoverHelixId = null; needDraw = true }
    _ghostShiftBp = 0
    if (needDraw) _draw()
  })

  canvasEl.addEventListener('pointercancel', () => {
    if (_endDragActive)   { _endDragActive = false; _endDragDeltaBp = 0; _draw() }
    if (_domDragActive)   { _domDragActive = false; _domDragDeltaBp = 0; _hideDragTooltip(); _draw() }
    if (_xoverDragActive) { _xoverDragActive = false; _xoverDragSnapBp = null; _xoverDragCursorBp = null; _xoverDragGroup = []; _hideDragTooltip(); _draw() }
    if (_forcedLigActive) { _forcedLigActive = false; _forcedLigStrand = null; _forcedLigDom = null; _forcedLigHoverTarget = null; _draw() }
    if (_helixDragArmed || _helixDragActive)      { _helixDragArmed = false; _helixDragActive = false; canvasEl.style.cursor = 'default'; _draw() }
    if (_gutterLassoStarted || _gutterLassoActive){ _gutterLassoStarted = false; _gutterLassoActive = false; _draw() }
    if (_panActive)       { _panActive = false; _draw() }
    if (_sliceDragging)   { _sliceDragging = false; _draw() }
    if (_pbNearDragging || _pbFarDragging) { _pbNearDragging = false; _pbFarDragging = false; _draw() }
    _ghostShiftBp = 0
  })

  canvasEl.addEventListener('contextmenu', (e) => {
    e.preventDefault()
    // Right-button drag pans the view; this contextmenu is fired on release. If
    // the press actually dragged, swallow it so no menu pops where the drag ended
    // (even if that's on a crossover / overhang / strand). A stationary right-click
    // leaves the flag false and still opens the menu.
    if (_rightDragMoved) { _rightDragMoved = false; return }
    // Resolve through the mirror so right-clicking a crossover arc on the mirror
    // side targets the real crossover.
    const { wx, wy } = _screenToRealWorld(e.offsetX, e.offsetY)
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
      if (DBG) console.log('[FORCED LIG] cancelled via Escape')
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
      _helixDragArmed = false; _helixDragActive = false
      _gutterLassoStarted = false; _gutterLassoActive = false
      if (tool !== 'select') _selectedHelices = new Set()
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
      const next = !!vt.periodicBoundary
      if (next !== _pbActive) {
        _pbActive = next
        // Recompute slider defaults from the current design each time it's enabled;
        // clear when disabled. Camera (pan/zoom) is intentionally left untouched so the
        // toggle preserves the user's current view.
        _pbInit = false
        if (next) _pbInitDefaults()
      }
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
        const oldHelixById = new Map(_design.helices.map(helix => [helix.id, helix]))
        for (const h of design.helices) {
          const old = oldHelixById.get(h.id)
          if (!old || old.length_bp !== h.length_bp || old.bp_start !== h.bp_start)
            changedHelixIds.add(h.id)
        }
        if (DBG && changedHelixIds.size > 0) {
          const nextHelixById = new Map(design.helices.map(helix => [helix.id, helix]))
          console.group(`%c[DESIGN UPDATE] ${changedHelixIds.size} helix(es) changed`, 'color:cyan;font-weight:bold')
          for (const hid of changedHelixIds) {
            const h = nextHelixById.get(hid)
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
      _selectedHelices  = new Set()   // clear gutter-circle selection too
      _rebuildLayout()
      // Periodic boundary: keep sliders in step with the active-strand extent.
      if (_pbActive) {
        if (!_pbInit) {
          _pbInitDefaults()
        } else {
          const ext = _activeStrandExtent()
          if (ext) {
            // Auto-shift fires ONLY when an EDIT grows the extent OUTWARD past a slider
            // (compared to the last-seen extent) — then TRANSLATE the whole window by that
            // delta so the exceeded slider lands on the new extent while the PERIOD P stays
            // constant (the rest of the design / mirror copy doesn't jump). Gating on
            // "extent grew" — NOT merely "the slider sits inside the structure" — lets the
            // user park a slider at an interior jagged point for a puzzle-fit seam without
            // it snapping back out on the next refresh. User rule: a mirrored resize driving
            // the near end to bp -10 moves the seam in by 10; both sliders shift -10, P fixed.
            const prev = _pbLastExt ?? ext
            const grewNear = ext.lo < prev.lo && ext.lo < _pbNearBp
            const grewFar  = ext.hi > prev.hi && ext.hi + 1 > _pbFarBp
            if (grewNear && grewFar) {
              // Both ends grew past at once — P can't be preserved; grow to enclose.
              _pbNearBp = ext.lo; _pbFarBp = ext.hi + 1; _pbFlash()
            } else if (grewNear) {
              const d = ext.lo - _pbNearBp; _pbNearBp += d; _pbFarBp += d; _pbFlash()
            } else if (grewFar) {
              const d = (ext.hi + 1) - _pbFarBp; _pbNearBp += d; _pbFarBp += d; _pbFlash()
            }
            _pbLastExt = ext
          }
        }
      }
      _resize()
      if (!_fitDone && _helices.length > 0) {
        _fitDone = true
        _updateSliceBp(Math.floor(_totalBp / 3))
        requestAnimationFrame(() => { _fitToContent(); _draw() })
      }
    },
  }
}
