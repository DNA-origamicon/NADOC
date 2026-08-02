/**
 * Cluster panel — sidebar list of named cluster rigid transforms.
 *
 * Displays all design.cluster_transforms. Click a cluster row to activate
 * the 3D gizmo (or deactivate if already active). Delete button removes the
 * cluster from the design. "New Cluster from Selection" creates a cluster
 * from the current multiSelectedStrandIds.
 *
 * Joint placement and move/rotate transform controls now live in their own
 * dedicated panels (joints_panel.js and the right-sidebar move-rotate-panel).
 *
 * @param {object} store
 * @param {object} opts
 * @param {function} opts.onClusterClick    — called with (clusterId, {additive}) when user clicks a row
 * @param {object}  opts.api               — api module for createCluster / deleteCluster
 * @param {function} [opts.onVisibilityChange] — called with Set<clusterId> of hidden clusters
 * @param {function} [opts.onStylePreview] — called with (clusterId, {color?, opacity?}) while
 *   the style popover's controls are dragged; renderer-only, no persistence.
 */
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { initClusterStylePopover } from './cluster_style_popover.js'
import { STAPLE_PALETTE } from '../scene/helix_renderer/palette.js'

/** The auto palette slot a cluster gets when it has no explicit colour — the same
 *  index-mod-12 rule the 3D cluster coloring uses, so the swatch agrees with it. */
function _paletteHex(index) {
  const c = STAPLE_PALETTE[index % STAPLE_PALETTE.length]
  return '#' + c.toString(16).padStart(6, '0')
}

