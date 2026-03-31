/**
 * Feature Log panel — unified timeline of geometry operations + saved configs.
 *
 * Shows feature_log as a vertical ordered list (oldest at top).
 * A draggable "playhead" bar marks the last active entry (feature_log_cursor).
 * Entries below the playhead are greyed out (suppressed).
 *
 * Checkpoint entries (saved configs) appear inline as styled dividers with
 * animate-to (▶), rename (✎), and delete (×) buttons — replacing the old
 * Configurations panel.
 *
 * Clicking a non-checkpoint entry seeks to that position.
 * Dragging the playhead calls api.seekFeatures(newPosition).
 *
 * @param {object} store
 * @param {object} opts.api             — API module (seekFeatures, createConfiguration, etc.)
 * @param {function} opts.getHelixCtrl  — returns live helix renderer controller
 * @param {function} opts.getBluntEnds  — returns blunt-end manager (optional)
 * @param {function} opts.getUnfoldView — returns unfold-view controller (optional)
 */

import * as THREE from 'three'

export function initFeatureLogPanel(store, { api, getHelixCtrl, getBluntEnds, getUnfoldView }) {
  const listEl     = document.getElementById('feature-log-list')
  const captureBtn = document.getElementById('feature-log-capture-btn')
  const heading    = document.getElementById('feature-log-panel-heading')
  const arrow      = document.getElementById('feature-log-panel-arrow')
  const body       = document.getElementById('feature-log-panel-body')
  if (!listEl || !heading) return

  let _collapsed     = false
  let _isSeeking     = false
  let _isAnimating   = false
  let _latestDesign  = null   // always current, even while collapsed

  // ── Collapse / expand ──────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
    // Rebuild with latest design when expanding so stale state is never shown.
    if (!_collapsed) _rebuild(_latestDesign)
  })

  // ── Capture Config button ──────────────────────────────────────────────────
  if (captureBtn) {
    captureBtn.addEventListener('click', async () => {
      const { currentDesign } = store.getState()
      if (!currentDesign) return
      const clusters = currentDesign.cluster_transforms ?? []
      if (!clusters.length) return
      const cpCount = (currentDesign.feature_log ?? []).filter(e => e.feature_type === 'checkpoint').length
      const entries = clusters.map(c => ({
        cluster_id:  c.id,
        translation: [...c.translation],
        rotation:    [...c.rotation],
      }))
      captureBtn.disabled = true
      try {
        await api.createConfiguration(`Config ${cpCount + 1}`, entries)
      } finally {
        captureBtn.disabled = false
      }
    })
  }

  // ── Button styles ──────────────────────────────────────────────────────────
  const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:10px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:10px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _goStyle   = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:10px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:10px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'

  // ── Seek ───────────────────────────────────────────────────────────────────
  async function _seek(position) {
    if (_isSeeking) return
    _isSeeking = true
    try {
      await api.seekFeatures(position)
    } finally {
      _isSeeking = false
    }
  }

  // ── Animate clusters to a saved config (600 ms ease-in-out) ───────────────
  async function _animateToConfig(config) {
    if (_isAnimating) return
    const { currentDesign } = store.getState()
    const clusters = currentDesign?.cluster_transforms ?? []
    const entries  = config.entries ?? []
    if (!clusters.length || !entries.length) return

    const helixCtrl = getHelixCtrl?.()
    if (!helixCtrl) return

    const bluntEnds   = getBluntEnds?.()
    const unfoldView  = getUnfoldView?.()

    let first = true
    for (const entry of entries) {
      const cluster = clusters.find(c => c.id === entry.cluster_id)
      if (!cluster) continue
      helixCtrl.captureClusterBase(cluster.helix_ids, cluster.domain_ids?.length ? cluster.domain_ids : null, !first)
      bluntEnds?.captureClusterBase(cluster.helix_ids, !first)
      first = false
    }

    const baseClusters = clusters.map(c => ({
      id:          c.id,
      translation: [...c.translation],
      rotation:    [...c.rotation],
      pivot:       [...c.pivot],
      helix_ids:   [...c.helix_ids],
      domain_ids:  c.domain_ids ? [...c.domain_ids] : [],
    }))

    const DURATION = 600
    const startTime = performance.now()
    _isAnimating = true
    listEl.style.pointerEvents = 'none'
    listEl.style.opacity = '0.45'
    try {
      await new Promise(resolve => {
        function step(now) {
          const rawT = Math.min((now - startTime) / DURATION, 1)
          const t    = rawT < 0.5 ? 2 * rawT * rawT : -1 + (4 - 2 * rawT) * rawT

          for (const entry of entries) {
            const base = baseClusters.find(c => c.id === entry.cluster_id)
            if (!base) continue

            const tx = base.translation[0] + (entry.translation[0] - base.translation[0]) * t
            const ty = base.translation[1] + (entry.translation[1] - base.translation[1]) * t
            const tz = base.translation[2] + (entry.translation[2] - base.translation[2]) * t

            const qFrom   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
            const qTo     = new THREE.Quaternion(entry.rotation[0], entry.rotation[1], entry.rotation[2], entry.rotation[3])
            const qInterp = qFrom.clone().slerp(qTo, t)
            const qBase   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
            const incrRot = qInterp.multiply(qBase.clone().invert())

            const pivot  = new THREE.Vector3(...base.pivot)
            const center = pivot.clone().add(new THREE.Vector3(...base.translation))
            const dummy  = pivot.clone().add(new THREE.Vector3(tx, ty, tz))

            helixCtrl.applyClusterTransform(base.helix_ids, center, dummy, incrRot, base.domain_ids?.length ? base.domain_ids : null)
            bluntEnds?.applyClusterTransform(base.helix_ids, center, dummy, incrRot)
          }

          const allHelixIds = entries.flatMap(e => baseClusters.find(c => c.id === e.cluster_id)?.helix_ids ?? [])
          if (allHelixIds.length) {
            unfoldView?.applyClusterArcUpdate(allHelixIds)
            unfoldView?.applyClusterExtArcUpdate(allHelixIds)
            helixCtrl.applyClusterXbUpdate(allHelixIds)
          }

          if (rawT < 1) {
            requestAnimationFrame(step)
          } else {
            resolve()
          }
        }
        requestAnimationFrame(step)
      })

      // Persist final transforms, then refresh currentGeometry.
      // Awaiting ensures currentGeometry is up-to-date before the user can
      // press Q (expanded spacing) or D (deform view), both of which read it
      // as the base bead-position anchor.
      await Promise.all(entries.map(async entry => {
        const cluster = clusters.find(c => c.id === entry.cluster_id)
        if (!cluster) return
        await api.patchCluster(cluster.id, { translation: entry.translation, rotation: entry.rotation })
      })).catch(err => console.error('[feature_log] patchCluster failed:', err))

      if (typeof api.getGeometry === 'function') await api.getGeometry()

    } finally {
      _isAnimating = false
      listEl.style.pointerEvents = ''
      listEl.style.opacity = ''
    }
  }

  // ── Checkpoint rename ──────────────────────────────────────────────────────
  function _enterCheckpointEdit(e, entry, nameSpan, editBtn) {
    e.stopPropagation()
    const inp = document.createElement('input')
    inp.type = 'text'; inp.value = entry.name
    inp.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px'
    nameSpan.replaceWith(inp)
    inp.focus(); inp.select()
    editBtn.textContent = '✓'; editBtn.title = 'Save name'; editBtn.style.cssText = _saveStyle

    async function _save() {
      const newName = inp.value.trim() || entry.name
      inp.replaceWith(nameSpan); nameSpan.textContent = newName
      editBtn.textContent = '✎'; editBtn.title = 'Rename'; editBtn.style.cssText = _editStyle
      editBtn.onclick = ev => _enterCheckpointEdit(ev, entry, nameSpan, editBtn)
      if (newName !== entry.name) await api.updateConfiguration(entry.config_id, { name: newName })
    }
    inp.addEventListener('keydown', e2 => {
      e2.stopPropagation()
      if (e2.key === 'Enter')  { e2.preventDefault(); _save() }
      if (e2.key === 'Escape') {
        inp.replaceWith(nameSpan)
        editBtn.textContent = '✎'; editBtn.style.cssText = _editStyle
        editBtn.onclick = ev => _enterCheckpointEdit(ev, entry, nameSpan, editBtn)
      }
    })
    editBtn.onclick = e2 => { e2.stopPropagation(); _save() }
  }

  // ── Playhead drag ──────────────────────────────────────────────────────────

  function _getPositionFromY(y) {
    // Scan gap markers top-to-bottom; return seek position for given Y.
    const gaps = listEl.querySelectorAll('[data-gap-after]')
    if (!gaps.length) return -1
    for (const gap of gaps) {
      const rect = gap.getBoundingClientRect()
      if (y <= rect.top + rect.height) {
        return parseInt(gap.dataset.gapAfter)
      }
    }
    return -1
  }

  function _applyPreview(pos) {
    listEl.querySelectorAll('[data-log-index]').forEach(el => {
      const idx = parseInt(el.dataset.logIndex)
      if (pos < 0 || idx <= pos) {
        el.classList.remove('fl-entry-suppressed')
      } else {
        el.classList.add('fl-entry-suppressed')
      }
    })
    listEl.querySelectorAll('.fl-playhead').forEach(el => el.remove())
    if (pos >= 0) _insertPlayheadAt(pos)
  }

  function _insertPlayheadAt(pos) {
    const target = listEl.querySelector(`[data-gap-after="${pos}"]`)
    if (!target) return
    const ph     = document.createElement('div')
    ph.className = 'fl-playhead'
    ph.title     = 'Drag to scrub through feature timeline'
    const lineL  = document.createElement('div'); lineL.className = 'fl-playhead-line'
    const label  = document.createElement('span'); label.textContent = '◆ seek'
    const lineR  = document.createElement('div'); lineR.className = 'fl-playhead-line'
    ph.append(lineL, label, lineR)
    ph.addEventListener('pointerdown', _startDrag)
    target.after(ph)
  }

  function _startDrag(e) {
    e.preventDefault()
    e.stopPropagation()
    let currentPos = -1
    document.body.style.cursor = 'ns-resize'

    function onMove(me) {
      const pos = _getPositionFromY(me.clientY)
      if (pos !== currentPos) { currentPos = pos; _applyPreview(pos) }
    }
    function onUp() {
      document.body.style.cursor = ''
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
      _seek(currentPos)
    }
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup',  onUp)
  }

  // ── Rebuild list ───────────────────────────────────────────────────────────
  function _rebuild(design) {
    listEl.innerHTML = ''
    const log        = design?.feature_log ?? []
    const cursor     = design?.feature_log_cursor ?? -1
    const deformMap  = Object.fromEntries((design?.deformations ?? []).map(d => [d.id, d]))
    const clusterMap = Object.fromEntries((design?.cluster_transforms ?? []).map(c => [c.id, c]))
    const configMap  = Object.fromEntries((design?.configurations ?? []).map(c => [c.id, c]))

    if (log.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#6e7681;font-size:11px;padding:4px 0'
      empty.textContent = 'No features recorded yet.'
      listEl.appendChild(empty)
      return
    }

    log.forEach((entry, i) => {
      const suppressed = cursor >= 0 && i > cursor

      if (entry.feature_type === 'checkpoint') {
        // ── Checkpoint divider ─────────────────────────────────────────────
        const config = configMap[entry.config_id]
        const row    = document.createElement('div')
        row.dataset.logIndex = i
        if (suppressed) row.classList.add('fl-entry-suppressed')
        row.style.cssText = 'display:flex;align-items:center;gap:5px;padding:5px 0;border-top:1px solid #30363d;border-bottom:1px solid #30363d;margin:3px 0'

        const icon = document.createElement('span')
        icon.textContent = '⚑'
        icon.style.cssText = 'color:#58a6ff;font-size:12px;flex-shrink:0'

        const nameSpan = document.createElement('span')
        nameSpan.textContent = entry.name || 'Config'
        nameSpan.style.cssText = 'flex:1;min-width:0;font-size:11px;color:#58a6ff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer'
        nameSpan.title = config ? 'Click to animate to this configuration' : '(configuration removed)'
        if (config) nameSpan.addEventListener('click', () => _animateToConfig(config))

        const goBtn = document.createElement('button')
        goBtn.textContent = '▶'; goBtn.title = 'Animate to this configuration'
        goBtn.style.cssText = _goStyle
        goBtn.addEventListener('pointerenter', () => { goBtn.style.background = '#0f3a5c' })
        goBtn.addEventListener('pointerleave', () => { goBtn.style.cssText = _goStyle })
        goBtn.addEventListener('click', e => { e.stopPropagation(); if (config) _animateToConfig(config) })

        const editBtn = document.createElement('button')
        editBtn.textContent = '✎'; editBtn.title = 'Rename'
        editBtn.style.cssText = _editStyle
        editBtn.addEventListener('pointerenter', () => { editBtn.style.background = '#2d333b' })
        editBtn.addEventListener('pointerleave', () => { editBtn.style.cssText = _editStyle })
        editBtn.onclick = ev => _enterCheckpointEdit(ev, entry, nameSpan, editBtn)

        const delBtn = document.createElement('button')
        delBtn.textContent = '×'; delBtn.title = 'Delete configuration'
        delBtn.style.cssText = _delStyle
        delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c' })
        delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
        delBtn.addEventListener('click', e => { e.stopPropagation(); api.deleteConfiguration(entry.config_id) })

        row.append(icon, nameSpan, goBtn, editBtn, delBtn)
        listEl.appendChild(row)

      } else {
        // ── Deformation or cluster_op row ──────────────────────────────────
        const row = document.createElement('div')
        row.dataset.logIndex = i
        if (suppressed) row.classList.add('fl-entry-suppressed')
        row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;font-size:11px;color:#c9d1d9;cursor:pointer;border-radius:3px'
        row.title = `Click to seek timeline to position ${i}`
        row.addEventListener('mouseenter', () => { if (!suppressed) row.style.background = '#161b22' })
        row.addEventListener('mouseleave', () => { row.style.background = '' })
        row.addEventListener('click', () => _seek(i))

        const icon  = document.createElement('span')
        icon.style.flexShrink = '0'
        const label = document.createElement('span')
        label.style.flex = '1'

        if (entry.feature_type === 'deformation') {
          const op = entry.op_snapshot || deformMap[entry.deformation_id]
          icon.textContent  = op?.type === 'bend' ? '↪' : '↺'
          const range = op ? `bp ${op.plane_a_bp}–${op.plane_b_bp}` : '(removed)'
          const name  = op?.type ? (op.type.charAt(0).toUpperCase() + op.type.slice(1)) : 'Deformation'
          label.textContent = `${name}  ${range}`
        } else {
          const cluster = clusterMap[entry.cluster_id]
          icon.textContent  = '⟳'
          const clusterName = cluster?.name ?? entry.cluster_id.slice(0, 8)
          label.textContent = `Transform  ${clusterName}`
        }

        row.append(icon, label)
        listEl.appendChild(row)
      }

      // Gap marker after every entry (playhead drop target)
      const gap = document.createElement('div')
      gap.dataset.gapAfter = i
      gap.style.cssText = 'height:4px'
      listEl.appendChild(gap)
    })

    // Insert playhead after last active entry (when not fully at end)
    if (cursor >= 0 && cursor < log.length) {
      _insertPlayheadAt(cursor)
    }
  }

  // ── Reactivity ─────────────────────────────────────────────────────────────
  store.subscribeSlice('design', (n, p) => {
    if (n.currentDesign === p.currentDesign) return
    _latestDesign = n.currentDesign
    if (!_collapsed) _rebuild(_latestDesign)
  })

  _latestDesign = store.getState().currentDesign
  _rebuild(_latestDesign)
}
