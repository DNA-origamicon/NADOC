// Read-only design diagnostics: red backbone clashes and cyan ring piercings.

import { getClashes } from '../api/client.js'
import { Matrix4, Vector3 } from 'three'
import { atomBaseKey, baseKey, xbKey } from './base_ref.js'

/**
 * PURE: given the clash report's pair list + the renderer's backbone entries,
 * return the subset of entries that sit on a clashing nucleotide.
 *
 * Each clash pair carries two sides { helix_id, bp_index, direction }; a backbone
 * entry is highlighted when its nucleotide matches either side of any pair.
 *
 * @param {Array<{a:object, b:object}>} clashes  report.clashes
 * @param {Array} backboneEntries  designRenderer.getBackboneEntries()
 * @returns {Array} de-duplicated entries to highlight (possibly empty)
 */
export function clashEntriesFor(clashes, backboneEntries) {
  if (!clashes?.length || !backboneEntries?.length) return []
  const keys = new Set()
  for (const c of clashes ?? []) {
    for (const side of [c?.a, c?.b]) {
      if (side) keys.add(`${side.helix_id}:${side.bp_index}:${side.direction}`)
    }
  }
  const seen = new Set()
  const out = []
  for (const e of backboneEntries) {
    const n = e?.nuc
    if (!n) continue
    if (keys.has(`${n.helix_id}:${n.bp_index}:${n.direction}`) && !seen.has(e)) {
      seen.add(e)
      out.push(e)
    }
  }
  return out
}

/** Resolve detector nucleotide identities, never their shared extension/insert anchor. */
export function piercingEntriesFor(nucleotides, backboneEntries = [], xoverEntries = []) {
  const entries = new Map(backboneEntries.map(e => [baseKey(e.nuc, e.nuc?.copy_k ?? 0), e]))
  for (const e of xoverEntries) {
    const matrix = new Matrix4(), pos = new Vector3()
    entries.set(xbKey(e.xoId, e.simK), { getPosition() {
      e.instMesh.getMatrixAt(e.id, matrix)
      return pos.setFromMatrixPosition(matrix).applyMatrix4(e.instMesh.matrixWorld)
    } })
  }
  const seen = new Set(), out = []
  for (const atom of nucleotides ?? []) {
    const key = atomBaseKey(atom)
    if (!key || seen.has(key)) continue
    seen.add(key)
    const entry = entries.get(key)
    if (entry) out.push(entry)
    else if (atom.position?.length === 3 && atom.position.every(Number.isFinite)) {
      out.push({ pos: new Vector3(...atom.position) })
    }
  }
  return out
}

