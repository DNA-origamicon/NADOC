/**
 * Assembly panel — sidebar UI shown when an assembly (.nass) file is open.
 *
 * Shows the assembly name, list of part instances (with connector sub-lists),
 * a "Mates" section listing all joints with edit/delete, and an "Add Part" button.
 *
 * @param {object} store
 * @param {object} opts
 * @param {object}   opts.api                   — api module
 * @param {function} opts.onInstanceSelect       — called with (instanceId | null)
 * @param {function} opts.onPartContextChange    — called with (instanceId, design, patchFn) or (null,null,null) on deselect
 * @param {function} opts.beforePatchDesign      — called with (instanceId) before each design patch (e.g. to invalidate geometry cache)
 */

import { openFileBrowser } from './file_browser.js'

const _REPR_OPTIONS = [
  { value: 'full',       label: 'Full (CG)' },
  { value: 'beads',      label: 'Beads' },
  { value: 'cylinders',  label: 'Cylinders' },
  { value: 'hull-prism', label: 'Hull Prism' },
  { value: 'vdw',        label: 'VDW (atomistic)' },
  { value: 'ballstick',  label: 'Ball+Stick (atomistic)' },
]
const _ATOMISTIC_REPRS = new Set(['vdw', 'ballstick'])

const _JOINT_TYPE_ICON = {
  revolute:  '↻',
  prismatic: '↕',
  spherical: '⊕',
  rigid:     '⊞',
}

const _JOINT_TYPES = ['revolute', 'prismatic', 'rigid', 'spherical']

