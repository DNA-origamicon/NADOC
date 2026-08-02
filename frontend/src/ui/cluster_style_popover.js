/**
 * Cluster style popover — the colour + opacity editor behind each swatch button in
 * the Movable Clusters sidebar.
 *
 * Colour applies only in cluster-coloring mode; opacity applies in every coloring
 * mode. Both persist on the cluster (see backend ClusterRigidTransform).
 *
 * Why this is a factory owning ONE reused element in document.body, rather than a
 * per-row div: cluster_panel rebuilds its whole list with `innerHTML = ''` on every
 * currentDesign change — including the response to this popover's own PATCH. A
 * popover living inside a row would be destroyed under the user's cursor mid-drag.
 * So it is keyed by clusterId, positioned once on open from the anchor's rect, and
 * never re-anchored; the panel just tells it to close if its cluster disappears.
 *
 * Commit strategy (mirrors the rename in cluster_panel.js — no undo push for a
 * cosmetic edit):
 *    'input'  → onPreview only, ZERO network. Patching at frame rate would rebuild
 *               the sidebar ~60×/s under the cursor.
 *    'change' → one onCommit, debounced so keyboard arrow-stepping collapses.
 *    close    → flush anything pending.
 *
 * Pure helpers (normaliseHex, popoverPosition) are unit-tested in
 * cluster_style_popover.test.js; the factory's observable contract is too.
 */
import { normaliseHex } from './hex_color.js'

export { normaliseHex }

/** Trailing debounce on the commit, in ms. Arrow-key stepping fires `change` per
 *  keypress in Chrome, so a burst must collapse to one request. */
const COMMIT_DEBOUNCE_MS = 300
const MARGIN = 8

/**
 * Where to put the popover given its anchor. The cluster panel lives in the right
 * sidebar, so prefer opening to the LEFT of the swatch; flip right only when that
 * would run off-screen, and clamp vertically either way.
 *
 * @param {{left:number, right:number, top:number}} anchorRect
 * @param {{width:number, height:number}} size
 * @param {{width:number, height:number}} viewport
 * @returns {{left:number, top:number}}
 */
export function popoverPosition(anchorRect, size, viewport) {
  let left = anchorRect.left - size.width - MARGIN
  if (left < MARGIN) {
    const flipped = anchorRect.right + MARGIN
    left = (flipped + size.width + MARGIN <= viewport.width) ? flipped : MARGIN
  }
  left = Math.min(left, Math.max(MARGIN, viewport.width - size.width - MARGIN))

  const top = Math.min(
    Math.max(MARGIN, anchorRect.top),
    Math.max(MARGIN, viewport.height - size.height - MARGIN),
  )
  return { left, top }
}

const PANEL_CSS = [
  'position:fixed', 'z-index:9998',
  'background:#161b22', 'border:1px solid #30363d', 'border-radius:6px',
  'padding:10px', 'width:190px',
  'box-shadow:0 6px 20px rgba(0,0,0,0.5)',
  'font-size:var(--text-xs,11px)', 'color:#c9d1d9',
].join(';')

const ROW_CSS   = 'display:flex;align-items:center;gap:8px;margin-bottom:8px'
const LABEL_CSS = 'flex:1;color:#8b949e'

/**
 * @param {object} opts
 * @param {(clusterId:string, patch:object) => void} opts.onPreview  live, renderer-only
 * @param {(clusterId:string, patch:object) => void} opts.onCommit   persist (debounced)
 */
