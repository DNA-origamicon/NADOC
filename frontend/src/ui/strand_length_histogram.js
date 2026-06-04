/**
 * Strand length histogram — collapsible left-sidebar canvas panel showing the
 * staple-length distribution as a bar chart. Bars for out-of-range lengths
 * (< 18 or > 50 nt) are red; clicking a bar selects + zooms to a matching
 * strand (cycling on repeat clicks); right-click offers delete-by-bin.
 *
 * Stateful: owns the canvas, a context menu, and a store subscription. So it's a
 * factory — pass its dependencies in. The bin computation is pulled out as the
 * pure `computeStrandLengthBins(design)` (unit-tested in
 * strand_length_histogram.test.js); the canvas drawing stays here.
 *
 * Extracted verbatim from main.js's `_initStrandHistogram` IIFE.
 *
 * @param {object}   deps
 * @param {object}   deps.store             — Zustand-style store (getState/subscribe)
 * @param {object}   deps.selectionManager  — needs selectStrand(id)
 * @param {object}   deps.api               — needs deleteStrand(id) / deleteStrandsBatch(ids)
 * @param {Function} deps.centerOnStrand    — (strandId) => void; camera-center on a strand
 * @returns {{ redraw: Function }}
 */
import { strandLengthNtFromDesign } from '../scene/strand_length.js'

// Canonical staple-length window for DNA origami QC.
export const HIST_MIN_NT = 18
export const HIST_MAX_NT = 50

/**
 * Pure: bin the design's staple strands by length (loop/skip-aware).
 * Returns a status + a ready-to-draw summary; `status: 'ok'` additionally
 * carries the ordered bins and range/count stats.
 *
 * @param {object} design — Design with .strands / .helices
 * @returns {{status:'no-design'|'no-staples', summary:string}
 *          | {status:'ok', staples:object[], bins:{length:number,strandIds:string[],count:number,isOut:boolean}[],
 *             lengths:number[], minLen:number, maxLen:number, maxCount:number,
 *             nOk:number, nShort:number, nLong:number, pct:number, summary:string}}
 */
export function computeStrandLengthBins(design) {
  if (!design?.strands?.length) return { status: 'no-design', summary: 'No design loaded.' }

  const staples = design.strands.filter(s => s.strand_type === 'staple')
  if (staples.length === 0) return { status: 'no-staples', summary: 'No staple strands.' }

  // Group staple ids by length value.
  const byLength = new Map()
  for (const s of staples) {
    const len = strandLengthNtFromDesign(s, design)
    if (!byLength.has(len)) byLength.set(len, [])
    byLength.get(len).push(s.id)
  }

  const lengths  = [...byLength.keys()].sort((a, b) => a - b)
  const minLen   = lengths[0]
  const maxLen   = lengths[lengths.length - 1]
  const maxCount = Math.max(...[...byLength.values()].map(v => v.length))

  // In-range / short / long counts (mutually exclusive, exhaustive).
  let nOk = 0, nShort = 0, nLong = 0
  for (const s of staples) {
    const l = strandLengthNtFromDesign(s, design)
    if (l < HIST_MIN_NT) nShort++
    else if (l > HIST_MAX_NT) nLong++
    else nOk++
  }
  const pct = Math.round(100 * nOk / staples.length)
  const summary = `${staples.length} staples · ${pct}% in ${HIST_MIN_NT}–${HIST_MAX_NT} nt`
    + (nShort ? ` · ${nShort} short` : '')
    + (nLong  ? ` · ${nLong} long`   : '')

  const bins = lengths.map(len => ({
    length:    len,
    strandIds: byLength.get(len),
    count:     byLength.get(len).length,
    isOut:     len < HIST_MIN_NT || len > HIST_MAX_NT,
  }))

  return { status: 'ok', staples, bins, lengths, minLen, maxLen, maxCount, nOk, nShort, nLong, pct, summary }
}

