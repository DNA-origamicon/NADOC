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
 * @param {function} opts.onClusterClick    — called with (clusterId) when user clicks a row
 * @param {object}  opts.api               — api module for createCluster / deleteCluster
 * @param {function} [opts.onVisibilityChange] — called with Set<clusterId> of hidden clusters
 */
export function initClusterPanel(store, { onClusterClick, api, onVisibilityChange = null }) {
  const listEl   = document.getElementById('cluster-list')
  const newBtn   = document.getElementById('cluster-new-btn')
  const heading  = document.getElementById('cluster-panel-heading')
  const arrow    = document.getElementById('cluster-panel-arrow')
  const body     = document.getElementById('cluster-panel-body')
  if (!listEl || !newBtn || !heading) return

  // ── Cluster visibility state ──────────────────────────────────────────────────
  const _hiddenClusterIds = new Set()

  function _notifyVisibility() {
    onVisibilityChange?.(_hiddenClusterIds)
  }

  let _collapsed = false

  // ── Collapse / expand ────────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── Enable / disable new-cluster button ──────────────────────────────────────
  function _syncNewBtn(state) {
    newBtn.disabled = !state.multiSelectedStrandIds?.length && !state.multiSelectedDomainIds?.length
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
    if (n.currentDesign === p.currentDesign && n.activeClusterId === p.activeClusterId) return
    if (!_collapsed) _rebuild(n.currentDesign?.cluster_transforms ?? [], n.activeClusterId)
  })

  function _rebuild(clusters, activeId, _design) {
    listEl.innerHTML = ''

    if (!clusters.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'Lasso-select strands or domains, then click the button below.'
      listEl.appendChild(empty)
      return
    }

    for (const cluster of clusters) {
      const isActive = cluster.id === activeId

      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px;padding:5px 6px',
        'border-radius:4px;cursor:pointer',
        `background:${isActive ? '#1e3a5f' : 'transparent'}`,
        'transition:background 0.1s',
      ].join(';')

      // Hover highlight
      row.addEventListener('mouseenter', () => {
        if (cluster.id !== store.getState().activeClusterId) {
          row.style.background = '#161b22'
        }
      })
      row.addEventListener('mouseleave', () => {
        row.style.background = cluster.id === store.getState().activeClusterId
          ? '#1e3a5f' : 'transparent'
      })

      // Gizmo indicator dot
      const dot = document.createElement('span')
      dot.style.cssText = `
        width:8px;height:8px;border-radius:50%;flex-shrink:0;
        background:${isActive ? '#58a6ff' : '#3a4a5a'};
        transition:background 0.15s;
      `
      dot.title = isActive ? 'Selected — click to deselect' : 'Click to select'

      const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
      const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
      const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'

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
          'color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px;'
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
      badge.style.cssText = 'font-size:9px;color:#484f58;flex-shrink:0'
      const countStr = cluster.domain_ids?.length
        ? `${cluster.domain_ids.length}d`
        : `${cluster.helix_ids.length}h`
      badge.textContent = cluster.is_default ? `◆ ${countStr}` : countStr
      if (cluster.is_default) badge.title = 'Auto-created default cluster'

      // Visibility toggle button
      const isHidden = _hiddenClusterIds.has(cluster.id)
      const _visOnStyle  = 'background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
      const _visOffStyle = 'background:#161b22;border:1px solid #30363d;color:#484f58;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
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

      // Row click → notify parent
      row.addEventListener('click', () => {
        onClusterClick(cluster.id)
      })

      row.append(dot, nameSpan, badge, visBtn, editBtn, delBtn)
      listEl.appendChild(row)
    }
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
