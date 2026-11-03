import { canEditAtCursor } from '../ui/feature_edit_cursor.js'
import { isNativeExtrusionFeature } from '../ui/extrusion_feature_editor.js'
import { signedAlong } from '../scene/axis_snap.js'

const KINDS = new Set(['bundle-create', 'extrude-segment', 'extrude-continuation', 'extrude-deformed-continuation'])
export const usesExtrudeTool = entry => isNativeExtrusionFeature(entry) && KINDS.has(entry.op_kind)
  && !(entry.op_kind === 'extrude-continuation' && entry.params.source_frame_id)

/** The ordinary lattice tool, bound to a recorded extrusion's pre-feature inputs. */
export function createExtrudeHistoryEditor({ store, api, slicePlane, panel, getCamera, getControls,
  setPreviewHelices = () => {}, showToast = () => {}, events = globalThis.window }) {
  let session = null
  const recoveryKeys = new Set(['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64',
    'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'])
  function current(s) {
    if (session !== s) return false
    if (api.isFeatureEditContextCurrent(s.context)) return true
    const before = s.context.source, after = store.getState().currentDesign
    // Passive refreshes and recovery bodies arrive asynchronously. They replace
    // the design wrapper, but not its revision, cursor or authored inputs.
    const rebound = { ...s.context, source: after }
    if (!before || !after || !api.isFeatureEditContextCurrent(rebound)) return false
    const keys = new Set([...Object.keys(before), ...Object.keys(after)])
    const inputs = log => JSON.stringify(log, (key, value) => recoveryKeys.has(key) ? undefined : value)
    if ([...keys].some(key => before[key] !== after[key] && inputs(before[key]) !== inputs(after[key]))) return false
    s.context = rebound
    return true
  }
  function retire(s, restoreView = false) {
    if (session !== s) return
    session = null
    panel.finishEdit()
    s.release?.()
    setPreviewHelices([])
    s.saveHold?.release()
    if (restoreView && s.camera === getCamera() && s.controls === getControls()) {
      s.camera.position.copy(s.view.position); s.camera.quaternion.copy(s.view.quaternion)
      s.camera.up.copy(s.view.up); s.camera.zoom = s.view.zoom; s.camera.updateProjectionMatrix()
      s.controls.target.copy(s.view.target); s.controls.enableRotate = s.view.enableRotate
      s.controls.update()
      s.camera.updateMatrixWorld()
    }
  }
  async function seek(s, position, subPosition = null) {
    if (!current(s)) throw new Error('The part changed. Reopen Extrude on the current part.')
    if (!await api.seekFeatures(position, subPosition) || session !== s) throw new Error('History could not be restored.')
    s.context = api.captureFeatureEditContext()
    if (s.context.designId !== s.designId || s.context.docId !== s.docId)
      throw new Error('The active document changed.')
  }
  function align(s) {
    const camera = getCamera(), controls = getControls()
    const normal = signedAlong(slicePlane.getPlaneNormalWorld(), camera.position.clone().sub(controls.target))
    const center = slicePlane.getPlaneCenterWorld()
    const distance = Math.max(20, camera.position.distanceTo(controls.target))
    camera.up.copy(slicePlane.getPlaneUpWorld())
    controls.target.copy(center)
    camera.position.copy(center).addScaledVector(normal, distance)
    camera.lookAt(center); controls.update(); camera.updateMatrixWorld()
  }
  function showPicker(s, inputs = s.params) {
    const continuation = s.entry.op_kind === 'extrude-continuation'
    if (s.entry.op_kind === 'extrude-deformed-continuation') {
      slicePlane.showDeformed(s.frame ?? inputs, { plane: inputs.plane, continuation: true,
        refHelixId: inputs.ref_helix_id, sourceBp: inputs.source_bp, allowOrbit: true })
    } else {
      slicePlane.show(inputs.plane, inputs.offset_nm ?? 0, continuation, false, {
        latticeType: inputs.lattice_type ?? s.prefix.lattice_type,
        newBundle: !continuation,
      })
    }
    slicePlane.setExtrudeInputs(inputs)
  }
  async function cancel() {
    const s = session
    if (!s || s.busy) return false
    if (!current(s)) { retire(s); return false }
    s.busy = true
    try {
      await seek(s, s.cursor, s.subCursor)
      retire(s, true)
      return true
    } catch (error) { showToast(error.message, 6000); retire(s); return false }
  }
  async function apply(values) {
    const s = session
    if (!s || s.busy || !current(s) || s.release?.isCurrent?.() === false)
      throw new Error('The Extrude edit is no longer current.')
    if (!values.cells.length) throw new Error('Select at least one lattice cell.')
    const params = { ...s.params, cells: values.cells, length_bp: values.lengthBp, plane: values.plane }
    if (s.entry.op_kind !== 'extrude-deformed-continuation')
      Object.assign(params, { strand_filter: values.strandFilter, ligate_adjacent: values.ligateAdjacent })
    if (['extrude-segment', 'extrude-continuation'].includes(s.entry.op_kind) && values.offsetNm != null)
      params.offset_nm = values.offsetNm
    s.busy = true
    try {
      await seek(s, -1)
      const result = await api.editNativeExtrusionFeature(s.index, params, s.context, s.entry.id)
      if (!result) throw new Error('Extrude was not applied.')
      // Publication replaces the source. Restore navigation against the new
      // revision, without replaying the edit a second time if navigation fails.
      if (session !== s) return result
      s.context = api.captureFeatureEditContext()
      try {
        if (s.cursor !== -1 || s.subCursor != null) await seek(s, s.cursor, s.subCursor)
      } catch (error) { showToast(`Extrude applied, but the previous history position could not be restored: ${error.message}`, 6000) }
      retire(s, true)
      return result
    } catch (error) {
      // Keep the draft available after an atomic native rejection. Never restore
      // another document or overwrite a result published by a different action.
      if (current(s)) {
        try { await seek(s, s.index); showPicker(s, params) }
        catch { retire(s) }
      } else retire(s)
      showToast(error.message, 6000)
      throw error
    } finally { s.busy = false }
  }
  async function open(entry, index) {
    if (session || !usesExtrudeTool(entry) || !canEditAtCursor(store.getState().currentDesign, index)) return false
    const context = api.captureFeatureEditContext(), design = context.source
    if (store.getState().assemblyActive || design?.feature_log?.[index]?.id !== entry.id) return false
    const camera = getCamera(), controls = getControls()
    const s = { entry, index, params: structuredClone(entry.params), context, busy: true,
      designId: context.designId, docId: context.docId,
      cursor: design.feature_log_cursor ?? -1, subCursor: design.feature_log_sub_cursor ?? null,
      camera, controls, view: { position: camera.position.clone(), quaternion: camera.quaternion.clone(),
        up: camera.up.clone(), zoom: camera.zoom, target: controls.target.clone(), enableRotate: controls.enableRotate } }
    session = s
    try {
      s.saveHold = api.holdFeatureEditSaves?.()
      if (s.saveHold) {
        await s.saveHold.ready
        if (session !== s) throw new Error('The Extrude edit was closed.')
        // An already-running save may have confirmed identity and advanced the
        // revision. Drain it before capturing the source for temporary seeks.
        s.context = { ...s.context, revision: api.captureFeatureEditContext().revision }
        if (!current(s)) throw new Error('The part changed while waiting for its save.')
      }
      panel.hide()
      // Use the real recorded prefix for occupancy. The viewport then displays
      // this feature's output while the picker edits its original input cells.
      await seek(s, index === 0 ? -2 : index - 1)
      s.prefix = store.getState().currentDesign
      const axes = store.getState().currentHelixAxes ?? {}
      if (entry.op_kind === 'extrude-deformed-continuation' && s.params.source_bp != null) {
        s.frame = await api.getDeformedFrame(s.params.source_bp, s.params.ref_helix_id)
        if (!s.frame || !current(s)) throw new Error('The source frame is no longer available.')
      }
      await seek(s, index)
      const prefixIds = new Set(s.prefix.helices?.map(helix => helix.id) ?? [])
      setPreviewHelices((store.getState().currentDesign.helices ?? []).filter(helix => !prefixIds.has(helix.id)).map(helix => helix.id))
      s.release = slicePlane.usePrivateContext({ design: s.prefix, helixAxes: axes, displayLayer: 0, onExtrude: apply })
      panel.activateEdit({ plane: s.params.plane, onCancel: cancel,
        onPlaneChange: ['bundle-create', 'extrude-segment'].includes(entry.op_kind) ? plane => {
          const inputs = slicePlane.getExtrudeInputs()
          s.params.plane = plane
          showPicker(s, { ...s.params, ...inputs }); align(s)
        } : null })
      showPicker(s); align(s)
      s.busy = false
      return true
    } catch (error) {
      if (current(s)) { try { await seek(s, s.cursor, s.subCursor) } catch {} }
      retire(s, true); showToast(`Extrude history unavailable: ${error.message}`, 6000)
      return false
    }
  }
  const unsubscribe = store.subscribe(() => {
    if (session && !session.busy && (!current(session) || session.release?.isCurrent?.() === false)) retire(session)
  })
  const reset = () => { if (session) retire(session) }
  events?.addEventListener('nadoc:document-reset', reset)
  return { open, cancel, active: () => session !== null,
    dispose() { reset(); unsubscribe?.(); events?.removeEventListener('nadoc:document-reset', reset) } }
}
