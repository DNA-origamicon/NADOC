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
 *
 * Co-editing honesty (ISSUE-2 sub-phase B): a flat green "saved" badge used to
 * imply siblings-in-sync, but two tabs holding the SAME workspace file each own a
 * DIFFERENT backend document (ISSUE-2 root cause), so their saves can clobber each
 * other on disk. `setSiblingCoediting(count)` flags that: when ≥1 other tab shares
 * our file AND the resting state is "saved" (green), the dot turns a distinct
 * "coedit" colour and the label calls it out. An active save / error keeps its own
 * colour so transient sync state is never masked. `countCoeditingSiblings` is the
 * pure detector main.js feeds from the doc-presence broadcast.
 */
export function initSyncBadge() {
  const dot   = document.querySelector('#sync-status .sync-dot')
  const text  = document.getElementById('sync-status-text')
  const panel = document.getElementById('sync-debug-panel')
  // Verbose console output is tied to the debug panel being visible.
  let debugLogging = false
  // Composed badge state: the base sync status, plus how many OTHER tabs hold our
  // file. _render() folds the two so a sibling count only annotates the resting
  // "saved" (green) state.
  let _baseState = 'green'
  let _baseLabel = ''
  let _baseTs    = ''
  let _siblingCount = 0
  document.getElementById('sync-debug-close')?.addEventListener('click', () => {
    panel?.classList.remove('visible')
    debugLogging = false
  })

  function _render() {
    const coedit = _siblingCount > 0 && _baseState === 'green'
    if (dot)  { dot.className = coedit ? 'sync-dot coedit' : `sync-dot ${_baseState}` }
    if (text) {
      text.textContent = coedit
        ? `${_baseLabel} · ${_siblingCount} tab${_siblingCount > 1 ? 's' : ''} editing this file ${_baseTs}`
        : `${_baseLabel} ${_baseTs}`
    }
  }

  function setSyncStatus(state, label) {
    _baseState = state
    _baseLabel = label
    _baseTs    = new Date().toLocaleTimeString('en-US', { hour12: false })
    _render()
  }

  // How many OTHER tabs hold this same workspace file (different backend doc).
  // 0 ⇒ plain "saved"; ≥1 ⇒ the co-editing annotation when at rest.
  function setSiblingCoediting(count) {
    _siblingCount = Math.max(0, count | 0)
    _render()
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
    setSiblingCoediting,
    syncLog,
    showDebugPanel()   { panel?.classList.add('visible');    debugLogging = true },
    hideDebugPanel()   { panel?.classList.remove('visible'); debugLogging = false },
    toggleDebugPanel() { debugLogging = !!panel?.classList.toggle('visible') },
  }
}

/**
 * Pure detector: how many OTHER tabs hold our same workspace file in a DIFFERENT
 * backend document — the divergence/clobber risk the badge surfaces. `others` is
 * the list of sibling doc-presence records ({ workspacePath, docId, … }). A sibling
 * sharing our docId (e.g. a cadnano editor child window opened with our ?doc=) is
 * genuinely in-sync (same backend doc) and is NOT counted.
 */
export function countCoeditingSiblings(myPath, myDocId, others) {
  if (!myPath || !Array.isArray(others)) return 0
  let n = 0
  for (const o of others) {
    if (o && o.workspacePath === myPath && o.docId !== myDocId) n++
  }
  return n
}
