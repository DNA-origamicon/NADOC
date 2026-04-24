/**
 * Joints panel — left sidebar section for placing and listing cluster joints.
 *
 * Has its own cluster dropdown independent of the move/rotate cluster selection.
 * Only the prism hull for the cluster selected here is shown during joint placement.
 * Calls jointRenderer.enterDefineMode(clusterId, onExit) when Place Joint is clicked.
 *
 * @param {object} store
 * @param {object} opts.api
 * @param {object} opts.jointRenderer  — joint_renderer instance
 * @param {function} [opts.onJointHighlight]  — called with (jointId|null) on hover
 * @param {function} [opts.onJointAdded]      — called after a joint is placed
 */
export function initJointsPanel(store, { api, jointRenderer, onJointHighlight = null, onJointAdded = null, onJointRotate = null }) {
  const heading    = document.getElementById('joints-panel-heading')
  const arrow      = document.getElementById('joints-panel-arrow')
  const body       = document.getElementById('joints-panel-body')
  const clusterSel = document.getElementById('joints-cluster-sel')
  const listEl     = document.getElementById('joints-list')
  const placeBtn   = document.getElementById('joints-place-btn')
  if (!heading || !clusterSel || !listEl || !placeBtn) return

  let _collapsed       = false
  let _activeClusterId = null

  // ── Collapse / expand ────────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── Cluster dropdown ─────────────────────────────────────────────────────────
  clusterSel.addEventListener('change', () => {
    _activeClusterId = clusterSel.value || null
    _rebuildList(store.getState().currentDesign)
  })

  // ── Place Joint button ───────────────────────────────────────────────────────
  placeBtn.addEventListener('click', e => {
    e.stopPropagation()
    if (!jointRenderer || !_activeClusterId) return
    placeBtn.disabled = true
    placeBtn.style.opacity = '0.5'
    jointRenderer.enterDefineMode(_activeClusterId, () => {
      placeBtn.disabled = false
      placeBtn.style.opacity = ''
      onJointAdded?.(_activeClusterId)
    })
  })

  // ── Rebuild cluster dropdown ─────────────────────────────────────────────────
  function _rebuildClusterDropdown(design) {
    const clusters = design?.cluster_transforms ?? []
    clusterSel.innerHTML = ''
    if (!clusters.length) {
      const opt = document.createElement('option')
      opt.textContent = 'No clusters'
      opt.disabled = true
      clusterSel.appendChild(opt)
      placeBtn.disabled = true
      _activeClusterId = null
      return
    }
    for (const c of clusters) {
      const opt = document.createElement('option')
      opt.value = c.id
      opt.textContent = c.name
      clusterSel.appendChild(opt)
    }
    // Keep selection if still valid, else pick the last cluster
    if (!clusters.find(c => c.id === _activeClusterId)) {
      _activeClusterId = clusters[clusters.length - 1].id
    }
    clusterSel.value = _activeClusterId
    placeBtn.disabled = false
  }

  // ── Rebuild joint list for the selected cluster ──────────────────────────────
  function _rebuildList(design) {
    listEl.innerHTML = ''
    if (!_activeClusterId) return
    const joints = (design?.cluster_joints ?? []).filter(j => j.cluster_id === _activeClusterId)

    if (!joints.length) {
      const hint = document.createElement('div')
      hint.style.cssText = 'font-size:10px;color:#484f58;padding:2px 0'
      hint.textContent = 'No joints — click "Place Joint" to define a rotation axis.'
      listEl.appendChild(hint)
      return
    }

    for (const joint of joints) {
      const jrow = document.createElement('div')
      jrow.style.cssText = [
        'display:flex;align-items:center;gap:4px;padding:3px 0',
        'border-radius:3px;cursor:default',
      ].join(';')

      const dot = document.createElement('span')
      dot.style.cssText = 'width:6px;height:6px;border-radius:50%;background:#ff8800;flex-shrink:0'
      dot.title = 'Joint axis'

      const nameLbl = document.createElement('span')
      nameLbl.textContent = joint.name
      nameLbl.style.cssText = [
        'flex:1;font-size:10px;color:#c9d1d9',
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
      ].join(';')

      const rotBtn = document.createElement('button')
      rotBtn.textContent = '↻'
      rotBtn.title = 'Open move/rotate tool with this joint selected'
      const _rotStyle = [
        'background:#162420;border:1px solid #3fb950;color:#3fb950',
        'border-radius:3px;font-size:10px;padding:0 4px;cursor:pointer',
      ].join(';')
      rotBtn.style.cssText = _rotStyle
      rotBtn.addEventListener('pointerenter', () => { rotBtn.style.background = '#1e3a28'; rotBtn.style.color = '#56d364' })
      rotBtn.addEventListener('pointerleave', () => { rotBtn.style.cssText = _rotStyle })
      rotBtn.addEventListener('click', e => {
        e.stopPropagation()
        onJointRotate?.(joint)
      })

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete joint'
      const _delStyle = [
        'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c',
        'border-radius:3px;font-size:10px;padding:0 4px;cursor:pointer',
      ].join(';')
      delBtn.style.cssText = _delStyle
      delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.deleteJoint?.(joint.id)
      })

      jrow.addEventListener('mouseenter', () => onJointHighlight?.(joint.id))
      jrow.addEventListener('mouseleave', () => onJointHighlight?.(null))

      jrow.append(dot, nameLbl, rotBtn, delBtn)
      listEl.appendChild(jrow)
    }
  }

  // ── Full rebuild ─────────────────────────────────────────────────────────────
  function _rebuild(design) {
    _rebuildClusterDropdown(design)
    _rebuildList(design)
  }

  // ── Reactivity ───────────────────────────────────────────────────────────────
  store.subscribe((n, p) => {
    if (n.currentDesign === p.currentDesign) return
    if (!_collapsed) _rebuild(n.currentDesign)
  })

  _rebuild(store.getState().currentDesign)

  return {
    /** Returns the cluster ID currently selected in the joints panel. */
    getSelectedClusterId: () => _activeClusterId,
  }
}