export function initClusterPanel(store, { onClusterClick, onAssemblyClusterClick = null, api, onVisibilityChange = null, onStylePreview = null }) {
  const listEl   = document.getElementById('cluster-list')
  const newBtn   = document.getElementById('cluster-new-btn')
  const heading  = document.getElementById('cluster-panel-heading')
  const arrow    = document.getElementById('cluster-panel-arrow')
  const body     = document.getElementById('cluster-panel-body')
  if (!listEl || !newBtn || !heading) return {}

  // ── Cluster visibility state ──────────────────────────────────────────────────
  const _hiddenClusterIds = new Set()

  function _notifyVisibility() {
    onVisibilityChange?.(_hiddenClusterIds)
  }

  // ── Cluster colour + opacity ────────────────────────────────────────────────
  // One shared popover in document.body, reused across rows (the list is rebuilt
  // wholesale on every design change, so it cannot live inside a row).
  // Commit is the no-commit PATCH form, exactly like the rename below: a cosmetic
  // edit must not land on the undo stack.
  const _stylePopover = initClusterStylePopover({
    onPreview: (id, patch, uiState) => onStylePreview?.(id, patch, uiState),
    onCommit:  (id, patch) => api.patchCluster(id, patch),
  })

  let _collapsed = getSectionCollapsed('dynamics', 'cluster-panel', false)

  // Apply persisted collapse state to DOM.
  body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)

  // ── Collapse / expand ────────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'cluster-panel', _collapsed)
  })

  // ── Enable / disable new-cluster button ──────────────────────────────────────
  function _syncNewBtn(state) {
    newBtn.disabled = _assemblyMode ||
      (!state.multiSelectedStrandIds?.length && !state.multiSelectedDomainIds?.length)
  }

  store.subscribe((n, p) => {
    if (n.multiSelectedStrandIds !== p.multiSelectedStrandIds ||
        n.multiSelectedDomainIds  !== p.multiSelectedDomainIds) {
      _syncNewBtn(n)
    }
  })

  // ── New cluster from selection ────────────────────────────────────────────────
  newBtn.addEventListener('click', async () => {
    const { multiSelectedStrandIds, multiSelectedDomainIds, currentDesign } = store.getState()
    if (!currentDesign) return
    const n = (currentDesign.cluster_transforms?.length ?? 0) + 1

    if (multiSelectedDomainIds?.length) {
      // Domain-level cluster: transform only the selected domains
      const domainIds = multiSelectedDomainIds.map(d => ({ strand_id: d.strandId, domain_index: d.domainIndex }))
      const helixIds  = _helixIdsFromDomainIds(domainIds, currentDesign)
      if (!helixIds.length) return
      await api.createCluster({ name: `Cluster ${n}`, helix_ids: helixIds, domain_ids: domainIds })
    } else if (multiSelectedStrandIds?.length) {
      const helixIds = _helixIdsFromStrandIds(multiSelectedStrandIds, currentDesign)
      if (!helixIds.length) return
      await api.createCluster({ name: `Cluster ${n}`, helix_ids: helixIds })
    }
  })

  // ── Rebuild list when design or active cluster changes ───────────────────────
  store.subscribe((n, p) => {
    if (n.currentDesign === p.currentDesign && n.activeClusterId === p.activeClusterId &&
        n.multiSelectedClusterIds === p.multiSelectedClusterIds) return
    if (_assemblyMode) return
    if (!_collapsed) _rebuild(n.currentDesign?.cluster_transforms ?? [], n.activeClusterId)
  })

  // ── Assembly mode state ───────────────────────────────────────────────────────
  let _assemblyMode    = false
  let _instanceOrder   = []
  const _instanceNames      = new Map()
  const _instanceDesigns    = new Map()
  const _expandedInstances  = new Map()  // instanceId → boolean

  // Active cluster selection in assembly mode
  let _activeAsmInstId    = null
  let _activeAsmClusterId = null

  function _rebuild(clusters, activeId) {
    if (_assemblyMode) { _rebuildAssembly(); return }
    _rebuildFlat(clusters, activeId)
  }

  /** A row is lit for the single active cluster OR any cluster in the multi-selection
   *  (Ctrl+click / lasso at cluster level — the two are mutually exclusive states). */
  function _isSelected(clusterId) {
    const s = store.getState()
    return clusterId === s.activeClusterId ||
      (s.multiSelectedClusterIds ?? []).includes(clusterId)
  }

  function _rebuildFlat(clusters, activeId) {
    listEl.innerHTML = ''

    if (!clusters.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'Lasso-select strands or domains, then click the button below.'
      listEl.appendChild(empty)
      return
    }

    for (const [clusterIndex, cluster] of clusters.entries()) {
      const isActive = _isSelected(cluster.id)

      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px;padding:5px 6px',
        'border-radius:4px;cursor:pointer',
        `background:${isActive ? '#1c3a2a' : 'transparent'}`,
        'transition:background 0.1s',
      ].join(';')

      // Hover highlight
      row.addEventListener('mouseenter', () => {
        if (!_isSelected(cluster.id)) row.style.background = '#161b22'
      })
      row.addEventListener('mouseleave', () => {
        row.style.background = _isSelected(cluster.id) ? '#1c3a2a' : 'transparent'
      })

      // Selected-cluster indicator dot — green, matching the 3D selection glow.
      const dot = document.createElement('span')
      dot.style.cssText = `
        width:8px;height:8px;border-radius:50%;flex-shrink:0;
        background:${isActive ? '#3fb950' : '#3a4a5a'};
        transition:background 0.15s;
      `
      dot.title = isActive ? 'Selected — click to deselect' : 'Click to select (Ctrl+click to add)'

      const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
      const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
      const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'

      // Name label + inline edit toggle
      const nameSpan = document.createElement('span')
      nameSpan.textContent = cluster.name
      nameSpan.style.cssText = 'flex:1;min-width:0;font-size:11px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

      // Edit / Save button — use only onclick (never addEventListener) so exactly
      // one handler is active at a time and there's no stale-listener accumulation.
      const editBtn = document.createElement('button')
      editBtn.textContent = '✎'
      editBtn.title = 'Rename cluster'
      editBtn.style.cssText = _editStyle
      editBtn.addEventListener('pointerenter', () => {
        editBtn.style.background = editBtn.textContent === '✓' ? '#1f3d2a' : '#2d333b'
        editBtn.style.color      = editBtn.textContent === '✓' ? '#57d05a' : '#c9d1d9'
      })
      editBtn.addEventListener('pointerleave', () => {
        editBtn.style.cssText = editBtn.textContent === '✓' ? _saveStyle : _editStyle
      })

      function _enterEdit(e) {
        e.stopPropagation()
        const nameInput = document.createElement('input')
        nameInput.type = 'text'
        nameInput.value = cluster.name
        nameInput.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;' +
          'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
          'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'
        nameSpan.replaceWith(nameInput)
        nameInput.focus(); nameInput.select()
        editBtn.textContent = '✓'
        editBtn.title = 'Save name'
        editBtn.style.cssText = _saveStyle

        async function _save() {
          const newName = nameInput.value.trim() || cluster.name
          nameInput.replaceWith(nameSpan)
          nameSpan.textContent = newName
          editBtn.textContent = '✎'
          editBtn.title = 'Rename cluster'
          editBtn.style.cssText = _editStyle
          editBtn.onclick = _enterEdit
          if (newName !== cluster.name) await api.patchCluster(cluster.id, { name: newName })
        }
        nameInput.addEventListener('keydown', e2 => {
          e2.stopPropagation()
          if (e2.key === 'Enter')  { e2.preventDefault(); _save() }
          if (e2.key === 'Escape') {
            nameInput.replaceWith(nameSpan)
            editBtn.textContent = '✎'
            editBtn.title = 'Rename cluster'
            editBtn.style.cssText = _editStyle
            editBtn.onclick = _enterEdit
          }
        })
        editBtn.onclick = e2 => { e2.stopPropagation(); _save() }
      }
      editBtn.onclick = _enterEdit

      // Count badge — domains if domain cluster, helices otherwise; ◆ if default
      const badge = document.createElement('span')
      badge.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
      const countStr = cluster.domain_ids?.length
        ? `${cluster.domain_ids.length}d`
        : `${cluster.helix_ids.length}h`
      badge.textContent = cluster.is_default ? `◆ ${countStr}` : countStr
      if (cluster.is_default) badge.title = 'Auto-created default cluster'

      // Duplex tag — clusters that carry an overhang duplex (made from a connection).
      // Rotation-point dropdown (root/centroid) lives on the Move/Rotate panel.
      let duplexTag = null
      if (cluster.overhang_duplex_driver_id) {
        duplexTag = document.createElement('span')
        duplexTag.textContent = '⛓'
        duplexTag.title = 'Overhang-duplex cluster — pick a rotation point in Move/Rotate'
        duplexTag.style.cssText = 'font-size:var(--text-xs);color:#57d0b0;flex-shrink:0'
      }

      // Colour + opacity swatch → the style popover. The swatch shows this
      // cluster's OWN colour (its explicit one, else its auto palette slot) and
      // dims to advertise a fade, so the list reads at a glance.
      const swatchBtn = document.createElement('button')
      const swatchHex = cluster.color ?? _paletteHex(clusterIndex)
      const swatchOpacity = typeof cluster.opacity === 'number' ? cluster.opacity : 1
      swatchBtn.style.cssText = _editStyle +
        ';border-color:#30363d;width:18px;padding:3px 0'
      // Set the colour as its OWN property rather than a second `background` shorthand
      // in the cssText above — a duplicate declaration only works by last-one-wins and
      // is invisible to anything reading backgroundColor.
      swatchBtn.style.backgroundColor = swatchHex
      swatchBtn.style.opacity = String(Math.max(0.25, swatchOpacity))
      swatchBtn.title = swatchOpacity < 1
        ? `Colour & opacity — ${Math.round(swatchOpacity * 100)}%`
        : 'Colour & opacity'
      swatchBtn.addEventListener('click', e => {
        // The row's own click handler would otherwise toggle cluster selection
        // every time the swatch is opened.
        e.stopPropagation()
        if (_stylePopover.isOpenFor(cluster.id)) {
          _stylePopover.close()
        } else {
          _stylePopover.openFor(cluster.id, swatchBtn,
            { color: cluster.color ?? null, opacity: swatchOpacity })
        }
      })

      // Visibility toggle button
      const isHidden = _hiddenClusterIds.has(cluster.id)
      const _visOnStyle  = 'background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
      const _visOffStyle = 'background:#161b22;border:1px solid #30363d;color:#484f58;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
      const visBtn = document.createElement('button')
      visBtn.textContent = '◉'
      visBtn.title = isHidden ? 'Show cluster' : 'Hide cluster'
      visBtn.style.cssText = isHidden ? _visOffStyle : _visOnStyle
      visBtn.addEventListener('click', e => {
        e.stopPropagation()
        if (_hiddenClusterIds.has(cluster.id)) {
          _hiddenClusterIds.delete(cluster.id)
          visBtn.title = 'Hide cluster'
          visBtn.style.cssText = _visOnStyle
        } else {
          _hiddenClusterIds.add(cluster.id)
          visBtn.title = 'Show cluster'
          visBtn.style.cssText = _visOffStyle
        }
        _notifyVisibility()
      })

      // Delete button
      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.style.cssText = _delStyle
      delBtn.title = 'Delete cluster'
      delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        _hiddenClusterIds.delete(cluster.id)
        await api.deleteCluster(cluster.id)
      })

      // Row click → notify parent. Ctrl/Cmd/Shift+click = additive multi-select, the
      // same modifier set the 3D canvas uses.
      row.addEventListener('click', e => {
        onClusterClick(cluster.id, { additive: e.ctrlKey || e.metaKey || e.shiftKey })
      })

      row.append(dot, nameSpan, ...(duplexTag ? [duplexTag] : []), badge, swatchBtn, visBtn, editBtn, delBtn)
      listEl.appendChild(row)
    }
    // The list was just rebuilt from scratch, so an open popover's anchor button is
    // gone. It lives in document.body and is keyed by id, so it survives — unless
    // its cluster was deleted or reshuffled away.
    _stylePopover.closeIfMissing(new Set(clusters.map(c => c.id)))
  }

  // ── Assembly mode rendering ───────────────────────────────────────────────────

  function _rebuildAssembly() {
    listEl.innerHTML = ''

    if (!_instanceOrder.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'No parts in assembly.'
      listEl.appendChild(empty)
      return
    }

    for (const instanceId of _instanceOrder) {
      const partName = _instanceNames.get(instanceId) ?? instanceId
      const design   = _instanceDesigns.get(instanceId)
      const clusters = (design?.cluster_transforms ?? []).filter(c => !c.is_default)

      const sectionEl = document.createElement('div')
      sectionEl.style.cssText = 'margin-bottom:2px'

      // Part header row
      const headerRow = document.createElement('div')
      headerRow.style.cssText = [
        'display:flex;align-items:center;gap:4px;cursor:pointer',
        'padding:3px 4px;border-radius:3px',
      ].join(';')
      headerRow.addEventListener('mouseenter', () => { headerRow.style.background = '#161b22' })
      headerRow.addEventListener('mouseleave', () => { headerRow.style.background = '' })

      const arrowSpan = document.createElement('span')
      arrowSpan.textContent = '▶'
      arrowSpan.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0;width:8px'

      const nameSpan = document.createElement('span')
      nameSpan.textContent = partName
      nameSpan.style.cssText = [
        'flex:1;font-size:11px;color:#8b949e',
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
      ].join(';')

      const countBadge = document.createElement('span')
      countBadge.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
      countBadge.textContent = design ? `${clusters.length}` : '…'

      headerRow.append(arrowSpan, nameSpan, countBadge)

      // Cluster list — expand state persisted in _expandedInstances map
      const _isExpanded = _expandedInstances.get(instanceId) ?? false
      const clusterListEl = document.createElement('div')
      clusterListEl.style.cssText = `display:${_isExpanded ? '' : 'none'};max-height:88px;overflow-y:auto;padding-left:10px`
      arrowSpan.textContent = _isExpanded ? '▼' : '▶'

      headerRow.addEventListener('click', () => {
        const expanded = !(_expandedInstances.get(instanceId) ?? false)
        _expandedInstances.set(instanceId, expanded)
        clusterListEl.style.display = expanded ? '' : 'none'
        arrowSpan.textContent = expanded ? '▼' : '▶'
      })

      if (!design) {
        const loadingEl = document.createElement('div')
        loadingEl.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:3px 2px'
        loadingEl.textContent = 'Loading…'
        clusterListEl.appendChild(loadingEl)
      } else if (!clusters.length) {
        const noneEl = document.createElement('div')
        noneEl.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:3px 2px'
        noneEl.textContent = 'No clusters'
        clusterListEl.appendChild(noneEl)
      } else {
        for (const cluster of clusters) {
          const isActive = _activeAsmInstId === instanceId && _activeAsmClusterId === cluster.id

          const row = document.createElement('div')
          row.style.cssText = [
            'display:flex;align-items:center;gap:5px',
            'padding:3px 4px;border-radius:3px;cursor:pointer',
            isActive ? 'background:#0d2137' : '',
          ].filter(Boolean).join(';')
          row.addEventListener('mouseenter', () => { row.style.background = '#161b22' })
          row.addEventListener('mouseleave', () => {
            row.style.background = (_activeAsmInstId === instanceId && _activeAsmClusterId === cluster.id)
              ? '#0d2137' : ''
          })
          row.addEventListener('click', () => {
            const selecting = !(_activeAsmInstId === instanceId && _activeAsmClusterId === cluster.id)
            _activeAsmInstId    = selecting ? instanceId  : null
            _activeAsmClusterId = selecting ? cluster.id  : null
            _rebuildAssembly()
            onAssemblyClusterClick?.(selecting ? instanceId : null, selecting ? cluster.id : null)
          })

          const dot = document.createElement('span')
          dot.style.cssText = `width:6px;height:6px;border-radius:50%;flex-shrink:0;background:${isActive ? '#58a6ff' : '#3a4a5a'}`

          const rowName = document.createElement('span')
          rowName.textContent = cluster.name
          rowName.style.cssText = [
            'flex:1;font-size:var(--text-xs);color:#c9d1d9',
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
          ].join(';')

          const rowBadge = document.createElement('span')
          rowBadge.style.cssText = 'font-size:var(--text-xs);color:#484f58;flex-shrink:0'
          rowBadge.textContent = cluster.domain_ids?.length
            ? `${cluster.domain_ids.length}d`
            : `${cluster.helix_ids.length}h`

          row.append(dot, rowName, rowBadge)
          clusterListEl.appendChild(row)
        }
      }

      sectionEl.append(headerRow, clusterListEl)
      listEl.appendChild(sectionEl)
    }
  }

  // ── Exported assembly methods ─────────────────────────────────────────────────

  function setAssemblyMode(instances) {
    _assemblyMode = true
    _stylePopover.close()   // the assembly list has no swatches
    _instanceOrder.length = 0
    _instanceNames.clear()
    _instanceDesigns.clear()
    for (const inst of instances) {
      _instanceOrder.push(inst.id)
      _instanceNames.set(inst.id, inst.name)
    }
    newBtn.disabled = true
    if (!_collapsed) _rebuildAssembly()
    // Fetch each unique SOURCE's design once and share it across every instance
    // of that source — same-source instances have an identical cluster list, so
    // the panel only needs one fetch per part. Fetching per-instance fired O(N)
    // `GET /assembly/instances/{id}/design` requests (~480ms each), which on the
    // single-worker backend WAS the assembly-load O(N) cold-open at scale
    // (~43 s for 500 instances). See path_to_thousands LOD benchmark.
    const _srcKey = inst =>
      inst.source?.type === 'file'
        ? `file:${inst.source.path ?? ''}`
        : `inline:${inst.source?.design?.id ?? ''}`
    const _bySource = new Map()   // srcKey → instanceId[]
    for (const inst of instances) {
      const k = _srcKey(inst)
      if (!_bySource.has(k)) _bySource.set(k, [])
      _bySource.get(k).push(inst.id)
    }
    for (const ids of _bySource.values()) {
      api.getInstanceDesign(ids[0]).then(result => {
        if (!_assemblyMode) return
        if (result?.design) {
          for (const id of ids) _instanceDesigns.set(id, result.design)
          if (!_collapsed) _rebuildAssembly()
        }
      }).catch(() => {})
    }
  }

  function clearAssemblyMode() {
    _assemblyMode = false
    _stylePopover.close()
    _instanceOrder.length = 0
    _instanceNames.clear()
    _instanceDesigns.clear()
    _expandedInstances.clear()
    if (_activeAsmInstId !== null) {
      _activeAsmInstId    = null
      _activeAsmClusterId = null
      onAssemblyClusterClick?.(null, null)
    }
    _syncNewBtn(store.getState())
    if (!_collapsed) {
      const { currentDesign, activeClusterId } = store.getState()
      _rebuildFlat(currentDesign?.cluster_transforms ?? [], activeClusterId)
    }
  }

  function syncInstanceDesign(instanceId, design) {
    if (!_assemblyMode) return
    _instanceDesigns.set(instanceId, design)
    if (!_collapsed) _rebuildAssembly()
  }

  /** Programmatically expand the cluster list for a given instance. */
  function expandInstance(instanceId) {
    if (!_assemblyMode || !instanceId) return
    _expandedInstances.set(instanceId, true)
    if (!_collapsed) _rebuildAssembly()
  }

  /** Set the active cluster highlight in the sidebar without firing the click callback. */
  function selectAssemblyCluster(instanceId, clusterId) {
    if (!_assemblyMode) return
    _activeAsmInstId    = instanceId ?? null
    _activeAsmClusterId = clusterId  ?? null
    if (!_collapsed) _rebuildAssembly()
  }

  return {
    setAssemblyMode, clearAssemblyMode, syncInstanceDesign, expandInstance, selectAssemblyCluster,
    /** Tear down the style popover's document-level listeners (smoke-test gate). */
    destroy: _stylePopover.destroy,
  }
}

/**
 * Derive the deduplicated set of helix IDs touched by the given strand IDs.
 * Exported so selection_manager.js can reuse it.
 */
export function helixIdsFromStrandIds(strandIds, design) {
  const strandSet = new Set(strandIds)
  const helixSet  = new Set()
  for (const strand of design.strands ?? []) {
    if (!strandSet.has(strand.id)) continue
    for (const domain of strand.domains ?? []) helixSet.add(domain.helix_id)
  }
  return [...helixSet]
}

// Private alias for internal use
function _helixIdsFromStrandIds(strandIds, design) {
  return helixIdsFromStrandIds(strandIds, design)
}

/**
 * Derive the deduplicated set of helix IDs touched by the given domain refs.
 * domainIds: Array of { strand_id, domain_index }
 */
function _helixIdsFromDomainIds(domainIds, design) {
  const helixSet = new Set()
  for (const { strand_id, domain_index } of domainIds) {
    const strand = design.strands?.find(s => s.id === strand_id)
    const domain = strand?.domains?.[domain_index]
    if (domain?.helix_id) helixSet.add(domain.helix_id)
  }
  return [...helixSet]
}
