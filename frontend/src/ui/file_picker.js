/**
 * File picker — a standard folder navigator for choosing a downloaded file.
 *
 * `openFilePicker({ api, kind, title, onPick })` opens a modal that lists a
 * directory (via `api.browseFiles(path, kind)`), lets the user step into folders
 * or up a level, and calls `onPick(absolutePath)` when a file is chosen. It opens
 * at the user's Downloads folder (the backend resolves the Windows one on WSL),
 * with files sorted most-recent-first and likely matches highlighted.
 *
 * This exists because a browser `<input type=file>` hides the real filesystem
 * path, which the server-side install (extract NAMD / build ARBD) needs.
 *
 * Pure formatting helpers (formatSize / formatMtime) are unit-tested; the DOM +
 * navigation live in the factory.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

const _DIM = 'color:#8b949e;font-size:12px'

/** PURE: bytes → a short human size ('' for 0/dirs). */
export function formatSize(bytes) {
  if (!bytes || bytes < 0) return ''
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = bytes, i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  // one decimal for small non-integer sizes (1.4 MB); whole numbers stay whole (2 KB)
  const shown = (i === 0 || Number.isInteger(n)) ? Math.round(n)
    : (n < 10 ? Number(n.toFixed(1)) : Math.round(n))
  return `${shown} ${u[i]}`
}

/** PURE: epoch-seconds → a short local date string ('' when missing). */
export function formatMtime(mtime, now = Date.now()) {
  if (!mtime) return ''
  const ms = mtime * 1000
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const dayMs = 86400000
  const days = Math.floor((now - ms) / dayMs)
  if (days <= 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  return d.toLocaleDateString()
}

export function openFilePicker({ api, kind, title = 'Choose a file', onPick }) {
  let cwd = null
  const pathLine = el('div', { attrs: { style: 'font-family:monospace;font-size:11px;color:#8b949e;word-break:break-all;margin-bottom:6px' } })
  const listEl = el('div', { attrs: { style: 'max-height:340px;overflow:auto;border:1px solid #21262d;border-radius:6px;background:#0d1117' } })
  const upBtn = createButton({ label: '⬆ Up', size: 'sm', onClick: () => { if (cwd?.parent) _load(cwd.parent) } })

  const modal = createModal({
    title,
    size: 'md',
    body: [
      el('div', { text: 'Open your Downloads folder, then pick the file you downloaded:', attrs: { style: 'font-size:13px;margin-bottom:8px' } }),
      el('div', { attrs: { style: 'display:flex;gap:8px;align-items:center;margin-bottom:6px' }, children: [upBtn, pathLine] }),
      listEl,
    ],
    actions: [createButton({ label: 'Cancel', variant: 'primary', onClick: () => modal.close() })],
  })

  async function _load(path) {
    listEl.replaceChildren(el('div', { text: 'Loading…', attrs: { style: _DIM + ';padding:12px' } }))
    const res = await api.browseFiles(path, kind).catch(() => null)
    if (!res) { listEl.replaceChildren(el('div', { text: 'Could not read that folder.', attrs: { style: 'color:#f85149;font-size:12px;padding:12px' } })); return }
    cwd = res
    pathLine.textContent = res.cwd
    upBtn.disabled = !res.parent
    _render(res)
  }

  function _render(res) {
    listEl.replaceChildren()
    if (res.error) { listEl.appendChild(el('div', { text: res.error, attrs: { style: 'color:#f85149;font-size:12px;padding:12px' } })) }
    if (!res.entries.length && !res.error) { listEl.appendChild(el('div', { text: '(empty folder)', attrs: { style: _DIM + ';padding:12px' } })) }
    for (const e of res.entries) listEl.appendChild(_row(e))
  }

  function _row(e) {
    const icon = e.is_dir ? '📁' : (e.matches ? '📦' : '📄')
    const nameStyle = 'flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' +
      (e.matches ? ';color:#3fb950;font-weight:600' : e.is_dir ? ';color:#58a6ff' : ';color:#c9d1d9')
    const meta = e.is_dir ? '' : [formatMtime(e.mtime), formatSize(e.size)].filter(Boolean).join(' · ')
    const row = el('div', {
      attrs: { style: 'display:flex;gap:8px;align-items:center;padding:6px 10px;cursor:pointer;border-bottom:1px solid #161b22;font-size:13px' },
      children: [
        el('span', { text: icon, attrs: { style: 'flex:0 0 auto' } }),
        el('span', { text: e.name, attrs: { style: nameStyle } }),
        el('span', { text: e.is_dir ? '›' : meta, attrs: { style: _DIM + ';flex:0 0 auto' } }),
      ],
    })
    row.addEventListener('mouseenter', () => { row.style.background = '#161b22' })
    row.addEventListener('mouseleave', () => { row.style.background = '' })
    row.addEventListener('click', () => {
      if (e.is_dir) _load(e.path)
      else { modal.close(); onPick && onPick(e.path) }
    })
    return row
  }

  modal.open()
  _load(null)   // null → backend opens at the Downloads folder
  return modal
}
