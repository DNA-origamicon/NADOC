import { beginClusterSelection } from './tool_cluster_selection.js'
import * as THREE from 'three'
import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { canonicalSelection, selectedClusterIds } from '../scene/selection_model.js'
import { clusterMemberFilter } from '../scene/cluster_entries.js'
import { clusterLattice, latticeAligned, latticeCoordinates, latticePoint, snapToLattice, patternAngles } from './circular_pattern_math.js'
import { createCircularPattern } from '../api/client.js'
import './circular_pattern_panel.css'

// Preview state stays local until Confirm commits the pattern.
export function circularPatternTarget(state) {
  if (state.assemblyActive || canonicalSelection(state).context === 'assembly') return null
  const selection = canonicalSelection(state)
  const ids = selectedClusterIds(state)
  if (selection.items.some(ref => ref.kind !== 'cluster')) return null
  if (!ids.length && state.activeClusterId) ids.push(state.activeClusterId)
  if (ids.length !== 1) return null
  return circularPatternCluster(state, ids[0])
}

export function circularPatternCluster(state, id) {
  const cluster = state.currentDesign?.cluster_transforms?.find(c => c.id === id)
  const contains = clusterMemberFilter(cluster, state.currentDesign)
  const points = contains ? (state.currentGeometry ?? []).filter(contains)
    .map(n => n.backbone_position).filter(p => p?.length === 3 && p.every(Number.isFinite)) : []
  if (!points.length) return null
  const center = points.reduce((sum, p) => sum.map((v, i) => v + p[i] / points.length), [0, 0, 0])
  return { cluster, center, points: points.map(p => p.map((v, i) => v - center[i])) }
}

export function circularPatternBPTotals(design, cluster, count) {
  if (!Number.isInteger(count) || count < 1 || count > 128) return null
  const ids = new Set(cluster.helix_ids ?? [])
  const helices = design.helices ?? []
  const source = helices.filter(h => ids.has(h.id)).reduce((sum, h) => sum + h.length_bp, 0)
  const created = source * (count - 1)
  return { created, total: helices.reduce((sum, h) => sum + h.length_bp, 0) + created }
}

export function normalizedAxis(point, direction) {
  if (![...point, ...direction].every(Number.isFinite)) return null
  const length = Math.hypot(...direction)
  if (!Number.isFinite(length) || length < 1e-8) return null
  return { point: [...point], direction: direction.map(v => v / length) }
}

export function beginCircularPatternSelection(options) {
  return beginClusterSelection({ ...options, resolveTarget: circularPatternTarget })
}

