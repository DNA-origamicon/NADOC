/**
 * Ligation Debug Overlay — diagnostic tool for cross-tab extrude → ligate flow.
 *
 * Toggle with  Ctrl+Shift+L  or  window._ligDebug.toggle()
 *
 * What it shows:
 *   1. Live event log — every BroadcastChannel message and store update
 *   2. Strand topology table — domain count, helix IDs, bp ranges, cross-helix flag
 *   3. Diff view — what changed between the previous and current design
 *
 * Usage from the cadnano-editor main.js:
 *   import { initLigationDebug } from './ligation_debug.js'
 *   initLigationDebug(editorStore, nadocBroadcast)
 */

import { editorStore } from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'

// ── State ────────────────────────────────────────────────────────────────────

let _panel = null
let _logEl = null
let _topoEl = null
let _prevDesign = null
let _eventLog = []     // { ts, type, detail }
const MAX_LOG = 200

// ── Helpers ──────────────────────────────────────────────────────────────────

function _ts() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}.${String(d.getMilliseconds()).padStart(3,'0')}`
}

function _log(type, detail) {
  const entry = { ts: _ts(), type, detail }
  _eventLog.push(entry)
  if (_eventLog.length > MAX_LOG) _eventLog.shift()
  if (_logEl) {
    const line = document.createElement('div')
    line.className = `ld-log-${type}`
    line.textContent = `[${entry.ts}] ${type}: ${detail}`
    _logEl.appendChild(line)
    _logEl.scrollTop = _logEl.scrollHeight
  }
}

/** Summarise a strand's domains as a compact string. */
function _strandSummary(strand) {
  return strand.domains.map(d => {
    const dir = d.direction === 'FORWARD' ? '→' : '←'
    const lo = Math.min(d.start_bp, d.end_bp)
    const hi = Math.max(d.start_bp, d.end_bp)
    return `${d.helix_id} ${dir} [${lo}..${hi}]`
  }).join(' | ')
}

/** Check if a strand has domains on multiple helices (evidence of ligation). */
function _isCrossHelix(strand) {
  if (strand.domains.length < 2) return false
  const helices = new Set(strand.domains.map(d => d.helix_id))
  return helices.size > 1
}

/** Check if adjacent domains have the coaxial ±1 bp adjacency. */
function _coaxialPairs(strand) {
  const pairs = []
  for (let i = 0; i < strand.domains.length - 1; i++) {
    const a = strand.domains[i]
    const b = strand.domains[i + 1]
    if (a.helix_id === b.helix_id) continue
    const isFwd = a.direction === 'FORWARD'
    const adj = isFwd ? 1 : -1
    if (a.end_bp + adj === b.start_bp || a.end_bp === b.start_bp) {
      pairs.push({ domIdx: i, aBp: a.end_bp, bBp: b.start_bp, aHelix: a.helix_id, bHelix: b.helix_id })
    }
  }
  return pairs
}

// ── Topology Table ───────────────────────────────────────────────────────────

function _renderTopology(design) {
  if (!_topoEl) return
  if (!design?.strands?.length) {
    _topoEl.innerHTML = '<div style="color:#8b949e">No design loaded</div>'
    return
  }

  let html = `<div class="ld-topo-header">
    <span>${design.strands.length} strands</span>
    <span>${design.helices?.length ?? 0} helices</span>
  </div>`

  html += '<table class="ld-topo-table"><thead><tr>'
  html += '<th>ID</th><th>Type</th><th>Doms</th><th>Helices</th><th>BP range</th><th>X-helix</th><th>Coaxial</th>'
  html += '</tr></thead><tbody>'

  for (const s of design.strands) {
    const helixSet = new Set(s.domains.map(d => d.helix_id))
    const allBps = []
    for (const d of s.domains) {
      allBps.push(d.start_bp, d.end_bp)
    }
    const lo = Math.min(...allBps)
    const hi = Math.max(...allBps)
    const xHelix = _isCrossHelix(s)
    const coax = _coaxialPairs(s)
    const rowClass = xHelix ? 'ld-row-xhelix' : ''

    html += `<tr class="${rowClass}">`
    html += `<td title="${_strandSummary(s)}">${s.id.length > 18 ? s.id.slice(0, 18) + '...' : s.id}</td>`
    html += `<td>${s.strand_type === 'scaffold' ? 'SCAF' : 'STPL'}</td>`
    html += `<td>${s.domains.length}</td>`
    html += `<td>${[...helixSet].join(', ')}</td>`
    html += `<td>${lo}..${hi}</td>`
    html += `<td>${xHelix ? 'YES' : '-'}</td>`
    html += `<td>${coax.length > 0 ? coax.map(p => `${p.aHelix}:${p.aBp}↔${p.bHelix}:${p.bBp}`).join(', ') : '-'}</td>`
    html += '</tr>'
  }

  html += '</tbody></table>'

  // Domain detail (expanded view)
  html += '<details class="ld-detail"><summary>Full domain list</summary><pre class="ld-pre">'
  for (const s of design.strands) {
    html += `\n${s.id} (${s.strand_type}):\n`
    for (let i = 0; i < s.domains.length; i++) {
      const d = s.domains[i]
      const dir = d.direction === 'FORWARD' ? 'FWD' : 'REV'
      html += `  [${i}] ${d.helix_id} ${dir}  5'=${d.start_bp}  3'=${d.end_bp}\n`
    }
  }
  html += '</pre></details>'

  _topoEl.innerHTML = html
}

// ── Diff View ────────────────────────────────────────────────────────────────

function _diffDesigns(prev, curr) {
  if (!prev || !curr) return 'No previous design to diff against.'
  const lines = []

  // Strand count
  if (prev.strands.length !== curr.strands.length) {
    lines.push(`Strand count: ${prev.strands.length} → ${curr.strands.length}`)
  }

  // Helix count
  if ((prev.helices?.length ?? 0) !== (curr.helices?.length ?? 0)) {
    lines.push(`Helix count: ${prev.helices?.length ?? 0} → ${curr.helices?.length ?? 0}`)
  }

  // New strand IDs
  const prevIds = new Set(prev.strands.map(s => s.id))
  const currIds = new Set(curr.strands.map(s => s.id))
  const added = [...currIds].filter(id => !prevIds.has(id))
  const removed = [...prevIds].filter(id => !currIds.has(id))
  if (added.length) lines.push(`+ Strands added: ${added.join(', ')}`)
  if (removed.length) lines.push(`- Strands removed: ${removed.join(', ')}`)

  // Domain count changes
  for (const s of curr.strands) {
    const old = prev.strands.find(p => p.id === s.id)
    if (old && old.domains.length !== s.domains.length) {
      lines.push(`  ${s.id}: domains ${old.domains.length} → ${s.domains.length}`)
    }
    if (old) {
      // Check for cross-helix transition
      const oldHelices = new Set(old.domains.map(d => d.helix_id))
      const newHelices = new Set(s.domains.map(d => d.helix_id))
      if (newHelices.size > oldHelices.size) {
        lines.push(`  ${s.id}: helix spread ${[...oldHelices].join(',')} → ${[...newHelices].join(',')}`)
      }
    }
  }

  // New helix IDs
  const prevHids = new Set((prev.helices ?? []).map(h => h.id))
  const currHids = new Set((curr.helices ?? []).map(h => h.id))
  const newHelices = [...currHids].filter(id => !prevHids.has(id))
  if (newHelices.length) lines.push(`+ Helices added: ${newHelices.join(', ')}`)

  return lines.length ? lines.join('\n') : '(no changes detected)'
}

// ── Panel UI ─────────────────────────────────────────────────────────────────

function _createPanel() {
  if (_panel) return
  _panel = document.createElement('div')
  _panel.id = 'ligation-debug-panel'
  _panel.innerHTML = `
    <style>
      #ligation-debug-panel {
        position: fixed; top: 0; right: 0; bottom: 0;
        width: 480px; max-width: 50vw;
        background: #0d1117ee; border-left: 2px solid #30363d;
        font-family: 'Courier New', monospace; font-size: 11px;
        color: #e6edf3; z-index: 99999;
        display: flex; flex-direction: column;
        overflow: hidden;
        backdrop-filter: blur(8px);
      }
      #ligation-debug-panel.ld-hidden { display: none; }
      .ld-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 6px 10px; background: #161b22; border-bottom: 1px solid #30363d;
        font-weight: bold; font-size: 12px;
      }
      .ld-header button {
        background: none; border: 1px solid #30363d; color: #8b949e;
        padding: 2px 8px; cursor: pointer; font-family: inherit; font-size: var(--text-xs);
      }
      .ld-header button:hover { color: #e6edf3; border-color: #58a6ff; }
      .ld-tabs {
        display: flex; gap: 0; border-bottom: 1px solid #30363d;
      }
      .ld-tab {
        flex: 1; padding: 5px 8px; text-align: center; cursor: pointer;
        background: #0d1117; border: none; color: #8b949e;
        font-family: inherit; font-size: 11px;
        border-bottom: 2px solid transparent;
      }
      .ld-tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
      .ld-tab-content { flex: 1; overflow-y: auto; padding: 6px 8px; }
      .ld-tab-content.ld-hidden { display: none; }

      /* Log */
      .ld-log { font-size: var(--text-xs); line-height: 1.5; }
      .ld-log-broadcast { color: #58a6ff; }
      .ld-log-store { color: #3fb950; }
      .ld-log-diff { color: #d2a8ff; }
      .ld-log-error { color: #f85149; }
      .ld-log-info { color: #8b949e; }

      /* Topology */
      .ld-topo-header { display: flex; gap: 12px; padding: 4px 0 8px; color: #8b949e; }
      .ld-topo-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); }
      .ld-topo-table th { text-align: left; padding: 3px 4px; color: #8b949e; border-bottom: 1px solid #21262d; }
      .ld-topo-table td { padding: 3px 4px; border-bottom: 1px solid #161b22; }
      .ld-row-xhelix { background: #1a2636; }
      .ld-row-xhelix td:nth-child(6) { color: #3fb950; font-weight: bold; }
      .ld-detail { margin-top: 8px; }
      .ld-detail summary { color: #58a6ff; cursor: pointer; }
      .ld-pre { color: #c9d1d9; white-space: pre; font-size: var(--text-xs); line-height: 1.4; overflow-x: auto; }

      /* Snapshot */
      .ld-snapshot-btn {
        display: block; margin: 8px 0; padding: 3px 12px;
        background: #21262d; border: 1px solid #30363d; color: #e6edf3;
        cursor: pointer; font-family: inherit; font-size: 11px;
      }
      .ld-snapshot-btn:hover { border-color: #58a6ff; }
      .ld-snapshot-diff { margin-top: 8px; white-space: pre-wrap; color: #d2a8ff; font-size: var(--text-xs); line-height: 1.4; }
    </style>
    <div class="ld-header">
      <span>Ligation Debug <kbd style="font-size:var(--text-xs);color:#8b949e">Ctrl+Shift+L</kbd></span>
      <div>
        <button id="ld-snapshot-btn" title="Take topology snapshot for diffing">Snapshot</button>
        <button id="ld-clear-btn" title="Clear log">Clear</button>
        <button id="ld-close-btn">Close</button>
      </div>
    </div>
    <div class="ld-tabs">
      <button class="ld-tab active" data-tab="log">Event Log</button>
      <button class="ld-tab" data-tab="topo">Topology</button>
      <button class="ld-tab" data-tab="snapshot">Snapshot Diff</button>
    </div>
    <div id="ld-tab-log" class="ld-tab-content ld-log"></div>
    <div id="ld-tab-topo" class="ld-tab-content ld-hidden"></div>
    <div id="ld-tab-snapshot" class="ld-tab-content ld-hidden">
      <button class="ld-snapshot-btn" id="ld-take-snapshot">Take snapshot (before extrude)</button>
      <div id="ld-snapshot-result" class="ld-snapshot-diff"></div>
    </div>
  `
  document.body.appendChild(_panel)

  _logEl = _panel.querySelector('#ld-tab-log')
  _topoEl = _panel.querySelector('#ld-tab-topo')

  // Tab switching
  for (const tab of _panel.querySelectorAll('.ld-tab')) {
    tab.addEventListener('click', () => {
      _panel.querySelectorAll('.ld-tab').forEach(t => t.classList.remove('active'))
      _panel.querySelectorAll('.ld-tab-content').forEach(c => c.classList.add('ld-hidden'))
      tab.classList.add('active')
      _panel.querySelector(`#ld-tab-${tab.dataset.tab}`).classList.remove('ld-hidden')
    })
  }

  // Close
  _panel.querySelector('#ld-close-btn').addEventListener('click', () => toggle(false))

  // Clear log
  _panel.querySelector('#ld-clear-btn').addEventListener('click', () => {
    _eventLog = []
    _logEl.innerHTML = ''
    _log('info', 'Log cleared')
  })

  // Snapshot
  let _snapshot = null
  _panel.querySelector('#ld-take-snapshot').addEventListener('click', () => {
    const design = editorStore.getState().design
    if (!design) { _log('error', 'No design to snapshot'); return }
    _snapshot = JSON.parse(JSON.stringify(design))
    _log('info', `Snapshot taken: ${_snapshot.strands.length} strands, ${_snapshot.helices.length} helices`)
    _panel.querySelector('#ld-snapshot-result').textContent =
      `Snapshot taken at ${_ts()}\n${_snapshot.strands.length} strands, ${_snapshot.helices.length} helices\n\nNow extrude in 3D, then come back to see the diff.`
  })

  _panel.querySelector('#ld-snapshot-btn').addEventListener('click', () => {
    if (!_snapshot) {
      _log('info', 'No snapshot — switching to Snapshot tab')
      _panel.querySelectorAll('.ld-tab').forEach(t => t.classList.remove('active'))
      _panel.querySelectorAll('.ld-tab-content').forEach(c => c.classList.add('ld-hidden'))
      _panel.querySelector('[data-tab="snapshot"]').classList.add('active')
      _panel.querySelector('#ld-tab-snapshot').classList.remove('ld-hidden')
      return
    }
    const design = editorStore.getState().design
    const diff = _diffDesigns(_snapshot, design)
    _panel.querySelector('#ld-snapshot-result').textContent = diff
    _log('diff', `Snapshot diff:\n${diff}`)
  })

  // Replay existing log entries
  for (const entry of _eventLog) {
    const line = document.createElement('div')
    line.className = `ld-log-${entry.type}`
    line.textContent = `[${entry.ts}] ${entry.type}: ${entry.detail}`
    _logEl.appendChild(line)
  }
}

// ── Public API ───────────────────────────────────────────────────────────────

function toggle(force) {
  _createPanel()
  const show = force !== undefined ? force : _panel.classList.contains('ld-hidden')
  _panel.classList.toggle('ld-hidden', !show)
  if (show) {
    _renderTopology(editorStore.getState().design)
  }
}

export function initLigationDebug() {
  _log('info', 'Ligation debug initialised')

  // ── Hook: BroadcastChannel messages ──────────────────────────────────────
  nadocBroadcast.onMessage(({ type, source, ...rest }) => {
    _log('broadcast', `${type} from ${source?.slice(0, 8) ?? '?'}  ${JSON.stringify(rest).slice(0, 100)}`)

    if (type === 'design-changed') {
      // Wait a tick for fetchDesign() to complete, then log the result
      setTimeout(() => {
        const design = editorStore.getState().design
        if (!design) {
          _log('error', 'design-changed received but no design in store after fetch')
          return
        }
        const xHelixStrands = design.strands.filter(_isCrossHelix)
        _log('store', `Design updated: ${design.strands.length} strands, ${design.helices.length} helices, ${xHelixStrands.length} cross-helix strands`)
        if (xHelixStrands.length > 0) {
          for (const s of xHelixStrands) {
            _log('store', `  CROSS-HELIX: ${s.id} (${s.strand_type}) — ${_strandSummary(s)}`)
            const coax = _coaxialPairs(s)
            if (coax.length) {
              _log('store', `    coaxial pairs: ${coax.map(p => `${p.aHelix}:${p.aBp} ↔ ${p.bHelix}:${p.bBp}`).join(', ')}`)
            }
          }
        } else {
          _log('info', '  No cross-helix strands found — ligation may not have fired')
          // Dump all strand endpoints for diagnosis
          for (const s of design.strands) {
            _log('info', `  ${s.id} (${s.strand_type}): ${_strandSummary(s)}`)
          }
        }

        // Diff against previous
        if (_prevDesign) {
          const diff = _diffDesigns(_prevDesign, design)
          _log('diff', diff)
        }
        _prevDesign = JSON.parse(JSON.stringify(design))

        _renderTopology(design)
      }, 500)
    }
  })

  // ── Hook: editorStore subscription ───────────────────────────────────────
  editorStore.subscribe((state, prev) => {
    if (state.design !== prev.design && state.design) {
      _renderTopology(state.design)
    }
  })

  // ── Keyboard shortcut ────────────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && e.key === 'L') {
      e.preventDefault()
      toggle()
    }
  })

  // ── Expose on window for console debugging ───────────────────────────────
  window._ligDebug = {
    toggle,
    log: () => _eventLog,
    topo: () => {
      const design = editorStore.getState().design
      if (!design) return console.log('No design')
      for (const s of design.strands) {
        const xh = _isCrossHelix(s) ? ' [CROSS-HELIX]' : ''
        console.log(`${s.id} (${s.strand_type})${xh}:`)
        for (const d of s.domains) {
          const dir = d.direction === 'FORWARD' ? 'FWD' : 'REV'
          console.log(`  ${d.helix_id} ${dir}  5'=${d.start_bp}  3'=${d.end_bp}`)
        }
      }
    },
    diff: () => {
      if (!_prevDesign) return console.log('No previous design captured')
      const design = editorStore.getState().design
      console.log(_diffDesigns(_prevDesign, design))
    },
  }

  _log('info', 'Hooks installed — Ctrl+Shift+L to open panel, or window._ligDebug.toggle()')
}
