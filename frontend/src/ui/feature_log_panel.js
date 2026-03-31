/**
 * Feature Log panel — ordered list of geometry operations (bends, twists,
 * cluster transforms) with a "Roll Back Last" button.
 *
 * The feature_log on the design is the source of truth.  Checkpoints (config
 * saves) are shown as dividers; deformation and cluster ops are shown as rows.
 * Only the last non-checkpoint entry can be rolled back via this panel.
 */

export function initFeatureLogPanel(store, { api }) {
  const listEl      = document.getElementById('feature-log-list')
  const rollbackBtn = document.getElementById('feature-log-rollback-btn')
  const heading     = document.getElementById('feature-log-panel-heading')
  const arrow       = document.getElementById('feature-log-panel-arrow')
  const body        = document.getElementById('feature-log-panel-body')
  if (!listEl || !rollbackBtn || !heading) return

  let _collapsed = false

  // ── Collapse / expand ──────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.textContent  = _collapsed ? '▶' : '▼'
  })

  // ── Roll back last feature ─────────────────────────────────────────────────
  rollbackBtn.addEventListener('click', async () => {
    rollbackBtn.disabled = true
    try {
      await api.rollbackLastFeature()
    } catch (err) {
      console.error('[feature_log_panel] rollback failed:', err)
      rollbackBtn.disabled = false
    }
  })

  // ── Rebuild list ───────────────────────────────────────────────────────────
  function _rebuild(design) {
    listEl.innerHTML = ''
    const log         = design?.feature_log ?? []
    const deformMap   = Object.fromEntries((design?.deformations ?? []).map(d => [d.id, d]))
    const clusterMap  = Object.fromEntries((design?.cluster_transforms ?? []).map(c => [c.id, c]))

    // Find last non-checkpoint index to enable rollback button.
    const lastOpIdx = (() => {
      for (let i = log.length - 1; i >= 0; i--) {
        if (log[i].feature_type !== 'checkpoint') return i
      }
      return -1
    })()
    rollbackBtn.disabled = lastOpIdx < 0

    if (log.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#6e7681;font-size:11px;padding:4px 0'
      empty.textContent = 'No features recorded yet.'
      listEl.appendChild(empty)
      return
    }

    log.forEach((entry, i) => {
      if (entry.feature_type === 'checkpoint') {
        // Checkpoint divider
        const row = document.createElement('div')
        row.style.cssText = [
          'display:flex;align-items:center;gap:6px;padding:5px 0',
          'border-top:1px solid #30363d;border-bottom:1px solid #30363d',
          'margin:4px 0;color:#58a6ff;font-size:11px',
        ].join(';')
        const icon = document.createElement('span')
        icon.textContent = '⚑'
        const label = document.createElement('span')
        label.textContent = entry.name || 'Checkpoint'
        row.appendChild(icon)
        row.appendChild(label)
        listEl.appendChild(row)
        return
      }

      // Deformation or cluster op row
      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:8px',
        'padding:4px 0;font-size:11px;color:#c9d1d9',
        i === lastOpIdx ? 'font-weight:600' : '',
      ].join(';')

      const icon  = document.createElement('span')
      const label = document.createElement('span')
      label.style.flex = '1'

      if (entry.feature_type === 'deformation') {
        const op = deformMap[entry.deformation_id]
        icon.textContent  = op?.type === 'bend' ? '↪' : '↺'
        const range = op ? `bp ${op.plane_a_bp}–${op.plane_b_bp}` : '(removed)'
        const name  = op?.type
          ? (op.type.charAt(0).toUpperCase() + op.type.slice(1))
          : 'Deformation'
        label.textContent = `${name}  ${range}`
      } else {
        // cluster_op
        const cluster = clusterMap[entry.cluster_id]
        icon.textContent  = '⟳'
        const clusterName = cluster?.name ?? entry.cluster_id.slice(0, 8)
        label.textContent = `Transform  ${clusterName}`
      }

      row.appendChild(icon)
      row.appendChild(label)
      listEl.appendChild(row)
    })
  }

  // ── Reactivity ─────────────────────────────────────────────────────────────
  store.subscribeSlice('design', (n, p) => {
    if (n.currentDesign === p.currentDesign) return
    if (!_collapsed) _rebuild(n.currentDesign)
  })

  // Initial render
  _rebuild(store.getState().currentDesign)
}
