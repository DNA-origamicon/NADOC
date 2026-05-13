/**
 * Assembly Configurations panel — saved assembly transform snapshots.
 */
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showPersistentToast, dismissToast } from './toast.js'

export function initAssemblyConfigPanel(store, { api, onAnimateConfiguration }) {
  const panelEl = document.getElementById('assembly-config-panel')
  const heading = document.getElementById('assembly-config-panel-heading')
  const arrow = document.getElementById('assembly-config-panel-arrow')
  const body = document.getElementById('assembly-config-panel-body')
  const listEl = document.getElementById('assembly-config-list')
  const captureBtn = document.getElementById('assembly-config-capture-btn')
  if (!panelEl || !heading || !body || !listEl || !captureBtn) return null

  let _collapsed = getSectionCollapsed('scene', 'assembly-config-panel', false)
  let _isRestoring = false
  let _pendingConfigId = null

  const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _goStyle = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _updateStyle = 'background:#1f2d0d;border:1px solid #588a1e;color:#8ec550;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _delStyle = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'

  body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)

  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow?.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('scene', 'assembly-config-panel', _collapsed)
    if (!_collapsed) _rebuild(store.getState().currentAssembly)
  })

  captureBtn.addEventListener('click', async () => {
    const assembly = store.getState().currentAssembly
    if (!store.getState().assemblyActive || !assembly) return
    const n = (assembly.configurations?.length ?? 0) + 1
    await api.createAssemblyConfiguration?.(`Config ${n}`)
  })

  store.subscribeSlice('assembly', (n, p) => {
    if (n.currentAssembly === p.currentAssembly && n.assemblyActive === p.assemblyActive) return
    panelEl.style.display = n.assemblyActive && n.currentAssembly ? '' : 'none'
    if (!_collapsed) _rebuild(n.currentAssembly)
  })

  async function _restoreConfig(cfg) {
    if (!cfg) return
    if (_isRestoring) {
      _pendingConfigId = cfg.id
      return
    }
    _isRestoring = true
    showPersistentToast(`Loading ${cfg.name ?? 'configuration'}...`)
    try {
      await api.restoreAssemblyConfiguration?.(cfg.id)
    } finally {
      _isRestoring = false
      if (_pendingConfigId === null) dismissToast()
      if (_pendingConfigId !== null) {
        const nextId = _pendingConfigId
        _pendingConfigId = null
        const next = store.getState().currentAssembly?.configurations?.find(c => c.id === nextId)
        _restoreConfig(next)
      }
    }
  }

  async function _animateConfig(cfg) {
    if (!cfg) return
    if (onAnimateConfiguration) await onAnimateConfiguration(cfg)
    else await api.restoreAssemblyConfiguration?.(cfg.id)
  }

  function _rebuild(assembly) {
    listEl.innerHTML = ''
    const active = !!store.getState().assemblyActive && !!assembly
    panelEl.style.display = active ? '' : 'none'
    if (!active) return

    const configs = assembly.configurations ?? []
    if (!configs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'No configurations captured.'
      listEl.appendChild(empty)
      return
    }

    configs.forEach((cfg, i) => {
      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px',
        'padding:3px 6px;font-size:11px;border-radius:3px',
        cfg.id === assembly.configuration_cursor ? 'background:#161b22' : '',
      ].join(';')
      row.title = 'Click to restore this configuration'
      row.addEventListener('click', () => _restoreConfig(cfg))

      const icon = document.createElement('span')
      icon.textContent = '◆'
      icon.style.color = '#58a6ff'

      const label = document.createElement('span')
      label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9d1d9'
      const count = cfg.instance_states?.length ?? 0
      const labelText = name => `${name} — ${count} part${count === 1 ? '' : 's'}`
      label.textContent = labelText(cfg.name ?? `Config ${i + 1}`)

      const goBtn = document.createElement('button')
      goBtn.textContent = '▶'
      goBtn.title = 'Animate to this configuration'
      goBtn.style.cssText = _goStyle
      goBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await _animateConfig(cfg)
      })

      const overwriteBtn = document.createElement('button')
      overwriteBtn.textContent = '⟳'
      overwriteBtn.title = 'Overwrite configuration with current assembly state'
      overwriteBtn.style.cssText = _updateStyle
      overwriteBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.updateAssemblyConfiguration?.(cfg.id, { overwrite_current: true })
      })

      const editBtn = document.createElement('button')
      editBtn.textContent = '✎'
      editBtn.title = 'Rename configuration'
      editBtn.style.cssText = _editStyle

      function enterEdit(e) {
        e.stopPropagation()
        const input = document.createElement('input')
        input.type = 'text'
        input.value = cfg.name ?? `Config ${i + 1}`
        input.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px'
        label.replaceWith(input)
        input.focus()
        input.select()
        editBtn.textContent = '✓'
        editBtn.title = 'Save name'
        editBtn.style.cssText = _saveStyle

        async function save() {
          const oldName = cfg.name ?? `Config ${i + 1}`
          const newName = input.value.trim() || oldName
          input.replaceWith(label)
          label.textContent = labelText(newName)
          editBtn.textContent = '✎'
          editBtn.title = 'Rename configuration'
          editBtn.style.cssText = _editStyle
          editBtn.onclick = enterEdit
          if (newName !== oldName) await api.updateAssemblyConfiguration?.(cfg.id, { name: newName })
        }

        input.addEventListener('keydown', e2 => {
          e2.stopPropagation()
          if (e2.key === 'Enter') { e2.preventDefault(); save() }
          if (e2.key === 'Escape') {
            input.replaceWith(label)
            editBtn.textContent = '✎'
            editBtn.title = 'Rename configuration'
            editBtn.style.cssText = _editStyle
            editBtn.onclick = enterEdit
          }
        })
        editBtn.onclick = e2 => { e2.stopPropagation(); save() }
      }
      editBtn.onclick = enterEdit

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete configuration'
      delBtn.style.cssText = _delStyle
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.deleteAssemblyConfiguration?.(cfg.id)
      })

      row.append(icon, label, goBtn, overwriteBtn, editBtn, delBtn)
      listEl.appendChild(row)
    })
  }

  _rebuild(store.getState().currentAssembly)
  return { rebuild: () => _rebuild(store.getState().currentAssembly) }
}