export function initClusterStylePopover({ onPreview = null, onCommit = null } = {}) {
  let _clusterId = null
  let _pending   = null          // accumulated patch awaiting its debounced commit
  let _timer     = null

  // ── DOM (built once, reused) ────────────────────────────────────────────────
  const el = document.createElement('div')
  el.className = 'cluster-style-popover'
  el.style.cssText = PANEL_CSS
  el.style.display = 'none'   // set after cssText so it can't be lost to a parse hiccup

  const colorRow = document.createElement('div')
  colorRow.style.cssText = ROW_CSS
  const colorLabel = document.createElement('span')
  colorLabel.textContent = 'Colour'
  colorLabel.style.cssText = LABEL_CSS
  const colorInput = document.createElement('input')
  colorInput.type = 'color'
  colorInput.title = 'Cluster colour (cluster-coloring mode only)'
  colorInput.style.cssText = 'width:32px;height:22px;border:none;background:none;cursor:pointer;padding:0'
  colorRow.append(colorLabel, colorInput)

  const opacityRow = document.createElement('div')
  opacityRow.style.cssText = ROW_CSS
  const opacityLabel = document.createElement('span')
  opacityLabel.textContent = 'Opacity'
  opacityLabel.style.cssText = LABEL_CSS
  const opacityValue = document.createElement('span')
  opacityValue.style.cssText = 'width:34px;text-align:right;color:#8b949e;font-variant-numeric:tabular-nums'
  opacityRow.append(opacityLabel, opacityValue)

  const opacityInput = document.createElement('input')
  opacityInput.type = 'range'
  opacityInput.min = '0'
  opacityInput.max = '1'
  opacityInput.step = '0.01'
  opacityInput.title = 'Cluster opacity (applies in every coloring mode)'
  opacityInput.style.cssText = 'width:100%;margin:0 0 8px 0'

  const resetBtn = document.createElement('button')
  resetBtn.textContent = 'Reset'
  resetBtn.title = 'Back to the automatic palette colour, fully opaque'
  resetBtn.style.cssText =
    'width:100%;background:#21262d;border:1px solid #30363d;color:#8b949e;' +
    'border-radius:3px;font-size:var(--text-xs,11px);padding:4px;cursor:pointer'

  el.append(colorRow, opacityRow, opacityInput, resetBtn)
  // Clicks inside must never reach the sidebar row underneath (which would toggle
  // cluster selection) or the outside-click dismissal below.
  el.addEventListener('pointerdown', e => e.stopPropagation())
  el.addEventListener('click', e => e.stopPropagation())
  document.body.appendChild(el)

  // ── Commit plumbing ─────────────────────────────────────────────────────────
  function _flush() {
    if (_timer) { clearTimeout(_timer); _timer = null }
    if (!_pending || !_clusterId) { _pending = null; return }
    const patch = _pending
    const id = _clusterId
    _pending = null
    onCommit?.(id, patch)
  }

  function _queue(patch) {
    if (!_clusterId) return
    _pending = { ...(_pending ?? {}), ...patch }
    if (_timer) clearTimeout(_timer)
    _timer = setTimeout(_flush, COMMIT_DEBOUNCE_MS)
  }

  // Preview is coalesced to one call per animation frame. A drag across the colour
  // map fires `input` far faster than 60 Hz, and each preview is an O(nucleotides)
  // repaint of the scene — running one per event is what made the picker lag. Only
  // the newest patch matters, so intermediate ones are merged and dropped.
  let _previewPatch = null
  let _previewRaf   = null
  const _raf = (typeof requestAnimationFrame === 'function')
    ? requestAnimationFrame
    : (fn) => setTimeout(fn, 16)
  const _cancelRaf = (typeof cancelAnimationFrame === 'function')
    ? cancelAnimationFrame
    : clearTimeout

  function _preview(patch) {
    if (!_clusterId) return
    _previewPatch = { ...(_previewPatch ?? {}), ...patch }
    if (_previewRaf != null) return
    _previewRaf = _raf(() => {
      _previewRaf = null
      const p = _previewPatch
      _previewPatch = null
      if (p && _clusterId) onPreview?.(_clusterId, p)
    })
  }

  function _cancelPreview() {
    if (_previewRaf != null) { _cancelRaf(_previewRaf); _previewRaf = null }
    _previewPatch = null
  }

  /** Apply a queued preview right now instead of waiting for the frame. Used on
   *  close, so a discrete action (Reset, or releasing outside the popover) shows
   *  immediately rather than only once its PATCH round-trips. */
  function _flushPreview() {
    const p = _previewPatch
    const id = _clusterId
    _cancelPreview()
    if (p && id) onPreview?.(id, p)
  }

  function _setOpacityReadout(v) {
    opacityValue.textContent = `${Math.round(v * 100)}%`
  }

  // ── Input wiring ────────────────────────────────────────────────────────────
  colorInput.addEventListener('input',  () => _preview({ color: colorInput.value }))
  colorInput.addEventListener('change', () => _queue({ color: colorInput.value }))

  opacityInput.addEventListener('input', () => {
    const v = parseFloat(opacityInput.value)
    _setOpacityReadout(v)
    _preview({ opacity: v })
  })
  opacityInput.addEventListener('change', () => _queue({ opacity: parseFloat(opacityInput.value) }))

  resetBtn.addEventListener('click', () => {
    opacityInput.value = '1'
    _setOpacityReadout(1)
    // '' is the clear-to-auto-palette sentinel the PATCH body understands.
    _preview({ color: '', opacity: 1 })
    _queue({ color: '', opacity: 1 })
    close()
  })

  // ── Dismissal ───────────────────────────────────────────────────────────────
  // Containment test rather than relying on the popover's own stopPropagation:
  // this listener runs in the CAPTURE phase (so it beats the sidebar's handlers),
  // which means it fires on the way DOWN, before the target's own listeners.
  function _onDocPointerDown(e) {
    if (e.target && el.contains(e.target)) return
    close()
  }
  function _onKeyDown(e) {
    if (e.key !== 'Escape' || !_clusterId) return
    // Stop the app's global Escape handler too — same guard the rename input uses.
    e.stopPropagation()
    close()
  }
  function _onScroll() { if (_clusterId) close() }

  // Capture phase, so we beat the sidebar's own handlers.
  document.addEventListener('pointerdown', _onDocPointerDown, true)
  document.addEventListener('keydown', _onKeyDown, true)
  window.addEventListener('blur', _onScroll)
  window.addEventListener('scroll', _onScroll, true)

  function close() {
    if (!_clusterId) return
    _flushPreview()    // show the last previewed value without waiting for a frame
    _flush()
    _clusterId = null
    el.style.display = 'none'
  }

  return {
    /**
     * @param {string} clusterId
     * @param {HTMLElement} anchorEl  the swatch button (read once, never retained)
     * @param {{color: string|null, opacity: number}} current
     */
    openFor(clusterId, anchorEl, { color = null, opacity = 1 } = {}) {
      _cancelPreview()               // a queued preview belongs to the PREVIOUS cluster
      _flush()                       // …and so does a pending commit
      _clusterId = clusterId
      colorInput.value = normaliseHex(color, '#888888')
      const o = typeof opacity === 'number' ? opacity : 1
      opacityInput.value = String(o)
      _setOpacityReadout(o)

      el.style.display = 'block'
      const r = anchorEl?.getBoundingClientRect?.() ?? { left: 0, right: 0, top: 0 }
      const { left, top } = popoverPosition(
        r,
        { width: el.offsetWidth || 190, height: el.offsetHeight || 120 },
        { width: window.innerWidth, height: window.innerHeight },
      )
      el.style.left = `${left}px`
      el.style.top  = `${top}px`
    },

    close,
    isOpenFor: (clusterId) => _clusterId === clusterId,

    /** Called by cluster_panel after each list rebuild: an open popover whose
     *  cluster no longer exists (deleted, or reshuffled by a paste) must go. */
    closeIfMissing(idSet) {
      if (_clusterId && !idSet?.has?.(_clusterId)) close()
    },

    destroy() {
      close()
      document.removeEventListener('pointerdown', _onDocPointerDown, true)
      document.removeEventListener('keydown', _onKeyDown, true)
      window.removeEventListener('blur', _onScroll)
      window.removeEventListener('scroll', _onScroll, true)
      el.remove()
    },

    /** @internal test seam */
    _el: el,
  }
}