export function initCircularPatternPanel({ store, showToast, selectionManager, scene, canvas, getCamera, getControls, addFrameCallback, removeFrameCallback, commitPattern = createCircularPattern }) {
  const panel = document.getElementById('circular-pattern-panel')
  if (!panel) return null
  let picking = null
  let disposePreview = null
  let popup = null
  let committing = false
  const reveal = () => popup?.show()
  const close = () => {
    if (committing) return
    const pending = picking
    picking = null
    pending?.cancel()
    disposePreview?.()
    disposePreview = null
    popup?.dispose()
    popup = null
    document.body.append(panel)
    panel.replaceChildren()
    panel.style.display = 'none'
    document.removeEventListener('keydown', onKeyDown, true)
  }
  const onKeyDown = event => {
    if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('.modal__overlay')) return
    event.preventDefault()
    event.stopPropagation()
    close()
  }
  const showPreview = selectedTarget => {
    const state = store.getState()
    let target = selectedTarget ?? circularPatternTarget(state)
    if (!target) {
      showToast('Select exactly one cluster in a part with loaded geometry to explore rotation axes.', { severity: 'info' })
      return
    }
    const initialDesign = state.currentDesign, initialGeometry = state.currentGeometry
    let frame = clusterLattice(state, target)
    let radius = target.points.reduce((r, p) => Math.max(r, Math.hypot(...p)), 5)
    let point = frame ? frame.u.clone().multiplyScalar(radius * 1.4).toArray() : [radius * 1.4, 0, 0]
    let direction = frame ? frame.normal.toArray() : [0, 0, 1]
    let count = 6, degrees = 360, dragging = null
    const controlsPane = el('div', { className: 'cp-controls' })
    let directionMode = frame ? 'Helices' : 'Z', centered = false
    let offsetPoint = [...point]
    const targets = state.currentDesign.cluster_transforms.map(c => circularPatternCluster(state, c.id)).filter(Boolean)
    let reference = targets.find(t => t.cluster.id !== target.cluster.id)
    const readout = el('div', { className: 'cp-readout', attrs: { 'aria-live': 'polite' } })
    const snap = el('input', { attrs: { type: 'checkbox', 'aria-label': 'Snap to lattice' } })
    const bead = el('button', { className: 'cp-bead', attrs: { type: 'button', 'aria-label': 'Move rotation axis', title: 'Drag to move the axis in its perpendicular plane' } })
    const body = el('div', { className: 'cp-panel-body ox-card__body', children: [controlsPane, readout] })
    const preview = new THREE.Group()
    preview.name = 'circularPatternPreview'
    preview.position.set(...target.center)
    scene.add(preview)
    document.body.append(bead)
    let cloudGeometry = new THREE.BufferGeometry().setFromPoints(target.points.map(p => new THREE.Vector3(...p)))
    const copyMaterial = new THREE.PointsMaterial({ color: '#9fa9ef', size: Math.max(0.2, radius / 100), transparent: true, opacity: .42, depthWrite: false })
    const copies = new THREE.Group()
    preview.add(copies)
    const axisLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#ffbf58' }))
    const ring = new THREE.LineLoop(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: '#ffbf58', dashSize: radius / 16, gapSize: radius / 25, transparent: true, opacity: .4 }))
    // Lattice sites are actual helix-axis positions, including honeycomb staggering.
    const lattice = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: '#a8c6b7', size: 3, sizeAttenuation: false, transparent: true, opacity: .23, depthWrite: false }))
    preview.add(axisLine, ring, lattice)
    function render() {
      const camera = getCamera(), rect = canvas.getBoundingClientRect()
      camera.updateMatrixWorld()
      const projected = new THREE.Vector3(...point).add(preview.position).project(camera)
      bead.hidden = centered || committing || !(normalizedAxis(point, direction) && projected.z > -1 && projected.z < 1 && Math.abs(projected.x) < 1 && Math.abs(projected.y) < 1)
      bead.style.left = `${rect.left + (projected.x + 1) * rect.width / 2}px`
      bead.style.top = `${rect.top + (1 - projected.y) * rect.height / 2}px`
    }
    function update() {
      const axis = normalizedAxis(point, direction), angles = patternAngles(count, degrees)
      const aligned = !!axis && latticeAligned(frame, direction)
      confirm.disabled = committing || !axis || !angles
      const bp = circularPatternBPTotals(state.currentDesign, target.cluster, count)
      newBP.textContent = bp ? bp.created.toLocaleString() : '—'
      totalBP.textContent = bp ? bp.total.toLocaleString() : '—'
      snap.disabled = !aligned
      if (!aligned) snap.checked = false
      snap.parentElement.title = aligned ? 'Snap the axis to helical lattice sites' : 'Align the direction with a consistent helical lattice to enable snapping'
      directionButtons.forEach((button, name) => {
        button.setAttribute('aria-pressed', String(name === directionMode))
        button.disabled = name === 'Helices' && !frame
      })
      axisLine.visible = ring.visible = !!axis
      lattice.visible = aligned && !centered
      copies.visible = !!axis && !!angles
      if (!axis) {
        readout.hidden = false
        readout.textContent = 'Enter finite offsets.'
        render(); return
      }
      const p = new THREE.Vector3(...point), d = new THREE.Vector3(...axis.direction)
      const reach = Math.max(radius * 2, p.length() * 1.3)
      axisLine.geometry.dispose()
      axisLine.geometry = new THREE.BufferGeometry().setFromPoints([p.clone().addScaledVector(d, -reach), p.clone().addScaledVector(d, reach)])
      const center = p.clone().addScaledVector(d, -p.dot(d)), offset = center.clone().negate()
      ring.geometry.dispose()
      ring.geometry = new THREE.BufferGeometry().setFromPoints(Array.from({ length: 128 }, (_, i) => offset.clone().applyAxisAngle(d, i * Math.PI * 2 / 128).add(center)))
      ring.computeLineDistances()
      if (aligned) {
        const { row, col } = latticeCoordinates(frame, point)
        const sites = []
        // Keep a bounded patch around the movable bead, also showing the source
        // when nearby; all displayed sites and snapping use the same cell math.
        const extent = Math.min(65, Math.max(12, Math.ceil(radius / 2)))
        for (let r = row - extent; r <= row + extent; r++) for (let c = col - extent; c <= col + extent; c++) sites.push(latticePoint(frame, r, c, point))
        lattice.geometry.dispose()
        lattice.geometry = new THREE.BufferGeometry().setFromPoints(sites)
      }
      if (angles) {
        while (copies.children.length > angles.length - 1) copies.remove(copies.children.at(-1))
        while (copies.children.length < angles.length - 1) copies.add(new THREE.Points(cloudGeometry, copyMaterial))
        copies.children.forEach((copy, i) => {
          copy.quaternion.setFromAxisAngle(d, angles[i + 1])
          copy.position.copy(p).sub(p.clone().applyQuaternion(copy.quaternion))
        })
      }
      preview.userData.instances = angles?.length ?? 0
      preview.userData.axisPoint = [...point]
      preview.userData.sourceClusterId = target.cluster.id
      preview.userData.centerClusterId = centered ? reference?.cluster.id : null
      preview.userData.latticeVisible = aligned
      preview.traverse(object => { object.raycast = () => {} })
      readout.hidden = !!angles
      readout.textContent = angles ? '' : 'Enter an integer instance count from 1 to 128 and an angle greater than 0° and at most 360°.'
      render()
    }
    function numbers(title, values, changed) {
      const inputs = []
      const row = el('fieldset', { children: [el('legend', { text: title })] })
      values.forEach((value, i) => {
        const input = el('input', { attrs: { type: 'number', step: '0.001', value: Number(value.toFixed(3)), 'aria-label': `${title} ${['X', 'Y', 'Z'][i]}` }, on: {
          input: event => { values[i] = event.target.value === '' ? NaN : Number(Number(event.target.value).toFixed(3)); if (event.target.value.includes('.') && event.target.value.split('.')[1].length > 3) event.target.value = values[i]; offsetPoint = [...point]; update() },
          change: () => changed?.(),
        } })
        inputs.push(input)
        row.append(el('label', { children: [['X', 'Y', 'Z'][i], input] }))
      })
      controlsPane.append(row)
      return inputs
    }
    function syncInputs() {
      positionInputs.forEach((input, i) => { input.value = Number.isFinite(point[i]) ? Number(point[i].toFixed(3)) : '' })
    }
    function applySnap() {
      if (snap.checked && latticeAligned(frame, direction) && point.every(Number.isFinite)) point.splice(0, 3, ...snapToLattice(frame, point))
      if (!centered) offsetPoint = [...point]
      syncInputs(); update()
    }
    const sourceSelect = el('select', { className: 'input input--sm', attrs: { 'aria-label': 'Cluster', title: 'Cluster to repeat' } })
    const centerSelect = el('select', { className: 'input input--sm', attrs: { 'aria-label': 'Center cluster', title: 'Place the rotation axis through this cluster’s backbone centroid' } })
    const fillSelect = (select, choices, id) => {
      select.replaceChildren(...choices.map(t => el('option', { text: t.cluster.name || t.cluster.id, attrs: { value: t.cluster.id } })))
      select.value = id ?? ''
    }
    fillSelect(sourceSelect, targets, target.cluster.id)
    const centerRow = el('label', { children: ['Center cluster', centerSelect] })
    centerRow.hidden = true
    const centerButton = el('button', { text: 'Centered about', attrs: { 'aria-pressed': 'false', title: 'Place the axis through another cluster’s centroid' } })
    const offsetButton = el('button', { text: 'Offset', attrs: { 'aria-pressed': 'true', title: 'Position the axis by offsets in part coordinates or drag the amber bead' } })
    centerButton.disabled = targets.length < 2
    function setCentered(value) {
      if (value && !reference) return
      if (value && !centered) offsetPoint = [...point]
      centered = value
      centerButton.setAttribute('aria-pressed', String(value))
      offsetButton.setAttribute('aria-pressed', String(!value))
      centerRow.hidden = !value
      offsetFields.hidden = value
      snapRow.hidden = value
      if (value) {
        point.splice(0, 3, ...reference.center.map((v, i) => v - target.center[i]))
      } else {
        point.splice(0, 3, ...offsetPoint)
      }
      syncInputs(); update()
    }
    function refreshReference() {
      if (!reference || reference.cluster.id === target.cluster.id) reference = targets.find(t => t.cluster.id !== target.cluster.id)
      fillSelect(centerSelect, targets.filter(t => t.cluster.id !== target.cluster.id), reference?.cluster.id)
    }
    refreshReference()
    sourceSelect.addEventListener('change', () => {
      endDrag()
      target = targets.find(t => t.cluster.id === sourceSelect.value)
      frame = clusterLattice(state, target)
      radius = target.points.reduce((r, p) => Math.max(r, Math.hypot(...p)), 5)
      preview.position.set(...target.center)
      copies.clear(); cloudGeometry.dispose()
      cloudGeometry = new THREE.BufferGeometry().setFromPoints(target.points.map(p => new THREE.Vector3(...p)))
      if (directionMode === 'Helices') {
        if (!frame) directionMode = 'Z'
        direction = frame ? frame.normal.toArray() : [0, 0, 1]
      }
      refreshReference()
      if (centered) setCentered(true)
      else applySnap()
    })
    centerButton.addEventListener('click', () => setCentered(true))
    offsetButton.addEventListener('click', () => setCentered(false))
    centerSelect.addEventListener('change', () => { reference = targets.find(t => t.cluster.id === centerSelect.value); setCentered(true) })
    controlsPane.append(el('label', { children: ['Cluster', sourceSelect] }))
    const directionButtons = new Map()
    const presets = el('fieldset', { className: 'cp-presets', children: [el('legend', { text: 'Direction' })] })
    for (const name of ['X', 'Y', 'Z', 'Helices']) {
      const button = el('button', { text: name, attrs: { 'aria-pressed': String(name === directionMode), title: name === 'Helices' ? 'Use the cluster’s helical axis direction' : `Use the part’s ${name} axis` }, on: { click: () => {
        directionMode = name
        direction = name === 'Helices' ? frame.normal.toArray() : ['X', 'Y', 'Z'].map(axis => Number(axis === name))
        if (centered) update(); else applySnap()
      } } })
      directionButtons.set(name, button); presets.append(button)
    }
    controlsPane.append(presets, el('div', { className: 'cp-presets', children: [offsetButton, centerButton] }), centerRow)
    const positionInputs = numbers('Origin offset (nm)', point, applySnap)
    const offsetFields = positionInputs[0].closest('fieldset')
    positionInputs.forEach(input => {
      input.title = 'Offset from the source cluster’s backbone centroid in part coordinates; drag the amber bead to adjust'
    })
    const snapRow = el('label', { className: 'cp-snap', children: [snap, 'Snap to lattice'] })
    controlsPane.append(snapRow)
    snap.addEventListener('change', () => { if (snap.checked) setCentered(false); applySnap() })
    const pattern = el('fieldset', { children: [el('legend', { text: 'Pattern preview' })] })
    for (const [label, value, min, max, change] of [
      ['Instances', count, 1, 128, value => { count = value }],
      ['Total angle (degrees)', degrees, .001, 360, value => { degrees = value }],
    ]) {
      pattern.append(el('label', { children: [label, el('input', { attrs: { type: 'number', value, min, max, step: label === 'Instances' ? 1 : 'any', 'aria-label': label }, on: { input: event => { change(event.target.value === '' ? NaN : Number(event.target.value)); update() } } })] }))
    }
    pattern.title = 'Count includes the original. Full circles omit the duplicate endpoint; partial arcs include both ends. Violet points preview the copies.'
    const newBP = el('output', { attrs: { 'aria-label': 'New BP created' } })
    const totalBP = el('output', { attrs: { 'aria-label': 'Total after pattern' } })
    const totals = el('div', { className: 'cp-totals', attrs: { 'aria-live': 'polite', title: 'BP = sum of helix lengths. New BP excludes the original instance; total includes the whole part.' }, children: [
      el('label', { children: ['New BP created', newBP] }),
      el('label', { children: ['Total after pattern', totalBP] }),
    ] })
    const confirm = el('button', { text: 'Confirm', className: 'btn--primary', attrs: { title: 'Create the previewed copies as one undoable operation' }, on: { click: async () => {
      const axis = normalizedAxis(point, direction)
      if (committing || !axis || !patternAngles(count, degrees)) return
      committing = true
      endDrag()
      const controls = [...body.querySelectorAll('input, select, button')]
      controls.forEach(control => { control.disabled = true })
      confirm.textContent = 'Creating…'
      render()
      try {
        await commitPattern({ cluster_id: target.cluster.id, instances: count, total_angle: degrees,
          axis_point: point.map((v, i) => v + target.center[i]), axis_direction: axis.direction })
        committing = false; close()
      } catch (error) {
        committing = false
        controls.forEach(control => { control.disabled = false })
        centerButton.disabled = targets.length < 2
        confirm.textContent = 'Confirm'
        update()
        readout.hidden = false; readout.textContent = error.message
      }
    } } })
    const cancel = el('button', { text: 'Cancel', on: { click: close } })
    controlsPane.append(pattern, totals, el('div', { className: 'cp-actions', children: [cancel, confirm] }))
    const ray = new THREE.Raycaster(), pointer = new THREE.Vector2()
    const hitPlane = event => {
      const rect = canvas.getBoundingClientRect()
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2)
      ray.setFromCamera(pointer, getCamera())
      return ray.ray.intersectPlane(dragging.plane, new THREE.Vector3())
    }
    bead.addEventListener('pointerdown', event => {
      if (event.button !== 0 || centered || committing) return
      const axis = normalizedAxis(point, direction)
      if (!axis) return
      event.preventDefault(); event.stopPropagation()
      dragging = { plane: new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3(...axis.direction), new THREE.Vector3(...point).add(preview.position)) }
      const hit = hitPlane(event)
      if (!hit) { dragging = null; return }
      dragging.offset = new THREE.Vector3(...point).add(preview.position).sub(hit)
      dragging.controls = getControls()
      dragging.wasEnabled = dragging.controls.enabled
      dragging.controls.enabled = false
      bead.setPointerCapture(event.pointerId)
      bead.classList.add('is-dragging')
    })
    bead.addEventListener('pointermove', event => {
      if (!dragging) return
      const hit = hitPlane(event)
      if (!hit) return
      point.splice(0, 3, ...hit.add(dragging.offset).sub(preview.position).toArray())
      applySnap()
    })
    const endDrag = () => { if (dragging?.controls) dragging.controls.enabled = dragging.wasEnabled; dragging = null; bead.classList.remove('is-dragging') }
    bead.addEventListener('pointerup', event => { if (bead.hasPointerCapture(event.pointerId)) bead.releasePointerCapture(event.pointerId); endDrag() })
    bead.addEventListener('pointercancel', endDrag)
    bead.addEventListener('lostpointercapture', endDrag)
    let unsubscribe
    disposePreview = () => {
      unsubscribe?.(); removeFrameCallback(render); endDrag(); bead.remove(); preview.removeFromParent()
      const geometries = new Set(), materials = new Set()
      preview.traverse(object => { if (object.geometry) geometries.add(object.geometry); if (object.material) materials.add(object.material) })
      geometries.forEach(geometry => geometry.dispose()); materials.forEach(material => material.dispose())
      if (!materials.has(copyMaterial)) copyMaterial.dispose()
      if (!geometries.has(cloudGeometry)) cloudGeometry.dispose()
    }
    for (const button of body.querySelectorAll('button:not(.cp-bead)')) {
      button.classList.add('btn', 'btn--sm')
      button.type = 'button'
    }
    for (const input of body.querySelectorAll('input[type="number"]')) input.classList.add('input', 'input--sm')
    panel.replaceChildren(body)
    popup = createToolPopup({ panel, title: 'Circular Pattern', onClose: close })
    reveal(); update(); addFrameCallback(render)
    document.addEventListener('keydown', onKeyDown, true)
    unsubscribe = store.subscribe((next, previous) => {
      if (committing) return
      if (next.assemblyActive === previous.assemblyActive && next.selection === previous.selection && next.activeClusterId === previous.activeClusterId && next.currentDesign === previous.currentDesign && next.currentGeometry === previous.currentGeometry) return
      if (next.assemblyActive || next.currentDesign?.id !== initialDesign.id || next.currentGeometry !== initialGeometry || next.currentDesign?.cluster_transforms !== initialDesign.cluster_transforms) close()
    })
  }
  const open = () => {
    if (disposePreview || picking) { reveal(); return }
    const state = store.getState()
    if (state.assemblyActive || !state.currentDesign?.cluster_transforms?.length || !state.currentGeometry?.length) {
      showToast('Open a part with a cluster before creating a circular pattern.', { severity: 'info' })
      return
    }
    panel.replaceChildren(el('div', { className: 'ox-card__body', children: [
      el('p', { className: 'tool-picking-hint', text: 'Select a cluster', attrs: { 'aria-live': 'polite', title: 'Select in the 3D view or cluster list. Selection returns to Default automatically.' } }),
      el('button', { className: 'btn btn--sm', text: 'Cancel', attrs: { type: 'button' }, on: { click: close } }),
    ] }))
    popup = createToolPopup({ panel, title: 'Circular Pattern', onClose: close })
    picking = beginCircularPatternSelection({ store, selectionManager,
      onSelected: target => { close(); showPreview(target) }, onCancelled: close,
    })
    reveal()
    document.addEventListener('keydown', onKeyDown, true)
  }
  document.getElementById('menu-tools-circular-pattern')?.addEventListener('click', open)
  return { open, close, isActive: () => !!disposePreview || !!picking }
}
