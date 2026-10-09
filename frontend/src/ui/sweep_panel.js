import { createToolPopup } from './tool_popup.js'
import { initSweepPoints } from './sweep_points.js'
import { createSweepPreview } from '../scene/sweep_preview.js'
import { resolveExtrudeSourcePlane } from './extrude_source_plane.js'
import './sweep_panel.css'

export function initSweepPanel({ store, api, slicePlane, scene, extrudePanel, expandedSpacing, showToast, getDocId = () => null, setPreviewHelices, canvas, getCamera, getControls, addFrameCallback, removeFrameCallback }) {
  const panel = document.createElement('div')
  panel.id = 'sweep-panel'; panel.className = 'panel-section'; panel.style.display = 'none'
  panel.innerHTML = `<h2>Sweep</h2>
    <p id="sweep-step" role="status">Step 1/2 · Select lattice cells</p>
    <div id="sweep-footprint"><fieldset class="tool-section"><legend>Extrude from source</legend>
      <div class="def-row"><label for="sweep-source">From</label><select id="sweep-source"><option value="">New bundle</option></select></div>
      <div class="def-row"><label for="sweep-plane">Plane</label><select id="sweep-plane"><option>XY</option><option>XZ</option><option>YZ</option></select></div>
      <p class="tool-help" id="sweep-count">Select cells on the lattice plane.</p>
    </fieldset>
    <fieldset class="tool-section"><legend>Strands</legend>
      <div class="def-row"><label for="sweep-strands">Include</label><select id="sweep-strands"><option value="both">Both</option><option value="scaffold">Scaffold</option><option value="staples">Staples</option></select></div>
      <label><input id="sweep-ligate" type="checkbox" checked> Ligate adjacent</label>
    </fieldset>
    </div><fieldset id="sweep-path" class="tool-section" hidden><legend>Path</legend><div id="sweep-point-editor"></div></fieldset>
    <div class="sweep-info" id="sweep-info" role="status" hidden>New BP: <strong id="sweep-total-bp">—</strong></div>
    <p class="tool-help" id="sweep-status" role="status"></p>
    <details id="sweep-conflicts" hidden><summary></summary><ul></ul></details>
    <div class="def-btn-row"><button class="def-btn" id="sweep-cancel">Cancel</button><button class="def-btn primary" id="sweep-apply">Next</button></div>`
  const el = id => panel.querySelector(`#sweep-${id}`)
  const sourceSelect = el('source'), planeSelect = el('plane'), status = el('status'), apply = el('apply')
  const popup = createToolPopup({ panel, title: 'Sweep', onClose: hide })
  const preview = createSweepPreview(scene, { setPreviewHelices, canvas, getCamera, getControls, addFrameCallback, removeFrameCallback,
    onSelect: index => editor.select(index), onOrient: (index, value) => editor.orient(index, value), canOrient: index => editor.canOrient(index), onMove: (index, value) => editor.move(index, value) })
  const editor = initSweepPoints(el('point-editor'), () => { resetPathDirection = false; schedulePreview() }, index => preview.select(index), index => preview.getOrientation(index))
  let active = false, busy = false, editing = null, cells = [], source = null, sources = []
  let epoch = 0, timer = null, pin = {}, sweepId = null, updatingPicker = false, needsSourceFrame = false
  let previousPreview = true, resetPathDirection = false, step = 1, sourceFrame = null

  function body() {
    return { ...(sweepId ? { sweep_id: sweepId } : {}), cells, points_nm: editor.getPoints(), orientations_deg: editor.getOrientations(), plane: planeSelect.value,
      strand_filter: el('strands').value, ligate_adjacent: el('ligate').checked,
      source_helix_id: source?.id ?? null, source_end: source?.end ?? 'end', ...pin }
  }
  function hide() {
    if (!active) return
    active = false; epoch++; clearTimeout(timer)
    el('conflicts').hidden = true; el('conflicts').open = false
    store.setState({ sweepActive: false })
    preview.clear(); popup.hide(); slicePlane.hide()
    slicePlane.setPreviewEnabled(previousPreview)
    slicePlane.setExtrudeUiOpen(false)
  }
  function schedulePreview() {
    if (!active || updatingPicker || busy) return
    clearTimeout(timer); epoch++; apply.disabled = true
    el('total-bp').textContent = '…'
    status.textContent = cells.length ? 'Updating path…' : 'Select at least one lattice cell.'
    if (step === 2) preview.updateDraft(editor.getPoints(), editor.getOrientations(), editor.getSelected())
    if (!cells.length) preview.clearGeometry()
    if (cells.length) timer = setTimeout(refreshPreview, 120)
  }
  async function refreshPreview() {
    const version = epoch
    const request = body()
    if (step === 1) { request.points_nm = [[0, 0, 0], defaultDirection()]; request.orientations_deg = null }
    delete request.expected_revision // Preview resolves the latest source without mutating it.
    if (request.points_nm.some(p => p.some(v => !Number.isFinite(v)))) { preview.clearGeometry(); status.textContent = 'Enter a finite number for X, Y and Z.'; return }
    if (request.points_nm.length < 2) { preview.clearGeometry(); status.textContent = 'Add a second point to define the path.'; return }
    try {
      const response = editing == null ? await api.previewSweep(request) : await api.previewSweep(request, editing)
      if (!active || version !== epoch) return
      if (!response) throw new Error(store.getState().lastError?.message ?? 'Invalid sweep path')
      if (Number.isSafeInteger(response.revision)) pin.expected_revision = response.revision
      sourceFrame = response.source_frame ?? null
      if (resetPathDirection && source && response.source_frame) {
        resetPathDirection = false
        editor.setPoints([[0, 0, 0], response.source_frame.axis_dir.map(v => v * (source.end === 'start' ? -10 : 10))])
        schedulePreview(); return
      }
      if (step === 2) { preview.update(response, request); preview.select(editor.getSelected()) }
      el('total-bp').textContent = (response.total_new_bp ?? response.length_bp * cells.length).toLocaleString()
      status.textContent = step === 1 ? `${cells.length} lattice cells selected.` : `${response.length_nm.toFixed(2)} nm · ${response.length_bp} bp per helix`
      if (step === 1 && source && needsSourceFrame && response.source_frame) {
        updatingPicker = true
        slicePlane.showDeformed(response.source_frame, { plane: planeSelect.value, continuation: true, refHelixId: source.id, allowOrbit: true })
        slicePlane.setSelectedCells(cells)
        updatingPicker = false; needsSourceFrame = false
      }
      if (step === 2 && response.feasibility?.status === 'warning') status.textContent += ` · Warning: ${response.feasibility.message}`
      const conflicts = response.edit_warnings ?? []
      el('conflicts').hidden = !conflicts.length
      el('conflicts').querySelector('summary').textContent = `${conflicts.length} item(s) need review`
      el('conflicts').querySelector('ul').replaceChildren(...conflicts.map(text => { const li = document.createElement('li'); li.textContent = text; return li }))
      apply.disabled = false
    } catch (error) {
      if (active && version === epoch) { preview.clearGeometry(); status.textContent = error.message; apply.disabled = true }
    }
  }
  function showPicker(selected = []) {
    updatingPicker = true
    slicePlane.hide()
    slicePlane.show(planeSelect.value, 0, false, false, { latticeType: store.getState().currentDesign?.lattice_type ?? 'HONEYCOMB', newBundle: true })
    slicePlane.setSelectedCells(selected)
    cells = selected.map(c => [...c])
    updatingPicker = false
    el('count').textContent = `${cells.length} helices · select cells on the plane`
  }
  function defaultDirection() {
    const axis = sourceFrame?.axis_dir ?? (planeSelect.value === 'XY' ? [0, 0, 1] : planeSelect.value === 'XZ' ? [0, 1, 0] : [1, 0, 0])
    return axis.map(v => v * (source?.end === 'start' ? -10 : 10))
  }
  function setStep(value) {
    step = value; epoch++; clearTimeout(timer); preview.clear()
    el('footprint').hidden = step !== 1; el('path').hidden = step !== 2; el('info').hidden = step !== 2
    el('step').textContent = step === 1 ? 'Step 1/2 · Select lattice cells' : 'Step 2/2 · Define sweep path'
    el('cancel').textContent = step === 1 ? 'Cancel' : 'Previous'
    apply.textContent = step === 1 ? 'Next' : 'Confirm'
    if (step === 2) {
      editor.setOrientations(editor.getOrientations(), !!source)
      updatingPicker = true; slicePlane.hide(); updatingPicker = false
    } else {
      showPicker(cells); needsSourceFrame = !!source
    }
    schedulePreview()
  }
  function populateSources() {
    const design = store.getState().currentDesign
    sources = []
    sourceSelect.replaceChildren(new Option('New bundle', ''))
    for (const h of design?.helices ?? []) {
      if (!h.grid_pos) continue
      for (const end of ['start', 'end']) {
        const index = sources.push({ id: h.id, end, helix: h }) - 1
        sourceSelect.append(new Option(`${h.label ?? `Helix ${Math.floor(index / 2) + 1} (${h.grid_pos.join(', ')})`} · ${end}`, String(index)))
      }
    }
  }
  function activate() {
    const state = store.getState()
    if (state.assemblyActive) {
      const instance = state.currentAssembly?.instances?.find(i => i.id === state.activeInstanceId)
      if (!instance) { showToast?.('Select the assembly part that will own the sweep.'); return false }
      const doc = getDocId(), partDoc = `pe-${doc ?? 'default'}-${instance.id}`
      const query = new URLSearchParams({ 'part-instance': instance.id, doc: partDoc })
      if (doc) query.set('assembly-doc', doc)
      window.open(`/?${query}`, `nadoc-part-${instance.id}`)
      showToast?.('Add the sweep in this part’s editor; save it back to the assembly when ready.')
      return false
    }
    if (!state.currentDesign) { showToast?.('Create or open a part before sweeping.'); return false }
    if (active) hide()
    extrudePanel.hide(); expandedSpacing?.forceOff?.()
    previousPreview = slicePlane.isPreviewEnabled?.() ?? true
    slicePlane.setPreviewEnabled(false); slicePlane.setExtrudeUiOpen(false)
    active = true; editing = null; resetPathDirection = false; sweepId = crypto.randomUUID(); source = null; needsSourceFrame = false
    sourceFrame = null; store.setState({ sweepActive: true })
    pin = { expected_design_id: state.currentDesign.id }
    populateSources()
    planeSelect.value = resolveExtrudeSourcePlane(state.currentDesign, state.currentPlane).plane
    planeSelect.disabled = false; sourceSelect.disabled = false
    el('strands').value = 'both'; el('ligate').checked = true
    editor.setPoints([[0, 0, 0], planeSelect.value === 'XY' ? [0, 0, 10] : planeSelect.value === 'XZ' ? [0, 10, 0] : [10, 0, 0]])
    cells = []; popup.setTitle('Sweep'); popup.show(); setStep(1)
    return true
  }
  function edit(entry, index) {
    if (!activate()) return
    editing = index
    const p = entry.params
    sweepId = p.sweep_id
    planeSelect.value = p.plane; planeSelect.disabled = true; sourceSelect.disabled = true
    source = sources.find(s => s.id === p.source_helix_id && s.end === p.source_end) ?? null
    sourceSelect.value = source ? String(sources.indexOf(source)) : ''
    needsSourceFrame = !!source
    editor.setPoints(p.points_nm)
    editor.setOrientations(p.orientations_deg, !!p.source_helix_id)
    el('strands').value = p.strand_filter ?? 'both'; el('ligate').checked = p.ligate_adjacent ?? true
    popup.setTitle('Edit Sweep'); cells = p.cells.map(c => [...c]); setStep(2)
  }
  function changeSource() {
    sourceFrame = null
    source = sourceSelect.value === '' ? null : sources[Number(sourceSelect.value)]
    planeSelect.disabled = !!source
    let selected = []
    if (source) {
      const design = store.getState().currentDesign
      planeSelect.value = design.lattice_frames?.find(f => f.id === source.helix.lattice_frame_id)?.plane ?? resolveExtrudeSourcePlane({ helices: [source.helix] }).plane
      selected = [source.helix.grid_pos]
      const track = store.getState().currentHelixAxes?.[source.id]?.samples
      const start = track?.length > 1 ? (source.end === 'end' ? track.at(-2) : track[0]) : ['x','y','z'].map(a => source.helix.axis_start[a])
      const end = track?.length > 1 ? (source.end === 'end' ? track.at(-1) : track[1]) : ['x','y','z'].map(a => source.helix.axis_end[a])
      const tangent = end.map((v, i) => v - start[i]), norm = Math.hypot(...tangent)
      editor.setPoints([[0, 0, 0], tangent.map(v => v / (norm || 1) * (source.end === 'start' ? -10 : 10))])
      needsSourceFrame = true; resetPathDirection = true
    } else {
      needsSourceFrame = false; resetPathDirection = false
      editor.setPoints([[0,0,0], defaultDirection()])
    }
    showPicker(selected); schedulePreview()
  }
  sourceSelect.addEventListener('change', changeSource)
  planeSelect.addEventListener('change', () => { sourceFrame = null; editor.setPoints([[0,0,0], defaultDirection()]); showPicker(); schedulePreview() })
  for (const id of ['strands', 'ligate']) el(id).addEventListener('change', schedulePreview)
  el('cancel').addEventListener('click', () => { if (!busy) { if (step === 2) setStep(1); else hide() } })
  apply.addEventListener('click', async () => {
    if (busy || apply.disabled || !active) return
    if (step === 1) { setStep(2); return }
    busy = true; apply.disabled = true; status.textContent = 'Building sweep…'
    try {
      const request = body()
      // Saving workspace metadata can advance the revision without replacing
      // the design object. Refresh the guarded preview before using that draft.
      const revision = api.currentRevisionWatermark?.()
      if (Number.isSafeInteger(revision) && revision !== request.expected_revision) {
        const fresh = { ...request }; delete fresh.expected_revision
        const evaluated = editing == null ? await api.previewSweep(fresh) : await api.previewSweep(fresh, editing)
        if (!evaluated || !Number.isSafeInteger(evaluated.revision)) throw new Error('Refresh the sweep preview before confirming.')
        if (!active) return
        request.expected_revision = pin.expected_revision = evaluated.revision
      }
      const result = editing == null ? await api.createSweep(request) : await api.editFeature(editing, request)
      if (!result) throw new Error(store.getState().lastError?.message ?? 'Sweep failed')
      hide()
    } catch (error) { status.textContent = error.message }
    finally { busy = false; if (active) apply.disabled = false }
  })
  const unsubscribeSelection = slicePlane.subscribeSelection(selected => {
    if (!active || updatingPicker || step !== 1) return
    cells = selected; el('count').textContent = `${cells.length} helices · select cells on the plane`; schedulePreview()
  })
  const unsubscribe = store.subscribe((state, previous) => {
    if (active && (state.currentDesign?.id !== previous.currentDesign?.id || state.assemblyActive !== previous.assemblyActive)) hide()
    else if (active && !busy && state.currentDesign !== previous.currentDesign) schedulePreview()
  })
  const escape = event => { if (active && event.key === 'Escape' && !busy) hide() }
  const launch = () => { if (!busy) activate() }
  const otherTool = event => { if (active && event.target.closest('[id^=menu-tools-]') && event.target.id !== 'menu-tools-sweep') hide() }
  document.addEventListener('click', otherTool, true)
  const menu = document.getElementById('menu-tools-sweep')
  menu?.addEventListener('click', launch); window.addEventListener('keydown', escape)
  function activateFromEnd(info) {
    const helix = store.getState().currentDesign?.helices?.find(h => h.id === info.helixId)
    const end = info.openSide < 0 ? 'start' : 'end'
    const endpoint = helix ? (helix.bp_start ?? 0) + (end === 'end' ? helix.length_bp - 1 : 0) : null
    if (!helix || info.bp !== endpoint) { showToast?.('Sweep requires a terminal helix end.'); return }
    if (!activate()) return
    sourceSelect.value = String(sources.findIndex(s => s.id === info.helixId && s.end === end))
    changeSource()
  }
  return { activate, activateFromEnd, edit, hide, isActive: () => active,
    dispose() { hide(); unsubscribe?.(); unsubscribeSelection?.(); preview.dispose(); popup.dispose(); document.removeEventListener('click', otherTool, true); menu?.removeEventListener('click', launch); window.removeEventListener('keydown', escape) } }
}
