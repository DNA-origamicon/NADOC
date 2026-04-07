/**
 * Pathview — Canvas 2D strand editor.
 *
 * Layout
 * ──────
 * One row per helix, sorted by (row, col) from grid_pos.
 * Each helix row contains two tracks:
 *   Top track    — FORWARD strand (5'→3' left-to-right)
 *   Bottom track — REVERSE strand (5'→3' right-to-left)
 *
 * Pixels
 * ──────
 *   GUTTER    80 px  — left label area
 *   TRACK_H   12 px  — height of each single track
 *   GAP_H      8 px  — gap between helix rows
 *   ROW_H     32 px  — total height per helix (TRACK_H*2 + GAP_H + border)
 *   BP_W       8 px  — pixels per base pair (zoomed with Ctrl+scroll)
 *
 * Strand rendering
 * ────────────────
 * Domain → filled rect from lo_bp to hi_bp on the appropriate track.
 * Scaffold: #29b6f6 (sky blue)  Staple: palette colour  Unassigned: #445566
 * 5' end: small filled square    3' end: filled arrowhead
 *
 * Pencil tool (scaffold only, Phase 1)
 * ─────────────────────────────────────
 * mousedown on scaffold track → start drag, record (helix, lo_bp)
 * mousemove → update ghost highlight (no API call)
 * mouseup   → POST /design/scaffold-domain-paint {helix_id, lo_bp, hi_bp}
 *
 * Hover tooltip
 * ─────────────
 * mousemove over any painted domain → call onStrandHover({strandId, strandType, ntCount})
 * mouseleave over canvas → call onStrandHover(null)
 */

// ── Layout constants ──────────────────────────────────────────────────────────

const GUTTER      = 90    // px — left label gutter width
const TRACK_H     = 14    // px — height of one strand track
const TRACK_SEP   = 2     // px — separation between top and bottom tracks
const GAP_H       = 10    // px — vertical gap between helix rows
const ROW_H       = TRACK_H * 2 + TRACK_SEP + GAP_H
const MIN_BP_W    = 2     // px — minimum bp width (zoomed out)
const MAX_BP_W    = 32    // px — maximum bp width (zoomed in)
const ARROW_W     = 6     // px — width of 3' arrowhead

// ── Colours ───────────────────────────────────────────────────────────────────

const CLR_BG          = '#0d1117'
const CLR_TRACK_BG    = '#141c24'
const CLR_TRACK_SCAF  = '#1a2535'   // scaffold-track highlight (slightly brighter)
const CLR_SCAFFOLD    = '#29b6f6'
const CLR_STAPLE      = '#ff8c00'   // fallback; ideally use strand colour
const CLR_LABEL       = '#8b949e'
const CLR_LABEL_HL    = '#e6edf3'
const CLR_GHOST       = 'rgba(41,182,246,0.35)'   // pencil drag ghost

const STAPLE_PALETTE = [
  '#f87171','#fb923c','#fbbf24','#a3e635',
  '#34d399','#22d3ee','#818cf8','#e879f9',
  '#f9a8d4','#6ee7b7','#93c5fd','#fde68a',
]

// ── HC/SQ constants (mirrors sliceview.js) ────────────────────────────────────

const HC_R         = 1.125
const HC_COL_PITCH = HC_R * Math.sqrt(3)
const HC_ROW_PITCH = 2.25
const SQ_PITCH     = 2.25

function hcCellValue(row, col) { return (row + (col % 2 + 2) % 2) % 3 }
function hcIsForward(row, col)  { return hcCellValue(row, col) === 0 }
function sqIsForward(row, col)  { return (((row + col) % 2) + 2) % 2 === 0 }

function hcNmToCell(x, y) {
  const col = Math.round(x / HC_COL_PITCH)
  const rowOff = ((col % 2 + 2) % 2 === 0) ? HC_R : 0
  return { row: Math.round((y - rowOff) / HC_ROW_PITCH), col }
}
function sqNmToCell(x, y) {
  return { row: Math.round(y / SQ_PITCH), col: Math.round(x / SQ_PITCH) }
}

// ── Helix sorting ──────────────────────────────────────────────────────────────

function helixCell(helix, isHC) {
  if (helix.grid_pos) return { row: helix.grid_pos[0], col: helix.grid_pos[1] }
  return isHC
    ? hcNmToCell(helix.axis_start.x, helix.axis_start.y)
    : sqNmToCell(helix.axis_start.x, helix.axis_start.y)
}

function sortedHelices(design) {
  if (!design?.helices?.length) return []
  const isHC = design.lattice_type === 'HONEYCOMB'
  return [...design.helices].sort((a, b) => {
    const ca = helixCell(a, isHC), cb = helixCell(b, isHC)
    return ca.row !== cb.row ? ca.row - cb.row : ca.col - cb.col
  })
}

