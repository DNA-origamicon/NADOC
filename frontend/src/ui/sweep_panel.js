import { createToolPopup } from './tool_popup.js'
import { initSweepPoints } from './sweep_points.js'
import { createSweepPreview } from '../scene/sweep_preview.js'
import { resolveExtrudeSourcePlane } from './extrude_source_plane.js'
import { createSweepHistoryEditor, isNativeSweepFeature, SWEEP_HISTORY_EDITOR_ENABLED } from '../app/sweep_history_editor.js'
import './sweep_panel.css'

export function initSweepPanel({ store, api, slicePlane, scene, extrudePanel, expandedSpacing, showToast, getDocId = () => null, setPreviewHelices, canvas, getCamera, getControls, addFrameCallback, removeFrameCallback, historyEnabled = SWEEP_HISTORY_EDITOR_ENABLED, createHistoryEditor = createSweepHistoryEditor }) {
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
    <label id="sweep-visual-row" hidden><input id="sweep-visual" type="checkbox" checked> Show feature preview</label>
    <p class="tool-help" id="sweep-status" role="status"></p>
    <details id="sweep-conflicts" hidden><summary></summary><ul></ul></details>
    <div class="def-btn-row"><button class="def-btn" id="sweep-cancel">Cancel</button><button class="def-btn primary" id="sweep-apply">Next</button></div>`
  const el = id => panel.querySelector(`#sweep-${id}`)
  const sourceSelect = el('source'), planeSelect = el('plane'), status = el('status'), apply = el('apply')
  const popup = createToolPopup({ panel, title: 'Sweep', onClose: hide })
  const preview = createSweepPreview(scene, { setPreviewHelices, canvas, getCamera, getControls, addFrameCallback, removeFrameCallback,
    onSelect: index => editor.select(index), onOrient: (index, value) => editor.orient(index, value), canOrient: index => !busy && !locked && editor.canOrient(index), canMove: index => !busy && !locked && editor.canMove(index), onMove: (index, value) => editor.move(index, value) })
  const editor = initSweepPoints(el('point-editor'), () => {
    if (source && !detachedSource && editor.getPoints()[0].some(v => Number.isFinite(v) && v !== 0)) {
      detachedSource = true; editor.setOrientations(editor.getOrientations(), false)
    }
    resetPathDirection = false; schedulePreview()
  }, index => preview.select(index), index => preview.getOrientation(index))
  let active = false, busy = false, cells = [], source = null, sources = []
  let epoch = 0, timer = null, pin = {}, sweepId = null, updatingPicker = false, needsSourceFrame = false
  let detachedSource = false
  let previousPreview = true, resetPathDirection = false, step = 1, sourceFrame = null
  let owned = null, owner = null, locked = false
  const disabledBeforeLock = new Map()
  const controlDesign = () => owned?.design ?? store.getState().currentDesign
  const controlAxes = () => owned?.helixAxes ?? store.getState().currentHelixAxes

  function body() {
    return { ...(detachedSource ? { detach_source: true } : {}), ...(sweepId ? { sweep_id: sweepId } : {}), cells, points_nm: editor.getPoints(), orientations_deg: editor.getOrientations(), plane: planeSelect.value,
      strand_filter: el('strands').value, ligate_adjacent: el('ligate').checked,
      source_helix_id: source?.id ?? null, source_end: source?.end ?? 'end', ...pin }
  }
  function hide() {
    if (owner?.active()) return owner.cancel()
    closeLocal()
  }
  function closeLocal() {
    if (!active) return
    active = false; epoch++; clearTimeout(timer); timer = null
    const session = owned; owned = null; busy = locked = false; disabledBeforeLock.clear()
    el('conflicts').hidden = true; el('conflicts').open = false
    store.setState({ sweepActive: false })
    preview.clear(); if (session) preview.setPrivateDisplayLayer(null)
    popup.hide()
    if (!session || session.isPickerCurrent?.() !== false) {
      slicePlane.hide()
      slicePlane.setPreviewEnabled(previousPreview)
      slicePlane.setExtrudeUiOpen(false)
    }
  }
  function schedulePreview() {
    if (!active || updatingPicker || busy || locked) return
    clearTimeout(timer); epoch++; apply.disabled = true
    el('total-bp').textContent = '…'
    status.textContent = cells.length ? 'Updating path…' : 'Select at least one lattice cell.'
    if (step === 2 && (!owned || el('visual').checked)) preview.updateDraft(editor.getPoints(), editor.getOrientations(), editor.getSelected())
    if (!cells.length) preview.clearGeometry()
    if (cells.length) timer = setTimeout(refreshPreview, 120)
  }
  // A committed field value needs no typing/drag debounce. Flush only queued
  // work; the input handler has already updated and invalidated the draft.
  panel.addEventListener('change', () => {
    if (owned && active && !busy && !locked && timer !== null) {
      clearTimeout(timer)
      refreshPreview()
    }
  })
  async function refreshPreview() {
    const version = epoch
    timer = null
    const request = body()
    if (step === 1 && !owned) { request.points_nm = [[0, 0, 0], defaultDirection()]; request.orientations_deg = null }
    if (owned) {
      delete request.sweep_id; delete request.expected_design_id; delete request.expected_revision
      request.detach_source = detachedSource
      const session = owned
      try { await session.onChange(request, { includeGeometry: step === 2 && el('visual').checked }) }
      catch (error) { if (owned === session && version === epoch) { status.textContent = error.message; apply.disabled = true } }
      return
    }
    delete request.expected_revision // Creation preview resolves the latest source without mutating it.
    if (request.points_nm.some(p => p.some(v => !Number.isFinite(v)))) { preview.clearGeometry(); status.textContent = 'Enter a finite number for X, Y and Z.'; return }
    if (request.points_nm.length < 2) { preview.clearGeometry(); status.textContent = 'Add a second point to define the path.'; return }
    try {
      const response = await api.previewSweep(request)
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
      if (step === 2 && response.source_detached) status.textContent += ' · Detached from source; connecting strands split'
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
    slicePlane.show(planeSelect.value, 0, false, false, { latticeType: controlDesign()?.lattice_type ?? 'HONEYCOMB', newBundle: true })
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
      editor.setOrientations(editor.getOrientations(), !!source && !detachedSource)
      updatingPicker = true; slicePlane.hide(); updatingPicker = false
    } else {
      showPicker(cells); needsSourceFrame = !!source
    }
    schedulePreview()
  }
  function populateSources() {
    const design = controlDesign()
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
    if (owner?.active()) { showToast?.('Finish or cancel the Sweep history edit first.'); return false }
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
    if ((state.currentDesign.feature_log_cursor ?? -1) !== -1
        || state.currentDesign.feature_log_sub_cursor != null || state.featureSeekPending) {
      showToast?.('Return to the latest history position before creating a Sweep.'); return false
    }
    if (active) hide()
    extrudePanel.hide(); expandedSpacing?.forceOff?.()
    previousPreview = slicePlane.isPreviewEnabled?.() ?? true
    slicePlane.setPreviewEnabled(false); slicePlane.setExtrudeUiOpen(false)
    active = true; detachedSource = false; resetPathDirection = false; sweepId = crypto.randomUUID(); source = null; needsSourceFrame = false
    sourceFrame = null; store.setState({ sweepActive: true })
    pin = { expected_design_id: state.currentDesign.id }
    populateSources()
    planeSelect.value = resolveExtrudeSourcePlane(state.currentDesign, state.currentPlane).plane
    planeSelect.disabled = false; sourceSelect.disabled = false
    el('strands').value = 'both'; el('ligate').checked = true
    editor.setPoints([[0, 0, 0], planeSelect.value === 'XY' ? [0, 0, 10] : planeSelect.value === 'XZ' ? [0, 10, 0] : [10, 0, 0]])
    el('visual-row').hidden = true
    cells = []; popup.setTitle('Sweep'); popup.show(); setStep(1)
    return true
  }
  function edit(entry) {
    if (!historyEnabled || !isNativeSweepFeature(entry)) {
      showToast?.('Sweep history editing is unavailable for this feature. The part has not been changed.')
      return false
    }
    if (active && !owner.active()) closeLocal()
    return owner.open(entry)
  }
  function changeSource() {
    detachedSource = false; sourceFrame = null
    source = sourceSelect.value === '' ? null : sources[Number(sourceSelect.value)]
    planeSelect.disabled = !!source
    let selected = []
    if (source) {
      const design = controlDesign()
      planeSelect.value = design.lattice_frames?.find(f => f.id === source.helix.lattice_frame_id)?.plane ?? resolveExtrudeSourcePlane({ helices: [source.helix] }).plane
      selected = [source.helix.grid_pos]
      const track = controlAxes()?.[source.id]?.samples
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
  el('visual').addEventListener('change', () => { schedulePreview(); if (owned) { clearTimeout(timer); refreshPreview() } })
  for (const id of ['strands', 'ligate']) el(id).addEventListener('change', schedulePreview)
  el('cancel').addEventListener('click', () => {
    if (owned && (locked || busy)) { hide(); return }
    if (!busy) { if (step === 2) setStep(1); else hide() }
  })
  apply.addEventListener('click', async () => {
    if (busy || apply.disabled || !active) return
    if (step === 1) { setStep(2); return }
    if (owned) {
      const session = owned
      try { await session.onApply() }
      catch (error) { if (owned === session) { status.textContent = error.message; apply.disabled = false } }
      return
    }
    busy = true; apply.disabled = true; status.textContent = 'Building sweep…'
    try {
      const request = body()
      // Saving workspace metadata can advance the revision without replacing
      // the design object. Refresh the guarded preview before using that draft.
      const revision = api.currentRevisionWatermark?.()
      if (Number.isSafeInteger(revision) && revision !== request.expected_revision) {
        const fresh = { ...request }; delete fresh.expected_revision
        const evaluated = await api.previewSweep(fresh)
        if (!evaluated || !Number.isSafeInteger(evaluated.revision)) throw new Error('Refresh the sweep preview before confirming.')
        if (!active) return
        request.expected_revision = pin.expected_revision = evaluated.revision
      }
      const result = await api.createSweep(request)
      if (!result) throw new Error(store.getState().lastError?.message ?? 'Sweep failed')
      hide()
    } catch (error) { status.textContent = error.message }
    finally { busy = false; if (active) apply.disabled = false }
  })
  function ownedPreview(response) {
    if (!owned || !active || timer !== null) return
    sourceFrame = response.source_frame
    if (response.source_detached) detachedSource = true
    editor.setOrientations(editor.getOrientations(), !!source && !detachedSource)
    if (resetPathDirection && source && sourceFrame) {
      resetPathDirection = false
      editor.setPoints([[0, 0, 0], sourceFrame.axis_dir.map(v => v * (source.end === 'start' ? -10 : 10))])
      schedulePreview(); return
    }
    if (step === 2 && el('visual').checked) { preview.update(response, body()); preview.select(editor.getSelected()) }
    else preview.clear()
    el('total-bp').textContent = response.total_new_bp.toLocaleString()
    status.textContent = step === 1 ? `${cells.length} lattice cells selected.` : `${response.length_nm.toFixed(2)} nm · ${response.length_bp} bp per helix · Feature stage; later features not evaluated`
    if (response.source_detached) status.textContent += ' · Detached from source; connecting strands split'
    if (response.feasibility.status === 'warning') status.textContent += ` · Warning: ${response.feasibility.message}`
    if (step === 1 && source && needsSourceFrame && sourceFrame) {
      updatingPicker = true
      slicePlane.showDeformed(sourceFrame, { plane: planeSelect.value, continuation: true, refHelixId: source.id, allowOrbit: true })
      slicePlane.setSelectedCells(cells); updatingPicker = false; needsSourceFrame = false
    }
  }
  function ownedState(value) {
    if (!owned) return
    busy = !!value.busy && value.busy !== 'evaluate'
    const unresolved = value.publicationUnknown || value.refreshNeeded
    locked = !!unresolved || !!value.expired
    el('cancel').textContent = locked || busy || step === 1 ? 'Cancel' : 'Previous'
    apply.textContent = unresolved ? (value.refreshNeeded ? 'Refresh result' : 'Check result') : step === 1 ? 'Next' : 'Apply'
    apply.disabled = !!value.busy || (!unresolved && (!!value.error || value.expired || !cells.length || timer !== null))
    if (busy || locked) {
      for (const element of panel.querySelectorAll('input, select, #sweep-point-editor button')) {
        if (!disabledBeforeLock.has(element)) disabledBeforeLock.set(element, element.disabled)
        element.disabled = true
      }
    } else {
      for (const [element, disabled] of disabledBeforeLock) if (element.isConnected) element.disabled = disabled
      disabledBeforeLock.clear(); planeSelect.disabled = !!source
    }
    if (value.error) status.textContent = value.error.message
  }
  if (historyEnabled) owner = createHistoryEditor({ store, api, scene, camera: getCamera, slicePlane, getDocumentId: getDocId, showToast,
    view: {
      open(inputs, session) {
        owned = session; active = true; busy = locked = false; epoch++; clearTimeout(timer); timer = null
        extrudePanel.hide(); expandedSpacing?.forceOff?.()
        previousPreview = slicePlane.isPreviewEnabled?.() ?? true
        slicePlane.setPreviewEnabled(false); slicePlane.setExtrudeUiOpen(false)
        preview.setPrivateDisplayLayer(session.displayLayer)
        sweepId = inputs.sweep_id; pin = {}; resetPathDirection = false; sourceFrame = null
        populateSources(); source = sources.find(s => s.id === inputs.source_helix_id && s.end === inputs.source_end) ?? null
        if (inputs.source_helix_id && !source) throw new Error('The saved Sweep source is missing from this feature prefix')
        sourceSelect.value = source ? String(sources.indexOf(source)) : ''
        planeSelect.value = inputs.plane; planeSelect.disabled = !!source; sourceSelect.disabled = false
        detachedSource = inputs.detach_source; needsSourceFrame = !!source
        editor.setPoints(inputs.points_nm); editor.setOrientations(inputs.orientations_deg, !!source && !detachedSource)
        el('strands').value = inputs.strand_filter; el('ligate').checked = inputs.ligate_adjacent
        el('visual-row').hidden = false; el('visual').checked = true
        cells = inputs.cells.map(cell => [...cell]); step = 2
        el('footprint').hidden = true; el('path').hidden = false; el('info').hidden = false
        el('step').textContent = 'Step 2/2 · Define sweep path'; el('cancel').textContent = 'Previous'; apply.textContent = 'Apply'; apply.disabled = true
        updatingPicker = true; slicePlane.hide(); updatingPicker = false
        popup.setTitle('Edit Sweep'); popup.show(); store.setState({ sweepActive: true })
      },
      updatePreview: ownedPreview, setStatus: ownedState, close: closeLocal,
    } })
  const unsubscribeSelection = slicePlane.subscribeSelection(selected => {
    if (!active || updatingPicker || step !== 1) return
    cells = selected; el('count').textContent = `${cells.length} helices · select cells on the plane`; schedulePreview()
  })
  const unsubscribe = store.subscribe((state, previous) => {
    if (active && (state.currentDesign?.id !== previous.currentDesign?.id || state.assemblyActive !== previous.assemblyActive)) hide()
    else if (active && !owned && !busy && state.currentDesign !== previous.currentDesign) schedulePreview()
  })
  const escape = event => { if ((owner?.active() || active && !busy) && event.key === 'Escape') hide() }
  const launch = () => { if (!busy) activate() }
  const otherTool = event => {
    if (!(active || owner?.active()) || !event.target.closest('[id^=menu-tools-]') || event.target.id === 'menu-tools-sweep') return
    if (owner?.active()) { event.preventDefault(); event.stopImmediatePropagation() }
    hide()
  }
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
  return { activate, activateFromEnd, edit, hide, isActive: () => active || !!owner?.active(),
    dispose() { owner?.dispose(); closeLocal(); unsubscribe?.(); unsubscribeSelection?.(); preview.dispose(); popup.dispose(); document.removeEventListener('click', otherTool, true); menu?.removeEventListener('click', launch); window.removeEventListener('keydown', escape) } }
}
