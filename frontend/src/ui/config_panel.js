/**
 * Configurations panel — sidebar list of saved cluster-state snapshots.
 *
 * Each configuration captures the translation/rotation of every cluster at the
 * moment of saving.  "Go to" animates all clusters to the saved state and
 * persists the result.  Configurations persist inside the .nadoc file.
 *
 * @param {object} store
 * @param {object} opts
 * @param {function(): object|null} opts.getHelixCtrl  — returns live helix renderer controller
 * @param {object}   opts.api                          — API module
 */

import * as THREE from 'three'

export function initConfigPanel(store, { getHelixCtrl, api }) {
  const listEl     = document.getElementById('config-list')
  const captureBtn = document.getElementById('config-capture-btn')
  const heading    = document.getElementById('config-panel-heading')
  const arrow      = document.getElementById('config-panel-arrow')
  const body       = document.getElementById('config-panel-body')
  if (!listEl || !captureBtn || !heading) return

  let _collapsed = false

  // ── Collapse / expand ───────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── Capture current cluster state ───────────────────────────────────────────
  captureBtn.addEventListener('click', async () => {
    const { currentDesign } = store.getState()
    if (!currentDesign) return
    const clusters = currentDesign.cluster_transforms ?? []
    if (!clusters.length) {
      console.warn('[config] No clusters in design — nothing to capture.')
      return
    }
    const n = (currentDesign.configurations?.length ?? 0) + 1
    const entries = clusters.map(c => ({
      cluster_id:  c.id,
      translation: [...c.translation],
      rotation:    [...c.rotation],
    }))
    await api.createConfiguration(`Config ${n}`, entries)
  })

  // ── Store subscription ───────────────────────────────────────────────────────
  store.subscribe((n, p) => {
    if (n.currentDesign === p.currentDesign) return
    if (!_collapsed) _rebuild(n.currentDesign?.configurations ?? [])
  })

  // Drag state for reorder
  let _dragId   = null
  let _dragOver = null

  function _rebuild(configs) {
    listEl.innerHTML = ''
    if (!configs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent = 'No saved configurations. Move clusters and click Capture.'
      listEl.appendChild(empty)
      return
    }
    for (const cfg of configs) {
      listEl.appendChild(_makeRow(cfg, configs))
    }
  }

  const _editStyle   = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _saveStyle   = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _goStyle     = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _updateStyle = 'background:#1f2d0d;border:1px solid #588a1e;color:#8ec550;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'
  const _delStyle    = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:1px 5px;flex-shrink:0'

  // ── "Go to" cluster animation ────────────────────────────────────────────────

  /**
   * Smoothly interpolate all clusters to the saved config entries over durationMs,
   * then persist the final transforms to the backend.
   */
  async function _animateToConfig(config) {
    const { currentDesign } = store.getState()
    const clusters = currentDesign?.cluster_transforms ?? []
    const entries  = config.entries ?? []
    if (!clusters.length || !entries.length) return

    const helixCtrl = getHelixCtrl()
    if (!helixCtrl) {
      console.warn('[config] No helixCtrl — cannot animate clusters.')
      return
    }

    // Snapshot base positions for each relevant cluster (append=true so all captured)
    let first = true
    for (const entry of entries) {
      const cluster = clusters.find(c => c.id === entry.cluster_id)
      if (!cluster) {
        console.debug(`[config] cluster ${entry.cluster_id} not found in design — skipping`)
        continue
      }
      helixCtrl.captureClusterBase(cluster.helix_ids, cluster.domain_ids?.length ? cluster.domain_ids : null, !first)
      first = false
    }

    // Build per-cluster base data (snapshot of design state at animation start)
    const baseClusters = clusters.map(c => ({
      id:         c.id,
      translation: [...c.translation],
      rotation:    [...c.rotation],
      pivot:       [...c.pivot],
      helix_ids:   [...c.helix_ids],
      domain_ids:  c.domain_ids ? [...c.domain_ids] : [],
    }))

    const DURATION = 600  // ms
    const startTime = performance.now()

    await new Promise(resolve => {
      function step(now) {
        const rawT = Math.min((now - startTime) / DURATION, 1)
        const t    = rawT < 0.5 ? 2 * rawT * rawT : -1 + (4 - 2 * rawT) * rawT  // ease-in-out

        for (const entry of entries) {
          const base = baseClusters.find(c => c.id === entry.cluster_id)
          if (!base) continue

          // Lerp translation
          const tx = base.translation[0] + (entry.translation[0] - base.translation[0]) * t
          const ty = base.translation[1] + (entry.translation[1] - base.translation[1]) * t
          const tz = base.translation[2] + (entry.translation[2] - base.translation[2]) * t

          // Slerp rotation
          const qFrom   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
          const qTo     = new THREE.Quaternion(entry.rotation[0], entry.rotation[1], entry.rotation[2], entry.rotation[3])
          const qInterp = qFrom.clone().slerp(qTo, t)

          // incrRot = qInterp * qBase^-1
          const qBase   = new THREE.Quaternion(base.rotation[0], base.rotation[1], base.rotation[2], base.rotation[3])
          const incrRot = qInterp.multiply(qBase.clone().invert())

          const pivot  = new THREE.Vector3(...base.pivot)
          const center = pivot.clone().add(new THREE.Vector3(...base.translation))
          const dummy  = pivot.clone().add(new THREE.Vector3(tx, ty, tz))

          helixCtrl.applyClusterTransform(
            base.helix_ids,
            center,
            dummy,
            incrRot,
            base.domain_ids?.length ? base.domain_ids : null,
          )
        }

        if (rawT < 1) {
          requestAnimationFrame(step)
        } else {
          // Persist the final transforms to the backend
          for (const entry of entries) {
            const cluster = clusters.find(c => c.id === entry.cluster_id)
            if (!cluster) continue
            api.patchCluster(cluster.id, {
              translation: entry.translation,
              rotation:    entry.rotation,
            }).catch(err => console.error('[config] patchCluster failed:', err))
          }
          resolve()
        }
      }
      requestAnimationFrame(step)
    })
  }

  // ── Row builder ──────────────────────────────────────────────────────────────

  function _makeRow(cfg, allConfigs) {
    const row = document.createElement('div')
    row.dataset.cfgId = cfg.id
    row.style.cssText = [
      'display:flex;align-items:center;gap:5px;padding:5px 6px',
      'border-radius:4px;cursor:pointer;user-select:none',
      'border:1px solid transparent',
    ].join(';')
    row.title = 'Click to animate clusters to this configuration'
    row.addEventListener('mouseenter', () => { row.style.background = '#161b22' })
    row.addEventListener('mouseleave', () => { row.style.background = 'transparent' })
    row.addEventListener('click', () => _animateToConfig(cfg))

    // ── Drag handle ─────────────────────────────────────────────────────────
    const handle = document.createElement('span')
    handle.textContent = '⠿'
    handle.title = 'Drag to reorder'
    handle.style.cssText = 'color:#484f58;cursor:grab;font-size:12px;flex-shrink:0;line-height:1'
    handle.draggable = true

    handle.addEventListener('dragstart', e => {
      _dragId = cfg.id
      e.dataTransfer.effectAllowed = 'move'
      row.style.opacity = '0.5'
    })
    handle.addEventListener('dragend', () => {
      row.style.opacity = ''
      _dragId   = null
      _dragOver = null
      listEl.querySelectorAll('[data-cfg-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
    })

    row.addEventListener('dragover', e => {
      if (!_dragId || _dragId === cfg.id) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      const rect  = row.getBoundingClientRect()
      const isTop = (e.clientY - rect.top) < rect.height / 2
      listEl.querySelectorAll('[data-cfg-id]').forEach(r => { r.style.borderTop = ''; r.style.borderBottom = '' })
      if (isTop) row.style.borderTop    = '2px solid #58a6ff'
      else       row.style.borderBottom = '2px solid #58a6ff'
      _dragOver = { id: cfg.id, before: isTop }
    })

    row.addEventListener('drop', async e => {
      e.preventDefault()
      if (!_dragId || !_dragOver) return
      const { currentDesign } = store.getState()
      const cfgs = [...(currentDesign?.configurations ?? [])]
      const fromIdx = cfgs.findIndex(c => c.id === _dragId)
      let   toIdx   = cfgs.findIndex(c => c.id === _dragOver.id)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return
      const [moved] = cfgs.splice(fromIdx, 1)
      if (!_dragOver.before && toIdx >= fromIdx) toIdx++
      else if (_dragOver.before && toIdx > fromIdx) toIdx--
      cfgs.splice(_dragOver.before ? toIdx : toIdx + 1, 0, moved)
      await api.reorderConfigurations(cfgs.map(c => c.id))
    })

    // ── Name label + inline edit ─────────────────────────────────────────────
    const nameSpan = document.createElement('span')
    nameSpan.textContent = cfg.name
    nameSpan.style.cssText = 'flex:1;min-width:0;font-size:11px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

    const editBtn = document.createElement('button')
    editBtn.textContent = '✎'
    editBtn.title = 'Rename configuration'
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
      const inp = document.createElement('input')
      inp.type = 'text'; inp.value = cfg.name
      inp.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;' +
        'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
        'color:#c9d1d9;padding:2px 5px;font-family:monospace;font-size:11px;'
      nameSpan.replaceWith(inp)
      inp.focus(); inp.select()
      editBtn.textContent = '✓'; editBtn.title = 'Save name'; editBtn.style.cssText = _saveStyle

      async function _save() {
        const newName = inp.value.trim() || cfg.name
        inp.replaceWith(nameSpan); nameSpan.textContent = newName
        editBtn.textContent = '✎'; editBtn.title = 'Rename configuration'
        editBtn.style.cssText = _editStyle; editBtn.onclick = _enterEdit
        if (newName !== cfg.name) await api.updateConfiguration(cfg.id, { name: newName })
      }
      inp.addEventListener('keydown', e2 => {
        e2.stopPropagation()
        if (e2.key === 'Enter')  { e2.preventDefault(); _save() }
        if (e2.key === 'Escape') {
          inp.replaceWith(nameSpan)
          editBtn.textContent = '✎'; editBtn.title = 'Rename configuration'
          editBtn.style.cssText = _editStyle; editBtn.onclick = _enterEdit
        }
      })
      editBtn.onclick = e2 => { e2.stopPropagation(); _save() }
    }
    editBtn.onclick = _enterEdit

    // ── "Go to" button ───────────────────────────────────────────────────────
    const goBtn = document.createElement('button')
    goBtn.textContent = '▶'; goBtn.title = 'Animate clusters to this configuration'
    goBtn.style.cssText = _goStyle
    goBtn.addEventListener('pointerenter', () => { goBtn.style.background = '#0f3a5c'; goBtn.style.color = '#79bcff' })
    goBtn.addEventListener('pointerleave', () => { goBtn.style.cssText = _goStyle })
    goBtn.addEventListener('click', async e => { e.stopPropagation(); await _animateToConfig(cfg) })

    // ── "Update" button (overwrite with current cluster state) ───────────────
    const updateBtn = document.createElement('button')
    updateBtn.textContent = '⟳'; updateBtn.title = 'Overwrite with current cluster positions'
    updateBtn.style.cssText = _updateStyle
    updateBtn.addEventListener('pointerenter', () => { updateBtn.style.background = '#2a3f0e'; updateBtn.style.color = '#aee060' })
    updateBtn.addEventListener('pointerleave', () => { updateBtn.style.cssText = _updateStyle })
    updateBtn.addEventListener('click', async e => {
      e.stopPropagation()
      const clusters = store.getState().currentDesign?.cluster_transforms ?? []
      const entries  = clusters.map(c => ({
        cluster_id:  c.id,
        translation: [...c.translation],
        rotation:    [...c.rotation],
      }))
      await api.updateConfiguration(cfg.id, { entries })
    })

    // ── Delete button ────────────────────────────────────────────────────────
    const delBtn = document.createElement('button')
    delBtn.textContent = '×'; delBtn.title = 'Delete configuration'
    delBtn.style.cssText = _delStyle
    delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
    delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
    delBtn.addEventListener('click', async e => {
      e.stopPropagation()
      await api.deleteConfiguration(cfg.id)
    })

    row.append(handle, nameSpan, goBtn, updateBtn, editBtn, delBtn)
    return row
  }

  _rebuild(store.getState().currentDesign?.configurations ?? [])
  return {}
}