export function initClashOverlay({ store, designRenderer, api = { getClashes } } = {}) {
  let _on = false
  let _lastGeometry = null
  let _lastDesignId = null
  let _lastReport = null
  let _request = 0
  let _abort = null, _waitTimer
  const _legend     = document.getElementById('clash-legend')
  const _legendText = document.getElementById('clash-legend-text')
  const _piercingText = document.getElementById('piercing-legend-text')
  const _status = document.getElementById('clash-legend-status')
  const _progress = document.getElementById('piercing-check-progress')
  const _percent = document.getElementById('piercing-check-percent')

  function _stopWaiting() {
    clearTimeout(_waitTimer)
    if (_progress) _progress.hidden = true
    _abort?.abort()
    _abort = null
  }

  function _setLegend(report, status = '') {
    _legend?.classList.add('visible')
    _legend?.classList.toggle('none', !!report && report.count === 0 && report.piercing.count === 0 && !report.piercing.truncated)
    if (_status) _status.textContent = status
    if (!report) {
      if (_legendText) _legendText.textContent = 'Clashes —'
      if (_piercingText) _piercingText.textContent = 'Piercings —'
      return
    }
    const count = report.count, piercing = report.piercing
    if (_legendText) _legendText.textContent = count === 1 ? '1 clash' : `${count} clashes`
    if (_piercingText) _piercingText.textContent = `${piercing.count}${piercing.truncated ? '+' : ''} ${piercing.count === 1 && !piercing.truncated ? 'piercing' : 'piercings'}`
  }

  function _clearMarkers() {
    designRenderer?.clearClashHighlight?.()
    designRenderer?.clearPiercingHighlight?.()
  }

  function clear() {
    ++_request
    _stopWaiting()
    _lastReport = null
    _clearMarkers()
    _legend?.classList.remove('visible')
    window.dispatchEvent(new Event('nadoc:view-scene-changed'))
  }

  /** Re-resolve the LAST report against the current backbone entries — no refetch.
   *  For a rebuild that did not move anything (the capture-strand injection), the
   *  report is still valid; only the entry objects it was painted onto are stale. */
  function _repaint() {
    if (!_on || !_lastReport) return
    const backbone = designRenderer?.getBackboneEntries?.() ?? []
    const entries = clashEntriesFor(_lastReport.clashes, backbone)
    if (entries.length) designRenderer?.setClashHighlight?.(entries)
    else designRenderer?.clearClashHighlight?.()
    const pierced = piercingEntriesFor(_lastReport.piercing.nucleotides, backbone,
      designRenderer?.getXoverBeadEntries?.() ?? [])
    if (pierced.length) designRenderer?.setPiercingHighlight?.(pierced)
    else designRenderer?.clearPiercingHighlight?.()
    window.dispatchEvent(new Event('nadoc:view-scene-changed'))
  }

  /** Re-fetch the clash report and repaint (no-op while toggled off). */
  let pending = Promise.resolve()
  function refresh() {
    pending = refreshReport()
    return pending
  }
  async function whenReady() {
    let current
    do { current = pending; await current } while (current !== pending)
  }
  async function refreshReport() {
    if (!_on) return
    const design = store?.getState?.().currentDesign
    if (!design) { clear(); return }
    const request = ++_request
    _stopWaiting()
    _abort = new AbortController()
    _lastReport = null
    _clearMarkers()
    _setLegend(null, 'Checking design geometry…')
    if (_percent) _percent.textContent = '0%'
    _waitTimer = setTimeout(() => {
      if (_on && request === _request && _progress) _progress.hidden = false
    }, 1000)
    try {
      const report = await (api?.getClashes ?? getClashes)({ signal: _abort.signal, onProgress(value) {
        if (!_on || request !== _request) return
        if (_percent && Number.isFinite(value.percent)) _percent.textContent = `${Math.min(99, Math.max(0, Math.floor(value.percent)))}%`
        if (_status) _status.textContent = value.stage === 'Checking bonds'
          ? 'Checking bonds for ring piercing…' : 'Preparing atoms for piercing check…'
      } })
      if (!_on || request !== _request) return
      if (!report || !Number.isInteger(report.count) || !Array.isArray(report.clashes) ||
          !Number.isInteger(report.piercing?.count) || !Array.isArray(report.piercing?.nucleotides)) {
        throw new Error('Incomplete defect report')
      }
      _lastReport = report
      _repaint()
      _setLegend(report)
    } catch {
      if (_on && request === _request) _setLegend(null, 'Check unavailable. Toggle off/on to retry.')
    } finally {
      if (request === _request) _stopWaiting()
    }
  }

  /** Flip the toggle; returns the new on/off state. */
  function toggle() {
    _on = !_on
    if (_on) {
      const state = store?.getState?.()
      _lastGeometry = state?.currentGeometry; _lastDesignId = state?.currentDesign?.id
      refresh()
    }
    else clear()
    return _on
  }

  function isOn() { return _on }

  // A geometry rebuild replaces the backbone entries (and clears the glow layer)
  // and, more importantly, changes the posed positions the clash report is about —
  // re-fetch. Registered after the designRenderer subscriber so getBackboneEntries()
  // is fresh by the time the (async) report returns.
  const unsubscribe = store?.subscribe?.(() => {
    const { currentGeometry: geo, currentDesign: design } = store.getState()
    if (_on && (geo !== _lastGeometry || design?.id !== _lastDesignId)) {
      _lastGeometry = geo; _lastDesignId = design?.id; refresh()
    }
  })

  // A DISPLAY-ONLY rebuild (the oxDNA capture-strand injection) replaces the backbone
  // entries without touching the store or moving a single design nucleotide. Repaint
  // the standing report rather than re-fetching one per keystroke.
  window.addEventListener('nadoc:display-rebuilt', _repaint)

  function dispose() {
    _on = false; clear()
    if (typeof unsubscribe === 'function') unsubscribe()
    window.removeEventListener('nadoc:display-rebuilt', _repaint)
  }
  return { toggle, refresh, clear, isOn, dispose, whenReady }
}
