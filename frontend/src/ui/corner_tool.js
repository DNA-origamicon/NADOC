import { createCornerPopup } from './corner_popup.js'
import { beginClusterSelection } from './tool_cluster_selection.js'
import { createCornerPreview } from '../scene/corner_preview.js'
import { captureCornerSource, previewCorner, applyCorner } from '../api/corner.js'
import { holdFeatureEditSaves } from '../api/client.js'
import { isNativeCornerFeature } from './corner_parameters.js'

/** One source-bound Corner interaction, from cluster pick through preview/apply. */
export function initCornerTool({ store, selectionManager, scene, designRenderer, showToast,
  makePopup = createCornerPopup, makePreview = createCornerPreview,
  capture = captureCornerSource, calculate = previewCorner, commit = applyCorner,
  pick = beginClusterSelection, debounceMs = 80, holdSaves = holdFeatureEditSaves,
}) {
  let picker = null, source = null, sourceDesign = null, cluster = null, values = null
  let controller = null, timer = null, generation = 0, ready = false, applying = false, opened = false
  let previewToken = null, saveHold = null
  const preview = makePreview({ scene, getLiveRoot: () => designRenderer.getDisplayGeometry()?.root })
  const popup = makePopup({ onChange: change, onInvalid: invalidate, onSelect: select,
    onCancel: cancel, onApply: apply })
  function invalidate() {
    generation++; ready = false; previewToken = null; clearTimeout(timer); timer = null
    controller?.abort(); controller = null; preview.clear()
  }
  function cancel({ force = false } = {}) {
    if (applying && !force) return
    invalidate(); picker?.cancel(); picker = null; opened = false
    source = null; sourceDesign = null; cluster = null; popup.hide(); popup.setBusy(false)
    saveHold?.release(); saveHold = null
  }
  function afterSaves(begin) {
    const initial = store.getState().currentDesign, epoch = generation
    sourceDesign = null
    const proceed = () => {
      if (epoch !== generation || !opened) return
      const current = store.getState().currentDesign
      if (!current || current.id !== initial?.id) { cancel(); return }
      sourceDesign = current
      begin()
    }
    try {
      saveHold ??= holdSaves?.()
      if (saveHold) {
        popup.calculating(null, 'Waiting for the current save…')
        saveHold.ready.then(proceed).catch(error => {
          if (epoch === generation && opened) { cancel(); showToast(error.message, { severity: 'error' }) }
        })
      } else proceed()
    } catch (error) { cancel(); showToast(error.message, { severity: 'error' }) }
  }
  function select() {
    if (applying) return
    invalidate(); picker?.cancel(); popup.setEditing(false); popup.open(); opened = true
    source = null; cluster = null
    afterSaves(() => {
      picker = pick({ store, selectionManager, onCancelled: cancel, onSelected: selected => {
        if (!opened) return
        cluster = selected; sourceDesign = store.getState().currentDesign; source = capture(sourceDesign)
        const helices = sourceDesign.helices.filter(h => selected.helix_ids.includes(h.id))
        const lo = Math.max(...helices.map(h => h.bp_start ?? 0))
        const hi = Math.min(...helices.map(h => (h.bp_start ?? 0) + h.length_bp - 1))
        values = { positionBp: Math.round((lo + hi) / 2), angleDeg: 90, directionDeg: 0 }
        popup.selected(selected.name || 'Selected cluster', sourceDesign.lattice_type, values)
        change(values)
      } })
    })
  }
  function parameters() {
    return { cluster_id: cluster.id, position_bp: values.positionBp,
      angle_deg: values.angleDeg, direction_deg: values.directionDeg }
  }
  function change(next) {
    invalidate(); values = next
    if (!source || !cluster) return
    popup.calculating(null, 'Preparing cylinder preview…')
    const epoch = generation
    timer = setTimeout(async () => {
      controller = new AbortController()
      try {
        await calculate(source, parameters(), { signal: controller.signal, onEvent: event => {
          if (epoch !== generation || !opened) return
          if (event.type === 'guide') preview.guide(event.guide)
          if (event.type === 'progress') {
            const eta = event.remaining_seconds
            popup.calculating(event.percent, `${event.stage}${Number.isFinite(eta) && eta > .1 ? ` · ~${eta.toFixed(1)} s remaining` : ''}`)
          }
          if (event.type === 'ready') {
            if (!event.preview_token) throw new Error('Corner preview has no prepared result. Reopen the tool.')
            preview.full(event.candidate); previewToken = event.preview_token; ready = true
            popup.ready('Full corner preview ready.')
          }
        } })
      } catch (error) {
        if (epoch !== generation || error.name === 'AbortError') return
        ready = false; preview.clear(); popup.error(error.message)
      }
    }, debounceMs)
  }
  async function apply() {
    if (!ready || applying || !source) return
    if (store.getState().currentDesign !== sourceDesign) { cancel(); return }
    const epoch = generation
    applying = true; popup.setBusy(true); popup.calculating(null, source.featureId ? 'Updating Corner…' : 'Applying Corner…')
    try {
      await commit(source, parameters(), previewToken)
      applying = false; if (epoch === generation) cancel()
    } catch (error) {
      applying = false
      if (epoch !== generation) return
      ready = false; preview.clear(); popup.setBusy(false); popup.error(error.message)
    }
  }
  function open() {
    if (applying) return
    if (store.getState().assemblyActive) {
      // Corner changes the source part's strand graph. An instance selection
      // cannot choose shared-source versus independent-part ownership for it.
      showToast('Corner changes part topology. Open the source part from the library to edit it.', { severity: 'info' }); return
    }
    if (!store.getState().currentDesign?.helices?.length) {
      showToast('Load a DNA part before creating a Corner.', { severity: 'error' }); return
    }
    select()
  }
  function openEdit(entry) {
    if (applying) return
    if (!isNativeCornerFeature(entry)) { showToast('Select a recorded Corner feature to edit.', { severity: 'error' }); return }
    cancel()
    if (!store.getState().currentDesign?.feature_log?.some(row => row.id === entry.id)) return
    opened = true; popup.open(); popup.setEditing(true)
    afterSaves(() => {
      const current = sourceDesign.feature_log?.find(row => row.id === entry.id)
      if (!isNativeCornerFeature(current)) { cancel(); return }
      source = { ...capture(sourceDesign), featureId: current.id }
      cluster = sourceDesign.cluster_transforms?.find(row => row.id === current.params.cluster_id)
        ?? { id: current.params.cluster_id, name: 'Recorded Corner target' }
      values = { positionBp: current.params.position_bp, angleDeg: current.params.angle_deg, directionDeg: current.params.direction_deg }
      popup.selected(cluster.name || 'Recorded Corner target', sourceDesign.lattice_type, values)
      change(values)
    })
  }

  const unsubscribe = store.subscribe(next => {
    if (opened && !applying && sourceDesign && next.currentDesign !== sourceDesign) cancel()
    else if (opened && sourceDesign && next.currentDesign?.id !== sourceDesign.id) cancel({ force: true })
  })
  const button = document.getElementById('menu-tools-corner')
  button?.addEventListener('click', open)
  function escape(event) { if (opened && event.key === 'Escape') { event.preventDefault(); cancel() } }
  document.addEventListener('keydown', escape)
  const reset = () => cancel({ force: true })
  window.addEventListener('nadoc:document-reset', reset)
  return { open, openEdit, cancel, dispose() {
    applying = false; cancel(); unsubscribe(); button?.removeEventListener('click', open)
    document.removeEventListener('keydown', escape); window.removeEventListener('nadoc:document-reset', reset)
    popup.dispose(); preview.dispose()
  } }
}
