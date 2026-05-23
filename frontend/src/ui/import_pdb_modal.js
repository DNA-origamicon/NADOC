/**
 * Unified "Import PDB" popup.
 *
 * One entry point for both DNA-design PDBs and protein PDBs (routing is
 * server-side via /design/import/pdb-auto).  Offers two sources:
 *   • a 4-char RCSB Protein Data Bank ID to download + import, or
 *   • a local .pdb file,
 * plus a Recents list of previously-used codes and files (re-imported from a
 * cached copy, since browsers don't expose a file's full path).
 *
 * The caller passes `onResult(json)` to apply side effects (reset+sync for a
 * DNA design, refresh proteins for a protein).
 */

import {
  getRecentProteinImports,
  addRecentProteinCode,
  addRecentProteinFile,
} from '../api/recent_files.js'

const WRAP = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10001;display:flex;align-items:center;justify-content:center;'
const DIALOG = 'background:#0d1117;border:1px solid #30363d;border-radius:8px;width:420px;padding:18px;color:#c9d1d9;font:13px system-ui,sans-serif;'
const INPUT = 'flex:1;padding:6px 8px;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;text-transform:uppercase;'
const BTN = 'padding:6px 12px;background:#238636;color:#fff;border:none;border-radius:5px;cursor:pointer;'
const BTN2 = 'width:100%;padding:8px;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;cursor:pointer;'

