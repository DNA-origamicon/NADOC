import * as THREE from 'three'
import { beginCircularPatternSelection, circularPatternCluster, circularPatternBPTotals } from './circular_pattern_panel.js'
import { createLinearPattern } from '../api/client.js'
import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { createLinearPatternControls, linearPatternDefaults, linearPatternSection } from './linear_pattern_controls.js'
import { linearPatternOffsets } from './linear_pattern_math.js'
import './circular_pattern_panel.css'

export function initLinearPatternPanel({ store, showToast, selectionManager, scene, commitPattern = createLinearPattern }) {
  const panel = document.getElementById('linear-pattern-panel')
  if (!panel) return null
  let picking, popup, dispose, committing = false
  const close = () => {
    if (committing) return
    picking?.cancel(); picking = null
    dispose?.(); dispose = null
    popup?.dispose(); popup = null
    document.body.append(panel); panel.replaceChildren(); panel.style.display = 'none'
    document.removeEventListener('keydown', onKey, true)
  }
  const onKey = event => {
    if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('.modal__overlay')) return
    event.preventDefault(); event.stopPropagation(); close()
  }
  const show = () => {
    popup = createToolPopup({ panel, title: 'Linear Pattern', onClose: close })
    popup.show(); document.addEventListener('keydown', onKey, true)
  }
  function preview(target) {
    const initial = store.getState()
    const targets = initial.currentDesign.cluster_transforms.map(c => circularPatternCluster(initial, c.id)).filter(Boolean)
    const selected = new Set([target.cluster.id])
    let params = { ...linearPatternDefaults }
    const group = new THREE.Group(); group.name = 'linearPatternPreview'; scene.add(group)
    const material = new THREE.PointsMaterial({ color: '#9fa9ef', size: .3, transparent: true, opacity: .42, depthWrite: false })
    const geometries = new Map(targets.map(t => [t.cluster.id, new THREE.BufferGeometry().setFromPoints(t.points.map(p => new THREE.Vector3(...p)))]))
    const readout = el('div', { className: 'cp-readout', attrs: { 'aria-live': 'polite' } })
    const created = el('output', { attrs: { 'aria-label': 'New BP created' } })
    const total = el('output', { attrs: { 'aria-label': 'Total after pattern' } })
    const confirm = el('button', { className: 'btn btn--sm btn--primary', text: 'Confirm', on: { click: async () => {
      if (confirm.disabled || committing) return
      committing = true
      const inputs = [...panel.querySelectorAll('input, button')]
      inputs.forEach(input => { input.disabled = true }); confirm.textContent = 'Creating…'
      try {
        await commitPattern({ ...params, cluster_ids: [...selected] })
        committing = false; close()
      } catch (error) {
        committing = false; inputs.forEach(input => { input.disabled = false }); confirm.textContent = 'Confirm'
        update(); readout.hidden = false; readout.textContent = error.message
      }
    } } })
    function update() {
      group.clear()
      const offsets = linearPatternOffsets(params), ids = new Set()
      let overlaps = false
      for (const t of targets.filter(t => selected.has(t.cluster.id))) for (const id of t.cluster.helix_ids) {
        if (ids.has(id)) overlaps = true
        ids.add(id)
      }
      const valid = offsets && selected.size && !overlaps
      confirm.disabled = committing || !valid
      if (valid) for (const t of targets.filter(t => selected.has(t.cluster.id))) for (const offset of offsets.slice(1)) {
        const cloud = new THREE.Points(geometries.get(t.cluster.id), material)
        cloud.position.set(...t.center.map((v, i) => v + offset[i])); cloud.raycast = () => {}; group.add(cloud)
      }
      const bp = valid ? circularPatternBPTotals(initial.currentDesign, { helix_ids: [...ids] }, offsets.length) : null
      created.textContent = bp ? bp.created.toLocaleString() : '—'; total.textContent = bp ? bp.total.toLocaleString() : '—'
      group.userData = { instances: offsets?.length ?? 0, clusterIds: [...selected], offsets }
      readout.hidden = !!valid
      readout.textContent = !selected.size ? 'Select at least one cluster.' : overlaps ? 'Selected clusters overlap; select each helix only once.' : 'Use finite, nonzero vectors and spacing, and integer counts; at most 128 total instances. 2D directions must not be parallel.'
    }
    const list = el('div', { className: 'lp-cluster-list', attrs: { role: 'group', 'aria-label': 'Available clusters', tabindex: 0 } })
    const sources = linearPatternSection('Clusters', [list])
    for (const t of targets) {
      const input = el('input', { attrs: { type: 'checkbox', 'aria-label': `Include ${t.cluster.name || t.cluster.id}` }, on: { change: event => { if (event.target.checked) selected.add(t.cluster.id); else selected.delete(t.cluster.id); update() } } })
      input.checked = selected.has(t.cluster.id)
      list.append(el('label', { className: 'cp-snap', children: [input, t.cluster.name || t.cluster.id] }))
    }
    const controls = createLinearPatternControls(params, next => { params = next; update() })
    const totals = el('div', { className: 'cp-totals', children: [el('label', { children: ['New BP created', created] }), el('label', { children: ['Total after pattern', total] })] })
    const cancel = el('button', { className: 'btn btn--sm', text: 'Cancel', on: { click: close } })
    controls.element.prepend(sources)
    const info = linearPatternSection('Info', [el('p', { className: 'lp-help', text: 'Counts include the original. Negative spacing reverses a direction. Custom vectors are normalized; spacing is in nm.' }), totals, readout])
    controls.element.append(info, el('div', { className: 'cp-actions', children: [cancel, confirm] }))
    panel.replaceChildren(el('div', { className: 'cp-panel-body ox-card__body', children: [controls.element] }))
    const unsubscribe = store.subscribe(next => {
      if (!committing && (next.assemblyActive || next.currentDesign !== initial.currentDesign || next.currentGeometry !== initial.currentGeometry)) close()
    })
    dispose = () => { unsubscribe(); group.removeFromParent(); geometries.forEach(g => g.dispose()); material.dispose() }
    show(); update()
  }
  function open() {
    if (popup) { popup.show(); return }
    const state = store.getState()
    if (state.assemblyActive || !state.currentDesign?.cluster_transforms?.length || !state.currentGeometry?.length) {
      showToast('Open a part with a cluster before creating a linear pattern.', { severity: 'info' }); return
    }
    panel.replaceChildren(el('div', { className: 'ox-card__body', children: [el('p', { className: 'tool-picking-hint', text: 'Select a cluster' }), el('button', { className: 'btn btn--sm', text: 'Cancel', on: { click: close } })] }))
    picking = beginCircularPatternSelection({ store, selectionManager, onSelected: target => { close(); preview(target) }, onCancelled: close })
    show()
  }
  document.getElementById('menu-tools-linear-pattern')?.addEventListener('click', open)
  return { open, close, isActive: () => !!popup }
}
