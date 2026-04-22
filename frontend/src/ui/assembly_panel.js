/**
 * Assembly panel — sidebar UI shown when an assembly (.nass) file is open.
 *
 * Shows the assembly name and the list of included .nadoc part instances.
 * An "Add Part" button opens a file picker for .nadoc files.
 *
 * @param {object} store
 * @param {object} opts
 * @param {object}   opts.api              — api module
 * @param {function} opts.onInstanceSelect — called with (instanceId | null)
 */

import { openFileBrowser } from './file_browser.js'

export function initAssemblyPanel(store, { api, onInstanceSelect }) {
  const panelEl    = document.getElementById('assembly-panel')
  const instanceEl = document.getElementById('assembly-instance-list')
  const nameEl     = document.getElementById('assembly-panel-name')
  const heading    = document.getElementById('assembly-panel-heading')
  const arrow      = document.getElementById('assembly-panel-arrow')
  const body       = document.getElementById('assembly-panel-body')
  if (!instanceEl) return { show() {}, hide() {}, rebuild() {} }

  let _collapsed = false

  heading?.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── "Add Part" button → opens library picker modal ───────────────────────────

  const _addPartBtn = document.createElement('button')
  _addPartBtn.textContent = '+ Add Part'
  _addPartBtn.style.cssText = [
    'width:100%;padding:4px 0;margin-top:6px',
    'background:#162420;border:1px solid #3fb950;color:#3fb950',
    'border-radius:3px;font-size:11px;cursor:pointer',
  ].join(';')
  _addPartBtn.addEventListener('pointerenter', () => { _addPartBtn.style.background = '#1f3d2a' })
  _addPartBtn.addEventListener('pointerleave', () => { _addPartBtn.style.background = '#162420' })
  _addPartBtn.addEventListener('click', () => _openLibraryPicker())

  instanceEl.insertAdjacentElement('afterend', _addPartBtn)

  // ── Library picker modal ──────────────────────────────────────────────────────

  async function _openLibraryPicker() {
    const result = await openFileBrowser({
      title: 'Add Part from Library',
      mode: 'open',
      fileType: 'part',
      api,
    })
    if (!result) return
    await api.addInstance({ source: { type: 'file', path: result.path }, name: result.name })
  }

  // ── Instance list ─────────────────────────────────────────────────────────────

  function _eyeSVG(on) {
    return on
      ? `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
           <path d="M8 3C4.5 3 1.5 8 1.5 8s3 5 6.5 5 6.5-5 6.5-5S11.5 3 8 3z" stroke="#58a6ff" stroke-width="1.3" fill="none"/>
           <circle cx="8" cy="8" r="2" fill="#58a6ff"/>
         </svg>`
      : `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
           <path d="M8 3C4.5 3 1.5 8 1.5 8s3 5 6.5 5 6.5-5 6.5-5S11.5 3 8 3z" stroke="#484f58" stroke-width="1.3" fill="none"/>
           <circle cx="8" cy="8" r="2" fill="#484f58"/>
           <line x1="3" y1="3" x2="13" y2="13" stroke="#484f58" stroke-width="1.3"/>
         </svg>`
  }

  function _buildInstanceRow(inst, activeId) {
    const row = document.createElement('div')
    row.dataset.instanceId = inst.id
    const isActive = inst.id === activeId
    row.style.cssText = [
      'display:flex;align-items:center;gap:6px;padding:5px 6px',
      'border-radius:4px;cursor:pointer',
      `background:${isActive ? '#1e3a5f' : 'transparent'}`,
      'transition:background 0.1s',
    ].join(';')

    row.addEventListener('mouseenter', () => {
      if (inst.id !== store.getState().activeInstanceId) row.style.background = '#161b22'
    })
    row.addEventListener('mouseleave', () => {
      row.style.background = inst.id === store.getState().activeInstanceId
        ? '#1e3a5f' : 'transparent'
    })
    row.addEventListener('click', () => {
      const currentActive = store.getState().activeInstanceId
      onInstanceSelect(currentActive === inst.id ? null : inst.id)
    })

    const eyeBtn = document.createElement('button')
    eyeBtn.innerHTML = _eyeSVG(inst.visible)
    eyeBtn.title     = inst.visible ? 'Hide' : 'Show'
    eyeBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'display:flex;align-items:center;line-height:1',
    ].join(';')
    eyeBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      await api.patchInstance(inst.id, { visible: !inst.visible })
    })

    const editBtn = document.createElement('button')
    editBtn.textContent = '✎'
    editBtn.title       = 'Edit part in new tab'
    editBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:13px;line-height:1',
    ].join(';')
    editBtn.addEventListener('pointerenter', () => { editBtn.style.color = '#58a6ff' })
    editBtn.addEventListener('pointerleave', () => { editBtn.style.color = '#6e7681' })
    editBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      window.open(`/?part-instance=${inst.id}`, `nadoc-part-${inst.id}`)
    })

    const nameEl = document.createElement('span')
    nameEl.textContent = inst.name
    nameEl.style.cssText = [
      'flex:1;font-size:11px;color:#c9d1d9',
      'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
    ].join(';')

    const delBtn = document.createElement('button')
    delBtn.textContent = '×'
    delBtn.title       = 'Remove part'
    delBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:14px;line-height:1',
    ].join(';')
    delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
    delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
    delBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      if (inst.id === store.getState().activeInstanceId) onInstanceSelect(null)
      await api.deleteInstance(inst.id)
    })

    row.append(eyeBtn, editBtn, nameEl, delBtn)
    return row
  }

  function _rebuildInstances(assembly, activeId) {
    instanceEl.innerHTML = ''
    const instances = assembly?.instances ?? []
    if (!instances.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No parts — use "+ Add Part" below'
      empty.style.cssText = 'font-size:10px;color:#484f58;padding:4px 2px'
      instanceEl.appendChild(empty)
      return
    }
    for (const inst of instances) instanceEl.appendChild(_buildInstanceRow(inst, activeId))
  }

  // ── Public API ────────────────────────────────────────────────────────────────

  function _rebuild(state) {
    if (_collapsed) return
    if (nameEl) {
      const asmName = state.currentAssembly?.metadata?.name
      nameEl.textContent = asmName ? asmName : ''
    }
    _rebuildInstances(state.currentAssembly, state.activeInstanceId)
  }

  function show() {
    if (panelEl) panelEl.style.display = ''
  }

  function hide() {
    if (panelEl) panelEl.style.display = 'none'
  }

  store.subscribeSlice('assembly', (newState) => {
    if (!panelEl || panelEl.style.display === 'none') return
    _rebuild(newState)
  })

  return { show, hide, rebuild: _rebuild, openPicker: _openLibraryPicker }
}
