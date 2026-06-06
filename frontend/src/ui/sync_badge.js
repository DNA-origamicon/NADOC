/**
 * Sync status badge + debug log panel.
 *
 * The status dot (`#sync-status .sync-dot`) + label (`#sync-status-text`) reflect
 * the most recent backend-sync action (saving / saved / sync error …); the debug
 * panel (`#sync-debug-panel`) keeps a rolling 150-row log of sync events. This is
 * pure presentation — no store / scene / flag coupling — so the auto-save
 * subscribers, the connection monitor, the file-IO ops and the SSE handler all
 * just call `setSyncStatus` / `syncLog`. The flag-reading `window.__nadocSyncDebug`
 * helper stays in main.js (it inspects loop-prevention flags) and drives this panel
 * via show/hide.
 *
 * The console mirror in `syncLog` is SILENT BY DEFAULT (ISSUE-2 sub-phase C): it
 * only writes to the browser console while the debug panel is open (Ctrl+Shift+D /
 * `__nadocSyncDebug.show()`). The rolling in-panel log always records every event,
 * so opening the panel still shows recent history — the gating just keeps the
 * default console clean so real signal isn't drowned in sync chatter.
 */
export function initSyncBadge() {
  const dot   = document.querySelector('#sync-status .sync-dot')
  const text  = document.getElementById('sync-status-text')
  const panel = document.getElementById('sync-debug-panel')
  // Verbose console output is tied to the debug panel being visible.
  let debugLogging = false
  document.getElementById('sync-debug-close')?.addEventListener('click', () => {
    panel?.classList.remove('visible')
    debugLogging = false
  })

  function setSyncStatus(state, label) {
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
    if (dot)  { dot.className = `sync-dot ${state}` }
    if (text) { text.textContent = `${label} ${ts}` }
  }

  function syncLog(level, tag, msg) {
    const cls = level === 'err' ? 'error' : level === 'warn' ? 'warn' : 'log'
    if (debugLogging) console[cls](`[SYNC][${tag}] ${msg}`)
    const body = document.getElementById('sync-debug-body')
    if (!body) return
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
    const row  = document.createElement('div');  row.className  = 'sdp-row'
    const tsEl = document.createElement('span'); tsEl.className = 'sdp-ts';         tsEl.textContent = ts
    const tagEl= document.createElement('span'); tagEl.className= `sdp-type ${level==='err'?'err':level==='warn'?'warn':'info'}`; tagEl.textContent = tag
    const msgEl= document.createElement('span'); msgEl.className= 'sdp-msg';        msgEl.textContent = msg
    row.append(tsEl, tagEl, msgEl)
    body.insertBefore(row, body.firstChild)
    while (body.children.length > 150) body.removeChild(body.lastChild)
  }

  return {
    setSyncStatus,
    syncLog,
    showDebugPanel()   { panel?.classList.add('visible');    debugLogging = true },
    hideDebugPanel()   { panel?.classList.remove('visible'); debugLogging = false },
    toggleDebugPanel() { debugLogging = !!panel?.classList.toggle('visible') },
  }
}
