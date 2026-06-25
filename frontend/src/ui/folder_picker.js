/**
 * System folder picker — a visual navigator over the host filesystem.
 *
 * `pickSystemFolder({ api, title, initialPath })` → Promise<string|null>
 * resolves with the absolute path of the chosen folder, or null if cancelled.
 *
 * Used by the job-archive flow to let the user move a job's folder anywhere on
 * the host (including external drives). Backed by GET /fs/listdir + POST /fs/mkdir
 * (routes_fs.py) — directories only, with parent navigation and a "new folder"
 * action. Pure presentation: it only browses, the caller does the moving.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

const _DIM = 'color:#8b949e;font-size:12px'

export function pickSystemFolder({ api, title = 'Choose folder', initialPath = null } = {}) {
  return new Promise((resolve) => {
    let _cur = null          // current absolute path
    let _parent = null       // parent of _cur (null at fs root)
    let _settled = false

    const pathEl = el('div', { attrs: { style: 'font-family:var(--font-mono,monospace);font-size:12px;color:#c9d1d9;word-break:break-all;padding:4px 0' } })
    const listEl = el('div', { attrs: { style: 'border:1px solid #30363d;border-radius:6px;height:260px;overflow-y:auto;background:#0d1117' } })
    const msgEl  = el('div', { attrs: { style: 'color:#f85149;font-size:11px;min-height:14px' } })

    const selectBtn = createButton({ label: 'Select this folder', variant: 'primary', onClick: () => finish(_cur) })
    const newBtn    = createButton({ label: 'New folder', onClick: _newFolder })

    const body = el('div', { attrs: { style: 'display:flex;flex-direction:column;gap:8px;min-width:420px' } })
    body.append(pathEl, listEl, msgEl)

    const modal = createModal({
      title,
      size: 'md',
      body,
      onClose: () => finish(null),
      actions: [newBtn, createButton({ label: 'Cancel', onClick: () => finish(null) }), selectBtn],
    })

    function finish(value) {
      if (_settled) return
      _settled = true
      modal.close()
      resolve(value ?? null)
    }

    function _row(label, icon, onClick, { dim = false } = {}) {
      const r = el('div', {
        attrs: { style: `display:flex;align-items:center;gap:8px;padding:5px 10px;cursor:pointer;color:${dim ? '#8b949e' : '#c9d1d9'};font-size:12px` },
      })
      r.append(el('span', { text: icon, attrs: { style: 'flex-shrink:0' } }),
               el('span', { text: label, attrs: { style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap' } }))
      r.addEventListener('mouseenter', () => { r.style.background = '#161b22' })
      r.addEventListener('mouseleave', () => { r.style.background = '' })
      r.addEventListener('click', onClick)
      return r
    }

    async function _navigate(path) {
      msgEl.textContent = ''
      const res = await api.fsListDir(path)
      if (!res) {
        msgEl.textContent = api.lastErrorMessage?.() || 'Could not open that folder.'
        return
      }
      _cur = res.path
      _parent = res.parent
      pathEl.textContent = _cur
      listEl.innerHTML = ''
      if (_parent) listEl.append(_row('..', '⬆', () => _navigate(_parent), { dim: true }))
      if (!res.entries.length && !_parent) {
        listEl.append(el('div', { text: 'no subfolders', attrs: { style: _DIM + ';padding:8px 10px' } }))
      }
      for (const e of res.entries) {
        listEl.append(_row(e.name, '📁', () => _navigate(e.path)))
      }
    }

    async function _newFolder() {
      if (!_cur) return
      const name = window.prompt('New folder name:')
      if (!name) return
      const res = await api.fsMkdir(_cur, name.trim())
      if (!res) {
        msgEl.textContent = api.lastErrorMessage?.() || 'Could not create folder.'
        return
      }
      await _navigate(_cur)   // refresh listing
    }

    modal.open()
    _navigate(initialPath)
  })
}
