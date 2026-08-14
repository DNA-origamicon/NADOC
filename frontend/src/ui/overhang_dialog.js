/** Owns the Add Overhang dialog lifecycle and commit state machine. */
import * as api from '../api/client.js'
import { store } from '../state/store.js'
import {
  beginOperationTiming,
  markOperationTiming,
  finishOperationAfterRender,
} from '../perf/operation_timing.js'

export function initOverhangDialog({
  slicePlane,
  assemblyRenderer,
  getPreviewEnabled,
  setPreviewEnabled,
  setRefreshGhost,
  showGhost: _showOverhangGhost,
  clearGhost: _clearOverhangGhost,
  markGhostPending: _markOverhangGhostPending,
  rebuildOverhangLocations: _rebuildOverhangLocations,
  broadcastInstanceChanged: _broadcastInstanceChanged,
}) {
  const inputStyle = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                     'color:#c9d1d9;padding:2px 6px;font-family:inherit;font-size:12px;'
  const tabStyle   = 'flex:1;padding:4px 0;background:none;border:none;border-bottom:2px solid transparent;' +
                     'color:#8b949e;font-family:inherit;font-size:11px;cursor:pointer;'
  const tabActiveStyle = tabStyle + 'color:#00e5ff;border-bottom-color:#00e5ff;'

  const overlay = document.createElement('div')
  overlay.id = 'overhang-length-dialog'
  Object.assign(overlay.style, {
    display:      'none',
    position:     'fixed',
    background:   '#161b22',
    border:       '1px solid #30363d',
    borderRadius: '6px',
    padding:      '12px 16px',
    color:        '#c9d1d9',
    fontFamily:   "var(--font-ui)",
    fontSize:     'var(--text-xs)',
    zIndex:       '200',
    boxShadow:    '0 8px 24px rgba(0,0,0,0.5)',
    minWidth:     '260px',
  })
  overlay.innerHTML = `
    <div style="margin-bottom:10px;font-weight:bold;color:#00e5ff;">Add Overhang</div>

    <div style="margin-bottom:10px;">
      <div style="margin-bottom:4px;font-size:11px;color:#8b949e;">Name (optional):</div>
      <input id="ovhg-name-input" type="text" placeholder="e.g. toehold-1" autocomplete="off"
        style="width:100%;box-sizing:border-box;${inputStyle}">
    </div>

    <div style="display:flex;border-bottom:1px solid #30363d;margin-bottom:10px;">
      <button id="ovhg-tab-length" style="${tabActiveStyle}">By Length</button>
      <button id="ovhg-tab-seq"    style="${tabStyle}">By Sequence</button>
    </div>

    <div id="ovhg-panel-length">
      <label style="display:flex;align-items:center;gap:8px;">
        <span>Length (bp):</span>
        <input id="overhang-length-input" type="number" min="1" max="500" value="10"
          style="width:60px;${inputStyle}">
      </label>
    </div>

    <div id="ovhg-panel-seq" style="display:none">
      <div style="margin-bottom:4px;font-size:11px;color:#8b949e;">Paste sequence (5′→3′):</div>
      <input id="ovhg-seq-input" type="text" placeholder="ACGT…" autocomplete="off" spellcheck="false"
        style="width:100%;box-sizing:border-box;${inputStyle}letter-spacing:0.05em;">
      <div id="ovhg-seq-len" style="margin-top:3px;font-size:var(--text-xs);color:#484f58;">0 bp</div>
    </div>

    <label style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:11px;color:#c9d1d9;cursor:pointer"
           title="Show a translucent preview of the overhang this will add">
      <input id="ovhg-preview-toggle" type="checkbox" checked style="cursor:pointer"> Show preview
    </label>

    <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end;">
      <button id="overhang-cancel-btn"
        style="padding:3px 10px;background:#21262d;border:1px solid #30363d;border-radius:4px;
               color:#c9d1d9;font-family:inherit;font-size:12px;cursor:pointer;">Cancel</button>
      <button id="overhang-ok-btn"
        style="padding:3px 10px;background:#1f6feb;border:none;border-radius:4px;
               color:#fff;font-family:inherit;font-size:12px;cursor:pointer;">Extrude</button>
    </div>
  `
  document.body.appendChild(overlay)

  let _pendingEntry = null
  let _activeTab    = 'length'   // 'length' | 'seq'
  let _commitInFlight = false

  const tabLength  = overlay.querySelector('#ovhg-tab-length')
  const tabSeq     = overlay.querySelector('#ovhg-tab-seq')
  const panelLen   = overlay.querySelector('#ovhg-panel-length')
  const panelSeq   = overlay.querySelector('#ovhg-panel-seq')
  const seqInput   = overlay.querySelector('#ovhg-seq-input')
  const seqLenEl   = overlay.querySelector('#ovhg-seq-len')
  const okBtn      = overlay.querySelector('#overhang-ok-btn')
  const lenInput   = overlay.querySelector('#overhang-length-input')
  const nameInput  = overlay.querySelector('#ovhg-name-input')
  const previewToggle = overlay.querySelector('#ovhg-preview-toggle')

  // bp length for the active tab — drives the live ghost preview.
  function _currentOverhangLen() {
    if (_activeTab === 'length') return parseInt(lenInput.value, 10)
    return seqInput.value.replace(/\s/g, '').length
  }
  function _refreshGhost() { _showOverhangGhost(_pendingEntry, _currentOverhangLen()) }

  // "Show preview" lives in this popup; mirror the shared flag + persist + sync slice plane.
  previewToggle.addEventListener('change', () => {
    setPreviewEnabled(previewToggle.checked)
    localStorage.setItem('NADOC_EXTRUDE_PREVIEW', String(getPreviewEnabled()))
    slicePlane.setPreviewEnabled(getPreviewEnabled())
    _refreshGhost()   // shows or clears based on the flag
  })

  function _switchTab(tab) {
    _activeTab = tab
    const isLen = tab === 'length'
    tabLength.style.cssText  = isLen ? tabActiveStyle : tabStyle
    tabSeq.style.cssText     = isLen ? tabStyle : tabActiveStyle
    panelLen.style.display   = isLen ? '' : 'none'
    panelSeq.style.display   = isLen ? 'none' : ''
    okBtn.textContent        = isLen ? 'Extrude' : 'Extrude + Assign'
    setTimeout(() => (isLen ? lenInput : seqInput).focus(), 0)
    _refreshGhost()
  }

  tabLength.addEventListener('click', () => _switchTab('length'))
  tabSeq.addEventListener('click',    () => _switchTab('seq'))

  lenInput.addEventListener('input', _refreshGhost)
  seqInput.addEventListener('input', () => {
    const n = seqInput.value.replace(/\s/g, '').length
    seqLenEl.textContent = `${n} bp`
    seqLenEl.style.color = n > 0 ? '#8b949e' : '#484f58'
    _refreshGhost()
  })

  function _hide({ preserveGhost = false } = {}) {
    overlay.style.display = 'none'
    _pendingEntry = null
    seqInput.value  = ''
    nameInput.value = ''
    seqLenEl.textContent = '0 bp'
    seqLenEl.style.color = '#484f58'
    if (!preserveGhost) _clearOverhangGhost()
    setRefreshGhost(() => {})
  }

  function show(entry, clientX, clientY) {
    _pendingEntry = entry
    overlay.style.left    = `${Math.min(clientX, window.innerWidth  - 290)}px`
    overlay.style.top     = `${Math.min(clientY, window.innerHeight - 200)}px`
    overlay.style.display = 'block'
    _switchTab('length')
    lenInput.value  = '10'
    nameInput.value = ''
    previewToggle.checked = getPreviewEnabled()
    nameInput.focus()
    setRefreshGhost(_refreshGhost)
    _refreshGhost()
  }

  async function _doExtrude() {
    if (_commitInFlight) return
    const entry = _pendingEntry
    if (!entry) return

    let lengthBp, sequence
    if (_activeTab === 'length') {
      lengthBp = parseInt(lenInput.value, 10)
      if (!Number.isFinite(lengthBp) || lengthBp < 1) return
      sequence = null
    } else {
      sequence = seqInput.value.replace(/\s/g, '').toUpperCase()
      if (!sequence.length) return
      lengthBp = sequence.length
    }

    // Capture name BEFORE _hide() clears the input.
    const name = nameInput.value.trim() || null

    _commitInFlight = true
    _markOverhangGhostPending()
    _hide({ preserveGhost: true })
    const optimisticTrace = beginOperationTiming('POST /design/overhang/extrude', {
      optimisticPreview: true,
      body: { helixId: entry.helixId, bpIndex: entry.bpIndex, lengthBp },
    })
    markOperationTiming('optimistic-preview-visible', undefined, optimisticTrace)

    try {
      const params = {
        helixId:     entry.helixId,
        bpIndex:     entry.bpIndex,
        direction:   entry.direction,
        isFivePrime: entry.isFivePrime,
        neighborRow: entry.neighborRow,
        neighborCol: entry.neighborCol,
        lengthBp,
      }

      if (entry.instanceId) {
        // Assembly-mode extrude: writes to that PartInstance's design file,
        // then re-renders the affected instance and broadcasts so part-editor
        // and cadnano-editor tabs viewing the same instance auto-refresh.
        let resp
        try {
          resp = await api.extrudeInstanceOverhang(entry.instanceId, params)
        } catch (err) {
          console.error('Overhang extrude (instance) failed:', err?.message ?? err)
          return
        }

        // Patch sequence/label on the same instance if the user supplied them.
        // Use the per-overhang assembly endpoint so the change lands in the
        // part's feature_log (and an assembly-level metadata entry) — the
        // wholesale patchInstanceDesign path bypasses the feature log.
        if ((sequence || name) && resp?.design) {
          const endTag     = entry.isFivePrime ? '5p' : '3p'
          const overhangId = `ovhg_${entry.helixId}_${entry.bpIndex}_${endTag}`
          const patch = {}
          if (sequence) patch.sequence = sequence
          if (name)     patch.label    = name
          try {
            await api.patchInstanceOverhang(entry.instanceId, overhangId, patch)
          } catch (err) {
            console.warn('Overhang label/sequence patch failed:', err?.message ?? err)
          }
        }

        // Re-fetch and re-render this instance in the assembly scene, then
        // refresh the overhang locations (active-instance arrows now reflect
        // the new topology).
        assemblyRenderer.invalidateInstance(entry.instanceId)
        await assemblyRenderer.rebuild(store.getState().currentAssembly)
        markOperationTiming('assembly-scene-rebuilt')
        finishOperationAfterRender()
        _rebuildOverhangLocations()

        // Tell other tabs viewing this instance to refresh.
        _broadcastInstanceChanged(entry.instanceId)
        return
      }

      const result = await api.extrudeOverhang(params)
      if (!result) {
        console.error('Overhang extrude failed:', store.getState().lastError?.message)
        return
      }

      // Assign name and/or sequence to the new OverhangSpec immediately.
      if (sequence || name) {
        const endTag     = entry.isFivePrime ? '5p' : '3p'
        const overhangId = `ovhg_${entry.helixId}_${entry.bpIndex}_${endTag}`
        const patch = {}
        if (sequence) patch.sequence = sequence
        if (name)     patch.label    = name
        await api.patchOverhang(overhangId, patch)
      }
    } finally {
      // The API sync above has atomically installed canonical topology and
      // geometry. Removing the ghost now is authoritative reconciliation;
      // failures simply reveal the untouched confirmed scene underneath.
      _clearOverhangGhost()
      _commitInFlight = false
    }
  }

  okBtn.addEventListener('click', _doExtrude)
  overlay.querySelector('#overhang-cancel-btn').addEventListener('click', _hide)

  lenInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') _doExtrude()
    if (e.key === 'Escape') _hide()
  })
  seqInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') _doExtrude()
    if (e.key === 'Escape') _hide()
  })

  // Click outside closes dialog
  document.addEventListener('pointerdown', e => {
    if (overlay.style.display !== 'none' && !overlay.contains(e.target)) _hide()
  }, true)

  return { show }
}
