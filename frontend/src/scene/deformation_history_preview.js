/** Owns static native display layers. Never installs a Design or store geometry. */
import { buildDeformationPreviewLayer } from './part_dna_comparison_layer.js'
import { createDeformationPreviewCamera } from './deformation_preview_camera.js'

export function createDeformationHistoryPreview({ scene, getLiveRoot, camera, allowEmptyCandidate = false }) {
  let before = null, candidate = null, spare = null, live = null, wasVisible = false
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
    before?.dispose(); candidate?.dispose(); spare?.dispose(); before = null; candidate = null; spare = null
    viewport?.dispose(); viewport = null
    restoreLive(); live = null
  }
  function active() { if (disposed) throw new Error('Deformation preview is disposed') }
  return {
    open(packet) {
      active()
      let nextBefore, nextCandidate, nextSpare
      try {
        nextBefore = buildDeformationPreviewLayer(packet.before, scene)
        if (packet.candidate !== null) {
          nextCandidate = buildDeformationPreviewLayer(packet.candidate, scene)
          nextSpare = buildDeformationPreviewLayer(packet.candidate, scene)
          nextSpare.root.removeFromParent()
        }
        else if (!allowEmptyCandidate && (packet.mode !== 'create' || packet.awaiting_parameters !== true)) throw new Error('Missing initial deformation display')
      } catch (error) { nextBefore?.dispose(); nextCandidate?.dispose(); nextSpare?.dispose(); throw error }
      clear()
      try {
        if (camera) {
          viewport = createDeformationPreviewCamera({ scene, camera })
          viewport.include(nextBefore.root); if (nextCandidate) viewport.include(nextCandidate.root)
        }
      } catch (error) { nextBefore.dispose(); nextCandidate?.dispose(); nextSpare?.dispose(); viewport?.dispose(); viewport = null; throw error }
      before = nextBefore; candidate = nextCandidate ?? null; spare = nextSpare ?? null; mode = candidate ? 'candidate' : 'before'
      live = getLiveRoot?.(); wasVisible = live?.visible ?? false
      display()
    },
    replaceCandidate(component) {
      active()
      if (!before) throw new Error('Deformation preview is not open')
      // Update only a detached spare. A failed update cannot alter the last
      // complete candidate, and at most one spare survives between updates.
      let next = null
      try {
        if (component !== null) {
          if (spare?.update(component)) { next = spare; spare = null; scene.add(next.root) }
          else { spare?.dispose(); spare = null; next = buildDeformationPreviewLayer(component, scene) }
          viewport?.include(next.root)
        }
      } catch (error) { spare?.dispose(); spare = null; next?.dispose(); throw error }
      if (component === null) { candidate?.dispose(); spare?.dispose(); spare = null }
      else if (candidate) { candidate.root.removeFromParent(); spare = candidate }
      candidate = next; display()
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