function helixIsForward(helix, isHC, cell) {
  return isHC ? hcIsForward(cell.row, cell.col) : sqIsForward(cell.row, cell.col)
}

// ── Strand utility ────────────────────────────────────────────────────────────

function strandNtCount(strand) {
  return strand.domains.reduce((sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0)
}

function strandColor(strand, idx) {
  if (strand.strand_type === 'SCAFFOLD') return CLR_SCAFFOLD
  if (strand.color) return strand.color
  return STAPLE_PALETTE[idx % STAPLE_PALETTE.length]
}

// ── Main init ─────────────────────────────────────────────────────────────────

export function initPathview(canvasEl, containerEl, { onPaintScaffold, onStrandHover }) {
  const ctx = canvasEl.getContext('2d')

  // State
  let _design = null
  let _bpW    = 8           // current bp width in pixels
  let _scrollX = 0          // horizontal scroll offset in pixels
  let _helices = []         // sorted helices for current design
  let _rowMap  = new Map()  // helix.id → {y, fwd, cell}  layout info
  let _totalBp = 0          // total bp extent for canvas width

  // Pencil tool state
  let _painting  = false
  let _paintH    = null     // helix being painted
  let _paintLo   = 0        // drag start bp (lower bound, updated live)
  let _paintHi   = 0        // drag end bp   (upper bound, updated live)

  // ── Resize ───────────────────────────────────────────────────────────────────

  function _resize() {
    canvasEl.width  = containerEl.clientWidth  || 800
    canvasEl.height = containerEl.clientHeight || 400
    _draw()
  }
  new ResizeObserver(_resize).observe(containerEl)

  // ── Layout ───────────────────────────────────────────────────────────────────

  function _rebuildLayout() {
    _helices = sortedHelices(_design)
    _rowMap  = new Map()
    const isHC = _design?.lattice_type === 'HONEYCOMB'

    let y = 8   // top padding
    for (const h of _helices) {
      const cell = helixCell(h, isHC)
      const fwd  = helixIsForward(h, isHC, cell)
      _rowMap.set(h.id, { y, fwd, cell })
      y += ROW_H
    }

    // Find total bp extent across all helices
    if (_helices.length === 0) {
      _totalBp = 0
    } else {
      const maxBp = Math.max(..._helices.map(h => h.bp_start + h.length_bp))
      _totalBp = maxBp
    }
  }

  // ── Coordinate helpers ────────────────────────────────────────────────────────

  // bp index → canvas x (accounting for scroll)
  function _bpToX(bp) { return GUTTER + bp * _bpW - _scrollX }

  // canvas x → bp index
  function _xToBp(canvasX) { return Math.floor((canvasX + _scrollX - GUTTER) / _bpW) }

  // canvas y → helix info (returns null if not over a helix)
  function _yToHelix(canvasY) {
    for (const [hid, info] of _rowMap) {
      if (canvasY >= info.y && canvasY < info.y + ROW_H) {
        return { hid, info }
      }
    }
    return null
  }

  // Which track is the cursor in? Returns 'fwd' | 'rev' | null
  function _yToTrack(canvasY, rowY) {
    const rel = canvasY - rowY
    if (rel >= 0 && rel < TRACK_H)               return 'fwd'
    if (rel >= TRACK_H + TRACK_SEP && rel < TRACK_H * 2 + TRACK_SEP) return 'rev'
    return null
  }

  // ── Draw ──────────────────────────────────────────────────────────────────────

  function _draw() {
    const W = canvasEl.width, H = canvasEl.height
    ctx.clearRect(0, 0, W, H)
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, W, H)

    if (!_design?.helices?.length) {
      ctx.fillStyle = CLR_LABEL
      ctx.font = '11px Courier New, monospace'
      ctx.textAlign = 'left'
      ctx.fillText('No helices — click lattice cells in the Slice View to add helices.', 12, 30)
      return
    }

    // ── Draw helix rows ─────────────────────────────────────────────────────────
    for (const [hid, { y, fwd, cell }] of _rowMap) {
      // Row tracks background
      _drawTrackBg(y, fwd)

      // Helix label
      ctx.font = '10px Courier New, monospace'
      ctx.textAlign = 'right'
      ctx.fillStyle = CLR_LABEL
      ctx.fillText(`[${cell.row},${cell.col}]`, GUTTER - 4, y + TRACK_H)

      // Tick marks every 8 bp (crossover period)
      _drawTicks(y)
    }

    // ── Draw strand domains ─────────────────────────────────────────────────────
    if (_design.strands) {
      for (let si = 0; si < _design.strands.length; si++) {
        const strand = _design.strands[si]
        const color  = strandColor(strand, si)
        for (const dom of strand.domains) {
          const info = _rowMap.get(dom.helix_id)
          if (!info) continue
          _drawDomain(dom, info, color)
        }
      }
    }

    // ── Draw pencil ghost ──────────────────────────────────────────────────────
    if (_painting && _paintH) {
      const info = _rowMap.get(_paintH.id)
      if (info) {
        const trackTop = info.fwd
          ? info.y
          : info.y + TRACK_H + TRACK_SEP
        const x1 = _bpToX(_paintLo)
        const x2 = _bpToX(_paintHi + 1)
        ctx.fillStyle = CLR_GHOST
        ctx.fillRect(x1, trackTop, x2 - x1, TRACK_H)
      }
    }

    // ── Gutter background overlay ──────────────────────────────────────────────
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, GUTTER, H)

    // Redraw labels on top of gutter
    for (const [, { y, cell }] of _rowMap) {
      ctx.font = '10px Courier New, monospace'
      ctx.textAlign = 'right'
      ctx.fillStyle = CLR_LABEL
      ctx.fillText(`[${cell.row},${cell.col}]`, GUTTER - 4, y + TRACK_H)
    }

    // Top bp ruler
    _drawRuler()
  }

  function _drawTrackBg(y, fwd) {
    // Top track (FORWARD)
    ctx.fillStyle = fwd ? CLR_TRACK_SCAF : CLR_TRACK_BG
    ctx.fillRect(GUTTER - _scrollX % 1, y, canvasEl.width, TRACK_H)
    // Bottom track (REVERSE)
    ctx.fillStyle = fwd ? CLR_TRACK_BG : CLR_TRACK_SCAF
    ctx.fillRect(GUTTER - _scrollX % 1, y + TRACK_H + TRACK_SEP, canvasEl.width, TRACK_H)
  }

  function _drawTicks(y) {
    ctx.strokeStyle = '#1e2d3d'
    ctx.lineWidth = 1
    const period = 8
    const startBp = Math.floor((_scrollX) / _bpW)
    const endBp   = Math.ceil((_scrollX + canvasEl.width) / _bpW)
    for (let bp = Math.ceil(startBp / period) * period; bp <= endBp; bp += period) {
      const x = _bpToX(bp)
      if (x < GUTTER) continue
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x, y + TRACK_H * 2 + TRACK_SEP)
      ctx.stroke()
    }
  }

  function _drawRuler() {
    ctx.fillStyle = '#161b22'
    ctx.fillRect(0, 0, canvasEl.width, 18)
    ctx.strokeStyle = '#30363d'
    ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(0, 18); ctx.lineTo(canvasEl.width, 18); ctx.stroke()

    ctx.font = '9px Courier New, monospace'
    ctx.textAlign = 'center'
    ctx.fillStyle = '#8b949e'
    const period = _bpW >= 8 ? 10 : _bpW >= 4 ? 25 : 50
    const startBp = Math.floor(_scrollX / _bpW)
    const endBp   = Math.ceil((_scrollX + canvasEl.width) / _bpW)
    for (let bp = Math.ceil(startBp / period) * period; bp <= endBp; bp += period) {
      const x = _bpToX(bp)
      if (x < GUTTER) continue
      ctx.fillText(bp, x, 12)
    }
  }

  function _drawDomain(dom, info, color) {
    const isForwardDom = dom.direction === 'FORWARD'
    const trackTop = isForwardDom
      ? info.y
      : info.y + TRACK_H + TRACK_SEP

    const lo = Math.min(dom.start_bp, dom.end_bp)
    const hi = Math.max(dom.start_bp, dom.end_bp)
    const x1 = _bpToX(lo)
    const x2 = _bpToX(hi + 1)
    const y  = trackTop
    const h  = TRACK_H

    if (x2 < GUTTER || x1 > canvasEl.width) return   // off-screen

    ctx.fillStyle = color

    if (isForwardDom) {
      // 5' square cap on left, 3' arrow on right
      ctx.fillRect(x1, y + 2, Math.max(0, x2 - ARROW_W - x1), h - 4)
      // 5' square
      ctx.fillRect(x1, y + 2, 4, h - 4)
      // 3' arrow (right-pointing)
      if (x2 - ARROW_W >= GUTTER) {
        ctx.beginPath()
        ctx.moveTo(x2 - ARROW_W, y + 2)
        ctx.lineTo(x2,           y + h / 2)
        ctx.lineTo(x2 - ARROW_W, y + h - 2)
        ctx.closePath()
        ctx.fill()
      }
    } else {
      // 5' square cap on right, 3' arrow on left
      ctx.fillRect(x1 + ARROW_W, y + 2, Math.max(0, x2 - ARROW_W - x1), h - 4)
      // 5' square (right end)
      ctx.fillRect(x2 - 4, y + 2, 4, h - 4)
      // 3' arrow (left-pointing)
      if (x1 + ARROW_W <= canvasEl.width) {
        ctx.beginPath()
        ctx.moveTo(x1 + ARROW_W, y + 2)
        ctx.lineTo(x1,           y + h / 2)
        ctx.lineTo(x1 + ARROW_W, y + h - 2)
        ctx.closePath()
        ctx.fill()
      }
    }
  }

  // ── Hit testing ────────────────────────────────────────────────────────────

  /**
   * Find the strand/domain under canvas position (cx, cy).
   * Returns {strand, strandIdx, dom} or null.
   */
  function _hitTest(cx, cy) {
    if (!_design?.strands) return null
    const helixHit = _yToHelix(cy)
    if (!helixHit) return null
    const { hid, info } = helixHit
    const track = _yToTrack(cy, info.y)
    if (!track) return null
    const isFwdTrack = track === 'fwd'
    const bp = _xToBp(cx)

    for (let si = 0; si < _design.strands.length; si++) {
      const strand = _design.strands[si]
      for (const dom of strand.domains) {
        if (dom.helix_id !== hid) continue
        const isFwdDom = dom.direction === 'FORWARD'
        if (isFwdDom !== isFwdTrack) continue
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        if (bp >= lo && bp <= hi) return { strand, strandIdx: si, dom }
      }
    }
    return null
  }

  // ── Mouse events ──────────────────────────────────────────────────────────────

  canvasEl.addEventListener('mousemove', (e) => {
    const { offsetX: cx, offsetY: cy } = e

    if (_painting) {
      const bp = Math.max(0, _xToBp(cx))
      const start = _paintLo  // anchor point set on mousedown
      _paintLo = Math.min(start, bp)
      _paintHi = Math.max(start, bp)
      _draw()
      return
    }

    const hit = _hitTest(cx, cy)
    if (hit) {
      const { strand, strandIdx } = hit
      onStrandHover({
        strandId:   strand.id,
        strandType: strand.strand_type,
        ntCount:    strandNtCount(strand),
      })
    } else {
      onStrandHover(null)
    }
  })

  canvasEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return
    const { offsetX: cx, offsetY: cy } = e

    // Only start painting if pencil tool is active
    // (The active tool is read from the editorStore in main.js — here we
    //  expose a setTool() method and keep the tool state locally.)
    if (_activeTool !== 'pencil') return

    const helixHit = _yToHelix(cy)
    if (!helixHit) return
    const { hid, info } = helixHit
    const track = _yToTrack(cy, info.y)
    if (!track) return

    // Only allow painting on the scaffold track (the highlighted track)
    const scaffoldIsFwd = info.fwd
    if ((track === 'fwd') !== scaffoldIsFwd) return

    const bp = Math.max(0, _xToBp(cx))
    _painting = true
    _paintH   = _design.helices.find(h => h.id === hid) ?? null
    _paintLo  = bp
    _paintHi  = bp
    _draw()
  })

  canvasEl.addEventListener('mouseup', async (e) => {
    if (!_painting) return
    _painting = false
    if (_paintH && _paintLo <= _paintHi) {
      await onPaintScaffold(_paintH.id, _paintLo, _paintHi)
    }
    _paintH = null
    _draw()
  })

  canvasEl.addEventListener('mouseleave', () => {
    onStrandHover(null)
    if (_painting) {
      _painting = false
      _paintH   = null
      _draw()
    }
  })

  // Zoom with Ctrl+scroll
  canvasEl.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) {
      // Plain scroll → horizontal pan
      _scrollX = Math.max(0, _scrollX + e.deltaY)
      e.preventDefault()
      _draw()
      return
    }
    e.preventDefault()
    const oldBpW = _bpW
    _bpW = Math.max(MIN_BP_W, Math.min(MAX_BP_W, _bpW * (e.deltaY < 0 ? 1.15 : 0.87)))
    // Keep cursor bp stationary under mouse
    const bp = _xToBp(e.offsetX)
    _scrollX = Math.max(0, bp * _bpW - (e.offsetX - GUTTER))
    if (_bpW !== oldBpW) _draw()
  }, { passive: false })

  // ── Tool state (set from main.js via setTool) ─────────────────────────────────

  let _activeTool = 'select'

  // ── Public interface ──────────────────────────────────────────────────────────

  return {
    setTool(tool) {
      _activeTool = tool
      canvasEl.style.cursor = tool === 'pencil' ? 'crosshair' : 'default'
    },

    update(design) {
      _design = design
      _rebuildLayout()
      _resize()
    },
  }
}
