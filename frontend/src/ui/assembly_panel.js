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
 * @param {function} opts.onDefineConnector      — called with active instance id when the sidebar button is clicked
 * @param {function} opts.onDefineMate           — called when the sidebar mate button is clicked
 */

import { openFileBrowser } from './file_browser.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showConfirm } from './primitives/confirm.js'
import { getDocId } from '../shared/doc_id.js'

const _REPR_OPTIONS = [
  { value: 'full',       label: 'Full (CG)' },
  { value: 'beads',      label: 'Beads' },
  { value: 'cylinders',  label: 'Cylinders' },
  { value: 'hull-prism', label: 'Hull Prism' },
  { value: 'vdw',        label: 'VDW (atomistic)' },
  { value: 'ballstick',  label: 'Ball+Stick (atomistic)' },
  { value: 'stick',      label: 'Stick (atomistic)' },
]
const _ATOMISTIC_REPRS = new Set(['vdw', 'ballstick', 'stick'])

const _JOINT_TYPE_ICON = {
  revolute:  '↻',
  prismatic: '↕',
  spherical: '⊕',
  rigid:     '⊞',
}

const _JOINT_TYPES = ['revolute', 'prismatic', 'rigid', 'spherical']

export function initAssemblyPanel(store, { api, onInstanceSelect, onPartContextChange, beforePatchDesign, onDefineConnector, onDefineMate, onMateHighlight, onMateHighlightClear, onMateDebugMarkers, computeDuplicateOffset, onEditBeltPath, isBeltHidden, onToggleBeltVisibility, onAttachToBelt, onDeleteBeltRider }) {
  const panelEl    = document.getElementById('assembly-panel')
  const instanceEl = document.getElementById('assembly-instance-list')
  const nameEl     = document.getElementById('assembly-panel-name')
  const heading    = document.getElementById('assembly-panel-heading')
  const arrow      = document.getElementById('assembly-panel-arrow')
  const body       = document.getElementById('assembly-panel-body')
  const connectorBtn = document.getElementById('assembly-define-connector-btn')
  const mateBtn      = document.getElementById('assembly-define-mate-btn')
  if (!instanceEl) return { show() {}, hide() {}, rebuild() {} }

  let _collapsed = getSectionCollapsed('right', 'assembly-panel', false)

  // Apply persisted collapse state to DOM.
  if (body) body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)

  heading?.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('right', 'assembly-panel', _collapsed)
    _syncActionButtons()
  })

  connectorBtn?.addEventListener('click', () => {
    const id = store.getState().activeInstanceId
    if (id) onDefineConnector?.(id)
  })
  mateBtn?.addEventListener('click', () => onDefineMate?.())

  function _syncActionButtons(state = store.getState()) {
    if (connectorBtn) connectorBtn.disabled = !(state.assemblyActive && state.activeInstanceId)
    if (mateBtn) mateBtn.disabled = !state.assemblyActive
  }

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
  let _lastAssemblyRef     = null

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

  async function _onPartInstanceChanged(instanceId, { force = false } = {}) {
    if (!instanceId) {
      _partCacheInstanceId = null
      _partCacheDesign     = null
      _partPatchFn         = null
      onPartContextChange?.(null, null, null)
      return
    }
    if (!force && instanceId === _partCacheInstanceId && _partCacheDesign) {
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
          const ok = await showConfirm({
            title: 'Delete connector in use',
            message: `Connector "${ip.label}" is used in ${usedCount} mate(s). Delete anyway?`,
            danger: true,
            confirmLabel: 'Delete',
          })
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
    const multiIds = store.getState().multiSelectedInstanceIds ?? []
    const isMultiSel = multiIds.includes(inst.id)
    row.style.cssText = [
      'display:flex;align-items:center;gap:6px;padding:5px 6px',
      'border-radius:4px;cursor:pointer',
      `background:${isActive ? '#1e3a5f' : (isMultiSel ? '#192c45' : 'transparent')}`,
      'transition:background 0.1s',
    ].join(';')

    function _rowBgFromState() {
      const s = store.getState()
      if (inst.id === s.activeInstanceId) return '#1e3a5f'
      if ((s.multiSelectedInstanceIds ?? []).includes(inst.id)) return '#192c45'
      return 'transparent'
    }

    row.addEventListener('mouseenter', () => {
      if (inst.id !== store.getState().activeInstanceId) row.style.background = '#161b22'
    })
    row.addEventListener('mouseleave', () => {
      row.style.background = _rowBgFromState()
    })
    row.addEventListener('click', (e) => {
      // Ctrl/Meta-click: toggle membership in the multi-select set without
      // changing the single-select activeInstanceId. Lets users build up a
      // selection for the Group action.
      if (e.ctrlKey || e.metaKey) {
        e.stopPropagation()
        const cur = store.getState().multiSelectedInstanceIds ?? []
        const next = cur.includes(inst.id)
          ? cur.filter(id => id !== inst.id)
          : [...cur, inst.id]
        store.setState({ multiSelectedInstanceIds: next })
        return
      }
      const currentActive = store.getState().activeInstanceId
      store.setState({ multiSelectedInstanceIds: [], activeGroupId: null })
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
      // Pass an EXPLICIT per-part doc (NOT inherited): window.open copies the
      // opener's sessionStorage, so without an explicit `?doc=` the part editor
      // would resolve to the assembly tab's sticky doc and clobber sibling parts.
      // `&assembly-doc=` names where the assembly lives (source-read + save-back).
      // Mirrors onEditPart in main.js.
      const asmDoc  = getDocId()
      const partDoc = `pe-${asmDoc ?? 'default'}-${inst.id}`
      const asm     = asmDoc ? `&assembly-doc=${encodeURIComponent(asmDoc)}` : ''
      window.open(`/?part-instance=${inst.id}&doc=${encodeURIComponent(partDoc)}${asm}`, `nadoc-part-${inst.id}`)
    })

    const dupBtn = document.createElement('button')
    dupBtn.textContent = '⎘'
    dupBtn.title       = 'Duplicate this part (same source + connectors, offset placement)'
    dupBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:13px;line-height:1',
    ].join(';')
    dupBtn.addEventListener('pointerenter', () => { dupBtn.style.color = '#58a6ff' })
    dupBtn.addEventListener('pointerleave', () => { dupBtn.style.color = '#6e7681' })
    dupBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      const offset = computeDuplicateOffset?.(inst.id)
      const result = await api.duplicateInstance(inst.id, offset ? { offset } : {})
      if (!result) {
        const err = store.getState().lastError
        window.alert(`Duplicate failed: ${err?.message || 'unknown error'}`)
      }
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
        const ok = await showConfirm({
          title: 'Apply atomistic representation',
          message: 'Atomistic rendering computes all-atom geometry for this part and can be slow for large designs or assemblies with many parts.\n\nApply anyway?',
          confirmLabel: 'Apply',
        })
        if (!ok) {
          reprSel.value = inst.representation ?? 'full'
          return
        }
      }
      await api.patchInstance(inst.id, { representation: repr })
    })

    reprRow.append(reprLabel, reprSel)
    row.append(eyeBtn, editBtn, dupBtn, nameSpan, delBtn)
    return { row, reprRow }
  }

  // ── Instance list ──────────────────────────────────────────────────────────────

  // Track which id we last autoscrolled to so we don't fight the user's
  // scroll position on every unrelated assembly rebuild.
  let _lastScrolledActiveId = null

  // Indices computed per-rebuild — used by group rendering AND multi-select.
  function _buildGroupIndex(groups) {
    const byId = new Map()
    const parent = new Map()       // member id (instance or group) → owning group id
    for (const g of groups) byId.set(g.id, g)
    for (const g of groups) {
      for (const iid of (g.instance_ids ?? [])) parent.set(iid, g.id)
      for (const sgid of (g.subgroup_ids ?? [])) parent.set(sgid, g.id)
    }
    const topLevelGroupIds = groups.filter(g => !parent.has(g.id)).map(g => g.id)
    return { byId, parent, topLevelGroupIds }
  }

  /** External-facing connectors for a group:
   *  every InterfacePoint on any member whose label is NOT consumed by a joint
   *  whose OTHER endpoint is also a member of the same group. */
  function _externalConnectorsForGroup(memberInstanceIds, instances, joints) {
    const memberSet = new Set(memberInstanceIds)
    const internalJoints = joints.filter(j =>
      memberSet.has(j.instance_a_id) && memberSet.has(j.instance_b_id),
    )
    const usedInternally = new Set()  // `${instanceId}::${label}`
    for (const j of internalJoints) {
      if (j.connector_a_label && j.instance_a_id) usedInternally.add(`${j.instance_a_id}::${j.connector_a_label}`)
      if (j.connector_b_label && j.instance_b_id) usedInternally.add(`${j.instance_b_id}::${j.connector_b_label}`)
    }
    const out = []
    for (const iid of memberInstanceIds) {
      const inst = instances.find(i => i.id === iid)
      if (!inst) continue
      for (const ip of (inst.interface_points ?? [])) {
        if (!usedInternally.has(`${iid}::${ip.label}`)) {
          out.push({ instanceId: iid, instanceName: inst.name, label: ip.label })
        }
      }
    }
    return out
  }

  function _collectGroupMemberInstanceIds(groupId, index) {
    const out = []
    const stack = [groupId]
    while (stack.length) {
      const gid = stack.pop()
      const g = index.byId.get(gid)
      if (!g) continue
      for (const iid of (g.instance_ids ?? [])) out.push(iid)
      for (const sgid of (g.subgroup_ids ?? [])) stack.push(sgid)
    }
    return out
  }

  function _buildGroupRow(group, level, instances, joints, activeGroupId) {
    const isActive = group.id === activeGroupId
    const indentPx = 6 + level * 12

    const row = document.createElement('div')
    row.dataset.groupId = group.id
    row.style.cssText = [
      'display:flex;align-items:center;gap:6px;padding:5px 6px',
      `padding-left:${indentPx}px`,
      'border-radius:4px;cursor:pointer',
      `background:${isActive ? '#3a2a5f' : 'transparent'}`,
      `border-left:3px solid ${isActive ? '#8b5cf6' : '#3a2a5f'}`,
      'transition:background 0.1s',
    ].join(';')

    row.addEventListener('mouseenter', () => {
      if (group.id !== store.getState().activeGroupId) row.style.background = '#1d1a2e'
    })
    row.addEventListener('mouseleave', () => {
      row.style.background = group.id === store.getState().activeGroupId ? '#3a2a5f' : 'transparent'
    })
    row.addEventListener('click', (e) => {
      e.stopPropagation()
      const cur = store.getState().activeGroupId
      store.setState({
        activeGroupId:    cur === group.id ? null : group.id,
        activeInstanceId: null,
        multiSelectedInstanceIds: [],
        groupDiveStack:   [],
      })
    })

    // Caret toggles expanded (persisted via PATCH)
    const caret = document.createElement('span')
    caret.textContent = group.expanded === false ? '▶' : '▼'
    caret.style.cssText = 'font-size:9px;color:#8b5cf6;cursor:pointer;flex-shrink:0;width:10px'
    caret.addEventListener('click', async (e) => {
      e.stopPropagation()
      await api.patchGroup(group.id, { expanded: !(group.expanded !== false) })
    })

    const eyeBtn = document.createElement('button')
    eyeBtn.innerHTML = _eyeSVG(group.visible !== false)
    eyeBtn.title = group.visible === false ? 'Show group' : 'Hide group'
    eyeBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'display:flex;align-items:center;line-height:1',
    ].join(';')
    eyeBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      await api.patchGroup(group.id, { visible: group.visible === false })
    })

    const dupBtn = document.createElement('button')
    dupBtn.textContent = '⎘'
    dupBtn.title = 'Duplicate group (clones internals; external connections dropped)'
    dupBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:13px;line-height:1',
    ].join(';')
    dupBtn.addEventListener('pointerenter', () => { dupBtn.style.color = '#8b5cf6' })
    dupBtn.addEventListener('pointerleave', () => { dupBtn.style.color = '#6e7681' })
    dupBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      await api.duplicateGroup(group.id)
    })

    // Move-group dialog — rigid translate the whole group + transitive
    // rigid-joint partners. Three small inputs in a popover; on Apply we
    // POST /assembly/groups/{id}/transform with {translation}.
    const moveBtn = document.createElement('button')
    moveBtn.textContent = '↔'
    moveBtn.title = 'Move group (rigid translation, nm — externally rigid-mated parts follow)'
    moveBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:13px;line-height:1',
    ].join(';')
    moveBtn.addEventListener('pointerenter', () => { moveBtn.style.color = '#8b5cf6' })
    moveBtn.addEventListener('pointerleave', () => { moveBtn.style.color = '#6e7681' })
    moveBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      const txt = window.prompt(
        'Translate group by (x, y, z) nm — comma separated:',
        '5, 0, 0',
      )
      if (!txt) return
      const parts = txt.split(/[,\s]+/).map(s => parseFloat(s)).filter(v => !Number.isNaN(v))
      if (parts.length !== 3) {
        window.alert('Need three numbers (x, y, z) in nm')
        return
      }
      api.transformGroup(group.id, { translation: parts }).catch(err => {
        window.alert(`Move group failed: ${err?.message ?? err}`)
      })
    })

    const nameSpan = document.createElement('span')
    nameSpan.textContent = group.name || 'Group'
    nameSpan.title = 'Double-click to rename'
    nameSpan.style.cssText = [
      'flex:1;font-size:11px;font-weight:600;color:#c9d1d9',
      'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
    ].join(';')
    nameSpan.addEventListener('dblclick', async (e) => {
      e.stopPropagation()
      const next = window.prompt('Rename group:', group.name || '')
      if (next == null) return
      const trimmed = next.trim()
      if (!trimmed || trimmed === group.name) return
      await api.patchGroup(group.id, { name: trimmed })
    })

    // Ungroup button (keeps members, removes group wrapper)
    const ungroupBtn = document.createElement('button')
    ungroupBtn.textContent = '⤴'
    ungroupBtn.title = 'Ungroup (members re-enter top level)'
    ungroupBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:13px;line-height:1',
    ].join(';')
    ungroupBtn.addEventListener('pointerenter', () => { ungroupBtn.style.color = '#d29922' })
    ungroupBtn.addEventListener('pointerleave', () => { ungroupBtn.style.color = '#6e7681' })
    ungroupBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      if (group.id === store.getState().activeGroupId) store.setState({ activeGroupId: null })
      await api.ungroup(group.id)
    })

    const delBtn = document.createElement('button')
    delBtn.textContent = '×'
    delBtn.title = 'Delete group AND all member parts (cascade)'
    delBtn.style.cssText = [
      'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
      'color:#6e7681;font-size:14px;line-height:1',
    ].join(';')
    delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
    delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
    delBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      const ok = await showConfirm({
        title: `Delete group "${group.name || 'Group'}"`,
        message: 'This removes the group AND every part it contains. Use the ungroup button (↑) if you only want to dissolve the group.',
        danger: true,
        confirmLabel: 'Delete all',
      })
      if (!ok) return
      if (group.id === store.getState().activeGroupId) store.setState({ activeGroupId: null })
      await api.deleteGroupCascade(group.id)
    })

    row.append(caret, eyeBtn, dupBtn, moveBtn, nameSpan, ungroupBtn, delBtn)

    // ── Group representation overlay row ──
    const reprRow = document.createElement('div')
    reprRow.style.cssText = `display:flex;align-items:center;gap:4px;padding:2px 6px 4px ${indentPx + 20}px`
    const reprLabel = document.createElement('span')
    reprLabel.textContent = 'Repr:'
    reprLabel.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
    const reprSel = document.createElement('select')
    reprSel.style.cssText = [
      'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #3a2a5f',
      'border-radius:3px;font-size:var(--text-xs);padding:3px 2px;cursor:pointer',
    ].join(';')
    // "(member default)" = clear the overlay so each member renders its own repr.
    const defaultOpt = document.createElement('option')
    defaultOpt.value = '__default__'
    defaultOpt.text  = '(member default)'
    defaultOpt.selected = group.representation == null
    reprSel.appendChild(defaultOpt)
    for (const { value, label } of _REPR_OPTIONS) {
      const opt = document.createElement('option')
      opt.value   = value
      opt.text    = label
      opt.selected = group.representation === value
      reprSel.appendChild(opt)
    }
    reprSel.addEventListener('click', e => e.stopPropagation())
    reprSel.addEventListener('change', async (e) => {
      e.stopPropagation()
      if (reprSel.value === '__default__') {
        await api.patchGroup(group.id, { clearRepresentation: true })
      } else {
        await api.patchGroup(group.id, { representation: reprSel.value })
      }
    })
    reprRow.append(reprLabel, reprSel)

    // ── External-facing connectors ──
    const memberInstIds = _collectGroupMemberInstanceIds(group.id, _buildGroupIndex(store.getState().currentAssembly?.groups ?? []))
    const externalIps   = _externalConnectorsForGroup(memberInstIds, instances, joints)
    const connSection = document.createElement('div')
    connSection.style.cssText = `padding:0 6px 4px ${indentPx + 20}px`
    const connHeader = document.createElement('div')
    connHeader.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;padding:2px 0'
    const connArrow = document.createElement('span')
    connArrow.textContent = '▶'
    connArrow.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0'
    const connTitle = document.createElement('span')
    connTitle.textContent = `External connectors (${externalIps.length})`
    connTitle.style.cssText = 'font-size:var(--text-xs);color:#6e7681'
    connHeader.append(connArrow, connTitle)
    const connList = document.createElement('div')
    connList.style.display = 'none'
    let _connExpanded = false
    connHeader.addEventListener('click', (e) => {
      e.stopPropagation()
      _connExpanded = !_connExpanded
      connList.style.display = _connExpanded ? '' : 'none'
      connArrow.textContent  = _connExpanded ? '▼' : '▶'
    })
    for (const c of externalIps) {
      const r = document.createElement('div')
      r.style.cssText = 'display:flex;align-items:center;gap:4px;padding:2px 0 2px 8px'
      const lbl = document.createElement('span')
      lbl.textContent = `${c.instanceName} · ${c.label}`
      lbl.style.cssText = 'flex:1;font-size:var(--text-xs);color:#8b949e'
      r.appendChild(lbl)
      connList.appendChild(r)
    }
    if (!externalIps.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No external connectors'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:2px 0 2px 8px'
      connList.appendChild(empty)
    }
    connSection.append(connHeader, connList)

    return { row, reprRow, connSection }
  }

  // ── Tree walker: groups (with nested subgroups + member instances) first,
  //    then orphan top-level instances. Returns the row matching the active
  //    instance id (for autoscroll).
  function _renderGroupSubtree(groupId, level, instances, joints, activeId, activeGroupId, index, rendered) {
    const group = index.byId.get(groupId)
    if (!group) return null
    let activeRow = null
    const { row, reprRow, connSection } = _buildGroupRow(group, level, instances, joints, activeGroupId)
    instanceEl.appendChild(row)
    instanceEl.appendChild(reprRow)
    instanceEl.appendChild(connSection)

    // Children only visible when expanded.
    if (group.expanded === false) return null

    for (const sgid of (group.subgroup_ids ?? [])) {
      const r = _renderGroupSubtree(sgid, level + 1, instances, joints, activeId, activeGroupId, index, rendered)
      if (r) activeRow = r
    }
    for (const iid of (group.instance_ids ?? [])) {
      const inst = instances.find(i => i.id === iid)
      if (!inst || rendered.has(iid)) continue
      rendered.add(iid)
      const { row: ir, reprRow: irRepr } = _buildInstanceRow(inst, activeId, joints)
      // Indent nested member rows so the hierarchy reads visually.
      ir.style.paddingLeft = `${6 + (level + 1) * 12}px`
      irRepr.style.paddingLeft = `${26 + (level + 1) * 12}px`
      instanceEl.appendChild(ir)
      instanceEl.appendChild(irRepr)
      instanceEl.appendChild(_buildConnectorSection(inst, joints))
      if (inst.id === activeId) activeRow = ir
    }
    return activeRow
  }

  function _rebuildInstances(assembly, activeId) {
    instanceEl.innerHTML = ''
    const instances = assembly?.instances ?? []
    const joints    = assembly?.joints    ?? []
    const groups    = assembly?.groups    ?? []
    if (!instances.length && !groups.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No parts — use "+ Add Part" below'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:3px 2px'
      instanceEl.appendChild(empty)
      return
    }
    const index = _buildGroupIndex(groups)
    const activeGroupId = store.getState().activeGroupId
    const rendered = new Set()
    let activeRow = null

    // 1) Top-level groups (recursively render members)
    for (const gid of index.topLevelGroupIds) {
      const r = _renderGroupSubtree(gid, 0, instances, joints, activeId, activeGroupId, index, rendered)
      if (r) activeRow = r
    }
    // 2) Orphan instances (not inside any group)
    for (const inst of instances) {
      if (index.parent.has(inst.id) || rendered.has(inst.id)) continue
      const { row, reprRow } = _buildInstanceRow(inst, activeId, joints)
      const connSection = _buildConnectorSection(inst, joints)
      instanceEl.appendChild(row)
      instanceEl.appendChild(reprRow)
      instanceEl.appendChild(connSection)
      if (inst.id === activeId) activeRow = row
    }

    // Autoscroll the active row into view so a 3D click on a far-away part
    // surfaces its list entry in the (now scrollable) panel. Uses
    // 'nearest' so visible rows don't jump. Skip when the active id is
    // unchanged so the user's manual scrolling sticks.
    if (activeRow && _lastScrolledActiveId !== activeId) {
      _lastScrolledActiveId = activeId
      requestAnimationFrame(() => {
        try { activeRow.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }
        catch (_) { activeRow.scrollIntoView() }
      })
    } else if (!activeRow) {
      _lastScrolledActiveId = null
    }
  }

  // ── Mates section ──────────────────────────────────────────────────────────────

  let _matesCollapsed = false
  const _beltRidersExpanded = new Set()   // belt ids whose "Parts on path" list is open
  let _editingJointId = null
  let _editingGearId  = null
  let _highlightedJointId = null
  let _debugJointId = null
  const _debugDataByJoint = {}

  async function _setHighlightedJoint(jointId) {
    if (_highlightedJointId === jointId) {
      _highlightedJointId = null
      onMateHighlightClear?.()
      _rebuildMates(store.getState().currentAssembly)
      return
    }
    _highlightedJointId = jointId
    _rebuildMates(store.getState().currentAssembly)
    if (!jointId) { onMateHighlightClear?.(); return }
    try {
      const frames = await api.getJointConnectorFrames(jointId)
      if (_highlightedJointId === jointId) onMateHighlight?.(frames)
    } catch (err) {
      console.error('[assembly] connector-frames fetch failed:', err)
    }
  }
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

    let minIn = null, maxIn = null, valIn = null, limitsEnabledIn = null
    let rpmIn = null, pauseIn = null

    function _rebuildLimits() {
      limitsDiv.innerHTML = ''
      minIn = null; maxIn = null; valIn = null; limitsEnabledIn = null
      rpmIn = null; pauseIn = null
      const t = typeSel.value
      if (t !== 'revolute' && t !== 'prismatic') return
      const isDeg = t === 'revolute'
      const u     = isDeg ? '°' : 'nm'
      const step  = isDeg ? 1 : 0.1
      const toDisplay = v => (v != null && isFinite(v))
        ? (isDeg ? (v * 180 / Math.PI).toFixed(2) : String(v))
        : ''
      valIn = _numInput(toDisplay(joint.current_value ?? 0), step)
      limitsDiv.appendChild(_labelRow(`Value (${u})`, valIn))

      if (t === 'revolute') {
        limitsEnabledIn = document.createElement('input')
        limitsEnabledIn.type = 'checkbox'
        limitsEnabledIn.checked = joint.min_limit != null || joint.max_limit != null
        limitsEnabledIn.style.cssText = 'cursor:pointer'
        const limitsTxt = document.createElement('span')
        limitsTxt.textContent = 'Use rotation limits'
        limitsTxt.style.cssText = 'font-size:var(--text-xs);color:#c9d1d9'
        const limitsLabel = document.createElement('label')
        limitsLabel.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1'
        limitsLabel.append(limitsEnabledIn, limitsTxt)
        const limitsToggleRow = document.createElement('div')
        limitsToggleRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding-left:64px'
        limitsToggleRow.append(limitsLabel)
        limitsDiv.appendChild(limitsToggleRow)

        const limitRows = document.createElement('div')
        limitRows.style.cssText = 'display:flex;flex-direction:column;gap:5px'
        minIn = _numInput(toDisplay(joint.min_limit), step)
        maxIn = _numInput(toDisplay(joint.max_limit), step)
        limitRows.appendChild(_labelRow(`Min (${u})`, minIn))
        limitRows.appendChild(_labelRow(`Max (${u})`, maxIn))
        limitsDiv.appendChild(limitRows)
        const syncLimitRows = () => { limitRows.style.display = limitsEnabledIn.checked ? '' : 'none' }
        limitsEnabledIn.addEventListener('change', syncLimitRows)
        syncLimitRows()

        rpmIn = _numInput(joint.angular_velocity_rpm ?? 0, 0.5)
        rpmIn.title = 'Revolutions per minute. 0 = static. Positive = right-hand rule around the axis.'
        limitsDiv.appendChild(_labelRow('RPM', rpmIn))

        pauseIn = document.createElement('input')
        pauseIn.type = 'checkbox'
        pauseIn.checked = !!joint.spin_paused
        pauseIn.style.cssText = 'cursor:pointer'
        const pauseTxt = document.createElement('span')
        pauseTxt.textContent = 'Pause this motor'
        pauseTxt.style.cssText = 'font-size:var(--text-xs);color:#c9d1d9'
        const pauseLabel = document.createElement('label')
        pauseLabel.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1'
        pauseLabel.append(pauseIn, pauseTxt)
        const pauseRow = document.createElement('div')
        pauseRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding-left:64px'
        pauseRow.append(pauseLabel)
        limitsDiv.appendChild(pauseRow)

        if (joint.min_limit != null || joint.max_limit != null) {
          const warn = document.createElement('div')
          warn.textContent = 'Limits set — spin will stall at limit.'
          warn.style.cssText = 'font-size:10px;color:#d29922;padding-left:64px'
          limitsDiv.appendChild(warn)
        }
      } else {
        minIn = _numInput(toDisplay(joint.min_limit), step)
        maxIn = _numInput(toDisplay(joint.max_limit), step)
        limitsDiv.insertBefore(_labelRow(`Max (${u})`, maxIn), valIn.parentElement?.nextSibling ?? null)
        limitsDiv.insertBefore(_labelRow(`Min (${u})`, minIn), valIn.parentElement ?? null)
      }
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
      if (hasLimits && valIn) {
        const isDeg  = (patches.joint_type ?? joint.joint_type) === 'revolute'
        const toRad  = v => isDeg ? v * Math.PI / 180 : v
        const curVal = valIn.value !== '' ? toRad(parseFloat(valIn.value)) : 0
        if (curVal !== (joint.current_value ?? 0))  patches.current_value = curVal
        if (isDeg) {
          if (!limitsEnabledIn?.checked) {
            if (joint.min_limit != null || joint.max_limit != null) patches.clear_limits = true
          } else if (minIn && maxIn) {
            const minVal = minIn.value !== '' ? toRad(parseFloat(minIn.value)) : null
            const maxVal = maxIn.value !== '' ? toRad(parseFloat(maxIn.value)) : null
            if (minVal !== joint.min_limit) patches.min_limit = minVal
            if (maxVal !== joint.max_limit) patches.max_limit = maxVal
          }
        } else if (minIn && maxIn) {
          const minVal = minIn.value !== '' ? toRad(parseFloat(minIn.value)) : null
          const maxVal = maxIn.value !== '' ? toRad(parseFloat(maxIn.value)) : null
          if (minVal !== joint.min_limit) patches.min_limit = minVal
          if (maxVal !== joint.max_limit) patches.max_limit = maxVal
        }
      }

      if ((patches.joint_type ?? joint.joint_type) === 'revolute') {
        if (rpmIn) {
          const rpmVal = rpmIn.value !== '' ? parseFloat(rpmIn.value) : 0
          if (Number.isFinite(rpmVal) && rpmVal !== (joint.angular_velocity_rpm ?? 0)) {
            patches.angular_velocity_rpm = rpmVal
          }
        }
        if (pauseIn) {
          const pauseVal = !!pauseIn.checked
          if (pauseVal !== !!joint.spin_paused) patches.spin_paused = pauseVal
        }
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
    // Scrollable window sized to ~4 rows. Rows are ~26px each; cap at 4 × 26 + a
    // little breathing room so the 4th row sits flush against the scrollbar.
    listEl.style.cssText = [
      'display:flex;flex-direction:column;gap:2px;padding:0 2px 4px 0',
      'max-height:112px;overflow-y:auto;overflow-x:hidden',
    ].join(';')
    listEl.style.display = _matesCollapsed ? 'none' : ''

    // Edit form for whichever mate / gear is being edited. Lives BELOW the
    // scrollable list so an open form doesn't push other rows out of view and
    // its inputs aren't trapped inside a scroll container.
    const editFormHostEl = document.createElement('div')
    editFormHostEl.style.cssText = 'margin-top:4px'
    editFormHostEl.style.display = _matesCollapsed ? 'none' : ''

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
      const isHighlighted = _highlightedJointId === joint.id

      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:3px;cursor:pointer',
        `border-left:2px solid ${broken ? '#f85149' : '#ff8c00'}`,
        'padding-left:6px',
        isHighlighted ? 'background:#1c2d3f' : '',
      ].join(';')
      row.addEventListener('click', (e) => {
        // Ignore clicks that originated from the row's action buttons.
        if (e.target.closest('button')) return
        _setHighlightedJoint(joint.id)
      })

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

      const isRigidMate = (joint.joint_type === 'rigid' || joint.joint_type === 'spherical')
        && !!joint.connector_a_label && !!joint.connector_b_label && !!joint.instance_a_id

      // Debug toggle button — fetches multi-position candidate frames and
      // renders side-by-side coloured markers in the scene + a numeric
      // breakdown beneath the row. Helps diagnose where each path computes
      // a connector when the dots, joint icon, and DNA disagree.
      const debugBtn = document.createElement('button')
      const isDebug = _debugJointId === joint.id
      debugBtn.textContent = '🪲'
      debugBtn.title = 'Debug: show all candidate connector positions (white = T_inst @ ip.position, red = T_inst @ Ct @ ip.position, gold = axis_origin) + numeric breakdown.'
      debugBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        `color:${isDebug ? '#d29922' : '#6e7681'};font-size:11px;line-height:1`,
      ].join(';')
      debugBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        if (_debugJointId === joint.id) {
          _debugJointId = null
          onMateDebugMarkers?.(null)
          _rebuildMates(store.getState().currentAssembly)
          return
        }
        _debugJointId = joint.id
        _rebuildMates(store.getState().currentAssembly)
        try {
          const debugFrames = await api.getJointDebugFrames(joint.id)
          if (_debugJointId === joint.id) {
            onMateDebugMarkers?.(debugFrames)
            _debugDataByJoint[joint.id] = debugFrames
            _rebuildMates(store.getState().currentAssembly)
          }
        } catch (err) {
          console.error('[assembly] debug-frames fetch failed:', err)
        }
      })

      const refreshBtn = document.createElement('button')
      refreshBtn.textContent = '⟳'
      refreshBtn.title = joint.mate_relative_transform
        ? 'Re-capture this mate\'s current alignment as the intended state. Resolve will restore this pose after future part edits.'
        : 'Capture this mate\'s current alignment. Without this, Resolve falls back to position-only snap (no rotation).'
      refreshBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        `color:${joint.mate_relative_transform ? '#6e7681' : '#d29922'};font-size:11px;line-height:1`,
      ].join(';')
      refreshBtn.disabled = !isRigidMate
      if (!isRigidMate) refreshBtn.style.opacity = '0.3'
      refreshBtn.addEventListener('pointerenter', () => { if (isRigidMate) refreshBtn.style.color = '#58a6ff' })
      refreshBtn.addEventListener('pointerleave', () => {
        refreshBtn.style.color = joint.mate_relative_transform ? '#6e7681' : '#d29922'
      })
      refreshBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        try { await api.refreshMate(joint.id) }
        catch (err) { console.error('[assembly] refresh-mate failed:', err) }
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

      row.append(icon, label, typeTag, debugBtn, refreshBtn, editBtn, delBtn)
      wrapper.appendChild(row)

      if (isEditing) {
        const form = _buildEditForm(joint, () => {
          _editingJointId = null
          _rebuildMates(store.getState().currentAssembly)
        })
        editFormHostEl.appendChild(form)
      }

      if (isDebug && _debugDataByJoint[joint.id]) {
        const dbg = _debugDataByJoint[joint.id]
        const panel = document.createElement('div')
        panel.style.cssText = [
          'font-size:10px;font-family:monospace;color:#8b949e',
          'padding:4px 6px;margin:2px 0 4px 8px',
          'background:#0d1117;border-left:2px solid #d29922;border-radius:2px',
          'white-space:pre;overflow-x:auto',
        ].join(';')
        const fmt = (v) => v == null ? '—' : `(${v.map(x => x.toFixed(3)).join(', ')})`
        const sideText = (key) => {
          const s = dbg[key]
          if (!s) return `  ${key.toUpperCase()}: <missing>`
          if (s.missing) return `  ${key.toUpperCase()}: IP "${s.label}" not registered on instance`
          const lines = [
            `  ${key.toUpperCase()} ${s.label}`,
            `    instance:        ${s.instance_id?.slice(0,8) ?? '—'}`,
            `    cluster_id:      ${s.cluster_id ?? '—'}`,
            `    raw ip.position: ${fmt(s.raw_local)}`,
            `    T_inst @ ip.pos: ${fmt(s.T_inst_only)}    (white marker)`,
          ]
          if (s.T_inst_and_Ct) {
            lines.push(`    T_inst @ Ct @ ip.pos: ${fmt(s.T_inst_and_Ct)}  (red marker)`)
            lines.push(`    Ct.translation:  ${fmt(s.Ct_translation)}`)
            lines.push(`    Ct.rotation:     ${fmt(s.Ct_rotation_quat)}`)
            lines.push(`    Ct.pivot:        ${fmt(s.Ct_pivot)}`)
          }
          return lines.join('\n')
        }
        const M = dbg.mate_relative_transform
        const Mtail = M ? `\n  mate_relative_transform.translation: (${M[3].toFixed(3)}, ${M[7].toFixed(3)}, ${M[11].toFixed(3)})` : ''
        panel.textContent = [
          sideText('a'),
          sideText('b'),
          `  axis_origin (joint icon): ${fmt(dbg.axis_origin)}  (gold marker)${Mtail}`,
        ].join('\n')
        wrapper.appendChild(panel)
      }

      listEl.appendChild(wrapper)
    }

    // Gear-relation rows are rendered in the same scrollable Mates list. Each
    // side shows the *moving body* of the referenced revolute joint — the
    // owning group's name if the instance lives in a group, otherwise the
    // part instance's own name. Falls back to '?' if the joint or instance
    // has been deleted out from under the relation.
    const gearRelations = assembly?.gear_relations ?? []
    const groups        = assembly?.groups ?? []
    function _groupLabelForInstance(id) {
      const byId = new Map(groups.map(g => [g.id, g]))
      for (const g of groups) {
        const stack = [g.id]
        while (stack.length) {
          const cur = byId.get(stack.pop())
          if (!cur) continue
          if ((cur.instance_ids ?? []).includes(id)) return g.name || cur.name || 'Group'
          for (const sgid of (cur.subgroup_ids ?? [])) stack.push(sgid)
        }
      }
      return null
    }

    function _gearEndpointLabel(rel, which, joint) {
      if (!joint) return '?'
      const explicitId = rel[`endpoint_${which}_instance_id`]
      const side = rel[`endpoint_${which}_side`]
      const id = explicitId || (side === 'a' ? joint.instance_a_id : joint.instance_b_id)
      if (!id) return 'World'
      const inst = instances.find(i => i.id === id)
      if (!inst) return id.slice(0, 6)
      const groupLabel = _groupLabelForInstance(id)
      if (groupLabel) return groupLabel
      return inst.name || id.slice(0, 6)
    }
    for (const rel of gearRelations) {
      const ja = joints.find(j => j.id === rel.joint_a_id)
      const jb = joints.find(j => j.id === rel.joint_b_id)
      const broken = !ja || !jb
      const aLabel = _gearEndpointLabel(rel, 'a', ja)
      const bLabel = _gearEndpointLabel(rel, 'b', jb)
      const isEditing = _editingGearId === rel.id

      const wrapper = document.createElement('div')
      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:3px;cursor:pointer',
        `border-left:2px solid ${broken ? '#f85149' : '#58a6ff'}`,
        'padding-left:6px',
      ].join(';')

      const icon = document.createElement('span')
      icon.textContent = broken ? '⚠' : '⚙'
      icon.title = broken ? 'Broken gear relation — a referenced joint was deleted' : 'Gear relation'
      icon.style.cssText = `font-size:var(--text-xs);color:${broken ? '#f85149' : '#58a6ff'};flex-shrink:0`

      const label = document.createElement('span')
      const arrowStr = rel.invert ? '⇌' : '×'
      label.textContent = `${aLabel} ${arrowStr} ${bLabel}`
      label.title = `${rel.name} (ratio ${rel.ratio})`
      label.style.cssText = [
        'flex:1;font-size:var(--text-xs);overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
        `color:${broken ? '#f85149' : '#c9d1d9'}`,
      ].join(';')

      const ratioTag = document.createElement('span')
      ratioTag.textContent = `r=${Number(rel.ratio).toFixed(2)}`
      ratioTag.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0'

      const editBtn = document.createElement('button')
      editBtn.textContent = isEditing ? '▴' : '✎'
      editBtn.title = isEditing ? 'Collapse' : 'Edit gear relation'
      editBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        `color:${isEditing ? '#58a6ff' : '#6e7681'};font-size:11px;line-height:1`,
      ].join(';')
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation()
        _editingGearId = _editingGearId === rel.id ? null : rel.id
        _rebuildMates(store.getState().currentAssembly)
      })

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete gear relation'
      delBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px',
        'color:#6e7681;font-size:13px;line-height:1',
      ].join(';')
      delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        const ok = await showConfirm({
          title: 'Delete gear relation?',
          message: `${rel.name} (${aLabel} ${arrowStr} ${bLabel})`,
        })
        if (!ok) return
        try { await api.deleteGearRelation(rel.id) }
        catch (err) { console.error('[assembly] delete gear relation failed:', err) }
      })

      row.append(icon, label, ratioTag, editBtn, delBtn)
      wrapper.appendChild(row)

      if (isEditing) {
        const form = document.createElement('div')
        form.style.cssText = [
          'padding:6px 8px;margin-top:2px;background:#161b22',
          'border:1px solid #30363d;border-radius:4px',
          'display:flex;flex-direction:column;gap:5px',
        ].join(';')
        function _gearRow(text, inputEl) {
          const r = document.createElement('div')
          r.style.cssText = 'display:flex;align-items:center;gap:6px'
          const lbl = document.createElement('label')
          lbl.textContent = text
          lbl.style.cssText = 'font-size:var(--text-xs);color:#8b949e;width:58px;flex-shrink:0;text-align:right'
          r.append(lbl, inputEl)
          return r
        }
        function _gearNum(val, step) {
          const el = document.createElement('input')
          el.type  = 'number'; el.value = val; el.step = step
          el.style.cssText = [
            'flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #30363d',
            'border-radius:3px;font-size:var(--text-xs);padding:2px 4px',
          ].join(';')
          return el
        }
        const ratioIn = _gearNum(rel.ratio, 0.1)
        const invertIn = document.createElement('input')
        invertIn.type = 'checkbox'; invertIn.checked = !!rel.invert
        invertIn.style.cssText = 'cursor:pointer'
        const invertWrap = document.createElement('label')
        invertWrap.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1'
        const invertTxt = document.createElement('span')
        invertTxt.textContent = 'Reverse direction'
        invertTxt.style.cssText = 'font-size:var(--text-xs);color:#c9d1d9'
        invertWrap.append(invertIn, invertTxt)
        const invertRow = document.createElement('div')
        invertRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding-left:64px'
        invertRow.append(invertWrap)

        form.appendChild(_gearRow('Ratio', ratioIn))
        form.appendChild(invertRow)

        const btnRow = document.createElement('div')
        btnRow.style.cssText = 'display:flex;gap:4px;justify-content:flex-end;margin-top:2px'
        const cancelBtn = document.createElement('button')
        cancelBtn.textContent = 'Cancel'
        cancelBtn.style.cssText = [
          'background:none;border:1px solid #30363d;color:#8b949e',
          'border-radius:3px;font-size:var(--text-xs);padding:2px 8px;cursor:pointer',
        ].join(';')
        cancelBtn.addEventListener('click', () => { _editingGearId = null; _rebuildMates(store.getState().currentAssembly) })
        const saveBtn = document.createElement('button')
        saveBtn.textContent = 'Save'
        saveBtn.style.cssText = [
          'background:#1f3d2a;border:1px solid #3fb950;color:#3fb950',
          'border-radius:3px;font-size:var(--text-xs);padding:2px 8px;cursor:pointer',
        ].join(';')
        saveBtn.addEventListener('click', async () => {
          const patches = {}
          const newRatio = parseFloat(ratioIn.value)
          if (Number.isFinite(newRatio) && newRatio !== rel.ratio) patches.ratio = newRatio
          if (invertIn.checked !== !!rel.invert) patches.invert = invertIn.checked
          if (Object.keys(patches).length === 0) { _editingGearId = null; _rebuildMates(store.getState().currentAssembly); return }
          saveBtn.disabled = true
          try { await api.patchGearRelation(rel.id, patches) }
          finally { _editingGearId = null }
        })
        btnRow.append(cancelBtn, saveBtn)
        form.appendChild(btnRow)
        editFormHostEl.appendChild(form)
      }

      listEl.appendChild(wrapper)
    }

    _matesSectionEl.append(header, listEl, editFormHostEl)

    // ── Belt paths — own sub-section below Mates ────────────────────────────
    const beltPaths = assembly?.belt_paths ?? []
    if (beltPaths.length) {
      const beltHeader = document.createElement('div')
      beltHeader.style.cssText = [
        'font-size:var(--text-xs);font-weight:600;color:#8b949e',
        'padding:4px 0 2px;margin-top:6px;border-top:1px solid #21262d',
      ].join(';')
      beltHeader.textContent = `Belt Paths (${beltPaths.length})`

      const beltList = document.createElement('div')
      beltList.style.cssText = 'display:flex;flex-direction:column;gap:2px;padding:0 2px 2px 0'

      function _pulleyLabel(pulley) {
        const id = pulley?.instance_id
        if (!id) return '?'
        const groupLabel = _groupLabelForInstance(id)
        if (groupLabel) return groupLabel
        const inst = instances.find(i => i.id === id)
        return inst?.name ?? id.slice(0, 6)
      }

      for (const belt of beltPaths) {
        const aLabel = _pulleyLabel(belt.pulley_a)
        const bLabel = _pulleyLabel(belt.pulley_b)
        const row = document.createElement('div')
        row.style.cssText = [
          'display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:3px',
          'border-left:2px solid #3fb950;padding-left:6px',
        ].join(';')

        const hidden = isBeltHidden?.(belt.id) ?? false

        const eyeBtn = document.createElement('button')
        eyeBtn.textContent = hidden ? '○' : '◉'
        eyeBtn.title = hidden ? 'Show belt path' : 'Hide belt path'
        eyeBtn.style.cssText = `background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px;font-size:11px;line-height:1;color:${hidden ? '#484f58' : '#3fb950'}`
        eyeBtn.addEventListener('click', (e) => { e.stopPropagation(); onToggleBeltVisibility?.(belt.id) })

        const icon = document.createElement('span')
        icon.textContent = '⟳'
        icon.title = 'Belt path'
        icon.style.cssText = 'font-size:var(--text-xs);color:#3fb950;flex-shrink:0'

        const label = document.createElement('span')
        label.textContent = `${aLabel} ⟿ ${bLabel}`
        label.title = belt.name
        label.style.cssText = `flex:1;font-size:var(--text-xs);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:${hidden ? '#6e7681' : '#c9d1d9'}`

        const attachBtn = document.createElement('button')
        attachBtn.textContent = '⊕'
        attachBtn.title = 'Attach a part to this belt'
        attachBtn.style.cssText = 'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px;color:#6e7681;font-size:13px;line-height:1'
        attachBtn.addEventListener('pointerenter', () => { attachBtn.style.color = '#3fb950' })
        attachBtn.addEventListener('pointerleave', () => { attachBtn.style.color = '#6e7681' })
        attachBtn.addEventListener('click', (e) => { e.stopPropagation(); onAttachToBelt?.(belt.id) })

        const editBtn = document.createElement('button')
        editBtn.textContent = '✎'
        editBtn.title = 'Edit belt path'
        editBtn.style.cssText = 'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px;color:#6e7681;font-size:11px;line-height:1'
        editBtn.addEventListener('pointerenter', () => { editBtn.style.color = '#58a6ff' })
        editBtn.addEventListener('pointerleave', () => { editBtn.style.color = '#6e7681' })
        editBtn.addEventListener('click', (e) => { e.stopPropagation(); onEditBeltPath?.(belt) })

        const delBtn = document.createElement('button')
        delBtn.textContent = '×'
        delBtn.title = 'Delete belt path'
        delBtn.style.cssText = 'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px;color:#6e7681;font-size:13px;line-height:1'
        delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
        delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation()
          const ok = await showConfirm({
            title: 'Delete belt path?',
            message: `${belt.name} (${aLabel} ⟿ ${bLabel})`,
          })
          if (!ok) return
          try { await api.deleteBeltPath(belt.id) }
          catch (err) { console.error('[assembly] delete belt path failed:', err) }
        })

        row.append(eyeBtn, icon, label, attachBtn, editBtn, delBtn)
        beltList.appendChild(row)

        // ── Collapsible "Parts on path" sub-list (belt riders) ──────────────
        const riders = (assembly?.belt_riders ?? []).filter(r => r.belt_path_id === belt.id)
        const expanded = _beltRidersExpanded.has(belt.id)
        const subHeader = document.createElement('div')
        subHeader.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;padding:1px 0 1px 18px;font-size:var(--text-xs);color:#6e7681'
        subHeader.textContent = `${expanded ? '▾' : '▸'} Parts on path (${riders.length})`
        subHeader.addEventListener('click', (e) => {
          e.stopPropagation()
          if (_beltRidersExpanded.has(belt.id)) _beltRidersExpanded.delete(belt.id)
          else _beltRidersExpanded.add(belt.id)
          _rebuildMates(store.getState().currentAssembly)
        })
        beltList.appendChild(subHeader)

        if (expanded) {
          if (!riders.length) {
            const empty = document.createElement('div')
            empty.textContent = 'No parts attached'
            empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:1px 0 1px 30px'
            beltList.appendChild(empty)
          }
          for (const rider of riders) {
            const inst = instances.find(i => i.id === rider.instance_id)
            const rRow = document.createElement('div')
            rRow.style.cssText = 'display:flex;align-items:center;gap:4px;padding:1px 4px 1px 30px'
            const rLabel = document.createElement('span')
            rLabel.textContent = `${inst?.name ?? rider.instance_id.slice(0, 6)} · ${Math.round((rider.arc_param ?? 0) * 100)}%`
            rLabel.style.cssText = 'flex:1;font-size:var(--text-xs);color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
            const rDel = document.createElement('button')
            rDel.textContent = '×'
            rDel.title = 'Detach part from belt'
            rDel.style.cssText = 'background:none;border:none;cursor:pointer;flex-shrink:0;padding:0 2px;color:#6e7681;font-size:12px;line-height:1'
            rDel.addEventListener('pointerenter', () => { rDel.style.color = '#f85149' })
            rDel.addEventListener('pointerleave', () => { rDel.style.color = '#6e7681' })
            rDel.addEventListener('click', async (e) => {
              e.stopPropagation()
              try { await onDeleteBeltRider?.(rider.id) }
              catch (err) { console.error('[assembly] detach belt rider failed:', err) }
            })
            rRow.append(rLabel, rDel)
            beltList.appendChild(rRow)
          }
        }
      }
      _matesSectionEl.append(beltHeader, beltList)
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────────

  function _rebuild(state) {
    if (_collapsed) return
    _syncActionButtons(state)
    const assemblyChanged = state.currentAssembly !== _lastAssemblyRef
    _lastAssemblyRef = state.currentAssembly
    if (nameEl) {
      const asmName = state.currentAssembly?.metadata?.name
      nameEl.textContent = asmName ? asmName : ''
    }
    _rebuildInstances(state.currentAssembly, state.activeInstanceId)
    _editingJointId = null
    _solveStatus    = {}
    // Keep the mate highlight alive across rebuilds as long as the joint
    // still exists — but re-fetch its connector frames so the markers
    // follow any instance-transform changes (e.g. after Resolve).
    if (_highlightedJointId) {
      const stillExists = (state.currentAssembly?.joints ?? []).some(j => j.id === _highlightedJointId)
      if (!stillExists) {
        _highlightedJointId = null
        onMateHighlightClear?.()
      } else {
        api.getJointConnectorFrames(_highlightedJointId)
          .then(frames => { if (_highlightedJointId) onMateHighlight?.(frames) })
          .catch(() => {})
      }
    }
    if (_debugJointId) {
      const stillExists = (state.currentAssembly?.joints ?? []).some(j => j.id === _debugJointId)
      if (!stillExists) {
        _debugJointId = null
        onMateDebugMarkers?.(null)
      } else {
        api.getJointDebugFrames(_debugJointId)
          .then(d => {
            if (_debugJointId) {
              onMateDebugMarkers?.(d)
              _debugDataByJoint[_debugJointId] = d
            }
          })
          .catch(() => {})
      }
    }
    _rebuildMates(state.currentAssembly)

    // Part context — notify sidebar panels when the selected instance changes
    const prevPartId = _partLastRebuildId
    _partLastRebuildId = state.activeInstanceId
    if (state.activeInstanceId !== prevPartId || assemblyChanged) {
      _onPartInstanceChanged(state.activeInstanceId, { force: assemblyChanged })
    }
  }

  function show() {
    if (panelEl) panelEl.style.display = ''
    _syncActionButtons()
  }

  function hide() {
    if (panelEl) panelEl.style.display = 'none'
    _syncActionButtons()
  }

  store.subscribeSlice('assembly', (newState) => {
    if (!panelEl || panelEl.style.display === 'none') return
    _rebuild(newState)
  })

  /** Push solve_status from an external source (e.g. auto-resolve during a
   *  feature-log seek) so the Mates panel reflects which joints just had to
   *  be re-snapped, without needing a separate Resolve click. */
  function applySolveStatus(solveStatus) {
    if (!solveStatus) return
    _solveStatus = solveStatus
    _rebuildMates(store.getState().currentAssembly)
  }
  return { show, hide, rebuild: _rebuild, openPicker: _openLibraryPicker, applySolveStatus }
}
