/**
 * Centred progress popup for long-running operations.
 *
 * Shipped as a single module so both main.js (for tool-driven progress —
 * autostaple, scaffold routing, cluster apply, …) and client.js (for any
 * API call that takes long enough to warrant a "still working" indicator)
 * share the same DOM widget without duplicating logic.
 *
 * Markup is defined in frontend/index.html (#op-progress + children); this
 * module is a thin imperative API around it.
 */

let _busyDepth = 0   // ref-count so concurrent showers don't fight
let _entries = []    // active operations, oldest first: {token, header, label, detail, startedAt}
let _nextToken = 1
let _tick = null
let _meta = null
let _copyBtn = null
let _label  = null
let _header = null
let _bar    = null
let _track  = null
let _fill   = null
let _cancel = null
let _cancelHandler = null

const _ELAPSED_TICK_MS = 500

/** Human-readable duration: 4.2s, 1m 05s, 1h 02m. */
export function formatElapsed(ms) {
  const s = Math.max(0, ms) / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(Math.floor(s % 60)).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

/** Plain-text snapshot of everything the popup is tracking, for pasting into a
 *  troubleshooting note. Newest operation (the one on screen) first. */
export function buildOpProgressReport(now = performance.now()) {
  const lines = [
    'NADOC working popup',
    `Captured: ${new Date().toISOString()}`,
    `Active operations: ${_entries.length}`,
  ]
  for (const e of [..._entries].reverse()) {
    lines.push('')
    lines.push(`Operation: ${e.header}`)
    if (e.label)  lines.push(`Status: ${e.label}`)
    if (e.detail) lines.push(`Process: ${e.detail}`)
    lines.push(`Elapsed: ${formatElapsed(now - e.startedAt)}`)
  }
  const frac = _fill?.style?.width
  if (frac && frac !== '0%' && !_bar?.classList.contains('indeterminate')) lines.push('', `Progress: ${frac}`)
  if (typeof location !== 'undefined') lines.push('', `Page: ${location.href}`)
  return lines.join('\n')
}

function _renderMeta() {
  if (!_meta) return
  const top = _entries[_entries.length - 1]
  if (!top) { _meta.textContent = ''; return }
  const parts = []
  if (top.detail) parts.push(top.detail)
  parts.push(`elapsed ${formatElapsed(performance.now() - top.startedAt)}`)
  if (_entries.length > 1) parts.push(`+${_entries.length - 1} more`)
  _meta.textContent = parts.join(' · ')
}

function _startTick() {
  if (_tick != null || typeof setInterval === 'undefined') return
  _tick = setInterval(_renderMeta, _ELAPSED_TICK_MS)
}

function _stopTick() {
  if (_tick == null) return
  clearInterval(_tick)
  _tick = null
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Non-secure context (e.g. LAN/Tailscale http) has no async clipboard API.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    ta.remove()
    return ok
  }
}

function _emitProgressDiagnostic(action) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('nadoc:op-progress', {
    detail: {
      action,
      depth: _busyDepth,
      visible: !!_bar?.classList.contains('visible'),
      header: (_header?.textContent || '').trim(),
      label: (_label?.textContent || '').trim(),
      meta: (_meta?.textContent || '').trim(),
      fraction: _fill?.style?.width || '',
      at: performance.now(),
    },
  }))
}

function _ensureRefs() {
  if (_label) return
  _bar    = document.getElementById('op-progress')
  _label  = document.getElementById('op-progress-label')
  _header = document.getElementById('op-progress-header')
  _track  = document.getElementById('op-progress-track')
  _fill   = document.getElementById('op-progress-fill')
  _cancel = document.getElementById('op-progress-cancel')
  _meta   = document.getElementById('op-progress-meta')
  _copyBtn = document.getElementById('op-progress-copy')
  if (_copyBtn && !_copyBtn._wired) {
    _copyBtn._wired = true
    _copyBtn.addEventListener('click', async () => {
      const ok = await copyText(buildOpProgressReport())
      _copyBtn.textContent = ok ? 'Copied' : 'Copy failed'
      setTimeout(() => { if (_copyBtn) _copyBtn.textContent = 'Copy details' }, 1500)
    })
  }
  if (_cancel && !_cancel._wired) {
    _cancel._wired = true
    _cancel.addEventListener('click', () => {
      const fn = _cancelHandler
      _cancelHandler = null
      if (_cancel) _cancel.style.display = 'none'
      if (fn) fn()
    })
  }
}

