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
import { formatBytes } from './format_bytes.js'

const _DIM = 'color:#8b949e;font-size:12px'

export function pickSystemFolder({ api, title = 'Choose folder', initialPath = null } = {}) {
  return new Promise((resolve) => {
    let _cur = null          // current absolute path
    let _parent = null       // parent of _cur (null at fs root)
    let _settled = false
    let _navigation = 0

    const pathEl = el('input', { attrs: { type: 'text', 'aria-label': 'Folder path',
      placeholder: 'Enter a Linux or Windows folder path',
      style: 'flex:1;min-width:0;font-family:var(--font-mono,monospace);font-size:12px;color:#c9d1d9;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:6px' } })
    const locationsEl = el('div', { attrs: { 'aria-label': 'Drives and locations', style: 'display:flex;flex-wrap:wrap;gap:6px' } })
    const hintEl = el('div', { attrs: { style: _DIM } })
    const listEl = el('div', { attrs: { style: 'border:1px solid #30363d;border-radius:6px;height:260px;overflow-y:auto;background:#0d1117' } })
    const msgEl  = el('div', { attrs: { style: 'color:#f85149;font-size:11px;min-height:14px' } })

    const selectBtn = createButton({ label: 'Select this folder', disabled: true, variant: 'primary', onClick: () => finish(_cur) })
    const newBtn    = createButton({ label: 'New folder', disabled: true, onClick: _newFolder })

    const body = el('div', { attrs: { style: 'display:flex;flex-direction:column;gap:8px;min-width:420px' } })
    const pathBar = el('div', { attrs: { style: 'display:flex;gap:6px' } })
    pathBar.append(pathEl, createButton({ label: 'Go', onClick: () => _navigate(pathEl.value) }))
    pathEl.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); void _navigate(pathEl.value) }
    })
    pathEl.addEventListener('input', () => { selectBtn.disabled = true; newBtn.disabled = true })
    const homeBtn = createButton({ label: 'Home', onClick: () => _navigate(null) })
    locationsEl.append(homeBtn)
    body.append(locationsEl, pathBar, hintEl, listEl, msgEl)

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
      const r = el('button', {
        attrs: { type: 'button', style: `width:100%;border:0;background:transparent;text-align:left;display:flex;align-items:center;gap:8px;padding:5px 10px;cursor:pointer;color:${dim ? '#8b949e' : '#c9d1d9'};font-size:12px` },
      })
      r.append(el('span', { text: icon, attrs: { style: 'flex-shrink:0' } }),
               el('span', { text: label, attrs: { style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap' } }))
      r.addEventListener('mouseenter', () => { r.style.background = '#161b22' })
      r.addEventListener('mouseleave', () => { r.style.background = '' })
      r.addEventListener('click', onClick)
      return r
    }

    async function _navigate(path, { initial = false } = {}) {
      const request = ++_navigation
      selectBtn.disabled = true
      newBtn.disabled = true
      msgEl.textContent = 'Loading…'
      let res
      try { res = await api.fsListDir(path) } catch { res = null }
      if (_settled || request !== _navigation) return
      if (!res) {
        const error = api.lastErrorMessage?.() || 'Could not open that folder. Check that its drive is connected and mounted.'
        _cur = null
        if (initial && path) {
          await _navigate(null)
          if (!_settled && request + 1 === _navigation) msgEl.textContent = error
        } else msgEl.textContent = error
        return
      }
      msgEl.textContent = ''
      _cur = res.path
      _parent = res.parent
      pathEl.value = _cur
      selectBtn.disabled = false
      newBtn.disabled = false
      if (res.locations) {
        locationsEl.replaceChildren()
        for (const location of res.locations) {
          const free = location.free_bytes == null ? '' : ` · ${formatBytes(location.free_bytes)} free`
          locationsEl.append(createButton({ label: location.name + free, size: 'sm',
            title: location.path, onClick: () => _navigate(location.path) }))
        }
      }
      hintEl.textContent = res.wsl
        ? 'Windows and external drives appear here when mounted in WSL. You can also paste a Windows path, such as F:\\NADOC.'
        : 'Choose a mounted drive or enter a folder path on the computer running NADOC.'
      listEl.replaceChildren()
      const parent = _parent
      if (parent) listEl.append(_row('..', '⬆', () => _navigate(parent), { dim: true }))
      if (!res.entries.length) {
        listEl.append(el('div', { text: 'No subfolders', attrs: { style: _DIM + ';padding:8px 10px' } }))
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
    _navigate(initialPath, { initial: true })
  })
}