export function initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand }) {
  const heading  = document.getElementById('strand-hist-heading')
  const arrow    = document.getElementById('strand-hist-arrow')
  const body     = document.getElementById('strand-hist-body')
  const canvas   = document.getElementById('strand-hist-canvas')
  const tooltip  = document.getElementById('strand-hist-tooltip')
  const summary  = document.getElementById('strand-hist-summary')
  if (!heading || !canvas) return { redraw: () => {} }

  let _expanded = false
  let _barData  = []  // [{x, w, y, h, strandIds, length, isOut}] — hit areas

  heading.addEventListener('click', () => {
    _expanded = !_expanded
    body.style.display = _expanded ? 'block' : 'none'
    arrow.classList.toggle('is-collapsed', !(_expanded))
    if (_expanded) _redraw(store.getState().currentDesign)
  })

  function _redraw(design) {
    const ctx = canvas.getContext('2d')
    const W   = canvas.width
    const H   = canvas.height
    ctx.clearRect(0, 0, W, H)
    _barData = []

    const data = computeStrandLengthBins(design)
    summary.textContent = data.summary
    if (data.status !== 'ok') return

    const { bins, minLen, maxLen, maxCount } = data
    const nBins  = bins.length
    const pad    = 4
    const barW   = Math.max(2, Math.floor((W - 2 * pad) / nBins) - 1)
    const totalW = (barW + 1) * nBins
    const startX = pad + Math.floor((W - 2 * pad - totalW) / 2)

    // Draw canonical range background
    if (nBins > 1) {
      const xRange18 = startX + (HIST_MIN_NT >= minLen ? (HIST_MIN_NT - minLen) * (barW + 1) : 0)
      const xRange50 = startX + (HIST_MAX_NT <= maxLen ? (HIST_MAX_NT - minLen + 1) * (barW + 1) : W - 2 * pad)
      ctx.fillStyle = 'rgba(61,220,132,0.06)'
      ctx.fillRect(Math.max(pad, xRange18), 0, xRange50 - xRange18, H - 1)
    }

    // Draw bars
    for (let i = 0; i < nBins; i++) {
      const bin   = bins[i]
      const x     = startX + i * (barW + 1)
      const barH  = Math.max(2, Math.round((bin.count / maxCount) * (H - 14)))
      const y     = H - barH - 1

      ctx.fillStyle = bin.isOut ? '#ff6b6b' : '#3ddc84'
      ctx.fillRect(x, y, barW, barH)

      _barData.push({ x, w: barW, y, h: barH, strandIds: bin.strandIds, length: bin.length, isOut: bin.isOut })
    }

    // X-axis ticks for 18 and 50
    ctx.fillStyle = '#484f58'
    ctx.font = '8px monospace'
    ctx.textAlign = 'center'
    for (const tick of [HIST_MIN_NT, HIST_MAX_NT]) {
      if (tick >= minLen && tick <= maxLen) {
        const xi = startX + (tick - minLen) * (barW + 1) + barW / 2
        ctx.fillText(tick, xi, H)
      }
    }
  }

  // Click: select a strand of the clicked bar, cycling through all strands on repeated clicks
  let _lastClickedLength = null
  let _cycleIndex = 0
  canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const mx = (e.clientX - rect.left) * scaleX

    for (const bar of _barData) {
      if (mx >= bar.x && mx <= bar.x + bar.w) {
        if (bar.length === _lastClickedLength) {
          _cycleIndex = (_cycleIndex + 1) % bar.strandIds.length
        } else {
          _lastClickedLength = bar.length
          _cycleIndex = 0
        }
        const strandId = bar.strandIds[_cycleIndex]
        const total = bar.strandIds.length
        tooltip.textContent = `${bar.length} nt · ${_cycleIndex + 1}/${total} strand(s)`

        selectionManager.selectStrand(strandId)
        centerOnStrand(strandId)
        return
      }
    }
    tooltip.textContent = ''
  })

  // Tooltip on hover
  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const mx = (e.clientX - rect.left) * scaleX
    for (const bar of _barData) {
      if (mx >= bar.x && mx <= bar.x + bar.w) {
        tooltip.textContent = `${bar.length} nt · ${bar.strandIds.length} strand(s)${bar.isOut ? ' ⚠ out of range' : ''}`
        return
      }
    }
    tooltip.textContent = ''
  })
  canvas.addEventListener('mouseleave', () => { tooltip.textContent = '' })

  // ── Right-click context menu: delete all strands of this bin length ──────
  const _histCtx       = document.getElementById('hist-ctx-menu')
  const _histCtxHeader = document.getElementById('hist-ctx-header')
  const _histCtxCount  = document.getElementById('hist-ctx-count')
  const _histCtxDelete = document.getElementById('hist-ctx-delete-btn')
  let _ctxBar = null

  function _hideHistCtx() {
    if (_histCtx) _histCtx.style.display = 'none'
    _ctxBar = null
  }

  canvas.addEventListener('contextmenu', e => {
    e.preventDefault()
    const rect   = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const mx     = (e.clientX - rect.left) * scaleX
    for (const bar of _barData) {
      if (mx >= bar.x && mx <= bar.x + bar.w) {
        _ctxBar = bar
        if (_histCtxHeader) _histCtxHeader.textContent = `${bar.length} nt`
        if (_histCtxCount)  _histCtxCount.textContent  = bar.strandIds.length
        if (_histCtx) {
          _histCtx.style.left    = `${e.clientX}px`
          _histCtx.style.top     = `${e.clientY}px`
          _histCtx.style.display = 'block'
        }
        return
      }
    }
  })

  document.addEventListener('pointerdown', e => {
    if (_histCtx?.style.display !== 'none' && !_histCtx.contains(e.target)) _hideHistCtx()
  })

  _histCtxDelete?.addEventListener('click', async () => {
    if (!_ctxBar) return
    const bar = _ctxBar
    _hideHistCtx()
    if (bar.strandIds.length === 1) await api.deleteStrand(bar.strandIds[0])
    else await api.deleteStrandsBatch(bar.strandIds)
  })

  // Redraw when design changes and histogram is visible; reset cycle state
  store.subscribe((newState, prevState) => {
    if (_expanded && newState.currentDesign !== prevState.currentDesign) {
      _lastClickedLength = null
      _cycleIndex = 0
      _redraw(newState.currentDesign)
    }
  })

  return { redraw: _redraw }
}
