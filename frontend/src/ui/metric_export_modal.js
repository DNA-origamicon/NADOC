/**
 * metric_export_modal.js — the "what to export" checkbox dialog for the oxDNA
 * Graphs & Metrics card.  Opens a small modal with PNG / Data checkboxes and
 * resolves the user's choice; the card then downloads the PNG (from the chart
 * canvas) and/or the CSV data.  Built lazily on first open, reused thereafter.
 */

// ── Pure: which artefacts a choice yields (unit-tested) ──────────────────────
/** `{png, data}` → ordered list of artefact kinds to emit. */
export function exportChoiceFiles(choice) {
  const out = []
  if (choice?.png) out.push('png')
  if (choice?.data) out.push('data')
  return out
}

// ── Download helpers ─────────────────────────────────────────────────────────
/** Download a data/object URL as `filename` via a transient `<a>`. */
export function downloadHref(filename, href) {
  const a = document.createElement('a')
  a.href = href; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
}

/** Download `text` as a file (Blob → object URL, revoked after). */
export function downloadText(filename, text, mime = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  downloadHref(filename, url)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

// ── Modal ─────────────────────────────────────────────────────────────────────
let _root = null, _pngChk = null, _dataChk = null, _resolve = null

function _build() {
  if (_root) return
  const overlay = document.createElement('div')
  overlay.style.cssText = [
    'position:fixed;inset:0;z-index:10001',
    'background:rgba(0,0,0,0.5);display:none',
    'align-items:center;justify-content:center',
    'font-family:var(--font-ui, sans-serif)',
  ].join(';')
  overlay.innerHTML = `
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                padding:18px 20px;min-width:240px;color:#c9d1d9">
      <div style="font-size:14px;font-weight:600;margin-bottom:12px">Export what?</div>
      <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer">
        <input type="checkbox" id="metric-export-png" checked> Graph image (PNG)</label>
      <label style="display:flex;align-items:center;gap:8px;margin-bottom:14px;cursor:pointer">
        <input type="checkbox" id="metric-export-data" checked> Data (CSV)</label>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="metric-export-cancel"
          style="padding:5px 12px;background:#21262d;border:1px solid #30363d;
                 border-radius:6px;color:#c9d1d9;cursor:pointer">Cancel</button>
        <button id="metric-export-ok"
          style="padding:5px 12px;background:#238636;border:1px solid #2ea043;
                 border-radius:6px;color:#fff;cursor:pointer">Export</button>
      </div>
    </div>`
  document.body.appendChild(overlay)
  _root = overlay
  _pngChk = overlay.querySelector('#metric-export-png')
  _dataChk = overlay.querySelector('#metric-export-data')
  const done = choice => { _root.style.display = 'none'; const r = _resolve; _resolve = null; r && r(choice) }
  overlay.querySelector('#metric-export-cancel').addEventListener('click', () => done(null))
  overlay.querySelector('#metric-export-ok').addEventListener('click',
    () => done({ png: _pngChk.checked, data: _dataChk.checked }))
  overlay.addEventListener('click', e => { if (e.target === overlay) done(null) })
}

/** Open the export dialog → resolves `{png, data}` (both booleans) or `null` on cancel. */
export function openMetricExportModal() {
  _build()
  return new Promise(resolve => {
    _resolve = resolve
    _pngChk.checked = true; _dataChk.checked = true
    _root.style.display = 'flex'
  })
}
