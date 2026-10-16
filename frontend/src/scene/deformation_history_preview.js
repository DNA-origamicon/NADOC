/** Owns static native display layers. Never installs a Design or store geometry. */
import { buildDeformationPreviewLayer } from './part_dna_comparison_layer.js'
import { createDeformationPreviewCamera } from './deformation_preview_camera.js'

export function createDeformationHistoryPreview({ scene, getLiveRoot, camera }) {
  let before = null, candidate = null, live = null, wasVisible = false
  let viewport = null
  let mode = 'candidate', disposed = false

  function restoreLive() {
    // A rebuild/document switch can replace the canonical owner while a request
    // is pending. Teardown must not change that new owner's visibility.
    if (!camera && live && getLiveRoot() === live) live.visible = wasVisible
  }
  function display() {
    if (before) before.root.visible = mode === 'before'
    if (candidate) candidate.root.visible = mode === 'candidate'
    const showing = (mode === 'before' && before) || (mode === 'candidate' && candidate)
    if (!camera && showing && live && getLiveRoot() === live) live.visible = false
    else restoreLive()
  }
  function clear() {
    before?.dispose(); candidate?.dispose(); before = null; candidate = null
    viewport?.dispose(); viewport = null
    restoreLive(); live = null
  }
  function active() { if (disposed) throw new Error('Deformation preview is disposed') }
  return {
    open(packet) {
      active()
      let nextBefore, nextCandidate
      try {
        nextBefore = buildDeformationPreviewLayer(packet.before, scene)
        nextCandidate = buildDeformationPreviewLayer(packet.candidate, scene)
      } catch (error) { nextBefore?.dispose(); nextCandidate?.dispose(); throw error }
      clear()
      try {
        if (camera) {
          viewport = createDeformationPreviewCamera({ scene, camera })
          viewport.include(nextBefore.root); viewport.include(nextCandidate.root)
        }
      } catch (error) { nextBefore.dispose(); nextCandidate.dispose(); viewport?.dispose(); viewport = null; throw error }
      before = nextBefore; candidate = nextCandidate; mode = 'candidate'
      live = getLiveRoot?.(); wasVisible = live?.visible ?? false
      display()
    },
    replaceCandidate(component) {
      active()
      if (!before) throw new Error('Deformation preview is not open')
      // Build completely before releasing the last valid result.
      const next = component === null ? null : buildDeformationPreviewLayer(component, scene)
      if (next) viewport?.include(next.root)
      candidate?.dispose(); candidate = next; display()
    },
    show(value) {
      active()
      if (!['before', 'candidate', 'off'].includes(value)) throw new Error('Unknown deformation preview view')
      if (camera && value === 'off') throw new Error('Choose the feature prefix or candidate in the isolated viewport')
      mode = value; display()
    },
    dispose() { if (!disposed) { clear(); disposed = true } },
  }
}
