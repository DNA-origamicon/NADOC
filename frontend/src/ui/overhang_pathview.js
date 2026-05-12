/**
 * Domain Designer pathview — cadnano-faithful single-overhang renderer.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ [Reset view]                                                 │
 *   │ BP ruler (major every 7|8 bp, minor every 1 bp)              │
 *   ├──────────────────────────────────────────────────────────────┤
 *   │      ╭─╮                                                     │
 *   │  ─┐  │N│  FORWARD row ──■━━━━━━━━━━━━━━━━━━━━━━━━━▶          │
 *   │  ─┘  ╰─╯  REVERSE row    [partner strand if bound/linker]    │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * Rev (2026-05-10):
 *   • light cadnano background (CLR_BG)
 *   • free pan/zoom (right/middle drag = pan, wheel = zoom-on-cursor)
 *   • 150-bp visible canvas; current overhang fits 50% of view on reset
 *   • both grid rows reserved as DNA tracks (sequence letters never
 *     spill into the empty row)
 *   • binding/linker partner sub-domain renders antiparallel on the
 *     opposite row, scaffold-style
 *   • right-click → split sub-domain at cursor bp; left-click → select
 *
 * Public API:
 *
 *     initOverhangPathview(canvasEl, { store, onSplit, onSelectSubDomain, wrapEl? })
 *       → { rebuild(overhangSpec, geometry, design), resetView(), destroy() }
 *
 * Three-Layer Law: this module is RENDER-ONLY. The only mutations are
 * routed through CRUD callbacks — never via direct store writes.
 */

import {
  BP_W,
  CELL_H,
  PAIR_Y,
  GUTTER,
} from '../cadnano-editor/pathview.js'
import {
  STAPLE_PALETTE,
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
  CLR_CELL_BG,
  CLR_CELL_GRID,
} from '../cadnano-editor/pathview/palette.js'

// ── Debug instrumentation ────────────────────────────────────────────────────
const DEBUG = true
const _debug = (...args) => { if (DEBUG) console.debug('[DD-pathview]', ...args) }

// ── Local layout constants (mirror cadnano-editor) ───────────────────────────
const RULER_H       = 26
const LABEL_R       = 12
const TOP_PAD       = 12
const BOTTOM_PAD    = 12

// 150-bp visible window on Reset view; current overhang scales to 50%.
const VISIBLE_WINDOW_BP = 150
const TARGET_OVHG_FRACTION = 0.5

// Empty grid extension on both sides of the overhang strand (bp).
const GRID_EXTEND_BP = 50

// Resize-drag: minimum |delta_bp| before sending a request.
const RESIZE_MIN_DRAG_PX = 2

// Free pan/zoom limits (match cadnano editor MIN/MAX ZOOM).
const MIN_ZOOM = 0.06
const MAX_ZOOM = 10

const SELECT_CLR    = '#1f6feb'
const LOCK_CLR      = '#d08800'
const HOVER_CLR     = '#ff8c00'
const NAME_CLR      = '#1a2530'
const TM_CLR        = '#3a4a58'
const WARN_CLR      = '#d63031'
const SEPARATOR_CLR = 'rgba(60, 80, 100, 0.55)'
const PARTNER_CLR   = CLR_SCAFFOLD     // bound partner uses cadnano scaffold blue

const NAME_FONT     = 'bold 10px sans-serif'
const TM_FONT       = '9px monospace'
const SEQ_FONT      = '8px monospace'
const WARN_FONT     = 'bold 10px sans-serif'
const RULER_FONT    = '9px Courier New, monospace'

const HOVER_DEBOUNCE_MS = 50


// ── Public API ───────────────────────────────────────────────────────────────

