import { buildAssemblyVisualization } from './assembly_visualization.js'

/** Swap complete display-only scenes; stale asynchronous previews never win. */
export function initAssemblyViewVolumes({ scene, store, api, assemblyRenderer, onError = console.error }) {
  let generation = 0, current = null, signature = null, flight = Promise.resolve()
  assemblyRenderer.onRebuildComplete?.(() => { signature = null })
  const clear = () => { current?.removeFromParent(); current?.disposeVisualization(); current = null }
  const stage = phase => window.dispatchEvent(new CustomEvent('nadoc:view-volume-stage', { detail: { stage: `assembly-${phase}`, viewVolume: true } }))
  async function update(layers) {
    const state = store.getState()
    const next = JSON.stringify([state.assemblyActive, state.currentAssembly, state.coloringMode, layers])
    if (signature === next) { if (current && state.assemblyActive) assemblyRenderer.setVisible(false); return }
    signature = next
    const mine = ++generation
    if (!state.assemblyActive || !layers.length) {
      clear(); if (state.assemblyActive) assemblyRenderer.setVisible(true)
      stage('cleared'); return
    }
    stage('scheduled')
    flight = flight.catch(() => {}).then(async () => {
      if (mine !== generation) return
      try {
        const built = await buildAssemblyVisualization({ state, api, layers })
        if (mine !== generation) { built.disposeVisualization(); return }
        clear(); current = built; scene.add(built)
        assemblyRenderer.setVisible(false); stage('applied')
      } catch (error) {
        if (mine === generation) { signature = null; stage('failed'); onError(error) }
      }
    })
    return flight
  }
  return { update, getBoundingBox: () => current?.visualizationBounds?.clone() ?? null, dispose() { generation++; clear() } }
}