export function initAssemblyPanel(store, { api, onInstanceSelect, onPartContextChange, beforePatchDesign }) {
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
    arrow.classList.toggle('is-collapsed', _collapsed)
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

  // ── Mates section (appended after Add Part button) ────────────────────────────

  const _matesSectionEl = document.createElement('div')
  _matesSectionEl.id = '_assembly-mates-section'
  _addPartBtn.insertAdjacentElement('afterend', _matesSectionEl)

  // ── Part context — fetch instance design and notify sidebar panels ────────────

  let _partCacheInstanceId = null   // last fetched instance id
  let _partCacheDesign     = null   // last fetched Design object
  let _partPatchFn         = null   // patch function for the current instance
  let _partLastRebuildId   = null   // detect activeInstanceId changes in _rebuild

  function _makePatchFn(instanceId) {
    return async (modifier) => {
      if (!_partCacheDesign || _partCacheInstanceId !== instanceId) return
      beforePatchDesign?.(instanceId)   // e.g. invalidate geometry cache
      const design = JSON.parse(JSON.stringify(_partCacheDesign))
      modifier(design)
      _partCacheDesign = design
      // Optimistic notification so panels update immediately
      onPartContextChange?.(instanceId, _partCacheDesign, _partPatchFn)
      await api.patchInstanceDesign(instanceId, JSON.stringify(design))
      // Re-fetch server-canonical design and notify again
      try {
        const fresh = await api.getInstanceDesign(instanceId)
        if (fresh?.design && _partCacheInstanceId === instanceId) {
          _partCacheDesign = fresh.design
          onPartContextChange?.(instanceId, _partCacheDesign, _partPatchFn)
        }
      } catch { /* keep optimistic */ }
    }
  }

  async function _onPartInstanceChanged(instanceId) {
    if (!instanceId) {
      _partCacheInstanceId = null
      _partCacheDesign     = null
      _partPatchFn         = null
      onPartContextChange?.(null, null, null)
      return
    }
    if (instanceId === _partCacheInstanceId && _partCacheDesign) {
      // Same instance — re-notify panels (design may have changed)
      onPartContextChange?.(instanceId, _partCacheDesign, _partPatchFn)
      return
    }
    _partCacheInstanceId = instanceId
    _partCacheDesign     = null
    _partPatchFn         = null
    try {
      const result = await api.getInstanceDesign(instanceId)
      if (!result?.design || _partCacheInstanceId !== instanceId) return  // stale
      _partCacheDesign = result.design
      _partPatchFn     = _makePatchFn(instanceId)
      onPartContextChange?.(instanceId, _partCacheDesign, _partPatchFn)
    } catch {
      onPartContextChange?.(null, null, null)
    }
  }

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

  // ── Broken-mate detection helper ──────────────────────────────────────────────

  function _isBrokenMate(joint, instances) {
    if (!joint.connector_b_label) return false
    const instB = instances.find(i => i.id === joint.instance_b_id)
    if (instB && !instB.interface_points.some(ip => ip.label === joint.connector_b_label)) return true
    if (joint.connector_a_label && joint.instance_a_id) {
      const instA = instances.find(i => i.id === joint.instance_a_id)
      if (instA && !instA.interface_points.some(ip => ip.label === joint.connector_a_label)) return true
    }
    return false
  }

  // ── Connector sub-section under each instance row ─────────────────────────────

  function _buildConnectorSection(inst, joints) {
    const connectors = inst.interface_points ?? []

    const section = document.createElement('div')
    section.style.cssText = 'padding:0 6px 4px 26px'

    const headerRow = document.createElement('div')
    headerRow.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;padding:2px 0'

    const arrowSpan = document.createElement('span')
    arrowSpan.textContent = '▶'
    arrowSpan.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0'

    const titleSpan = document.createElement('span')
    titleSpan.style.cssText = 'font-size:var(--text-xs);color:#6e7681'
    titleSpan.textContent = `Connectors (${connectors.length})`

    headerRow.append(arrowSpan, titleSpan)

    const listEl = document.createElement('div')
    listEl.style.display = 'none'
    let _expanded = false

    headerRow.addEventListener('click', () => {
      _expanded = !_expanded
      listEl.style.display = _expanded ? '' : 'none'
      arrowSpan.textContent = _expanded ? '▼' : '▶'
    })

    for (const ip of connectors) {
      const usedCount = joints.filter(j =>
        (j.instance_b_id === inst.id && j.connector_b_label === ip.label) ||
        (j.instance_a_id === inst.id && j.connector_a_label === ip.label),
      ).length

      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:4px;padding:2px 0 2px 8px'

      const lbl = document.createElement('span')
      lbl.textContent = ip.label
      lbl.style.cssText = 'flex:1;font-size:var(--text-xs);color:#8b949e'

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete connector'
      delBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;padding:0 2px',
        'color:#6e7681;font-size:12px;line-height:1',
      ].join(';')
      delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        if (usedCount > 0) {
          const ok = window.confirm(
            `Connector "${ip.label}" is used in ${usedCount} mate(s). Delete anyway?`,
          )
          if (!ok) return
        }
        await api.deleteInstanceConnector(inst.id, ip.label)
      })

      row.append(lbl, delBtn)
      listEl.appendChild(row)
    }

    if (!connectors.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No connectors defined'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:2px 0 2px 8px'
      listEl.appendChild(empty)
    }

    section.append(headerRow, listEl)
    return section
  }

  // ── Eye SVG ───────────────────────────────────────────────────────────────────

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

  // ── Instance row ──────────────────────────────────────────────────────────────

  function _buildInstanceRow(inst, activeId, joints) {
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

    const nameSpan = document.createElement('span')
    nameSpan.textContent = inst.name
    nameSpan.style.cssText = [
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

    // ── Representation selector ──────────────────────────────────────────────

    const reprRow = document.createElement('div')
    reprRow.style.cssText = 'display:flex;align-items:center;gap:4px;padding:2px 6px 4px 26px'

    const reprLabel = document.createElement('span')
    reprLabel.textContent = 'Repr:'
    reprLabel.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'

    const reprSel = document.createElement('select')
    reprSel.style.cssText = [
      'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #30363d',
      'border-radius:3px;font-size:var(--text-xs);padding:3px 2px;cursor:pointer',
    ].join(';')
    for (const { value, label } of _REPR_OPTIONS) {
      const opt = document.createElement('option')
      opt.value   = value
      opt.text    = label
      opt.selected = (inst.representation ?? 'full') === value
      reprSel.appendChild(opt)
    }
    reprSel.addEventListener('click', e => e.stopPropagation())
    reprSel.addEventListener('change', async (e) => {
      e.stopPropagation()
      const repr = reprSel.value
      if (_ATOMISTIC_REPRS.has(repr)) {
        const ok = window.confirm(
          'Atomistic rendering computes all-atom geometry for this part and can be slow for ' +
          'large designs or assemblies with many parts.\n\nApply anyway?',
        )
        if (!ok) {
          reprSel.value = inst.representation ?? 'full'
          return
        }
      }
      await api.patchInstance(inst.id, { representation: repr })
    })

    reprRow.append(reprLabel, reprSel)
    row.append(eyeBtn, editBtn, nameSpan, delBtn)
    return { row, reprRow }
  }

  // ── Instance list ──────────────────────────────────────────────────────────────

  function _rebuildInstances(assembly, activeId) {
    instanceEl.innerHTML = ''
    const instances = assembly?.instances ?? []
    const joints    = assembly?.joints    ?? []
    if (!instances.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No parts — use "+ Add Part" below'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:3px 2px'
      instanceEl.appendChild(empty)
      return
    }
    for (const inst of instances) {
      const { row, reprRow } = _buildInstanceRow(inst, activeId, joints)
      const connSection = _buildConnectorSection(inst, joints)
      instanceEl.appendChild(row)
      instanceEl.appendChild(reprRow)
      instanceEl.appendChild(connSection)
    }
  }

  // ── Mates section ──────────────────────────────────────────────────────────────

  let _matesCollapsed = false
  let _editingJointId = null
  // { [jointId]: { satisfied: bool, discrepancy: float } } — cleared on full assembly change
  let _solveStatus    = {}

  function _buildEditForm(joint, onDone) {
    const form = document.createElement('div')
    form.style.cssText = [
      'padding:6px 8px;margin-top:2px;background:#161b22',
      'border:1px solid #30363d;border-radius:4px',
      'display:flex;flex-direction:column;gap:5px',
    ].join(';')

    function _labelRow(labelText, inputEl) {
      const r = document.createElement('div')
      r.style.cssText = 'display:flex;align-items:center;gap:6px'
      const lbl = document.createElement('label')
      lbl.textContent = labelText
      lbl.style.cssText = 'font-size:var(--text-xs);color:#8b949e;width:58px;flex-shrink:0;text-align:right'
      r.append(lbl, inputEl)
      return r
    }

    function _numInput(val, step) {
      const el = document.createElement('input')
      el.type  = 'number'
      el.value = val ?? ''
      el.step  = step
      el.style.cssText = [
        'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #30363d',
        'border-radius:3px;font-size:var(--text-xs);padding:2px 4px',
      ].join(';')
      return el
    }

    function _textInput(val) {
      const el = document.createElement('input')
      el.type  = 'text'
      el.value = val ?? ''
      el.style.cssText = [
        'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #30363d',
        'border-radius:3px;font-size:var(--text-xs);padding:2px 4px',
      ].join(';')
      return el
    }

    const nameIn = _textInput(joint.name ?? '')
    form.appendChild(_labelRow('Name', nameIn))

    const typeSel = document.createElement('select')
    typeSel.style.cssText = [
      'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #30363d',
      'border-radius:3px;font-size:var(--text-xs);padding:2px 4px',
    ].join(';')
    for (const t of _JOINT_TYPES) {
      const opt = document.createElement('option')
      opt.value    = t
      opt.text     = t.charAt(0).toUpperCase() + t.slice(1)
      opt.selected = joint.joint_type === t
      typeSel.appendChild(opt)
    }
    form.appendChild(_labelRow('Type', typeSel))

    const limitsDiv = document.createElement('div')
    limitsDiv.style.cssText = 'display:flex;flex-direction:column;gap:5px'

    let minIn = null, maxIn = null, valIn = null

    function _rebuildLimits() {
      limitsDiv.innerHTML = ''
      minIn = null; maxIn = null; valIn = null
      const t = typeSel.value
      if (t !== 'revolute' && t !== 'prismatic') return
      const isDeg = t === 'revolute'
      const u     = isDeg ? '°' : 'nm'
      const step  = isDeg ? 1 : 0.1
      const toDisplay = v => (v != null && isFinite(v))
        ? (isDeg ? (v * 180 / Math.PI).toFixed(2) : String(v))
        : ''
      minIn = _numInput(toDisplay(joint.min_limit), step)
      maxIn = _numInput(toDisplay(joint.max_limit), step)
      valIn = _numInput(toDisplay(joint.current_value ?? 0), step)
      limitsDiv.appendChild(_labelRow(`Min (${u})`, minIn))
      limitsDiv.appendChild(_labelRow(`Max (${u})`, maxIn))
      limitsDiv.appendChild(_labelRow(`Value (${u})`, valIn))
    }

    _rebuildLimits()
    typeSel.addEventListener('change', _rebuildLimits)
    form.appendChild(limitsDiv)

    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;gap:4px;justify-content:flex-end;margin-top:2px'

    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'
    cancelBtn.style.cssText = [
      'background:none;border:1px solid #30363d;color:#8b949e',
      'border-radius:3px;font-size:var(--text-xs);padding:2px 8px;cursor:pointer',
    ].join(';')
    cancelBtn.addEventListener('click', onDone)

    const saveBtn = document.createElement('button')
    saveBtn.textContent = 'Save'
    saveBtn.style.cssText = [
      'background:#1f3d2a;border:1px solid #3fb950;color:#3fb950',
      'border-radius:3px;font-size:var(--text-xs);padding:2px 8px;cursor:pointer',
    ].join(';')
    saveBtn.addEventListener('click', async () => {
      const patches = {}

      const newName = nameIn.value.trim()
      if (newName !== (joint.name ?? '')) patches.name = newName || null

      const newType = typeSel.value
      if (newType !== joint.joint_type) patches.joint_type = newType

      const hasLimits = (patches.joint_type ?? joint.joint_type) === 'revolute' ||
                        (patches.joint_type ?? joint.joint_type) === 'prismatic'
      if (hasLimits && minIn) {
        const isDeg  = (patches.joint_type ?? joint.joint_type) === 'revolute'
        const toRad  = v => isDeg ? v * Math.PI / 180 : v
        const minVal = minIn.value !== '' ? toRad(parseFloat(minIn.value)) : null
        const maxVal = maxIn.value !== '' ? toRad(parseFloat(maxIn.value)) : null
        const curVal = valIn.value !== '' ? toRad(parseFloat(valIn.value)) : 0
        if (minVal !== joint.min_limit)             patches.min_limit     = minVal
        if (maxVal !== joint.max_limit)             patches.max_limit     = maxVal
        if (curVal !== (joint.current_value ?? 0))  patches.current_value = curVal
      }

      if (Object.keys(patches).length === 0) { onDone(); return }

      saveBtn.disabled    = true
      saveBtn.textContent = '…'
      try {
        await api.patchAssemblyJoint(joint.id, patches)
      } finally {
        onDone()
      }
    })

    btnRow.append(cancelBtn, saveBtn)
    form.appendChild(btnRow)
    return form
  }

  function _rebuildMates(assembly) {
    _matesSectionEl.innerHTML = ''
    const joints    = assembly?.joints    ?? []
    const instances = assembly?.instances ?? []

    const header = document.createElement('div')
    header.style.cssText = [
      'display:flex;align-items:center;gap:6px',
      'cursor:pointer;padding:4px 0;margin-top:8px',
      'border-top:1px solid #21262d',
    ].join(';')

    const headerLeft = document.createElement('span')
    headerLeft.style.cssText = 'font-size:var(--text-xs);font-weight:600;color:#8b949e;flex:1'
    headerLeft.textContent = `Mates (${joints.length})`

    const resolveBtn = document.createElement('button')
    resolveBtn.textContent = 'Resolve'
    resolveBtn.title = 'Re-apply all joint constraints and check satisfaction'
    resolveBtn.style.cssText = [
      'background:#161b22;border:1px solid #388bfd;color:#58a6ff',
      'border-radius:3px;font-size:var(--text-xs);padding:3px 7px;cursor:pointer;flex-shrink:0',
    ].join(';')
    resolveBtn.addEventListener('pointerenter', () => { resolveBtn.style.background = '#1c2d3f' })
    resolveBtn.addEventListener('pointerleave', () => { resolveBtn.style.background = '#161b22' })
    resolveBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      resolveBtn.disabled    = true
      resolveBtn.textContent = '…'
      try {
        const result = await api.resolveAssembly()
        // Store subscription fires synchronously during the await, triggering a full
        // _rebuild which clears _solveStatus. Set it after and re-render manually.
        _solveStatus = result?.solve_status ?? {}
        _rebuildMates(store.getState().currentAssembly)
      } catch (err) {
        console.error('[assembly] resolve failed:', err)
        resolveBtn.disabled    = false
        resolveBtn.textContent = 'Resolve'
      }
    })

    const headerArrow = document.createElement('span')
    headerArrow.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    headerArrow.textContent = _matesCollapsed ? '▶' : '▼'

    header.append(headerLeft, resolveBtn, headerArrow)

    header.addEventListener('click', (e) => {
      if (e.target === resolveBtn) return
      _matesCollapsed = !_matesCollapsed
      listEl.style.display = _matesCollapsed ? 'none' : ''
      headerArrow.textContent = _matesCollapsed ? '▶' : '▼'
    })

    const listEl = document.createElement('div')
    listEl.style.cssText = 'display:flex;flex-direction:column;gap:2px;padding-bottom:4px'
    listEl.style.display = _matesCollapsed ? 'none' : ''

    if (!joints.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No mates defined'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:2px 0'
      listEl.appendChild(empty)
    }

    for (const joint of joints) {
      const instB    = instances.find(i => i.id === joint.instance_b_id)
      const instA    = joint.instance_a_id ? instances.find(i => i.id === joint.instance_a_id) : null
      const broken   = _isBrokenMate(joint, instances)
      const aName    = instA?.name ?? 'World'
      const bName    = instB?.name ?? joint.instance_b_id.slice(0, 6)
      const typeIcon = _JOINT_TYPE_ICON[joint.joint_type] ?? '⊞'
      const typeShort = joint.joint_type.slice(0, 3)
      const isEditing = _editingJointId === joint.id
      const status    = _solveStatus[joint.id]

      const wrapper = document.createElement('div')

      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:3px',
        `border-left:2px solid ${broken ? '#f85149' : '#ff8c00'}`,
        'padding-left:6px',
      ].join(';')

      if (status != null) {
        const dot = document.createElement('span')
        dot.textContent = status.satisfied ? '✓' : '⚠'
        dot.title = status.satisfied
          ? 'Satisfied before resolve'
          : `Unsatisfied before resolve (discrepancy: ${status.discrepancy?.toFixed(4) ?? '?'})`
        dot.style.cssText = `font-size:var(--text-xs);flex-shrink:0;color:${status.satisfied ? '#3fb950' : '#d29922'}`
        row.appendChild(dot)
      }

      const icon = document.createElement('span')
      icon.textContent = broken ? '⚠' : typeIcon
      icon.title = broken
        ? 'Broken mate — a referenced connector was deleted'
        : `${joint.joint_type} joint`
      icon.style.cssText = `font-size:var(--text-xs);color:${broken ? '#f85149' : '#ff8c00'};flex-shrink:0`

      const label = document.createElement('span')
      label.textContent = `${bName} ↔ ${aName}`
      label.title = joint.name
      label.style.cssText = [
        'flex:1;font-size:var(--text-xs);overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
        `color:${broken ? '#f85149' : '#c9d1d9'}`,
      ].join(';')

      const typeTag = document.createElement('span')
      typeTag.textContent = typeShort
      typeTag.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0;text-transform:capitalize'

      const editBtn = document.createElement('button')
      editBtn.textContent = isEditing ? '▴' : '✎'
      editBtn.title = isEditing ? 'Collapse' : 'Edit mate'
      editBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        `color:${isEditing ? '#58a6ff' : '#6e7681'};font-size:11px;line-height:1`,
      ].join(';')
      editBtn.addEventListener('pointerenter', () => { editBtn.style.color = '#58a6ff' })
      editBtn.addEventListener('pointerleave', () => {
        editBtn.style.color = (_editingJointId === joint.id) ? '#58a6ff' : '#6e7681'
      })
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation()
        _editingJointId = _editingJointId === joint.id ? null : joint.id
        _rebuildMates(store.getState().currentAssembly)
      })

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete mate'
      delBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        'color:#6e7681;font-size:12px;line-height:1',
      ].join(';')
      delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        if (_editingJointId === joint.id) _editingJointId = null
        await api.deleteAssemblyJoint(joint.id)
      })

      row.append(icon, label, typeTag, editBtn, delBtn)
      wrapper.appendChild(row)

      if (isEditing) {
        const form = _buildEditForm(joint, () => {
          _editingJointId = null
          _rebuildMates(store.getState().currentAssembly)
        })
        wrapper.appendChild(form)
      }

      listEl.appendChild(wrapper)
    }

    _matesSectionEl.append(header, listEl)
  }

  // ── Public API ────────────────────────────────────────────────────────────────

  function _rebuild(state) {
    if (_collapsed) return
    if (nameEl) {
      const asmName = state.currentAssembly?.metadata?.name
      nameEl.textContent = asmName ? asmName : ''
    }
    _rebuildInstances(state.currentAssembly, state.activeInstanceId)
    _editingJointId = null
    _solveStatus    = {}
    _rebuildMates(state.currentAssembly)

    // Part context — notify sidebar panels when the selected instance changes
    const prevPartId = _partLastRebuildId
    _partLastRebuildId = state.activeInstanceId
    if (state.activeInstanceId !== prevPartId) {
      _onPartInstanceChanged(state.activeInstanceId)
    }
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