export function initOverhangPathview(canvasEl, opts = {}) {
  const {
    store,
    onSplit,
    onSelectSubDomain,
    onResizeFreeEnd,
    onResizeLinker,
    onResizeBinding,
    wrapEl,
  } = opts
  const ctx = canvasEl.getContext('2d')

  // ── Per-instance state ─────────────────────────────────────────────────────
  let _ovhg     = null
  let _design   = null
  let _geometry = null

  // Pan/zoom (world-space px per unit BP_W, world-px = canvas-px when zoom=1).
  let _zoom = 1
  let _panX = 0
  let _panY = 0

  let _panActive    = false
  let _panStartCX   = 0, _panStartCY   = 0
  let _panStartPanX = 0, _panStartPanY = 0

  let _hoverBp      = null
  let _hoverSdId    = null
  let _hoverTimer   = null
  let _tooltipEl    = null

  // Free-end resize drag state.
  let _resizeActive = null  // { end, anchorBp, isFwd, startCX, ghostDelta }

  let _resizeObs    = null


  // ── Coordinate helpers ──────────────────────────────────────────────────────
  // World-space: x = GUTTER + bp * BP_W ; y centered around row pair.
  // Canvas-space: world * zoom + pan.

  function _bpToWX(bp)        { return GUTTER + bp * BP_W }
  function _wxToBp(wx)        { return Math.floor((wx - GUTTER) / BP_W) }
  function _c2w(cx, cy)       { return { wx: (cx - _panX) / _zoom, wy: (cy - _panY) / _zoom } }
  function _bpToCX(bp)        { return _bpToWX(bp) * _zoom + _panX }

  function _line(x1, y1, x2, y2, color, width = 1) {
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.strokeStyle = color
    ctx.lineWidth = width
    ctx.stroke()
  }

  function _colorForSubDomain(sd, idx, strandColor) {
    if (sd.color)    return sd.color
    if (strandColor) return strandColor
    return STAPLE_PALETTE[idx % STAPLE_PALETTE.length] ?? '#a0a0a0'
  }

  function _strandColorFromDesign(design, strandId) {
    const strand = design?.strands?.find(s => s.id === strandId)
    return strand?.color ?? undefined
  }

  function _helixIndex(design, helixId) {
    return design?.helices?.findIndex(h => h.id === helixId) ?? -1
  }

  function _helixDisplayName(design, helixId) {
    const h = design?.helices?.find(hh => hh.id === helixId)
    if (h?.label) return h.label
    const idx = _helixIndex(design, helixId)
    if (idx >= 0) return String(idx)
    return String(helixId).slice(0, 6) + '…'
  }

  /** Resolve the strand domain backing this overhang.
   *
   *  The overhang's `id` is the canonical link, but designs in the wild can
   *  carry "orphan" overhangs (id not on any domain) — typically when an
   *  inline-style overhang and an extrude-style overhang both reference the
   *  same helix. In that case, fall back to the strand's terminal domain on
   *  the overhang's helix so the pathview keeps a stable polarity reference
   *  instead of flipping FORWARD↔REVERSE on every backend round-trip. */
  function _overhangDomain(design, ovhg) {
    if (!design?.strands || !ovhg) return null
    const strand = design.strands.find(s => s.id === ovhg.strand_id)
    if (!strand) return null
    // Strict match by overhang_id.
    const exact = strand.domains?.find(d => d.overhang_id === ovhg.id)
    if (exact) return exact
    // Fallback 1: domain on the overhang's helix that already carries SOME
    // overhang_id tag (typically the inline-overhang sibling pointing at the
    // same physical extrude).
    const onHelix = (strand.domains ?? []).filter(d => d.helix_id === ovhg.helix_id)
    const tagged = onHelix.find(d => d.overhang_id != null)
    if (tagged) return tagged
    // Fallback 2: the strand's terminal domain on this helix (5p or 3p).
    if (onHelix.length) return onHelix[0]
    return null
  }

  /** Determine which strand-end the overhang's free tip is at, and which is
   *  the root (where the strand continues into the rest of the structure).
   *
   *  Returns `{ freeEnd: '5p'|'3p', rootEnd: '5p'|'3p'|null, domIdx, strand }`
   *  where `rootEnd` is null if the overhang spans the whole strand.
   *
   *  Determined from the strand domain order (NOT the ovhg id suffix), which
   *  is robust against renamed inline overhangs:
   *    - overhang at strand[0] → free = 5'      (strand continues 3'-ward)
   *    - overhang at strand[N-1] → free = 3'    (strand continues 5'-ward)
   *    - overhang in the middle → both ends are roots (rare); arbitrarily
   *      treat 5' as free for the resize-cap heuristic.
   */
  function _strandEnds(design, ovhg) {
    if (!design?.strands || !ovhg) return null
    const strand = design.strands.find(s => s.id === ovhg.strand_id)
    if (!strand) return null
    const domains = strand.domains ?? []
    // Try the strict tag match first.
    let domIdx = domains.findIndex(d => d.overhang_id === ovhg.id)
    if (domIdx < 0) {
      // Orphan-overhang fallback: any tagged domain on the same helix.
      domIdx = domains.findIndex(
        d => d.helix_id === ovhg.helix_id && d.overhang_id != null,
      )
    }
    if (domIdx < 0) {
      // Last-resort fallback: first domain that touches the overhang's
      // helix at all. This still gives `_strandEnds` a defined polarity
      // signal so the renderer never silently loses the root-end arc.
      domIdx = domains.findIndex(d => d.helix_id === ovhg.helix_id)
    }
    if (domIdx < 0) return null
    const isFirst = domIdx === 0
    const isLast  = domIdx === domains.length - 1
    if (isFirst && !isLast) return { freeEnd: '5p', rootEnd: '3p', domIdx, strand }
    if (isLast  && !isFirst) return { freeEnd: '3p', rootEnd: '5p', domIdx, strand }
    if (isFirst && isLast)   return { freeEnd: '5p', rootEnd: null, domIdx, strand }
    return { freeEnd: '5p', rootEnd: '3p', domIdx, strand }   // fallback for middle
  }

  // Vertical span allocated to ONE 2×N grid (top row + gap + bottom row).
  const GRID_PAIR_H   = PAIR_Y + CELL_H
  // Inter-grid vertical gap when stacking multiple grids.
  const GRID_STACK_GAP = 28

  /** Two-row layout for grid `kind` ('selected' | 'linker' | 'partner').
   *  Returns FIXED world y-centres for the two row tracks of that grid.
   *
   *  Single-grid mode: 'selected' is the only grid, sitting just below the
   *  ruler (legacy positioning unchanged).
   *  Multi-grid mode: 'partner' (top) / 'linker' (middle) / 'selected'
   *  (bottom), stacked top-to-bottom in that order. */
  function _rowYsWorld(kind = 'selected') {
    const baseSelected = RULER_H + TOP_PAD + CELL_H / 2
    if (kind === 'selected') {
      // Selected grid sits at the legacy y; in multi-grid mode it gets
      // pushed down by `_layout.selectedYShift`.
      const shift = _layout?.selectedYShift ?? 0
      const fwdY = baseSelected + shift
      return { fwdY, revY: fwdY + PAIR_Y }
    }
    if (kind === 'linker') {
      // Linker grid is centered between partner (top) and selected (bottom).
      const baseLinker = baseSelected - (GRID_PAIR_H + GRID_STACK_GAP)
                       + (_layout?.selectedYShift ?? 0)
      return { fwdY: baseLinker, revY: baseLinker + PAIR_Y }
    }
    // 'partner' — top of the stack.
    const basePartner = baseSelected - 2 * (GRID_PAIR_H + GRID_STACK_GAP)
                      + (_layout?.selectedYShift ?? 0)
    return { fwdY: basePartner, revY: basePartner + PAIR_Y }
  }

  /** Computed once per draw; describes the active layout. Module-level so
   *  the helper functions (`_rowYsWorld`, hit-tests, hover) can read it.   */
  let _layout = null

  function _computeLayout() {
    const linkers = _findLinkersForOverhang(_design, _ovhg)
    const linker = linkers[0] ?? null
    const partner = linker ? _partnerOvhgViaLinker(_design, _ovhg, linker) : null
    const strands = linker ? _linkerStrands(_design, linker) : null
    const isMulti = !!(linker && partner)
    return {
      isMulti,
      linker,
      partner,
      linkerStrands: strands,
      // Multi-grid: push the selected grid down so partner+linker fit above.
      selectedYShift: isMulti ? 2 * (GRID_PAIR_H + GRID_STACK_GAP) : 0,
    }
  }

  function _totalBp() {
    if (!_ovhg) return 0
    return (_ovhg.sub_domains ?? []).reduce(
      (acc, sd) => acc + (sd.length_bp ?? 0), 0,
    )
  }

  /** All OverhangConnections (linkers) that reference `ovhg`. */
  function _findLinkersForOverhang(design, ovhg) {
    if (!design?.overhang_connections || !ovhg) return []
    return design.overhang_connections.filter(
      c => c.overhang_a_id === ovhg.id || c.overhang_b_id === ovhg.id,
    )
  }

  /** Linker strands for `conn`. ds → {a, b, s:null}; ss → {a:null, b:null, s}. */
  function _linkerStrands(design, conn) {
    if (!design?.strands || !conn) return { a: null, b: null, s: null }
    if (conn.linker_type === 'ss') {
      const sId = `__lnk__${conn.id}__s`
      return {
        a: null,
        b: null,
        s: design.strands.find(st => st.id === sId) ?? null,
      }
    }
    const aId = `__lnk__${conn.id}__a`
    const bId = `__lnk__${conn.id}__b`
    return {
      a: design.strands.find(s => s.id === aId) ?? null,
      b: design.strands.find(s => s.id === bId) ?? null,
      s: null,
    }
  }

  /** The other overhang's OverhangSpec across the given linker. */
  function _partnerOvhgViaLinker(design, ovhg, conn) {
    if (!design?.overhangs || !ovhg || !conn) return null
    const partnerId = (conn.overhang_a_id === ovhg.id)
      ? conn.overhang_b_id
      : conn.overhang_a_id
    return design.overhangs.find(o => o.id === partnerId) ?? null
  }

  /** Find an OverhangBinding referencing one of this overhang's sub-domains.
   *  Returns {binding, partnerOvhg, partnerSd, isLocalA} or null. */
  function _findPartnerForOverhang(design, ovhg) {
    if (!design?.overhang_bindings || !ovhg) return null
    const myIds = new Set((ovhg.sub_domains ?? []).map(s => s.id))
    for (const b of design.overhang_bindings) {
      const aLocal = myIds.has(b.sub_domain_a_id)
      const bLocal = myIds.has(b.sub_domain_b_id)
      if (!aLocal && !bLocal) continue
      const partnerOvhgId = aLocal ? b.overhang_b_id : b.overhang_a_id
      const partnerSdId   = aLocal ? b.sub_domain_b_id : b.sub_domain_a_id
      const partnerOvhg = design.overhangs?.find(o => o.id === partnerOvhgId)
      if (!partnerOvhg) continue
      const partnerSd = (partnerOvhg.sub_domains ?? []).find(s => s.id === partnerSdId)
      if (!partnerSd) continue
      const localSdId = aLocal ? b.sub_domain_a_id : b.sub_domain_b_id
      const localSd = (ovhg.sub_domains ?? []).find(s => s.id === localSdId)
      return { binding: b, partnerOvhg, partnerSd, localSd, isLocalA: aLocal }
    }
    return null
  }

  /** Find an OverhangConnection (linker) referencing this overhang.
   *  Returns the partner OverhangSpec or null. */
  function _findLinkerPartnerForOverhang(design, ovhg) {
    if (!design?.overhang_connections || !ovhg) return null
    for (const c of design.overhang_connections) {
      const aLocal = c.overhang_a_id === ovhg.id
      const bLocal = c.overhang_b_id === ovhg.id
      if (!aLocal && !bLocal) continue
      const partnerId = aLocal ? c.overhang_b_id : c.overhang_a_id
      const partnerOvhg = design.overhangs?.find(o => o.id === partnerId)
      if (partnerOvhg) return { connection: c, partnerOvhg, isLocalA: aLocal }
    }
    return null
  }


  // ── Draw: background ────────────────────────────────────────────────────────

  function _clearBg() {
    const cssW = canvasEl.cssWidth ?? canvasEl.width
    const cssH = canvasEl.cssHeight ?? canvasEl.height
    // Fill in CSS px (DPR transform applied in _resize), then layer the world
    // via the pan/zoom transform inside the per-section draws.
    ctx.save()
    ctx.setTransform(canvasEl._dpr ?? 1, 0, 0, canvasEl._dpr ?? 1, 0, 0)
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, cssW, cssH)
    ctx.restore()
  }


  // ── Draw: ruler (top band, screen-fixed) ────────────────────────────────────
  //
  // Ticks are drawn in WORLD-bp coordinates but the band itself sits at the
  // top of the screen (NOT panned vertically). Pan-X is honored so the bp
  // numbers track the data; pan-Y is ignored (band is always at canvas top).

  function _drawRuler() {
    const cssW = canvasEl.cssWidth ?? canvasEl.width
    const totalBp = _totalBp()
    ctx.save()
    ctx.fillStyle = CLR_RULER_BG
    ctx.fillRect(0, 0, cssW, RULER_H)
    _line(0, RULER_H, cssW, RULER_H, '#b0bac4', 1)

    if (totalBp <= 0) { ctx.restore(); return }

    const isHC = _design?.lattice_type === 'HONEYCOMB'
    const major = isHC ? 7 : 8

    // Visible bp range, clamped to the extended grid window
    // [-GRID_EXTEND_BP, totalBp + GRID_EXTEND_BP].
    const wxLeft  = (-_panX) / _zoom
    const wxRight = (cssW - _panX) / _zoom
    const bpLo = Math.max(-GRID_EXTEND_BP,
                          Math.floor((wxLeft  - GUTTER) / BP_W) - 1)
    const bpHi = Math.min(totalBp + GRID_EXTEND_BP,
                          Math.ceil((wxRight - GUTTER) / BP_W) + 1)

    const tickTopMajor = RULER_H - 8
    const tickTopMinor = RULER_H - 4
    for (let bp = bpLo; bp <= bpHi; bp++) {
      const x = _bpToCX(bp)
      if (x < GUTTER || x > cssW) continue
      if (bp % major === 0) {
        _line(x, tickTopMajor, x, RULER_H, CLR_TICK_MAJOR, 1)
      } else {
        _line(x, tickTopMinor, x, RULER_H, CLR_TICK_MINOR, 0.5)
      }
    }

    ctx.beginPath(); ctx.rect(GUTTER, 0, cssW - GUTTER, RULER_H); ctx.clip()
    ctx.fillStyle = CLR_RULER_TEXT
    ctx.font = RULER_FONT
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const labelStart = Math.ceil(bpLo / major) * major
    for (let bp = labelStart; bp <= bpHi; bp += major) {
      const x = _bpToCX(bp)
      ctx.fillText(String(bp), x, RULER_H / 2 - 3)
    }
    ctx.restore()
  }


  // ── Draw: gutter (helix label circle on the left, screen-fixed) ─────────────

  /** Draw a single helix-label disc in the gutter at the row-pair midpoint
   *  for the given grid `kind`, with a custom label + colour. */
  function _drawGutterCircle(kind, label, isFwd) {
    const { fwdY, revY } = _rowYsWorld(kind)
    const cy = ((fwdY + revY) / 2) * _zoom + _panY
    const cx = GUTTER / 2

    ctx.beginPath()
    ctx.arc(cx, cy, LABEL_R, 0, 2 * Math.PI)
    ctx.fillStyle   = isFwd ? CLR_LABEL_FWD_FILL   : CLR_LABEL_REV_FILL
    ctx.fill()
    ctx.strokeStyle = isFwd ? CLR_LABEL_FWD_STROKE : CLR_LABEL_REV_STROKE
    ctx.lineWidth = 1.5
    ctx.stroke()

    ctx.fillStyle = CLR_LABEL_TEXT
    ctx.font = `bold ${LABEL_R * 1.0}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(label), cx, cy)
  }

  function _drawGutter() {
    const cssH = canvasEl.cssHeight ?? canvasEl.height
    ctx.save()
    ctx.fillStyle = CLR_BG
    ctx.fillRect(0, 0, GUTTER, cssH)
    _line(GUTTER, 0, GUTTER, cssH, CLR_TRACK, 1)

    if (!_ovhg) { ctx.restore(); return }

    const selDom = _overhangDomain(_design, _ovhg)
    const selIsFwd = selDom?.direction === 'FORWARD'
    const selLabel = _helixDisplayName(_design, _ovhg.helix_id)

    if (_layout?.isMulti) {
      // Three discs: partner (top), linker (middle), selected (bottom).
      if (_layout.partner) {
        const pDom = _overhangDomain(_design, _layout.partner)
        const pIsFwd = pDom?.direction === 'FORWARD'
        const pLabel = _helixDisplayName(_design, _layout.partner.helix_id)
        _drawGutterCircle('partner', pLabel, pIsFwd)
      }
      if (_layout.linker) {
        // Linker bridge has no helix index; use the connection's name (e.g. "L1").
        // Style: neutral grey ring (it's not a strand-type label).
        const { fwdY, revY } = _rowYsWorld('linker')
        const cy = ((fwdY + revY) / 2) * _zoom + _panY
        const cx = GUTTER / 2
        ctx.beginPath()
        ctx.arc(cx, cy, LABEL_R, 0, 2 * Math.PI)
        ctx.fillStyle   = '#5a6770'
        ctx.fill()
        ctx.strokeStyle = '#3a4a58'
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.fillStyle = CLR_LABEL_TEXT
        ctx.font = `bold ${LABEL_R * 1.0}px sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(_layout.linker.name ?? 'L', cx, cy)
      }
      _drawGutterCircle('selected', selLabel, selIsFwd)
    } else {
      // Single-grid layout — one disc, legacy positioning.
      _drawGutterCircle('selected', selLabel, selIsFwd)
    }
    ctx.restore()
  }


  // ── Draw: 2×N grid (BOTH rows reserved as DNA tracks) ───────────────────────

  /** Sum of sub-domain length_bp for any overhang. */
  function _totalBpOf(ovhg) {
    return (ovhg?.sub_domains ?? []).reduce((a, sd) => a + (sd.length_bp ?? 0), 0)
  }

  function _drawTrackGrid(kind = 'selected', overrideTotalBp = null) {
    const totalBp = overrideTotalBp ?? _totalBp()
    if (totalBp <= 0) return
    const { fwdY, revY } = _rowYsWorld(kind)
    const half = CELL_H / 2
    // Grid extends from -GRID_EXTEND_BP to totalBp + GRID_EXTEND_BP. The strand
    // body (drawn separately) still occupies bp 0..totalBp; the extension is
    // empty track providing context.
    const bpLo = -GRID_EXTEND_BP
    const bpHi = totalBp + GRID_EXTEND_BP
    const x0 = _bpToWX(bpLo)
    const xN = _bpToWX(bpHi)
    const isHC = _design?.lattice_type === 'HONEYCOMB'
    const major = isHC ? 7 : 8

    ctx.save()
    ctx.setTransform(
      (canvasEl._dpr ?? 1) * _zoom, 0,
      0, (canvasEl._dpr ?? 1) * _zoom,
      _panX * (canvasEl._dpr ?? 1),
      _panY * (canvasEl._dpr ?? 1),
    )

    // Faint extension cells (slightly fainter so the strand-occupied range
    // visually pops). Strand-occupied cells re-tint over the top.
    ctx.fillStyle = 'rgba(195, 208, 220, 0.22)'
    ctx.fillRect(x0, fwdY - half, xN - x0, CELL_H)
    ctx.fillRect(x0, revY - half, xN - x0, CELL_H)
    // Strand-occupied range — slightly darker.
    ctx.fillStyle = CLR_CELL_BG
    ctx.fillRect(_bpToWX(0), fwdY - half, _bpToWX(totalBp) - _bpToWX(0), CELL_H)
    ctx.fillRect(_bpToWX(0), revY - half, _bpToWX(totalBp) - _bpToWX(0), CELL_H)

    ctx.strokeStyle = CLR_TRACK
    ctx.lineWidth = 0.5 / _zoom
    ctx.strokeRect(x0, fwdY - half, xN - x0, CELL_H)
    ctx.strokeRect(x0, revY - half, xN - x0, CELL_H)

    for (let bp = bpLo; bp <= bpHi; bp++) {
      const x = _bpToWX(bp)
      const isMajor = (bp % major === 0)
      if (isMajor) {
        ctx.beginPath()
        ctx.moveTo(x, fwdY - half - 2); ctx.lineTo(x, revY + half + 2)
        ctx.strokeStyle = CLR_TICK_MAJOR; ctx.lineWidth = 0.7 / _zoom
        ctx.stroke()
      } else {
        ctx.beginPath()
        ctx.moveTo(x, fwdY - half); ctx.lineTo(x, fwdY + half)
        ctx.moveTo(x, revY - half); ctx.lineTo(x, revY + half)
        ctx.strokeStyle = CLR_CELL_GRID; ctx.lineWidth = 0.5 / _zoom
        ctx.stroke()
      }
    }
    ctx.restore()
  }


  // ── Draw: strand body (sub-domain segments + caps + name/Tm/sequence) ───────

  function _drawStrandBodyAndPartner() {
    const totalBp = _totalBp()
    if (totalBp <= 0) return
    const dom = _overhangDomain(_design, _ovhg)
    const isFwd = dom?.direction === 'FORWARD'
    const { fwdY, revY } = _rowYsWorld()
    const half = CELL_H / 2
    const sThick = CELL_H * 0.20
    const sqSz = Math.min(BP_W, CELL_H) * 0.80

    const x1 = _bpToWX(0)
    const x2 = _bpToWX(totalBp)

    const yMain    = isFwd ? fwdY : revY
    const yPartner = isFwd ? revY : fwdY

    const strandColor = _strandColorFromDesign(_design, _ovhg.strand_id)
    const ordered = [..._ovhg.sub_domains].sort(
      (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
    )
    const dd = store.getState().domainDesigner

    // Determine which end is FREE vs ROOT (cadnano-style: root has no cap;
    // body ends at the MIDDLE of the terminal cell where the arc takes over).
    const ends = _strandEnds(_design, _ovhg)
    const rootEnd = ends?.rootEnd                              // '5p' | '3p' | null
    // Visual sides (left vs right of the strand row in screen space):
    //   FORWARD: 5' = LEFT, 3' = RIGHT
    //   REVERSE: 5' = RIGHT, 3' = LEFT
    const leftEnd  = isFwd ? '5p' : '3p'
    const rightEnd = isFwd ? '3p' : '5p'
    const rootIsLeft  = rootEnd === leftEnd
    const rootIsRight = rootEnd === rightEnd

    // Body span:
    //   - At a FREE end: inset by half a cap so the cap shape has room.
    //   - At a ROOT end: extend to the MIDDLE of the terminal cell (where
    //     the crossover arc anchors).
    const leftMidX  = _bpToWX(0 + 0.5)
    const rightMidX = _bpToWX(totalBp - 1 + 0.5)
    const freeLeftStart  = leftEnd  === '5p' ? x1 + sqSz / 2 : x1 + BP_W
    const freeRightEnd   = rightEnd === '5p' ? x2 - sqSz / 2 : x2 - BP_W
    const bodyStartX = rootIsLeft  ? leftMidX  : freeLeftStart
    const bodyEndX   = rootIsRight ? rightMidX : freeRightEnd

    ctx.save()
    ctx.setTransform(
      (canvasEl._dpr ?? 1) * _zoom, 0,
      0, (canvasEl._dpr ?? 1) * _zoom,
      _panX * (canvasEl._dpr ?? 1),
      _panY * (canvasEl._dpr ?? 1),
    )

    // ── PARTNER strand on opposite row (binding OR linker connection) ───
    // In multi-grid mode (linker present), the partner has its OWN grid
    // above; skip the antiparallel-on-opposite-row representation.
    const binding = _layout?.isMulti ? null : _findPartnerForOverhang(_design, _ovhg)
    const linker  = _layout?.isMulti
      ? null
      : (binding ? null : _findLinkerPartnerForOverhang(_design, _ovhg))

    if (binding) {
      // Partner sub-domain renders ANTIPARALLEL across the local sub-domain's
      // bp range. Color = scaffold blue (cadnano convention for the
      // hybridization partner).
      const localSd = binding.localSd
      if (localSd) {
        const sx1 = _bpToWX(localSd.start_bp_offset ?? 0)
        const sx2 = _bpToWX((localSd.start_bp_offset ?? 0) + (localSd.length_bp ?? 0))
        ctx.fillStyle = PARTNER_CLR
        ctx.fillRect(sx1, yPartner - sThick / 2, sx2 - sx1, sThick)

        // End caps mirror cadnano scaffold convention (square 5', triangle 3').
        // Partner is antiparallel — flip the cap orientation relative to local.
        ctx.fillStyle = PARTNER_CLR
        if (isFwd) {
          // partner row = reverse → 5' RIGHT, 3' LEFT
          ctx.fillRect(sx2 - sqSz, yPartner - sqSz / 2, sqSz, sqSz)
          const triEnd = sx1 + BP_W
          ctx.beginPath()
          ctx.moveTo(triEnd, yPartner - half * 0.7)
          ctx.lineTo(sx1,    yPartner)
          ctx.lineTo(triEnd, yPartner + half * 0.7)
          ctx.closePath(); ctx.fill()
        } else {
          ctx.fillRect(sx1, yPartner - sqSz / 2, sqSz, sqSz)
          const triStart = sx2 - BP_W
          ctx.beginPath()
          ctx.moveTo(triStart, yPartner - half * 0.7)
          ctx.lineTo(sx2,      yPartner)
          ctx.lineTo(triStart, yPartner + half * 0.7)
          ctx.closePath(); ctx.fill()
        }

        // Partner sequence letters are drawn by the final top-z-order pass
        // below so they sit above the arc + caps + separators.
      }
    } else if (linker) {
      // No binding but a linker connection exists — show partner overhang's
      // outline on the opposite row (sequence-faint indication only).
      const partnerOvhg = linker.partnerOvhg
      const ordered2 = [...(partnerOvhg.sub_domains ?? [])].sort(
        (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
      )
      const partnerLen = ordered2.reduce((a, sd) => a + (sd.length_bp ?? 0), 0)
      // Scale partner span to fit local strand bp range (visual scaffold hint).
      if (partnerLen > 0) {
        const localLen = totalBp
        for (let i = 0; i < ordered2.length; i++) {
          const sd = ordered2[i]
          const f1 = (sd.start_bp_offset ?? 0) / partnerLen
          const f2 = ((sd.start_bp_offset ?? 0) + (sd.length_bp ?? 0)) / partnerLen
          const sx1 = _bpToWX(f1 * localLen)
          const sx2 = _bpToWX(f2 * localLen)
          ctx.fillStyle = PARTNER_CLR
          ctx.globalAlpha = 0.55
          ctx.fillRect(sx1, yPartner - sThick / 2, sx2 - sx1, sThick)
          ctx.globalAlpha = 1.0
        }
      }
    }

    // ── Coloured body segments per sub-domain (the OVERHANG itself) ─────────
    ordered.forEach((sd, idx) => {
      const sx1 = Math.max(bodyStartX, _bpToWX(sd.start_bp_offset ?? 0))
      const sx2 = Math.min(bodyEndX, _bpToWX((sd.start_bp_offset ?? 0) + (sd.length_bp ?? 0)))
      if (sx2 <= sx1) return
      const color = _colorForSubDomain(sd, idx, strandColor)
      ctx.fillStyle = color
      ctx.fillRect(sx1, yMain - sThick / 2, sx2 - sx1, sThick)

      // Selection highlight.
      if (sd.id === dd.selectedSubDomainId) {
        ctx.save()
        ctx.strokeStyle = SELECT_CLR
        ctx.lineWidth = 2 / _zoom
        ctx.strokeRect(sx1 + 1 / _zoom, yMain - half + 1 / _zoom,
                       (sx2 - sx1) - 2 / _zoom, CELL_H - 2 / _zoom)
        ctx.restore()
      }

      // Override-locked: dashed gold inset.
      if (sd.sequence_override) {
        ctx.save()
        ctx.setLineDash([3 / _zoom, 2 / _zoom])
        ctx.strokeStyle = LOCK_CLR
        ctx.lineWidth = 1.5 / _zoom
        const inset = (sd.id === dd.selectedSubDomainId) ? 3 / _zoom : 0.75 / _zoom
        ctx.strokeRect(sx1 + inset, yMain - half + inset,
                       (sx2 - sx1) - 2 * inset, CELL_H - 2 * inset)
        ctx.restore()
      }

      if (sd.hairpin_warning || sd.dimer_warning) {
        ctx.fillStyle = WARN_CLR
        ctx.font = WARN_FONT
        ctx.textAlign = 'right'
        ctx.textBaseline = 'top'
        ctx.fillText('⚠', sx2 - 2, yMain - half - 1)
      }

      if (sd.name) {
        ctx.fillStyle = NAME_CLR
        ctx.font = NAME_FONT
        ctx.textAlign = 'left'
        ctx.textBaseline = 'bottom'
        ctx.fillText(sd.name, sx1 + 2, yMain - half - 2)
      }

      if (sd.tm_celsius != null) {
        ctx.fillStyle = TM_CLR
        ctx.font = TM_FONT
        ctx.textAlign = 'right'
        ctx.textBaseline = 'bottom'
        ctx.fillText(`${Math.round(sd.tm_celsius)}°`, sx2 - 2, yMain + half + 9)
      }
    })

    // Sub-domain boundary separators on the strand row.
    for (let i = 1; i < ordered.length; i++) {
      const sd = ordered[i]
      const sx = _bpToWX(sd.start_bp_offset ?? 0)
      ctx.beginPath()
      ctx.moveTo(sx, yMain - half + 1)
      ctx.lineTo(sx, yMain + half - 1)
      ctx.strokeStyle = SEPARATOR_CLR
      ctx.lineWidth = 1 / _zoom
      ctx.stroke()
    }

    // 5'/3' end caps on the strand row — only at the FREE end.
    // The ROOT end has NO cap (cadnano convention: the body line stops at
    // the middle of the terminal cell where the crossover arc takes over).
    const first = ordered[0]
    const last  = ordered[ordered.length - 1]
    const firstColor = _colorForSubDomain(first, 0, strandColor)
    const lastColor  = _colorForSubDomain(last, ordered.length - 1, strandColor)

    // Pick the color of whichever sub-domain owns the free end.
    // FORWARD: 5' tip = first sub-domain (offset 0); 3' tip = last.
    // REVERSE: 5' tip = last sub-domain; 3' tip = first.
    const fivePrimeIsFirst = isFwd
    const fivePrimeColor = fivePrimeIsFirst ? firstColor : lastColor
    const threePrimeColor = fivePrimeIsFirst ? lastColor : firstColor

    // Free-end at LEFT: draw the corresponding cap at x1.
    if (!rootIsLeft) {
      if (leftEnd === '5p') {
        ctx.fillStyle = fivePrimeColor
        ctx.fillRect(x1, yMain - sqSz / 2, sqSz, sqSz)
      } else {  // '3p' — triangle pointing LEFT (free 3' tip)
        ctx.fillStyle = threePrimeColor
        const triEnd = x1 + BP_W
        ctx.beginPath()
        ctx.moveTo(triEnd, yMain - half)
        ctx.lineTo(x1,     yMain)
        ctx.lineTo(triEnd, yMain + half)
        ctx.closePath(); ctx.fill()
      }
    }
    // Free-end at RIGHT: draw the corresponding cap at x2.
    if (!rootIsRight) {
      if (rightEnd === '3p') {
        ctx.fillStyle = threePrimeColor
        const triStart = x2 - BP_W
        ctx.beginPath()
        ctx.moveTo(triStart, yMain - half)
        ctx.lineTo(x2,       yMain)
        ctx.lineTo(triStart, yMain + half)
        ctx.closePath(); ctx.fill()
      } else {  // '5p' — square at the right edge (free 5' tip)
        ctx.fillStyle = fivePrimeColor
        ctx.fillRect(x2 - sqSz, yMain - sqSz / 2, sqSz, sqSz)
      }
    }

    // ── Cadnano-style crossover arc at the root end ─────────────────────────
    // The root has NO cap — the colored body ends at the MIDDLE of the
    // terminal cell, and the arc anchors at that exact midpoint, dropping
    // straight down to a distant point that signifies "continues into the
    // bundle".
    if (rootEnd) {
      const rootBp = rootIsLeft ? 0 : (totalBp - 1)
      const rootCenterX = _bpToWX(rootBp + 0.5)
      const yFrom = yMain
      const yEnd  = yPartner + PAIR_Y * 5
      // Slight curvature so it reads as an arc, not a straight line. Bezier
      // control points stay on the rootCenterX column at top + bottom; the
      // mid handle bows out by ~half a bp toward the body side.
      const bowDx = BP_W * 0.5 * (rootIsLeft ? 1 : -1) * (isFwd ? 1 : -1)
      ctx.save()
      ctx.strokeStyle = strandColor || lastColor
      ctx.lineWidth = Math.max(1.5 / _zoom, sThick * 0.6)
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(rootCenterX, yFrom)
      ctx.bezierCurveTo(
        rootCenterX + bowDx, (yFrom + yPartner) / 2,
        rootCenterX + bowDx, yPartner + PAIR_Y * 2,
        rootCenterX,         yEnd,
      )
      ctx.stroke()
      // Arrowhead at the bottom suggesting "exits into the bundle".
      const arrowHalf = Math.max(2.5 / _zoom, sThick * 1.0)
      ctx.fillStyle = strandColor || lastColor
      ctx.beginPath()
      ctx.moveTo(rootCenterX - arrowHalf, yEnd - arrowHalf * 1.4)
      ctx.lineTo(rootCenterX + arrowHalf, yEnd - arrowHalf * 1.4)
      ctx.lineTo(rootCenterX,             yEnd)
      ctx.closePath(); ctx.fill()
      ctx.restore()
    }

    // ── Sequence letters drawn LAST so they sit on top of every other
    // pathview element (arc, caps, separators, partner strand). Sequence
    // letters are the most information-dense glyphs in the row; the user
    // wants them readable above all other ink. ────────────────────────────
    if (BP_W * _zoom >= 7) {
      ctx.save()
      ctx.font = SEQ_FONT
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      // Local strand sequences.
      ctx.fillStyle = '#0a1a2a'
      ordered.forEach((sd) => {
        const seq = sd.sequence_override
          ?? (_ovhg.sequence ? _ovhg.sequence.slice(
                sd.start_bp_offset ?? 0,
                (sd.start_bp_offset ?? 0) + (sd.length_bp ?? 0),
              ) : null)
        if (!seq) return
        for (let i = 0; i < seq.length && i < (sd.length_bp ?? 0); i++) {
          const cx = _bpToWX((sd.start_bp_offset ?? 0) + i + 0.5)
          ctx.fillText(seq[i], cx, yMain)
        }
      })
      // Partner sequence letters (binding only — linker is decorative).
      if (binding) {
        const localSd = binding.localSd
        const partnerSd = binding.partnerSd
        let partnerSeq = partnerSd?.sequence_override
        if (!partnerSeq && binding.partnerOvhg?.sequence) {
          const start = partnerSd.start_bp_offset ?? 0
          partnerSeq = binding.partnerOvhg.sequence.slice(
            start, start + (partnerSd.length_bp ?? 0),
          )
        }
        if (partnerSeq && localSd) {
          ctx.fillStyle = '#0a3a6e'
          const localStart = localSd.start_bp_offset ?? 0
          const len = localSd.length_bp ?? 0
          for (let i = 0; i < len && i < partnerSeq.length; i++) {
            const localBp = localStart + (len - 1 - i)
            const cx = _bpToWX(localBp + 0.5)
            ctx.fillText(partnerSeq[i], cx, yPartner)
          }
        }
      }
      ctx.restore()
    }

    // ── Inline labels: "overhang" + "OH linker" ─────────────────────────────
    // Drawn above the strand-body cells so they sit in the empty space inside
    // the row (between sub-domain name labels and the BP ruler).
    ctx.save()
    ctx.font = `bold ${Math.max(9, 10 / _zoom)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#3a4a58'
    const labelMidX = (_bpToWX(0) + _bpToWX(totalBp)) / 2
    // Y for the "overhang" label: just above the strand row name labels.
    const yMainLabel = yMain - half - CELL_H * 1.4
    ctx.fillText('overhang', labelMidX, yMainLabel)
    // Only render the partner label when there's actually a partner drawn.
    if (binding || linker) {
      ctx.fillStyle = '#1a4d80'
      const yPartnerLabel = yPartner + half + CELL_H * 1.0
      ctx.fillText('OH linker', labelMidX, yPartnerLabel)
    }
    ctx.restore()

    ctx.restore()
  }


  // ── Draw: partner overhang grid (multi-grid mode only) ───────────────────
  //
  // Renders the partner overhang's body in its OWN 2×N grid above the linker
  // bridge. The crossover arc goes UPWARD (symbolising the partner's root
  // into a DIFFERENT bundle), in contrast to the selected overhang's DOWNWARD
  // arc. Sub-domain colors, sequence letters, name + Tm glyphs all draw the
  // same way as for the selected grid.

  function _drawPartnerOverhangBody(partner) {
    const totalBp = _totalBpOf(partner)
    if (totalBp <= 0) return
    const dom = _overhangDomain(_design, partner)
    const isFwd = dom?.direction === 'FORWARD'
    const { fwdY, revY } = _rowYsWorld('partner')
    const half = CELL_H / 2
    const sThick = CELL_H * 0.20
    const sqSz = Math.min(BP_W, CELL_H) * 0.80
    const x1 = _bpToWX(0)
    const x2 = _bpToWX(totalBp)
    const yMain    = isFwd ? fwdY : revY
    const yPartner = isFwd ? revY : fwdY

    const strandColor = _strandColorFromDesign(_design, partner.strand_id)
    const ordered = [...(partner.sub_domains ?? [])].sort(
      (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
    )
    const dd = store.getState().domainDesigner

    // Root determination (root has no cap; arc lives at midcell).
    const ends = _strandEnds(_design, partner)
    const rootEnd = ends?.rootEnd
    const leftEnd  = isFwd ? '5p' : '3p'
    const rightEnd = isFwd ? '3p' : '5p'
    const rootIsLeft  = rootEnd === leftEnd
    const rootIsRight = rootEnd === rightEnd

    const leftMidX  = _bpToWX(0 + 0.5)
    const rightMidX = _bpToWX(totalBp - 1 + 0.5)
    const freeLeftStart  = leftEnd  === '5p' ? x1 + sqSz / 2 : x1 + BP_W
    const freeRightEnd   = rightEnd === '5p' ? x2 - sqSz / 2 : x2 - BP_W
    const bodyStartX = rootIsLeft  ? leftMidX  : freeLeftStart
    const bodyEndX   = rootIsRight ? rightMidX : freeRightEnd

    ctx.save()
    ctx.setTransform(
      (canvasEl._dpr ?? 1) * _zoom, 0,
      0, (canvasEl._dpr ?? 1) * _zoom,
      _panX * (canvasEl._dpr ?? 1),
      _panY * (canvasEl._dpr ?? 1),
    )

    // Coloured sub-domain bars.
    ordered.forEach((sd, idx) => {
      const sx1 = Math.max(bodyStartX, _bpToWX(sd.start_bp_offset ?? 0))
      const sx2 = Math.min(bodyEndX, _bpToWX((sd.start_bp_offset ?? 0) + (sd.length_bp ?? 0)))
      if (sx2 <= sx1) return
      const color = _colorForSubDomain(sd, idx, strandColor)
      ctx.fillStyle = color
      ctx.fillRect(sx1, yMain - sThick / 2, sx2 - sx1, sThick)

      // Selection highlight (sub-domain selected via this partner grid).
      if (sd.id === dd.selectedSubDomainId && dd.selectedOverhangId === partner.id) {
        ctx.save()
        ctx.strokeStyle = SELECT_CLR
        ctx.lineWidth = 2 / _zoom
        ctx.strokeRect(sx1 + 1 / _zoom, yMain - half + 1 / _zoom,
                       (sx2 - sx1) - 2 / _zoom, CELL_H - 2 / _zoom)
        ctx.restore()
      }

      if (sd.name) {
        ctx.fillStyle = NAME_CLR
        ctx.font = NAME_FONT
        ctx.textAlign = 'left'
        ctx.textBaseline = 'bottom'
        ctx.fillText(sd.name, sx1 + 2, yMain - half - 2)
      }
    })

    // 5'/3' free-end cap on the strand row (root end has no cap).
    const first = ordered[0]
    const last  = ordered[ordered.length - 1]
    const firstColor = _colorForSubDomain(first, 0, strandColor)
    const lastColor  = _colorForSubDomain(last, ordered.length - 1, strandColor)
    const fivePrimeColor  = isFwd ? firstColor : lastColor
    const threePrimeColor = isFwd ? lastColor  : firstColor

    if (!rootIsLeft) {
      if (leftEnd === '5p') {
        ctx.fillStyle = fivePrimeColor
        ctx.fillRect(x1, yMain - sqSz / 2, sqSz, sqSz)
      } else {
        ctx.fillStyle = threePrimeColor
        const triEnd = x1 + BP_W
        ctx.beginPath()
        ctx.moveTo(triEnd, yMain - half)
        ctx.lineTo(x1,     yMain)
        ctx.lineTo(triEnd, yMain + half)
        ctx.closePath(); ctx.fill()
      }
    }
    if (!rootIsRight) {
      if (rightEnd === '3p') {
        ctx.fillStyle = threePrimeColor
        const triStart = x2 - BP_W
        ctx.beginPath()
        ctx.moveTo(triStart, yMain - half)
        ctx.lineTo(x2,       yMain)
        ctx.lineTo(triStart, yMain + half)
        ctx.closePath(); ctx.fill()
      } else {
        ctx.fillStyle = fivePrimeColor
        ctx.fillRect(x2 - sqSz, yMain - sqSz / 2, sqSz, sqSz)
      }
    }

    // Root-end crossover arc — points UP from the partner's root midpoint
    // out the top of the partner grid (symbolises "continues into another
    // bundle").
    if (rootEnd) {
      const rootBp = rootIsLeft ? 0 : (totalBp - 1)
      const rootCenterX = _bpToWX(rootBp + 0.5)
      const yFrom = yMain
      const yEnd  = yPartner - PAIR_Y * 5
      const bowDx = BP_W * 0.5 * (rootIsLeft ? 1 : -1) * (isFwd ? 1 : -1)
      ctx.save()
      ctx.strokeStyle = strandColor || lastColor
      ctx.lineWidth = Math.max(1.5 / _zoom, sThick * 0.6)
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(rootCenterX, yFrom)
      ctx.bezierCurveTo(
        rootCenterX + bowDx, (yFrom + yPartner) / 2,
        rootCenterX + bowDx, yPartner - PAIR_Y * 2,
        rootCenterX,         yEnd,
      )
      ctx.stroke()
      const arrowHalf = Math.max(2.5 / _zoom, sThick * 1.0)
      ctx.fillStyle = strandColor || lastColor
      ctx.beginPath()
      ctx.moveTo(rootCenterX - arrowHalf, yEnd + arrowHalf * 1.4)
      ctx.lineTo(rootCenterX + arrowHalf, yEnd + arrowHalf * 1.4)
      ctx.lineTo(rootCenterX,             yEnd)
      ctx.closePath(); ctx.fill()
      ctx.restore()
    }

    // Sequence letters (top z-order within this grid).
    if (BP_W * _zoom >= 7) {
      ctx.fillStyle = '#0a1a2a'
      ctx.font = SEQ_FONT
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ordered.forEach((sd) => {
        const seq = sd.sequence_override
          ?? (partner.sequence ? partner.sequence.slice(
                sd.start_bp_offset ?? 0,
                (sd.start_bp_offset ?? 0) + (sd.length_bp ?? 0),
              ) : null)
        if (!seq) return
        for (let i = 0; i < seq.length && i < (sd.length_bp ?? 0); i++) {
          const cx = _bpToWX((sd.start_bp_offset ?? 0) + i + 0.5)
          ctx.fillText(seq[i], cx, yMain)
        }
      })
    }

    // Inline label.
    ctx.fillStyle = '#3a4a58'
    ctx.font = `bold ${Math.max(9, 10 / _zoom)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(`partner: ${partner.label ?? partner.id.slice(0, 8)}`,
                 (x1 + x2) / 2, yMain - half - CELL_H * 1.4)

    ctx.restore()
  }


  // ── Draw: linker bridge grid (multi-grid mode only) ──────────────────────
  //
  // For each linker strand (1 for ss, 2 for ds), draws the [0]-indexed domain
  // (the ssDNA/dsDNA bridge living on the linker helix). Each strand gets a
  // 5' square + 3' triangle cap and a coloured body line. Sub-domains aren't
  // a thing on linker strands in NADOC — linkers are raw synthetic strands.

  function _drawLinkerBridgeBody(conn, strands) {
    const bridgeBp = Math.max(
      ...(conn.length_unit === 'bp' ? [conn.length_value] : [30]),
      1,
    )
    const { fwdY, revY } = _rowYsWorld('linker')
    const half = CELL_H / 2
    const sThick = CELL_H * 0.20
    const sqSz = Math.min(BP_W, CELL_H) * 0.80
    const x1 = _bpToWX(0)
    const x2 = _bpToWX(bridgeBp)

    ctx.save()
    ctx.setTransform(
      (canvasEl._dpr ?? 1) * _zoom, 0,
      0, (canvasEl._dpr ?? 1) * _zoom,
      _panX * (canvasEl._dpr ?? 1),
      _panY * (canvasEl._dpr ?? 1),
    )

    function _drawLinkerStrand(strand, y, label) {
      if (!strand) return
      // Resolve the bridge domain (the one on the linker helix `__lnk__*`).
      const bridgeDom = (strand.domains ?? []).find(
        d => d.helix_id && d.helix_id.startsWith('__lnk__'),
      )
      if (!bridgeDom) return
      const isFwd = bridgeDom.direction === 'FORWARD'
      // Reject near-white colors (legacy default linker color was #ffffff,
      // invisible on the light cadnano background) — fall back to a strand-
      // distinguishing palette: blue for strand A, orange for strand B,
      // teal for the single ss strand. New linkers default to cyan and are
      // already legible, so the fallback only fires on legacy designs.
      const rawColor = (strand.color ?? '').toLowerCase()
      const isNearWhite = /^#?(f[0-9a-f]){3}$/i.test(rawColor)
      const fallback = (label === 'A') ? '#1f6feb'
                     : (label === 'B') ? '#f0883e'
                                       : '#16a085'   // ss
      const color = (rawColor && !isNearWhite) ? rawColor : fallback

      // Determine which end(s) are STRAND TIPS (=> caps) vs CROSSOVERS
      // (=> cell-centre body terminus). For the bridge:
      //   - if it's the FIRST domain in the strand: 5' end is the strand's
      //     5' tip → 5' cap (square).
      //   - if it's the LAST domain: 3' end is the strand's 3' tip →
      //     3' cap (triangle).
      //   - if MIDDLE (ss case [complementA, bridge, complementB]): both
      //     ends are crossovers → no caps.
      const idx = strand.domains.findIndex(d => d === bridgeDom)
      const bridgeIsFirst = idx === 0
      const bridgeIsLast  = idx === strand.domains.length - 1
      const fivePrimeIsTip  = bridgeIsFirst                    // strand 5'
      const threePrimeIsTip = bridgeIsLast                     // strand 3'

      // Cap-edge X for the 5' tip side; otherwise cell-centre.
      const fivePrimeMidX  = isFwd ? _bpToWX(0 + 0.5)            : _bpToWX(bridgeBp - 1 + 0.5)
      const threePrimeMidX = isFwd ? _bpToWX(bridgeBp - 1 + 0.5) : _bpToWX(0 + 0.5)
      const fivePrimeAnchorX = fivePrimeIsTip
        ? (isFwd ? (x1 + sqSz / 2) : (x2 - sqSz / 2))
        : fivePrimeMidX
      const threePrimeAnchorX = threePrimeIsTip
        ? (isFwd ? (x2 - BP_W * 0.4) : (x1 + BP_W * 0.4))
        : threePrimeMidX

      ctx.fillStyle = color
      const bodyL = Math.min(fivePrimeAnchorX, threePrimeAnchorX)
      const bodyR = Math.max(fivePrimeAnchorX, threePrimeAnchorX)
      ctx.fillRect(bodyL, y - sThick / 2, bodyR - bodyL, sThick)

      // Caps only at strand tips.
      if (fivePrimeIsTip) {
        if (isFwd) {
          ctx.fillRect(x1, y - sqSz / 2, sqSz, sqSz)            // 5' square LEFT
        } else {
          ctx.fillRect(x2 - sqSz, y - sqSz / 2, sqSz, sqSz)     // 5' square RIGHT
        }
      }
      if (threePrimeIsTip) {
        if (isFwd) {
          // 3' triangle pointing RIGHT (FWD).
          const triStart = x2 - BP_W
          ctx.beginPath()
          ctx.moveTo(triStart, y - half)
          ctx.lineTo(x2,       y)
          ctx.lineTo(triStart, y + half)
          ctx.closePath(); ctx.fill()
        } else {
          // 3' triangle pointing LEFT (REV).
          const triEnd = x1 + BP_W
          ctx.beginPath()
          ctx.moveTo(triEnd, y - half)
          ctx.lineTo(x1,     y)
          ctx.lineTo(triEnd, y + half)
          ctx.closePath(); ctx.fill()
        }
      }

      // Optional sequence overlay if the linker strand has a sequence.
      if (BP_W * _zoom >= 7 && strand.sequence) {
        ctx.save()
        ctx.fillStyle = '#0a1a2a'
        ctx.font = SEQ_FONT
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        const len = bridgeDom.end_bp - bridgeDom.start_bp
        const span = Math.abs(len) + 1
        // Map strand's full sequence indices onto the bridge bp window.
        for (let i = 0; i < span && i < strand.sequence.length; i++) {
          const cx = _bpToWX((isFwd ? i : (span - 1 - i)) + 0.5)
          ctx.fillText(strand.sequence[i], cx, y)
        }
        ctx.restore()
      }

      // Tag the strand row with a tiny label on the LEFT margin.
      ctx.fillStyle = '#3a4a58'
      ctx.font = NAME_FONT
      ctx.textAlign = 'right'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, x1 - 4, y)
    }

    // ds: strand A on top row, strand B on bottom row.
    // ss: single strand __s drawn on the centre row (between fwdY and revY).
    if (conn.linker_type === 'ss' && strands.s) {
      const ssY = (fwdY + revY) / 2
      _drawLinkerStrand(strands.s, ssY, 'S')
    } else {
      _drawLinkerStrand(strands.a, fwdY, 'A')
      if (conn.linker_type === 'ds' && strands.b) {
        _drawLinkerStrand(strands.b, revY, 'B')
      }
    }

    // Centre inline label.
    ctx.fillStyle = '#1a4d80'
    ctx.font = `bold ${Math.max(9, 10 / _zoom)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const labelText = `linker · ${conn.linker_type.toUpperCase()} · ${conn.length_value} ${conn.length_unit}`
    ctx.fillText(labelText, (x1 + x2) / 2, fwdY - half - CELL_H * 0.8)

    ctx.restore()
  }


  // ── Draw: linker binding domains + crossover-to-bridge arcs (multi-grid) ──
  //
  // Each linker strand has TWO domains in this codebase:
  //   [0] bridge  — on the linker helix `__lnk__{conn_id}` (drawn in linker grid)
  //   [1] binding — on one of the overhang helices (the part that hybridises
  //                 with the local overhang strand)
  // The binding domain renders as an antiparallel coloured bar on the OPPOSITE
  // row of the relevant overhang grid (selected or partner) with full 5'/3'
  // square + triangle caps. A crossover arc connects the binding domain's
  // junction-end to the matching end of the bridge in the linker grid.

  /** Returns the strand's domain that lives on `targetHelixId`, or null. */
  function _domainOnHelix(strand, targetHelixId) {
    return (strand?.domains ?? []).find(d => d.helix_id === targetHelixId) ?? null
  }

  /** Resolve the linker strand color (rejecting near-white defaults). */
  function _linkerStrandColor(strand, label) {
    const raw = (strand?.color ?? '').toLowerCase()
    const isNearWhite = /^#?(f[0-9a-f]){3}$/i.test(raw)
    if (raw && !isNearWhite) return raw
    return label === 'A' ? '#1f6feb' : '#f0883e'
  }

  /** Draw the binding-domain antiparallel on the OPPOSITE row of `kind` grid.
   *  Returns the {x, y} canvas-px anchor of the binding's "bridge-side" end
   *  (the end where the strand crosses to the bridge), so the caller can
   *  draw the crossover arc back to the bridge. */
  function _drawLinkerBindingDomain(strand, ovhg, kind, label) {
    if (!strand || !ovhg) return null
    const bindingDom = _domainOnHelix(strand, ovhg.helix_id)
    if (!bindingDom) return null
    // Resolve the overhang's backing-domain bp_lo so we can convert the
    // binding's helix-bp range to the overhang's LOCAL bp coordinates.
    const ovhgDom = _overhangDomain(_design, ovhg)
    if (!ovhgDom) return null
    const ovhgBpLo = Math.min(ovhgDom.start_bp, ovhgDom.end_bp)

    const bindBpLo = Math.min(bindingDom.start_bp, bindingDom.end_bp)
    const bindBpHi = Math.max(bindingDom.start_bp, bindingDom.end_bp)
    const localLo  = bindBpLo - ovhgBpLo
    const localHi  = bindBpHi - ovhgBpLo

    const dom = _overhangDomain(_design, ovhg)
    const isFwd = dom?.direction === 'FORWARD'
    const { fwdY, revY } = _rowYsWorld(kind)
    // The binding sits on the OPPOSITE row of the local strand.
    const yBind = isFwd ? revY : fwdY

    const sThick = CELL_H * 0.20
    const half = CELL_H / 2
    const sqSz = Math.min(BP_W, CELL_H) * 0.80
    const sx1 = _bpToWX(localLo)
    const sx2 = _bpToWX(localHi + 1)   // inclusive bp range
    const color = _linkerStrandColor(strand, label)

    ctx.save()
    ctx.setTransform(
      (canvasEl._dpr ?? 1) * _zoom, 0,
      0, (canvasEl._dpr ?? 1) * _zoom,
      _panX * (canvasEl._dpr ?? 1),
      _panY * (canvasEl._dpr ?? 1),
    )

    // Binding body. Determine which end is the strand's actual TIP (cap)
    // vs the CROSSOVER junction (no cap, cell-centre):
    //   - bindingDom is FIRST domain in strand → 5' is strand's 5' tip → square cap.
    //   - bindingDom is LAST domain in strand → 3' is strand's 3' tip → triangle cap.
    //   - middle (shouldn't happen for bindings) → no caps.
    const bindIdx = strand.domains.findIndex(d => d === bindingDom)
    const bindIsFirst = bindIdx === 0
    const bindIsLast  = bindIdx === strand.domains.length - 1
    const fivePrimeIsTip  = bindIsFirst   // 5' = strand 5' tip → square cap
    const threePrimeIsTip = bindIsLast    // 3' = strand 3' tip → triangle cap

    const bindIsFwd = bindingDom.direction === 'FORWARD'
    const localFiveMidX   = bindIsFwd ? _bpToWX(localLo + 0.5) : _bpToWX(localHi + 0.5)
    const localThreeMidX  = bindIsFwd ? _bpToWX(localHi + 0.5) : _bpToWX(localLo + 0.5)
    // 5' anchor: cell-centre (crossover) or cap-edge (strand tip).
    const fivePrimeAnchorX = fivePrimeIsTip
      ? (bindIsFwd ? (sx1 + sqSz / 2) : (sx2 - sqSz / 2))
      : localFiveMidX
    // 3' anchor: cap-edge (strand tip) or cell-centre (crossover).
    const threePrimeAnchorX = threePrimeIsTip
      ? (bindIsFwd ? (sx2 - BP_W * 0.4) : (sx1 + BP_W * 0.4))
      : localThreeMidX

    ctx.fillStyle = color
    const bodyL = Math.min(fivePrimeAnchorX, threePrimeAnchorX)
    const bodyR = Math.max(fivePrimeAnchorX, threePrimeAnchorX)
    ctx.fillRect(bodyL, yBind - sThick / 2, bodyR - bodyL, sThick)

    // 5' square cap (only when 5' is the strand's tip).
    if (fivePrimeIsTip) {
      if (bindIsFwd) {
        ctx.fillRect(sx1, yBind - sqSz / 2, sqSz, sqSz)
      } else {
        ctx.fillRect(sx2 - sqSz, yBind - sqSz / 2, sqSz, sqSz)
      }
    }
    // 3' triangle cap (only when 3' is the strand's tip).
    if (threePrimeIsTip) {
      if (bindIsFwd) {
        const triStart = sx2 - BP_W
        ctx.beginPath()
        ctx.moveTo(triStart, yBind - half)
        ctx.lineTo(sx2,      yBind)
        ctx.lineTo(triStart, yBind + half)
        ctx.closePath(); ctx.fill()
      } else {
        const triEnd = sx1 + BP_W
        ctx.beginPath()
        ctx.moveTo(triEnd, yBind - half)
        ctx.lineTo(sx1,    yBind)
        ctx.lineTo(triEnd, yBind + half)
        ctx.closePath(); ctx.fill()
      }
    }
    ctx.restore()

    // Crossover-junction anchor for the caller. Junction is the OPPOSITE
    // end of the strand-tip end:
    //   - bindingDom is FIRST (strand 5' tip on this binding) → junction at 3'.
    //   - bindingDom is LAST  (strand 3' tip on this binding) → junction at 5'.
    const junctionEnd = bindIsFirst ? '3p' : '5p'
    const junctionBp = (junctionEnd === '5p')
      ? (bindIsFwd ? localLo : localHi)
      : (bindIsFwd ? localHi : localLo)
    const junctionMidX = _bpToWX(junctionBp + 0.5)
    return {
      bindAnchorX: junctionMidX * _zoom + _panX,
      bindAnchorY: yBind * _zoom + _panY,
      color,
      junctionEnd,    // '5p' or '3p' — bridge connects to the OPPOSITE end
    }
  }

  /** Draw a single Bezier arc from `(xBridge, yBridge)` (a cell-centre on
   *  the linker grid) to the binding's junction anchor.  */
  function _drawArcBetween(xBridge, yBridge, bindingAnchor) {
    if (!bindingAnchor) return
    const sThick = CELL_H * 0.20
    const xEnd = bindingAnchor.bindAnchorX
    const yEnd = bindingAnchor.bindAnchorY
    ctx.save()
    ctx.strokeStyle = bindingAnchor.color
    ctx.lineWidth = Math.max(1.5, sThick * _zoom * 0.6)
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(xBridge, yBridge)
    const yMid = (yBridge + yEnd) / 2
    ctx.bezierCurveTo(
      xBridge, yMid,
      xEnd,    yMid,
      xEnd,    yEnd,
    )
    ctx.stroke()
    ctx.restore()
  }

  /** Resolve the canvas-px anchor of a specific bridge END (5p|3p) on the
   *  linker grid row `yWorld` for a given bridge domain. */
  function _bridgeEndAnchor(bridgeDom, conn, yWorld, end) {
    const bridgeIsFwd = bridgeDom.direction === 'FORWARD'
    const bridgeBp = (conn.length_unit === 'bp') ? conn.length_value : 30
    // Compute the bp at the requested end of the bridge.
    let bp
    if (end === '5p') bp = bridgeIsFwd ? 0          : bridgeBp
    else              bp = bridgeIsFwd ? bridgeBp   : 0
    // Cell-centre x for that bp (adjust ±0.5 inward).
    const offset = (end === '5p')
      ? (bridgeIsFwd ?  0.5 : -0.5)
      : (bridgeIsFwd ? -0.5 :  0.5)
    const xWorld = _bpToWX(bp + offset)
    return { x: xWorld * _zoom + _panX, y: yWorld * _zoom + _panY }
  }

  /** Draw bridge↔binding crossover arcs for ds (per-side strands). */
  function _drawLinkerCrossoversDs(conn, strands, bindingAnchors) {
    if (!conn) return
    const { fwdY: linkFwd, revY: linkRev } = _rowYsWorld('linker')

    function _arcForSide(bridgeStrand, label, bindingAnchor) {
      if (!bridgeStrand || !bindingAnchor) return
      const bridgeDom = (bridgeStrand.domains ?? []).find(
        d => d.helix_id && d.helix_id.startsWith('__lnk__'),
      )
      if (!bridgeDom) return
      // Bridge row Y: A on linker.fwdY, B on linker.revY.
      const yBridge = label === 'A' ? linkFwd : linkRev
      // The bridge end that connects to this binding is the OPPOSITE of the
      // binding's junctionEnd (e.g., binding's 5' junction → bridge's 5' tip).
      const bridgeEnd = bindingAnchor.junctionEnd === '5p' ? '5p' : '3p'
      const anchor = _bridgeEndAnchor(bridgeDom, conn, yBridge, bridgeEnd)
      _drawArcBetween(anchor.x, anchor.y, bindingAnchor)
    }
    _arcForSide(strands.a, 'A', bindingAnchors.aSide)
    _arcForSide(strands.b, 'B', bindingAnchors.bSide)
  }

  /** Draw the TWO crossover arcs for an ss linker (single strand
   *  [complementA, bridge, complementB]). Each arc connects one bridge end
   *  to its corresponding complement's junction anchor. */
  function _drawLinkerCrossoversSs(conn, strandS, anchorA, anchorB) {
    if (!conn || !strandS) return
    const bridgeDom = (strandS.domains ?? []).find(
      d => d.helix_id && d.helix_id.startsWith('__lnk__'),
    )
    if (!bridgeDom) return
    // ss bridge sits on the centre line of the linker grid.
    const { fwdY, revY } = _rowYsWorld('linker')
    const yBridge = (fwdY + revY) / 2
    // bridge 5' ↔ complementA's 3' junction (complementA is FIRST domain).
    if (anchorA) {
      const aAnchor = _bridgeEndAnchor(bridgeDom, conn, yBridge, '5p')
      _drawArcBetween(aAnchor.x, aAnchor.y, anchorA)
    }
    // bridge 3' ↔ complementB's 5' junction (complementB is LAST domain).
    if (anchorB) {
      const bAnchor = _bridgeEndAnchor(bridgeDom, conn, yBridge, '3p')
      _drawArcBetween(bAnchor.x, bAnchor.y, anchorB)
    }
  }

  /** Orchestrator: draw all linker bindings (on selected + partner grids)
   *  and the crossover arcs. Branches on linker_type:
   *    - ds → two strands, each with one binding + one crossover.
   *    - ss → one strand with TWO bindings (one per overhang) + TWO crossovers.
   */
  function _drawLinkerBindingsAndCrossovers() {
    if (!_layout?.isMulti) return
    const { linker, partner, linkerStrands } = _layout
    if (!linker || !partner || !linkerStrands) return

    if (linker.linker_type === 'ss' && linkerStrands.s) {
      // ss: ONE strand with bindings on BOTH overhang helices.
      const strandS = linkerStrands.s
      // complementA → partner overhang; complementB → selected overhang.
      // (Domain order in _build_ss_linker_strand is [complementA, bridge, complementB].)
      const anchorA = _drawLinkerBindingDomain(strandS, partner, 'partner',  'S')
      const anchorB = _drawLinkerBindingDomain(strandS, _ovhg,   'selected', 'S')
      _drawLinkerCrossoversSs(linker, strandS, anchorA, anchorB)
      return
    }

    // ds path (legacy): each strand has one complement on one of the helices.
    const bindingAnchors = { aSide: null, bSide: null }
    function _placeBinding(strand, label) {
      if (!strand) return
      const onSelected = _domainOnHelix(strand, _ovhg.helix_id)
      if (onSelected) {
        bindingAnchors[label === 'A' ? 'aSide' : 'bSide'] =
          _drawLinkerBindingDomain(strand, _ovhg, 'selected', label)
        return
      }
      const onPartner = _domainOnHelix(strand, partner.helix_id)
      if (onPartner) {
        bindingAnchors[label === 'A' ? 'aSide' : 'bSide'] =
          _drawLinkerBindingDomain(strand, partner, 'partner', label)
      }
    }
    _placeBinding(linkerStrands.a, 'A')
    _placeBinding(linkerStrands.b, 'B')

    _drawLinkerCrossoversDs(linker, linkerStrands, bindingAnchors)
  }


  // ── Draw: hover-split ghost line (right-click hover indicator) ─────────────

  function _drawHoverGhost() {
    if (_hoverBp == null || _hoverSdId == null) return
    const sd = (_ovhg?.sub_domains ?? []).find(s => s.id === _hoverSdId)
    if (!sd) return
    const start = sd.start_bp_offset ?? 0
    const length = sd.length_bp ?? 0
    const rel = _hoverBp - start
    if (rel <= 0 || rel >= length) return

    const cssH = canvasEl.cssHeight ?? canvasEl.height
    const x = _bpToCX(_hoverBp)
    ctx.save()
    ctx.setLineDash([3, 3])
    ctx.strokeStyle = HOVER_CLR
    ctx.lineWidth = 1.5
    _line(x, RULER_H, x, cssH - 4, HOVER_CLR, 1.5)
    ctx.restore()

    const len5 = rel
    const len3 = length - rel
    const text = `Right-click to split at bp ${_hoverBp} → [${len5}, ${len3}]`
    ctx.fillStyle = HOVER_CLR
    ctx.font = NAME_FONT
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText(text, Math.min(x + 4, (canvasEl.cssWidth ?? canvasEl.width) - 220), RULER_H + 2)
  }


  // ── Composite draw ──────────────────────────────────────────────────────────

  function _drawResizeGhost() {
    if (!_resizeActive) return
    const totalBp = _totalBp()
    if (totalBp <= 0) return
    const dom = _overhangDomain(_design, _ovhg)
    const isFwd = dom?.direction === 'FORWARD'
    const { fwdY, revY } = _rowYsWorld()
    const sY = (isFwd ? fwdY : revY) * _zoom + _panY
    const sAnchorX = _bpToCX(_resizeActive.anchorBp)
    const sNewX    = sAnchorX + _resizeActive.ghostDelta * BP_W * _zoom
    const cssH = canvasEl.cssHeight ?? canvasEl.height

    // Vertical guide line at the new endpoint.
    ctx.save()
    ctx.setLineDash([4, 4])
    ctx.strokeStyle = HOVER_CLR
    ctx.lineWidth = 1.5
    _line(sNewX, RULER_H, sNewX, cssH - 4, HOVER_CLR, 1.5)
    ctx.restore()

    // Tooltip with the new length.
    const newLen = totalBp + (isFwd ? _resizeActive.ghostDelta : -_resizeActive.ghostDelta)
    const lenStr = `Resize → ${Math.max(1, newLen)} bp (${_resizeActive.ghostDelta >= 0 ? '+' : ''}${_resizeActive.ghostDelta})`
    ctx.fillStyle = HOVER_CLR
    ctx.font = NAME_FONT
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    const tx = Math.min(sNewX + 4, (canvasEl.cssWidth ?? canvasEl.width) - 220)
    ctx.fillText(lenStr, tx, RULER_H + 2)

    // Phantom strand end-cap at the new position (so the user sees what
    // the resize will look like before releasing).
    const sqSz = Math.min(BP_W, CELL_H) * 0.80 * _zoom
    ctx.save()
    ctx.globalAlpha = 0.6
    ctx.fillStyle = HOVER_CLR
    if (_resizeActive.end === '5p') {
      ctx.fillRect(sNewX - sqSz / 2, sY - sqSz / 2, sqSz, sqSz)
    } else {
      const tw = BP_W * _zoom * 0.9
      ctx.beginPath()
      ctx.moveTo(sNewX - tw / 2, sY - sqSz / 2)
      ctx.lineTo(sNewX + tw / 2, sY)
      ctx.lineTo(sNewX - tw / 2, sY + sqSz / 2)
      ctx.closePath(); ctx.fill()
    }
    ctx.restore()
  }

  function _drawAll() {
    _clearBg()
    _layout = _computeLayout()
    if (_layout.isMulti) {
      // Multi-grid layout: partner (top) + linker bridge (middle) + selected (bottom).
      // Each grid has its own bp width; draw cells at the appropriate kind y-offset.
      _drawTrackGrid('partner', _totalBpOf(_layout.partner))
      _drawPartnerOverhangBody(_layout.partner)
      const bridgeBp = (_layout.linker.length_unit === 'bp')
        ? _layout.linker.length_value : 30
      _drawTrackGrid('linker', bridgeBp)
      _drawLinkerBridgeBody(_layout.linker, _layout.linkerStrands)
      // Selected grid (with its own y-shift baked into `_rowYsWorld`).
      _drawTrackGrid('selected')
      _drawStrandBodyAndPartner()
      // Linker binding domains (on each overhang grid's opposite row, with
      // 5'/3' caps) + crossover arcs back to the bridge ends.
      _drawLinkerBindingsAndCrossovers()
    } else {
      // Single-grid layout (legacy / no-linker scenario).
      _drawTrackGrid()
      _drawStrandBodyAndPartner()
    }
    _drawHoverGhost()
    _drawResizeGhost()
    _drawRuler()
    _drawGutter()
  }


  // ── Hit-testing (canvas-px → sub-domain) ────────────────────────────────────

  /** Hit-test a free-end cap on ANY editable strand row.
   *  Returns one of:
   *    { kind: 'overhang', ovhg, end, anchorBp, isFwd }
   *    { kind: 'linker',   conn, strandLabel, end, anchorBp, isFwd }
   *  or null when nothing was hit. */
  function _hitFreeEndCap(canvasX, canvasY) {
    const halfWPx = (BP_W * _zoom) / 2 + 2

    // Helper: test an overhang grid's free-end cap.
    const _tryOvhg = (kind, targetOvhg) => {
      if (!targetOvhg) return null
      const ends = _strandEnds(_design, targetOvhg)
      if (!ends) return null
      const dom = _overhangDomain(_design, targetOvhg)
      const isFwd = dom?.direction === 'FORWARD'
      const { fwdY, revY } = _rowYsWorld(kind)
      const sY = (isFwd ? fwdY : revY) * _zoom + _panY
      const tol = (CELL_H / 2 + 4) * _zoom
      if (canvasY < sY - tol || canvasY > sY + tol) return null
      const totalBp = _totalBpOf(targetOvhg)
      if (totalBp <= 0) return null
      let freeAnchorBp
      if (ends.freeEnd === '5p') {
        freeAnchorBp = isFwd ? 0 : totalBp
      } else {
        freeAnchorBp = isFwd ? totalBp : 0
      }
      const sAnchorX = _bpToCX(freeAnchorBp)
      if (canvasX < sAnchorX - halfWPx || canvasX > sAnchorX + halfWPx) return null
      return {
        kind: 'overhang', ovhg: targetOvhg,
        end: ends.freeEnd, anchorBp: freeAnchorBp, isFwd,
      }
    }

    // Helper: test a linker bridge strand end. Linker strands have BOTH ends
    // potentially editable: the 5' tip (with cap) AND the 3' end at the
    // crossover (cell-centre, no cap but still draggable for length-resize).
    const _tryLinker = (strand, label) => {
      if (!strand || !_layout?.linker) return null
      const bridgeDom = (strand.domains ?? []).find(
        d => d.helix_id && d.helix_id.startsWith('__lnk__'),
      )
      if (!bridgeDom) return null
      const isFwd = bridgeDom.direction === 'FORWARD'
      const { fwdY, revY } = _rowYsWorld('linker')
      const yLane = label === 'A' ? fwdY : revY
      const sY = yLane * _zoom + _panY
      const tol = (CELL_H / 2 + 4) * _zoom
      if (canvasY < sY - tol || canvasY > sY + tol) return null
      const bridgeBp = (_layout.linker.length_unit === 'bp')
        ? _layout.linker.length_value : 30
      // 5' tip = bp 0 if FWD else bp bridgeBp; 3' end (crossover) = the other.
      const fivePrimeBp  = isFwd ? 0 : bridgeBp
      const threePrimeBp = isFwd ? bridgeBp : 0
      // Test both ends — return whichever is closer to the cursor.
      const xFive  = _bpToCX(fivePrimeBp)
      const xThree = _bpToCX(threePrimeBp)
      const distFive  = Math.abs(canvasX - xFive)
      const distThree = Math.abs(canvasX - xThree)
      if (distFive < distThree && distFive <= halfWPx) {
        return { kind: 'linker', conn: _layout.linker, strandLabel: label,
                 end: '5p', anchorBp: fivePrimeBp, isFwd }
      }
      if (distThree <= distFive && distThree <= halfWPx) {
        return { kind: 'linker', conn: _layout.linker, strandLabel: label,
                 end: '3p', anchorBp: threePrimeBp, isFwd }
      }
      return null
    }

    // Helper: test a linker strand's BINDING-domain 3' triangle cap on the
    // overhang's opposite row. Hit returns enough info to call
    // `strand-end-resize` on the linker strand directly.
    const _tryBinding = (strand, ovhg, kind, label) => {
      if (!strand || !ovhg) return null
      const bindingDom = (strand.domains ?? []).find(d => d.helix_id === ovhg.helix_id)
      if (!bindingDom) return null
      const ovhgDom = _overhangDomain(_design, ovhg)
      if (!ovhgDom) return null
      const ovhgBpLo = Math.min(ovhgDom.start_bp, ovhgDom.end_bp)
      const bindBpLo = Math.min(bindingDom.start_bp, bindingDom.end_bp)
      const bindBpHi = Math.max(bindingDom.start_bp, bindingDom.end_bp)
      const localLo = bindBpLo - ovhgBpLo
      const localHi = bindBpHi - ovhgBpLo
      const isFwd = _overhangDomain(_design, ovhg)?.direction === 'FORWARD'
      const { fwdY, revY } = _rowYsWorld(kind)
      const yBind = isFwd ? revY : fwdY
      const sY = yBind * _zoom + _panY
      const tol = (CELL_H / 2 + 4) * _zoom
      if (canvasY < sY - tol || canvasY > sY + tol) return null
      // 3' tip anchor in WORLD-bp:
      //   FWD binding: 3' at the cell-rightmost edge (localHi + 1).
      //   REV binding: 3' at the cell-leftmost edge  (localLo).
      const bindIsFwd = bindingDom.direction === 'FORWARD'
      const tipBp = bindIsFwd ? (localHi + 1) : localLo
      const sTipX = _bpToCX(tipBp)
      if (canvasX < sTipX - halfWPx || canvasX > sTipX + halfWPx) return null
      return {
        kind: 'binding',
        strand,
        ovhg,
        end: '3p',                     // binding's 3' end (the only cap)
        anchorBp: tipBp,
        isFwd: bindIsFwd,
      }
    }

    // Test selected first; in multi-grid, also try partner + linker strands
    // + binding-domain triangles on either overhang grid.
    const sel = _tryOvhg('selected', _ovhg)
    if (sel) return sel
    if (!_layout?.isMulti) return null
    const partner = _tryOvhg('partner', _layout.partner)
    if (partner) return partner
    // Binding-domain 3' tips on each overhang grid.
    for (const [strand, label] of [
      [_layout.linkerStrands?.a, 'A'],
      [_layout.linkerStrands?.b, 'B'],
    ]) {
      const bindingOnSel = _tryBinding(strand, _ovhg,           'selected', label)
      if (bindingOnSel) return bindingOnSel
      const bindingOnPar = _tryBinding(strand, _layout.partner, 'partner',  label)
      if (bindingOnPar) return bindingOnPar
    }
    const linkA = _tryLinker(_layout.linkerStrands?.a, 'A')
    if (linkA) return linkA
    const linkB = _tryLinker(_layout.linkerStrands?.b, 'B')
    if (linkB) return linkB
    return null
  }

  /** Resolve which grid (selected | partner) the canvas-y hit, and the sub-
   *  domain at the bp under the cursor in that grid's bp space. Returns
   *  `{ kind: 'selected'|'partner', ovhg, sd, bp }` or null. */
  function _hitSubDomain(canvasX, canvasY) {
    if (!_ovhg) return null
    const _tryGrid = (kind, targetOvhg) => {
      const dom = _overhangDomain(_design, targetOvhg)
      const isFwd = dom?.direction === 'FORWARD'
      const { fwdY: wFwdY, revY: wRevY } = _rowYsWorld(kind)
      const sFwdY = wFwdY * _zoom + _panY
      const sRevY = wRevY * _zoom + _panY
      const yMain = isFwd ? sFwdY : sRevY
      const tol = (CELL_H / 2 + 4) * _zoom
      if (canvasY < yMain - tol || canvasY > yMain + tol) return null
      const { wx } = _c2w(canvasX, canvasY)
      const bp = _wxToBp(wx)
      if (bp < 0) return null
      const ordered = [...(targetOvhg.sub_domains ?? [])].sort(
        (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
      )
      for (const sd of ordered) {
        const start = sd.start_bp_offset ?? 0
        const end = start + (sd.length_bp ?? 0)
        if (bp >= start && bp < end) return { kind, ovhg: targetOvhg, sd, bp }
      }
      return null
    }
    // Selected grid first; if multi-grid, also try the partner grid.
    return _tryGrid('selected', _ovhg)
        ?? (_layout?.isMulti && _layout.partner
              ? _tryGrid('partner', _layout.partner)
              : null)
  }


  // ── Pointer event model — left-click select, right-click split ──────────────
  //
  // - Left button down + up over a sub-domain → select.
  // - Right (button 2) or middle (button 1) drag → pan.
  // - Right-click (no drag) over interior bp of a sub-domain → split.
  // - Wheel → zoom centred on cursor.

  function _onPointerMove(ev) {
    const rect = canvasEl.getBoundingClientRect()
    const cx = ev.clientX - rect.left
    const cy = ev.clientY - rect.top

    if (_panActive) {
      const dx = ev.clientX - _panStartCX
      const dy = ev.clientY - _panStartCY
      _panX = _panStartPanX + dx
      _panY = _panStartPanY + dy
      _drawAll()
      return
    }

    if (_resizeActive) {
      // Convert canvas-px drag delta to bp delta. The free end moves toward
      // higher global bp on a positive drag iff (isFwd && end==='3p') or
      // (!isFwd && end==='5p'); flipped otherwise. We pass that sign onto
      // delta_bp at commit time.
      const dxPx = cx - _resizeActive.startCX
      const dxBp = Math.round(dxPx / (BP_W * _zoom))
      _resizeActive.ghostDelta = dxBp
      _drawAll()
      return
    }

    if (!_ovhg) return
    // Cursor hint when hovering the free-end cap.
    const cap = _hitFreeEndCap(cx, cy)
    canvasEl.style.cursor = cap ? 'ew-resize' : 'default'
    const hit = _hitSubDomain(cx, cy)
    const prevBp = _hoverBp
    const prevSd = _hoverSdId
    if (hit) {
      const start = hit.sd.start_bp_offset ?? 0
      const length = hit.sd.length_bp ?? 0
      const rel = hit.bp - start
      _hoverBp = (rel > 0 && rel < length) ? hit.bp : null
      _hoverSdId = hit.sd.id
    } else {
      _hoverBp = null
      _hoverSdId = null
    }
    if (_hoverBp !== prevBp || _hoverSdId !== prevSd) _drawAll()
    if (_hoverTimer) clearTimeout(_hoverTimer)
    _hoverTimer = setTimeout(() => {
      if (hit && !_hoverBp) _showTooltip(ev.clientX, ev.clientY, hit.sd)
      else _hideTooltip()
    }, HOVER_DEBOUNCE_MS)
  }

  function _onPointerDown(ev) {
    if (!_ovhg) return
    const rect = canvasEl.getBoundingClientRect()
    const cx = ev.clientX - rect.left
    const cy = ev.clientY - rect.top

    // Right or middle → start pan.
    if (ev.button === 1 || ev.button === 2) {
      _panActive = true
      _panStartCX   = ev.clientX
      _panStartCY   = ev.clientY
      _panStartPanX = _panX
      _panStartPanY = _panY
      canvasEl.setPointerCapture(ev.pointerId)
      ev.preventDefault()
      return
    }

    if (ev.button !== 0) return  // ignore other buttons

    // Free-end cap drag → resize. cap.kind is 'overhang' (selected/partner)
    // or 'linker' (bridge end of a linker strand). Both routed through
    // _resizeActive; the commit handler dispatches by kind.
    const cap = _hitFreeEndCap(cx, cy)
    if (cap) {
      _resizeActive = {
        ...cap,         // kind, ovhg|conn, end, anchorBp, isFwd, strandLabel?
        startCX: cx,
        ghostDelta: 0,
      }
      canvasEl.setPointerCapture(ev.pointerId)
      ev.preventDefault()
      _debug('resize-start kind=', cap.kind, 'end=', cap.end, 'anchorBp=', cap.anchorBp)
      return
    }

    // Left button — record the hit; commit on pointerup.
    canvasEl.setPointerCapture(ev.pointerId)
    canvasEl._leftDownHit = _hitSubDomain(cx, cy)
    canvasEl._leftDownX = cx
    _debug('pointerdown LEFT', cx.toFixed(1), cy.toFixed(1),
           '→ sd', canvasEl._leftDownHit?.sd?.id, 'on', canvasEl._leftDownHit?.kind)
  }

  function _onPointerUp(ev) {
    const rect = canvasEl.getBoundingClientRect()
    const cx = ev.clientX - rect.left
    const cy = ev.clientY - rect.top

    if (_resizeActive) {
      const { kind, end, ghostDelta, ovhg, conn, strandLabel, strand } = _resizeActive
      _resizeActive = null
      try { canvasEl.releasePointerCapture(ev.pointerId) } catch { /* ignore */ }
      const deltaBp = ghostDelta
      if (Math.abs(deltaBp) >= 1) {
        if (kind === 'overhang' && ovhg && typeof onResizeFreeEnd === 'function') {
          _debug('resize-fire overhang', ovhg.id, end, 'delta_bp', deltaBp)
          onResizeFreeEnd(ovhg.id, { end, delta_bp: deltaBp })
        } else if (kind === 'binding' && strand && ovhg && typeof onResizeBinding === 'function') {
          // Linker strand's binding-domain 3' tip resize. Routes through the
          // generic strand-end-resize endpoint with the LINKER strand's id.
          // Sign: screen-Δ → delta_bp directly (positive = toward higher
          // global bp). For a REV binding, dragging the cap LEFT lowers
          // end_bp which extends the strand — handled by the same convention.
          _debug('resize-fire binding', strand.id, ovhg.id, 'delta_bp', deltaBp)
          onResizeBinding({
            strand_id: strand.id,
            helix_id:  ovhg.helix_id,
            end:       '3p',
            delta_bp:  deltaBp,
          })
        } else if (kind === 'linker' && conn && typeof onResizeLinker === 'function') {
          // Linker bridge length-resize: dragging "outward" grows, "inward"
          // shrinks. Determine which side of the bridge was grabbed:
          //   FWD bridge: 5p anchor at LEFT  (outward = -x); 3p anchor at RIGHT (outward = +x)
          //   REV bridge: 5p anchor at RIGHT (outward = +x); 3p anchor at LEFT  (outward = -x)
          const linkerStrand = (strandLabel === 'A')
            ? _layout?.linkerStrands?.a
            : _layout?.linkerStrands?.b
          const bridgeDom = (linkerStrand?.domains ?? []).find(
            d => d.helix_id && d.helix_id.startsWith('__lnk__'),
          )
          const bridgeIsFwd = bridgeDom?.direction === 'FORWARD'
          const isRightSide = (bridgeIsFwd && end === '3p')
                           || (!bridgeIsFwd && end === '5p')
          const lengthDelta = isRightSide ? deltaBp : -deltaBp
          _debug('resize-fire linker', conn.id, 'strand', strandLabel,
                 'end', end, 'screenΔ', deltaBp, 'lenΔ', lengthDelta)
          onResizeLinker(conn.id, lengthDelta)
        }
      } else {
        _debug('resize-cancel ghostDelta', ghostDelta)
      }
      _drawAll()
      return
    }

    if (_panActive) {
      // End pan; if pointer barely moved AND it was a right-click, treat it
      // as a split request at the bp under cursor.
      const drift = Math.hypot(ev.clientX - _panStartCX, ev.clientY - _panStartCY)
      _panActive = false
      try { canvasEl.releasePointerCapture(ev.pointerId) } catch { /* ignore */ }

      if (ev.button === 2 && drift < 4) {
        const hit = _hitSubDomain(cx, cy)
        if (hit) {
          const start = hit.sd.start_bp_offset ?? 0
          const length = hit.sd.length_bp ?? 0
          const rel = hit.bp - start
          if (rel > 0 && rel < length && typeof onSplit === 'function') {
            // Pass owning ovhg.id so the popup can route the split to the
            // correct overhang (selected OR partner) without changing focus.
            _debug('split fire (right-click)', hit.sd.id, 'on', hit.ovhg.id,
                   'at offset', hit.bp)
            onSplit(hit.ovhg.id, { sub_domain_id: hit.sd.id, split_at_offset: hit.bp })
          }
        }
      }
      _drawAll()
      return
    }

    if (ev.button === 0 && canvasEl._leftDownHit) {
      try { canvasEl.releasePointerCapture(ev.pointerId) } catch { /* ignore */ }
      const drift = Math.abs(cx - canvasEl._leftDownX)
      if (drift < 4) {
        const hit = _hitSubDomain(cx, cy)
        if (hit && hit.sd.id === canvasEl._leftDownHit.sd.id
            && typeof onSelectSubDomain === 'function') {
          // Pass owning ovhg.id; popup updates ONLY selectedSubDomainId so
          // the multi-grid perspective (anchored to selectedOverhangId from
          // the listing) does NOT change. Annotations panel walks all
          // overhangs to find the active sd.
          _debug('select fire', hit.sd.id, 'grid=', hit.kind, 'ovhg=', hit.ovhg.id)
          onSelectSubDomain(hit.sd.id, hit.ovhg.id)
        }
      }
      canvasEl._leftDownHit = null
    }
  }

  function _onPointerLeave() {
    _hoverBp = null
    _hoverSdId = null
    _hideTooltip()
    if (!_panActive) _drawAll()
  }

  function _onContextMenu(ev) {
    // Suppress browser context menu so right-click pan + split work.
    ev.preventDefault()
  }

  function _onWheel(ev) {
    ev.preventDefault()
    const rect = canvasEl.getBoundingClientRect()
    const cx = ev.clientX - rect.left
    const cy = ev.clientY - rect.top
    const factor = ev.deltaY < 0 ? 1.15 : 0.87
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, _zoom * factor))
    if (newZoom !== _zoom) {
      _panX = cx - (cx - _panX) * (newZoom / _zoom)
      _panY = cy - (cy - _panY) * (newZoom / _zoom)
      _zoom = newZoom
      _drawAll()
    }
  }


  // ── HTML tooltip (hover info) ───────────────────────────────────────────────

  function _showTooltip(clientX, clientY, sd) {
    if (!_tooltipEl) {
      _tooltipEl = document.createElement('div')
      _tooltipEl.style.cssText = (
        'position:fixed;z-index:9300;pointer-events:none;'
        + 'background:#161b22;border:1px solid #30363d;border-radius:4px;'
        + 'padding:6px 8px;font-family:monospace;font-size:11px;'
        + 'color:#c9d1d9;max-width:260px;white-space:pre'
      )
      document.body.appendChild(_tooltipEl)
    }
    const lines = []
    lines.push(`${sd.name ?? '(unnamed)'} · ${sd.length_bp} bp`)
    if (sd.tm_celsius != null) lines.push(`Tm: ${Math.round(sd.tm_celsius)}°C`)
    if (sd.gc_percent != null) lines.push(`GC: ${Math.round(sd.gc_percent)}%`)
    if (sd.sequence_override)  lines.push(`Seq: ${sd.sequence_override}`)
    if (sd.notes)              lines.push(`Notes: ${sd.notes}`)
    _tooltipEl.textContent = lines.join('\n')
    _tooltipEl.style.left = `${clientX + 12}px`
    _tooltipEl.style.top  = `${clientY + 12}px`
    _tooltipEl.style.display = 'block'
  }

  function _hideTooltip() {
    if (_hoverTimer) { clearTimeout(_hoverTimer); _hoverTimer = null }
    if (_tooltipEl) _tooltipEl.style.display = 'none'
  }


  // ── DPI-aware resize + initial fit ──────────────────────────────────────────

  function _resize() {
    const targetEl = wrapEl ?? canvasEl
    const rect = targetEl.getBoundingClientRect()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvasEl.width  = Math.max(1, Math.floor(rect.width  * dpr))
    canvasEl.height = Math.max(1, Math.floor(rect.height * dpr))
    canvasEl._dpr = dpr
    canvasEl.cssWidth  = rect.width
    canvasEl.cssHeight = rect.height
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  /** Reset the view: 150-bp window, current overhang fills 50% of canvas
   *  width, vertically centred. */
  function resetView() {
    _resize()
    const cssW = canvasEl.cssWidth ?? canvasEl.width
    const cssH = canvasEl.cssHeight ?? canvasEl.height
    const totalBp = _totalBp()
    const dataW = (cssW - GUTTER)

    // Determine zoom: overhang strand should occupy 50% of dataW
    // → BP_W * zoom * totalBp == 0.5 * dataW (when totalBp > 0).
    // Else: 150 bp fits the dataW.
    let zoom
    if (totalBp > 0) {
      zoom = (TARGET_OVHG_FRACTION * dataW) / (BP_W * totalBp)
    } else {
      zoom = dataW / (BP_W * VISIBLE_WINDOW_BP)
    }
    // In multi-grid mode the three stacked grids + their root-arcs need to
    // fit vertically too. Compute the minimum zoom that accommodates the
    // full stack (partner top-arc → selected bottom-arc) and clamp.
    const _layoutForFit = _computeLayout()
    if (_layoutForFit.isMulti) {
      // Vertical span (world-y): partner up-arc tip .. selected down-arc tip.
      // With selectedYShift = 2*(GRID_PAIR_H + GRID_STACK_GAP), using the
      // _rowYsWorld formulas:
      //   partner.revY  = baseSelected + PAIR_Y                    (with shift baked in)
      //   selected.revY = baseSelected + 2*(GRID_PAIR_H + GAP) + PAIR_Y
      // Each grid's root-arc reaches ±5*PAIR_Y past its row pair.
      const baseSelected = RULER_H + TOP_PAD + CELL_H / 2
      const partnerArcTop  = baseSelected + PAIR_Y - 5 * PAIR_Y - CELL_H
      const selectedArcBot = baseSelected + 2 * (GRID_PAIR_H + GRID_STACK_GAP) + PAIR_Y + 5 * PAIR_Y + CELL_H
      const verticalSpan = Math.max(1, selectedArcBot - partnerArcTop)
      const usableH = (canvasEl.cssHeight ?? canvasEl.height) - RULER_H - 8
      const vFitZoom = usableH / verticalSpan
      zoom = Math.min(zoom, vFitZoom)
    }
    zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom))
    _zoom = zoom

    // Pan-X: place bp 0 such that the overhang body is centred horizontally
    // in the data area (between GUTTER and right edge).
    const dataCx = GUTTER + dataW / 2
    const ovhgCxWorld = GUTTER + (totalBp / 2) * BP_W
    _panX = dataCx - ovhgCxWorld * _zoom

    // Pan-Y: vertically centre the visible content within the canvas. In
    // multi-grid mode (linker present), centre on the LINKER bridge so all
    // three grids fit symmetrically; otherwise centre on the selected grid.
    // Compute layout up front so `_rowYsWorld` returns the right offsets.
    _layout = _computeLayout()
    let rowMidWorld
    if (_layout.isMulti) {
      const linkerY = _rowYsWorld('linker')
      rowMidWorld = (linkerY.fwdY + linkerY.revY) / 2
    } else {
      const sel = _rowYsWorld('selected')
      rowMidWorld = (sel.fwdY + sel.revY) / 2
    }
    const dataCy = RULER_H + (cssH - RULER_H) / 2
    _panY = dataCy - rowMidWorld * _zoom

    _drawAll()
  }


  // ── Wire events ─────────────────────────────────────────────────────────────

  canvasEl.addEventListener('pointerdown',  _onPointerDown)
  canvasEl.addEventListener('pointermove',  _onPointerMove)
  canvasEl.addEventListener('pointerup',    _onPointerUp)
  canvasEl.addEventListener('pointerleave', _onPointerLeave)
  canvasEl.addEventListener('contextmenu',  _onContextMenu)
  canvasEl.addEventListener('wheel',        _onWheel, { passive: false })

  // Re-fit on container resize so the modal-resize-from-ohc-tab-switch
  // doesn't leave the pathview cropped.
  if (wrapEl && typeof ResizeObserver !== 'undefined') {
    _resizeObs = new ResizeObserver(() => {
      _resize()
      _drawAll()
    })
    _resizeObs.observe(wrapEl)
  }


  // ── Public ──────────────────────────────────────────────────────────────────

  return {
    rebuild(overhangSpec, geometry, design) {
      _debug('rebuild', overhangSpec?.id,
             'subdomains=', overhangSpec?.sub_domains?.length,
             'totalBp=', overhangSpec?.sub_domains?.reduce(
               (a, sd) => a + (sd.length_bp ?? 0), 0) ?? 0)
      const isFreshOverhang = !_ovhg || _ovhg.id !== overhangSpec?.id
      _ovhg = overhangSpec ?? null
      _geometry = geometry ?? null
      _design = design ?? null
      _hoverBp = null
      _hoverSdId = null
      if (isFreshOverhang) {
        // Switching overhangs → reset the view so the new strand fits 50%.
        resetView()
      } else {
        _resize()
        _drawAll()
      }
    },

    resetView,

    destroy() {
      canvasEl.removeEventListener('pointerdown',  _onPointerDown)
      canvasEl.removeEventListener('pointermove',  _onPointerMove)
      canvasEl.removeEventListener('pointerup',    _onPointerUp)
      canvasEl.removeEventListener('pointerleave', _onPointerLeave)
      canvasEl.removeEventListener('contextmenu',  _onContextMenu)
      canvasEl.removeEventListener('wheel',        _onWheel)
      _resizeObs?.disconnect?.(); _resizeObs = null
      _hideTooltip()
      if (_tooltipEl) { _tooltipEl.remove(); _tooltipEl = null }
      _ovhg = _design = _geometry = null
    },
  }
}
