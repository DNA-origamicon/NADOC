/**
 * Cluster panel — sidebar list of named cluster rigid transforms.
 *
 * Displays all design.cluster_transforms. Click a cluster row to activate
 * the 3D gizmo (or deactivate if already active). Delete button removes the
 * cluster from the design. "New Cluster from Selection" creates a cluster
 * from the current multiSelectedStrandIds.
 *
 * Joint section: each cluster can have a revolute joint defined on it. The
 * joint section shows below the cluster row (when that cluster is active) and
 * provides a "Place" button that enters surface-define mode in the 3D scene.
 * Two surface toggles are provided: "Hull surface" (convex hull prism) and
 * "Exterior panels" (lattice-aware panels), used while placing the joint.
 *
 * @param {object} store
 * @param {object} opts
 * @param {function} opts.onClusterClick       — called with (clusterId) when user clicks a row
 * @param {object}  opts.api                   — api module for createCluster / deleteCluster
 * @param {object}  [opts.jointRenderer]       — joint_renderer instance (enterDefineMode, etc.)
 * @param {function} [opts.onJointHighlight]   — called with (jointId|null) on joint row hover
 */
export function initClusterPanel(store, { onClusterClick, api, onTransformEdit = null, onJointAngleEdit = null, onVisibilityChange = null, jointRenderer = null, onJointHighlight = null, onPivotSelect = null }) {
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

  // ── Transform editor (shown when translate/rotate tool is active) ─────────────
  const _tfPanel = document.createElement('div')
  _tfPanel.style.cssText = 'display:none;padding:6px 0 2px'

  function _tfRow(label, axis) {
    const row = document.createElement('div')
    row.style.cssText = 'display:flex;align-items:center;gap:4px;margin-bottom:3px'
    const lbl = document.createElement('span')
    lbl.textContent = label
    lbl.style.cssText = 'font-size:10px;color:#6e7681;width:18px;flex-shrink:0;text-align:right'
    const inp = document.createElement('input')
    inp.type = 'number'
    inp.step = '0.1'
    inp.style.cssText = [
      'flex:1;min-width:0;box-sizing:border-box',
      'background:#0d1117;border:1px solid #30363d;border-radius:3px',
      'color:#c9d1d9;padding:2px 4px;font-family:monospace;font-size:10px',
    ].join(';')
    inp.dataset.axis = axis
    row.append(lbl, inp)
    return { row, inp }
  }

  const _tfSect = (title) => {
    const hdr = document.createElement('div')
    hdr.textContent = title
    hdr.style.cssText = 'font-size:9px;color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px;margin-top:4px'
    return hdr
  }

  const { row: _txRow, inp: _txInp } = _tfRow('X', 'tx')
  const { row: _tyRow, inp: _tyInp } = _tfRow('Y', 'ty')
  const { row: _tzRow, inp: _tzInp } = _tfRow('Z', 'tz')
  const { row: _rxRow, inp: _rxInp } = _tfRow('X', 'rx')
  const { row: _ryRow, inp: _ryInp } = _tfRow('Y', 'ry')
  const { row: _rzRow, inp: _rzInp } = _tfRow('Z', 'rz')

  // ── Joint angle row (shown instead of rx/ry/rz when joint pivot is active) ──
  const _jaRow = document.createElement('div')
  _jaRow.style.cssText = 'display:flex;align-items:center;gap:4px;margin-bottom:3px'
  const _jaLbl = document.createElement('span')
  _jaLbl.textContent = '°'
  _jaLbl.style.cssText = 'font-size:10px;color:#ff8800;width:18px;flex-shrink:0;text-align:right'
  const _jaInp = document.createElement('input')
  _jaInp.type = 'number'
  _jaInp.step = '1'
  _jaInp.style.cssText = [
    'flex:1;min-width:0;box-sizing:border-box',
    'background:#0d1117;border:1px solid #ff8800;border-radius:3px',
    'color:#c9d1d9;padding:2px 4px;font-family:monospace;font-size:10px',
  ].join(';')
  _jaRow.append(_jaLbl, _jaInp)

  // Section headers — kept as separate nodes so they can be toggled
  const _rotSectHdr = _tfSect('Rotation (°)')
  const _jaSectHdr  = _tfSect('Joint rotation (°)')
  _jaSectHdr.style.color = '#ff8800'

  // ── Pivot / axis dropdown ────────────────────────────────────────────────────
  const _pivotRow = document.createElement('div')
  _pivotRow.style.cssText = 'display:flex;align-items:center;gap:4px;margin-bottom:4px'
  const _pivotLbl = document.createElement('span')
  _pivotLbl.textContent = 'Pivot:'
  _pivotLbl.style.cssText = 'font-size:10px;color:#6e7681;width:32px;flex-shrink:0;text-align:right'
  const _pivotSel = document.createElement('select')
  _pivotSel.style.cssText = [
    'flex:1;min-width:0;box-sizing:border-box',
    'background:#0d1117;border:1px solid #30363d;border-radius:3px',
    'color:#c9d1d9;padding:2px 4px;font-size:10px',
  ].join(';')
  const _optCentroid = document.createElement('option')
  _optCentroid.value = 'centroid'
  _optCentroid.textContent = 'Centroid'
  _pivotSel.appendChild(_optCentroid)
  _pivotRow.append(_pivotLbl, _pivotSel)

  // Track whether a joint pivot is currently active
  let _pivotIsJoint = false

  function _showJointMode(on) {
    _pivotIsJoint = on
    _rxRow.style.display = on ? 'none' : ''
    _ryRow.style.display = on ? 'none' : ''
    _rzRow.style.display = on ? 'none' : ''
    _rotSectHdr.style.display = on ? 'none' : ''
    _jaSectHdr.style.display = on ? '' : 'none'
    _jaRow.style.display = on ? '' : 'none'
  }

  _pivotSel.addEventListener('change', () => {
    if (!onPivotSelect) return
    const val = _pivotSel.value
    if (val === 'centroid') {
      _showJointMode(false)
      onPivotSelect('centroid', null)
    } else {
      const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === val)
      if (joint) {
        _showJointMode(true)
        onPivotSelect('joint', joint)
      }
    }
  })

  _tfPanel.append(
    _pivotRow,
    _tfSect('Translation (nm)'), _txRow, _tyRow, _tzRow,
    _rotSectHdr, _rxRow, _ryRow, _rzRow,
    _jaSectHdr,  _jaRow,
  )
  // Joint mode hidden by default (centroid is the default pivot)
  _showJointMode(false)

  // Insert transform panel before the new-cluster button
  newBtn.parentNode.insertBefore(_tfPanel, newBtn)

  function _commitEdit() {
    if (_pivotIsJoint) {
      if (!onJointAngleEdit) return
      const deg = parseFloat(_jaInp.value)
      if (!isNaN(deg)) onJointAngleEdit(deg)
      return
    }
    if (!onTransformEdit) return
    const tx = parseFloat(_txInp.value) || 0
    const ty = parseFloat(_tyInp.value) || 0
    const tz = parseFloat(_tzInp.value) || 0
    const rx = parseFloat(_rxInp.value) || 0
    const ry = parseFloat(_ryInp.value) || 0
    const rz = parseFloat(_rzInp.value) || 0
    onTransformEdit(tx, ty, tz, rx, ry, rz)
  }

  for (const inp of [_txInp, _tyInp, _tzInp, _rxInp, _ryInp, _rzInp]) {
    inp.addEventListener('keydown', e => {
      e.stopPropagation()
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); _commitEdit() }
    })
    inp.addEventListener('change', _commitEdit)
  }
  _jaInp.addEventListener('keydown', e => {
    e.stopPropagation()
    if (e.key === 'Enter') { e.preventDefault(); _jaInp.blur(); _commitEdit() }
  })
  _jaInp.addEventListener('change', _commitEdit)

  // Show/hide based on translateRotateActive + activeClusterId
  store.subscribe((n, p) => {
    if (n.translateRotateActive === p.translateRotateActive && n.activeClusterId === p.activeClusterId) return
    const visible = !!(n.translateRotateActive && n.activeClusterId)
    _tfPanel.style.display = visible ? '' : 'none'
    // Reset to centroid mode when panel hides (new cluster selection)
    if (!visible) _showJointMode(false)
  })

  /** Called from main.js during drag or after setTransform. Skips focused inputs. */
  function setTransformValues(tx, ty, tz, rx, ry, rz) {
    const vals = [tx, ty, tz, rx, ry, rz]
    for (const [i, inp] of [_txInp, _tyInp, _tzInp, _rxInp, _ryInp, _rzInp].entries()) {
      if (document.activeElement !== inp) inp.value = vals[i].toFixed(3)
    }
  }

  /**
   * Update the joint angle field. Called from main.js when joint pivot is active
   * and the cluster transform changes (e.g. during a ring drag).
   * @param {number} deg  Current angle in degrees around the joint axis.
   */
  function setJointAngle(deg) {
    if (document.activeElement !== _jaInp) _jaInp.value = deg.toFixed(1)
  }

  /** Rebuild pivot dropdown: centroid + one entry per joint on the active cluster. */
  function setPivotOptions(joints) {
    while (_pivotSel.options.length > 1) _pivotSel.remove(1)
    for (const j of (joints ?? [])) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `Joint: ${j.name}`
      _pivotSel.appendChild(opt)
    }
  }

  /** Select a pivot option programmatically (jointId or 'centroid'). */
  function setSelectedPivot(id) {
    _pivotSel.value = id ?? 'centroid'
    _showJointMode(id !== 'centroid' && id != null)
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

  // ── Joint section builder ────────────────────────────────────────────────────

  /**
   * Build the joint sub-section for one cluster and append it to parentEl.
   * Only rendered when the cluster is the active one.
   */
  function _buildJointSection(cluster, parentEl, design) {
    const joints = (design?.cluster_joints ?? []).filter(j => j.cluster_id === cluster.id)

    const section = document.createElement('div')
    section.style.cssText = 'padding:4px 6px 6px 20px;border-top:1px solid #21262d'

    // Header row: "Joint" label + [Place] button
    const hdr = document.createElement('div')
    hdr.style.cssText = 'display:flex;align-items:center;gap:4px;margin-bottom:4px'
    const lbl = document.createElement('span')
    lbl.textContent = 'Joint'
    lbl.style.cssText = 'font-size:9px;color:#484f58;text-transform:uppercase;letter-spacing:.05em;flex:1'
    const addBtn = document.createElement('button')
    addBtn.textContent = 'Place'
    addBtn.title = 'Click a face on the surface approximation to place the rotation axis (replaces any existing joint)'
    addBtn.style.cssText = [
      'background:#162420;border:1px solid #3fb950;color:#3fb950',
      'border-radius:3px;font-size:10px;padding:1px 6px;cursor:pointer',
    ].join(';')
    addBtn.addEventListener('pointerenter', () => { addBtn.style.background = '#1f3d2a' })
    addBtn.addEventListener('pointerleave', () => { addBtn.style.background = '#162420' })
    addBtn.addEventListener('click', e => {
      e.stopPropagation()
      if (!jointRenderer) return
      addBtn.disabled = true
      addBtn.style.opacity = '0.5'
      jointRenderer.enterDefineMode(cluster.id, () => {
        addBtn.disabled = false
        addBtn.style.opacity = ''
      })
    })
    hdr.append(lbl, addBtn)
    section.appendChild(hdr)

    // Hull surface toggle (default on)
    const hsRow = document.createElement('div')
    hsRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px'
    const hsChk = document.createElement('input')
    hsChk.type = 'checkbox'; hsChk.id = `jnt-hs-${cluster.id}`; hsChk.checked = true
    hsChk.style.cssText = 'accent-color:#44ff88;cursor:pointer'
    const hsLbl = document.createElement('label')
    hsLbl.htmlFor = hsChk.id; hsLbl.textContent = 'Hull surface'
    hsLbl.style.cssText = 'font-size:9px;color:#6e7681;cursor:pointer;user-select:none'
    hsChk.addEventListener('change', () => jointRenderer?.setHullSurface(hsChk.checked))
    hsRow.append(hsChk, hsLbl)
    section.appendChild(hsRow)

    // Exterior panels toggle (default off)
    const epRow = document.createElement('div')
    epRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px'
    const epChk = document.createElement('input')
    epChk.type = 'checkbox'; epChk.id = `jnt-ep-${cluster.id}`; epChk.checked = false
    epChk.style.cssText = 'accent-color:#4488ff;cursor:pointer'
    const epLbl = document.createElement('label')
    epLbl.htmlFor = epChk.id; epLbl.textContent = 'Exterior panels'
    epLbl.style.cssText = 'font-size:9px;color:#6e7681;cursor:pointer;user-select:none'
    epChk.addEventListener('change', () => jointRenderer?.setExteriorPanels(epChk.checked))
    epRow.append(epChk, epLbl)
    section.appendChild(epRow)

    // Existing joint rows
    for (const joint of joints) {
      const jrow = document.createElement('div')
      jrow.style.cssText = [
        'display:flex;align-items:center;gap:4px;padding:3px 0',
        'border-radius:3px;cursor:default',
      ].join(';')

      const dot = document.createElement('span')
      dot.style.cssText = 'width:6px;height:6px;border-radius:50%;background:#ff8800;flex-shrink:0'
      dot.title = 'Revolute joint axis'

      const nameLbl = document.createElement('span')
      nameLbl.textContent = joint.name
      nameLbl.style.cssText = 'flex:1;font-size:10px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete joint'
      const _jDelStyle = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:10px;padding:0 4px;cursor:pointer'
      delBtn.style.cssText = _jDelStyle
      delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _jDelStyle })
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.deleteJoint?.(joint.id)
      })

      jrow.addEventListener('mouseenter', () => onJointHighlight?.(joint.id))
      jrow.addEventListener('mouseleave', () => onJointHighlight?.(null))

      jrow.append(dot, nameLbl, delBtn)
      section.appendChild(jrow)
    }

    if (!joints.length) {
      const hint = document.createElement('div')
      hint.style.cssText = 'font-size:10px;color:#484f58;padding:2px 0'
      hint.textContent = 'No joint — click "Place" to define a rotation axis.'
      section.appendChild(hint)
    }

    parentEl.appendChild(section)
  }

  // ── Rebuild list when design or active cluster changes ───────────────────────
  store.subscribe((n, p) => {
    if (n.currentDesign === p.currentDesign && n.activeClusterId === p.activeClusterId) return
    if (!_collapsed) _rebuild(n.currentDesign?.cluster_transforms ?? [], n.activeClusterId, n.currentDesign)
  })

  function _rebuild(clusters, activeId, design) {
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

      // Joint section — only visible for the active cluster
      if (isActive) _buildJointSection(cluster, listEl, design)
    }
  }

  return { setTransformValues, setJointAngle, setPivotOptions, setSelectedPivot }
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
