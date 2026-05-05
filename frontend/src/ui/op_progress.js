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
let _label  = null
let _header = null
let _bar    = null
let _track  = null
let _fill   = null
let _cancel = null
let _cancelHandler = null

function _ensureRefs() {
  if (_label) return
  _bar    = document.getElementById('op-progress')
  _label  = document.getElementById('op-progress-label')
  _header = document.getElementById('op-progress-header')
  _track  = document.getElementById('op-progress-track')
  _fill   = document.getElementById('op-progress-fill')
  _cancel = document.getElementById('op-progress-cancel')
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
 *  user-driven operations (animation bake, video export). */
export function showOpProgress(header, label, { indeterminate = false, onCancel = null } = {}) {
  _ensureRefs()
  if (!_bar) return
  _busyDepth++
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
}

/** Hide the progress widget. Safe to call when not shown. Uses ref-counting
 *  so two concurrent showers must each hide before the widget disappears. */
export function hideOpProgress() {
  _ensureRefs()
  if (!_bar) return
  _busyDepth = Math.max(0, _busyDepth - 1)
  if (_busyDepth > 0) return
  _bar.classList.remove('indeterminate')
  _bar.classList.remove('visible')
  _cancelHandler = null
  if (_cancel) _cancel.style.display = 'none'
}

/** Update header + label without changing visibility. */
export function setOpProgressLabel(header, label) {
  _ensureRefs()
  if (_header && header != null) _header.textContent = header
  if (_label  && label  != null) _label.textContent  = label
}

/** Drive a determinate fill (0-1). Useful when work units are countable. */
export function setOpProgressFraction(t) {
  _ensureRefs()
  if (!_fill || !_bar) return
  _bar.classList.remove('indeterminate')
  _fill.style.width = `${Math.max(0, Math.min(1, t)) * 100}%`
}
