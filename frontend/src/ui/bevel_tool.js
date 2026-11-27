import { createBevelPopup } from './bevel_popup.js'
import { beginClusterSelection } from './tool_cluster_selection.js'
import { createBevelPreview } from '../scene/bevel_preview.js'
import { createBevelPlaneControls } from '../scene/bevel_plane_controls.js'
import { bevelPlane, bevelMask } from '../scene/bevel_math.js'
import { captureBevelSource, applyBevel, loadBevelSource } from '../api/bevel.js'
import { holdFeatureEditSaves } from '../api/client.js'
import { isNativeBevelFeature } from './bevel_parameters.js'

/** One source-bound Bevel interaction, from cluster pick through preview/apply. */
export function initBevelTool({ store, selectionManager, scene, designRenderer, showToast, camera, canvas, controls,
  makePopup = createBevelPopup, makePreview = createBevelPreview,
  capture = captureBevelSource, commit = applyBevel,
  pick = beginClusterSelection, holdSaves = holdFeatureEditSaves,
  loadSource = loadBevelSource, makePlane = createBevelPlaneControls,
}) {
  let picker = null, source = null, sourceDesign = null, cluster = null, values = null
  let controller = null, generation = 0, ready = false, applying = false, opened = false
  let saveHold = null, paths = null, loading = null
  const preview = makePreview({ scene, getLiveRoot: () => designRenderer.getDisplayGeometry()?.root })
  const popup = makePopup({ onChange: change, onInvalid: invalidate, onSelect: select,
    onCancel: cancel, onApply: apply })
  const plane = makePlane({ scene, camera, canvas, controls, onChange: next => {
    if (applying) return
    popup.selected(cluster.name || 'Selected cluster', sourceDesign.lattice_type, next)
    change(next)
  }, onMode: mode => popup.mode?.(mode) })
  function invalidate() {
    generation++; ready = false
    controller?.abort(); controller = null; preview.clear(); plane.clear(); paths = null; loading = null
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
      popup.calculating(null, 'Select a cluster in the viewer.')
      picker = pick({ store, selectionManager, onCancelled: cancel, onSelected: selected => {
        if (!opened) return
        cluster = selected; sourceDesign = store.getState().currentDesign; source = capture(sourceDesign)
        const domains = sourceDesign.strands.flatMap(s => s.domains).filter(d => selected.helix_ids.includes(d.helix_id))
        if (!domains.length) { popup.error('Select a cluster containing duplex material.'); return }
        const lo = Math.min(...domains.map(d => Math.min(d.start_bp, d.end_bp)))
        const hi = Math.max(...domains.map(d => Math.max(d.start_bp, d.end_bp)))
        values = { positionBp: Math.round((lo + hi) / 2), angleDeg: 0, directionDeg: 0, trimEnd: 'end' }
        popup.selected(selected.name || 'Selected cluster', sourceDesign.lattice_type, values)
        change(values)
      } })
    })
  }
  function parameters() {
    return { cluster_id: cluster.id, position_bp: values.positionBp,
      angle_deg: values.angleDeg, direction_deg: values.directionDeg, trim_end: values.trimEnd }
  }
  function renderLocal() {
    if (!paths || !opened) return
    const start = performance.now()
    ready = false
    try {
      const frame = bevelPlane(paths, values)
      plane.update(frame, paths, values)
      const mask = bevelMask(paths, values, frame, true)
      preview.mask(mask, start)
      if (!mask.hasCut) throw new Error('Bevel needs material on both sides of the cutting plane.')
      ready = true
      popup.ready(source.featureId ? 'Live preview of this feature. Later features replay on Apply.'
        : 'Live Full preview. Ready to apply.')
    } catch (error) { popup.error(error.message) }
  }
  function change(next) {
    values = next; ready = false
    if (!source || !cluster) return
    if (paths) { renderLocal(); return }
    if (loading) return
    popup.calculating(null, 'Preparing live Full preview…')
    const epoch = generation
    controller = new AbortController()
    const current = store.getState()
    const component = !source.featureId && current.currentGeometry?.length && Object.keys(current.currentHelixAxes ?? {}).length
      ? { component_kind: 'corner-preview-dna', component_version: 1,
        display_topology: sourceDesign, nucleotides: current.currentGeometry,
        helix_axes: Object.entries(current.currentHelixAxes).map(([helix_id, axis]) => ({
          helix_id, ...axis, ovhg_axes: axis.ovhgAxes })), seam_inserts: [] } : null
    loading = loadSource(source, parameters(), { signal: controller.signal, includeGeometry: !component }).then(data => {
      if (epoch !== generation || !opened) return
      paths = data.paths; preview.full(data.component ?? component); renderLocal()
    }).catch(error => {
      if (epoch !== generation || error.name === 'AbortError') return
      popup.error(error.message); loading = null
    })
  }
  async function apply() {
    if (!ready || applying || !source) return
    if (store.getState().currentDesign !== sourceDesign) { cancel(); return }
    const epoch = generation
    applying = true; plane.setEnabled?.(false); popup.setBusy(true); popup.calculating(null, source.featureId ? 'Updating Bevel…' : 'Applying Bevel…')
    try {
      await commit(source, parameters())
      applying = false; if (epoch === generation) cancel()
    } catch (error) {
      applying = false
      if (epoch !== generation) return
      ready = false; plane.setEnabled?.(true); popup.setBusy(false); popup.error(error.message)
    }
  }
  function open() {
    if (applying) return
    if (store.getState().assemblyActive) {
      // Bevel changes the source part's strand graph. An instance selection
      // cannot choose shared-source versus independent-part ownership for it.
      showToast('Bevel changes part topology. Open the source part from the library to edit it.', { severity: 'info' }); return
    }
    if (!store.getState().currentDesign?.helices?.length) {
      showToast('Load a DNA part before creating a Bevel.', { severity: 'error' }); return
    }
    select()
  }
  function openEdit(entry) {
    if (applying) return
    if (!isNativeBevelFeature(entry)) { showToast('Select a recorded Bevel feature to edit.', { severity: 'error' }); return }
    cancel()
    if (!store.getState().currentDesign?.feature_log?.some(row => row.id === entry.id)) return
    opened = true; popup.open(); popup.setEditing(true)
    afterSaves(() => {
      const current = sourceDesign.feature_log?.find(row => row.id === entry.id)
      if (!isNativeBevelFeature(current)) { cancel(); return }
      source = { ...capture(sourceDesign), featureId: current.id }
      cluster = sourceDesign.cluster_transforms?.find(row => row.id === current.params.cluster_id)
        ?? { id: current.params.cluster_id, name: 'Recorded Bevel target' }
      values = { positionBp: current.params.position_bp, angleDeg: current.params.angle_deg, directionDeg: current.params.direction_deg, trimEnd: current.params.trim_end }
      popup.selected(cluster.name || 'Recorded Bevel target', sourceDesign.lattice_type, values)
      change(values)
    })
  }

  const unsubscribe = store.subscribe(next => {
    if (opened && !applying && sourceDesign && next.currentDesign !== sourceDesign) cancel()
    else if (opened && sourceDesign && next.currentDesign?.id !== sourceDesign.id) cancel({ force: true })
  })
  const button = document.getElementById('menu-tools-bevel')
  button?.addEventListener('click', open)
  function escape(event) { if (opened && event.key === 'Escape') { event.preventDefault(); cancel() } }
  document.addEventListener('keydown', escape)
  const reset = () => cancel({ force: true })
  window.addEventListener('nadoc:document-reset', reset)
  return { open, openEdit, cancel, dispose() {
    applying = false; cancel(); unsubscribe(); button?.removeEventListener('click', open)
    document.removeEventListener('keydown', escape); window.removeEventListener('nadoc:document-reset', reset)
    popup.dispose(); preview.dispose(); plane.dispose()
  } }
}
