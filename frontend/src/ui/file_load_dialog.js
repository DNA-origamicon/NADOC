// File-load progress overlay — the modal shown while a part/design is fetched,
// imported, and validated (e.g. the `?part-instance=` part-editor boot path).
//
// Owns the overlay's DOM refs (`#file-load-progress` + its `flp-*` children), the
// `_flLogOpen` details-pane toggle state, and the details-toggle button listener.
// Exposes show/hide/progress/log/success/error so callers drive a load sequence:
//   show('Opening Part') → setProgress(0,'…') → appendLog('…') →
//   showSuccess('…') | showError('…')
//
// Extracted verbatim from main.js (banner `// ── File-load overlay helpers`).
// Fully self-contained: no store/api/scene — only DOM + setTimeout. The `flp-main-menu`
// button stays wired in main.js because its handler bridges to the welcome screen.

/**
 * Wire the file-load progress overlay and return its control API.
 * @returns {{show:Function, hide:Function, setProgress:Function, appendLog:Function,
 *            expandDetails:Function, showSuccess:Function, showError:Function}}
 */
export function initFileLoadDialog() {
  const _flProgress   = document.getElementById('file-load-progress')
  const _flFillEl     = document.getElementById('flp-fill')
  const _flStatusEl   = document.getElementById('flp-status')
  const _flHeaderEl   = document.getElementById('flp-header')
  const _flLogEl      = document.getElementById('flp-log')
  const _flLogWrapEl  = document.getElementById('flp-log-wrap')
  const _flToggleBtn  = document.getElementById('flp-details-toggle')
  const _flActionsEl  = document.getElementById('flp-actions')

  let _flLogOpen = false

  _flToggleBtn?.addEventListener('click', () => {
    _flLogOpen = !_flLogOpen
    _flLogWrapEl.style.display  = _flLogOpen ? 'block' : 'none'
    _flToggleBtn.textContent    = (_flLogOpen ? '▾' : '▸') + ' Details'
  })

  function _showFileLoad(header) {
    _flLogOpen = false
    if (_flLogEl)     _flLogEl.innerHTML             = ''
    if (_flLogWrapEl) _flLogWrapEl.style.display     = 'none'
    if (_flToggleBtn) _flToggleBtn.textContent       = '▸ Details'
    if (_flActionsEl) _flActionsEl.style.display     = 'none'
    if (_flHeaderEl)  _flHeaderEl.textContent        = header
    if (_flFillEl)    { _flFillEl.style.background   = '#3ddc84'; _flFillEl.style.width = '0%' }
    if (_flStatusEl)  { _flStatusEl.textContent      = ''; _flStatusEl.style.color = '#c9d1d9' }
    _flProgress?.classList.add('visible')
  }

  function _hideFileLoad() {
    _flProgress?.classList.remove('visible')
  }

  function _flSetProgress(pct, msg) {
    if (_flFillEl)   _flFillEl.style.width    = pct + '%'
    if (_flStatusEl) _flStatusEl.textContent  = msg ?? ''
  }

  function _flAppendLog(msg, type = 'info') {
    if (!_flLogEl) return
    const colors = { info: '#8b949e', warn: '#d29922', error: '#f85149', success: '#3fb950' }
    const line = document.createElement('div')
    line.style.color  = colors[type] ?? colors.info
    line.textContent  = msg
    _flLogEl.appendChild(line)
    _flLogEl.scrollTop = _flLogEl.scrollHeight
  }

  function _flExpandDetails() {
    _flLogOpen = true
    if (_flLogWrapEl) _flLogWrapEl.style.display = 'block'
    if (_flToggleBtn) _flToggleBtn.textContent   = '▾ Details'
  }

  async function _flShowSuccess(msg) {
    if (_flFillEl)   { _flFillEl.style.width = '100%'; _flFillEl.style.background = '#3fb950' }
    if (_flStatusEl) { _flStatusEl.textContent = msg; _flStatusEl.style.color = '#3fb950' }
    await new Promise(r => setTimeout(r, 1500))
    _hideFileLoad()
  }

  function _flShowError(msg) {
    if (_flFillEl)   { _flFillEl.style.width = '100%'; _flFillEl.style.background = '#f85149' }
    if (_flStatusEl) { _flStatusEl.textContent = msg; _flStatusEl.style.color = '#f85149' }
    _flExpandDetails()
    if (_flActionsEl) _flActionsEl.style.display = 'flex'
  }

  return {
    show:          _showFileLoad,
    hide:          _hideFileLoad,
    setProgress:   _flSetProgress,
    appendLog:     _flAppendLog,
    expandDetails: _flExpandDetails,
    showSuccess:   _flShowSuccess,
    showError:     _flShowError,
  }
}