export function openImportPdbModal({ onResult }) {
  const backdrop = document.createElement('div')
  backdrop.style.cssText = WRAP
  const dialog = document.createElement('div')
  dialog.style.cssText = DIALOG
  backdrop.appendChild(dialog)
  document.body.appendChild(backdrop)
  const close = () => backdrop.remove()
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close() })

  // Header
  const h = document.createElement('div')
  h.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'
  h.innerHTML = '<h3 style="margin:0;font-size:15px;">Import PDB</h3>'
  const x = document.createElement('button')
  x.textContent = '✕'
  x.style.cssText = 'background:none;border:none;color:#8b949e;font-size:16px;cursor:pointer;'
  x.onclick = close
  h.appendChild(x)
  dialog.appendChild(h)

  const sub = document.createElement('div')
  sub.style.cssText = 'color:#8b949e;font-size:12px;margin-bottom:12px;'
  sub.textContent = 'DNA is imported as a design; protein is added to the protein library (auto-detected).'
  dialog.appendChild(sub)

  const status = document.createElement('div')
  status.style.cssText = 'color:#8b949e;font-size:12px;min-height:16px;margin:8px 0;'

  const setBusy = (msg) => { status.textContent = msg; status.style.color = '#8b949e' }
  const setErr = (msg) => { status.textContent = msg; status.style.color = '#f85149' }

  // `recentMeta` (the source that triggered this import) is threaded through so
  // the DNA-decision re-call still records the correct kind (code vs file).
  async function run(args, busyMsg, recentMeta) {
    setBusy(busyMsg)
    const json = await onResult(args)   // returns the response json or null
    if (json === null) {
      setErr('Import failed.')   // detailed message surfaced via the app toast/lastError
      return
    }
    if (json.needs_dna_decision) {
      showDnaChoice(json, recentMeta)   // structure has protein + DNA — ask before stripping
      return
    }
    if (recentMeta?.kind === 'code') addRecentProteinCode(recentMeta.code)
    else if (recentMeta?.kind === 'file') addRecentProteinFile(recentMeta.name, recentMeta.content)
    close()
  }

  // Inline choice when a protein structure also contains DNA.
  function showDnaChoice(json, recentMeta) {
    status.textContent = ''
    const box = document.createElement('div')
    box.style.cssText = 'margin-top:10px;padding:10px;border:1px solid #d29922;border-radius:6px;background:#1c1a12;'
    const msg = document.createElement('div')
    msg.style.cssText = 'margin-bottom:8px;'
    msg.textContent = 'This structure also contains DNA. Remove it from the imported protein?'
    box.appendChild(msg)
    const row = document.createElement('div')
    row.style.cssText = 'display:flex;gap:8px;'
    const mk = (label, remove, primary) => {
      const b = document.createElement('button')
      b.textContent = label
      b.style.cssText = primary ? BTN : BTN2.replace('width:100%;', '')
      b.onclick = () => run(
        { content: json.content, name: json.name, removeDnaFromProtein: remove },
        remove ? 'Importing protein (DNA removed)…' : 'Importing protein + DNA…',
        recentMeta,
      )
      return b
    }
    row.appendChild(mk('Remove DNA', true, true))
    row.appendChild(mk('Keep DNA', false, false))
    box.appendChild(row)
    dialog.appendChild(box)
  }

  function _pickFile(onContent) {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.pdb'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      onContent(await file.text(), file.name)
    }
    input.click()
  }

  // ── By RCSB ID ──────────────────────────────────────────────────────────────
  const idLabel = document.createElement('div')
  idLabel.style.cssText = 'font-size:12px;color:#8b949e;margin-bottom:4px;'
  idLabel.textContent = 'RCSB PDB ID'
  dialog.appendChild(idLabel)

  const idRow = document.createElement('div')
  idRow.style.cssText = 'display:flex;gap:8px;margin-bottom:6px;'
  const idInput = document.createElement('input')
  idInput.type = 'text'
  idInput.placeholder = 'e.g. 1BNA'
  idInput.maxLength = 4
  idInput.style.cssText = INPUT
  const dlBtn = document.createElement('button')
  dlBtn.textContent = 'Download & Import'
  dlBtn.style.cssText = BTN
  const doDownload = () => {
    const id = idInput.value.trim().toUpperCase()
    if (!/^[0-9A-Z]{4}$/.test(id)) { setErr('Enter a 4-character PDB ID.'); return }
    run({ pdbId: id, name: id }, `Downloading ${id} from RCSB…`, { kind: 'code', code: id })
  }
  dlBtn.onclick = doDownload
  // Stop global hotkeys from firing while typing a PDB code (codebase
  // convention — see other text inputs in main.js).
  idInput.addEventListener('keydown', (e) => {
    e.stopPropagation()
    if (e.key === 'Enter') doDownload()
  })
  idRow.appendChild(idInput)
  idRow.appendChild(dlBtn)
  dialog.appendChild(idRow)

  // ── divider ───────────────────────────────────────────────────────────────────
  const or = document.createElement('div')
  or.style.cssText = 'text-align:center;color:#6e7681;font-size:11px;margin:10px 0;'
  or.textContent = '— or —'
  dialog.appendChild(or)

  // ── From file ──────────────────────────────────────────────────────────────────
  const fileBtn = document.createElement('button')
  fileBtn.textContent = 'Import from File…'
  fileBtn.style.cssText = BTN2
  fileBtn.onclick = () => _pickFile((content, fileName) => {
    run({ content, name: fileName.replace(/\.pdb$/i, '') }, `Importing ${fileName}…`,
        { kind: 'file', name: fileName, content })
  })
  dialog.appendChild(fileBtn)

  // ── Recents (codes + files) ─────────────────────────────────────────────────
  renderRecents()

  function renderRecents() {
    const recents = getRecentProteinImports()
    if (!recents.length) return
    const hdr = document.createElement('div')
    hdr.style.cssText = 'font-size:11px;color:#6e7681;text-transform:uppercase;letter-spacing:.04em;margin:14px 0 4px;'
    hdr.textContent = 'Recent'
    dialog.appendChild(hdr)

    const listEl = document.createElement('div')
    listEl.style.cssText = 'display:flex;flex-direction:column;gap:2px;max-height:160px;overflow:auto;'
    for (const e of recents) {
      const rowEl = document.createElement('button')
      rowEl.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:5px 6px;background:none;border:none;border-radius:5px;color:#c9d1d9;cursor:pointer;font:inherit;'
      rowEl.onmouseenter = () => { rowEl.style.background = '#161b22' }
      rowEl.onmouseleave = () => { rowEl.style.background = 'none' }

      const tag = document.createElement('span')
      tag.style.cssText = 'flex:none;font-size:10px;font-weight:600;padding:1px 5px;border-radius:3px;'
      const label = document.createElement('span')
      label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'

      if (e.kind === 'code') {
        tag.textContent = 'PDB'
        tag.style.background = '#1f6feb'; tag.style.color = '#fff'
        label.textContent = e.code
        rowEl.onclick = () => run({ pdbId: e.code, name: e.code },
          `Downloading ${e.code} from RCSB…`, { kind: 'code', code: e.code })
      } else {
        tag.textContent = 'FILE'
        tag.style.background = '#30363d'; tag.style.color = '#c9d1d9'
        label.textContent = e.name
        if (e.content) {
          rowEl.onclick = () => run({ content: e.content, name: e.name.replace(/\.pdb$/i, '') },
            `Importing ${e.name}…`, { kind: 'file', name: e.name, content: e.content })
        } else {
          // Content wasn't cached (too large) — re-pick the file.
          label.title = 'File too large to cache — click to re-select'
          label.style.color = '#8b949e'
          rowEl.onclick = () => _pickFile((content, fileName) => {
            run({ content, name: fileName.replace(/\.pdb$/i, '') }, `Importing ${fileName}…`,
                { kind: 'file', name: fileName, content })
          })
        }
      }
      rowEl.appendChild(tag)
      rowEl.appendChild(label)
      listEl.appendChild(rowEl)
    }
    dialog.appendChild(listEl)
  }

  dialog.appendChild(status)
  setTimeout(() => idInput.focus(), 0)
  return { close }
}