/** Show the progress widget. ``opts.indeterminate`` switches to the animated
 *  sliding bar (use when total work isn't known); otherwise call
 *  ``setOpProgressFraction`` to drive a determinate fill.
 *  ``opts.onCancel`` — if provided, render a Cancel button below the label
 *  that invokes the callback and dismisses the widget. Use for long
 *  user-driven operations (animation bake, video export).
 *  ``opts.detail`` — process identity shown under the label and included in the
 *  copied troubleshooting report (e.g. ``POST /design/auto-break``).
 *  ``opts.startedAt`` — ``performance.now()`` timestamp the work began, when that
 *  predates this call (the request popup appears seconds after the request).
 *  Returns a token; pass it to ``hideOpProgress`` so concurrent operations
 *  release the right entry. */
export function showOpProgress(header, label, { indeterminate = false, onCancel = null, detail = '', startedAt = null } = {}) {
  _ensureRefs()
  if (!_bar) return null
  _busyDepth++
  const token = _nextToken++
  _entries.push({
    token,
    header: header ?? 'Working…',
    label: label ?? '',
    detail,
    startedAt: startedAt ?? performance.now(),
  })
  _startTick()
  if (_header) _header.textContent = header ?? 'Working…'
  if (_label)  _label.textContent  = label  ?? ''
  _bar.classList.toggle('indeterminate', !!indeterminate)
  if (_fill) _fill.style.width = '0%'
  if (_cancel) {
    if (typeof onCancel === 'function') {
      _cancelHandler = onCancel
      _cancel.style.display = ''
    } else {
      _cancelHandler = null
      _cancel.style.display = 'none'
    }
  }
  _bar.classList.add('visible')
  _renderMeta()
  _emitProgressDiagnostic('show')
  return token
}

/** Hide the progress widget. Safe to call when not shown. Uses ref-counting
 *  so two concurrent showers must each hide before the widget disappears. */
export function hideOpProgress(token = null) {
  _ensureRefs()
  if (!_bar) return
  _busyDepth = Math.max(0, _busyDepth - 1)
  const at = token == null ? _entries.length - 1 : _entries.findIndex(e => e.token === token)
  if (at >= 0) _entries.splice(at, 1)
  if (_busyDepth > 0) {
    _renderMeta()
    _emitProgressDiagnostic('hide-deferred')
    return
  }
  _entries = []
  _stopTick()
  if (_meta) _meta.textContent = ''
  _bar.classList.remove('indeterminate')
  _bar.classList.remove('visible')
  _cancelHandler = null
  if (_cancel) _cancel.style.display = 'none'
  _emitProgressDiagnostic('hide')
}

/** Update header + label without changing visibility. */
export function setOpProgressLabel(header, label) {
  _ensureRefs()
  if (_header && header != null) _header.textContent = header
  if (_label  && label  != null) _label.textContent  = label
  const top = _entries[_entries.length - 1]
  if (top) {
    if (header != null) top.header = header
    if (label  != null) top.label  = label
  }
  _emitProgressDiagnostic('label')
}

/** Drive a determinate fill (0-1). Useful when work units are countable. */
export function setOpProgressFraction(t) {
  _ensureRefs()
  if (!_fill || !_bar) return
  _bar.classList.remove('indeterminate')
  _fill.style.width = `${Math.max(0, Math.min(1, t)) * 100}%`
  _emitProgressDiagnostic('fraction')
}
