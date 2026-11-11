import { designRebuildAwaitingGeometry } from './design_render_readiness.js'
import { welcomeVisible } from '../shared/welcome_visibility.js'

/** Reveal notes only after geometry and the opening UI settle, then a model frame paints. */
export function createAnnotationLoadGate({ store, document, getAssemblyRenderer, requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame }) {
  let key = null, generation = 0, ready = false, frame = null, assemblyReady = false, waiting = false
  let abort = null, disposed = false
  const reset = () => {
    generation++; ready = false; assemblyReady = false; waiting = false
    abort?.abort(); abort = null
    if (frame !== null) cancelFrame(frame)
    frame = null
  }
  return {
    isReady() {
      if (disposed) return false
      const state = store.getState(), assembly = !!state.assemblyActive
      const model = assembly ? state.currentAssembly : state.currentDesign
      const next = model ? `${assembly ? 'assembly' : 'part'}:${model.id}` : null
      if (next !== key) { reset(); key = next }
      const blocked = !model || welcomeVisible(document) || document.getElementById('file-load-progress')?.classList.contains('visible')
        || (!assembly && designRebuildAwaitingGeometry(model, state.currentGeometry))
      if (blocked) { reset(); return false }
      if (assembly && model.instances?.length && !assemblyReady) {
        if (!waiting) {
          const renderer = getAssemblyRenderer?.()
          if (!renderer?.whenReady) {
            assemblyReady = !!renderer?.getInstanceRenderData && model.instances
              .filter(instance => instance.visible !== false).every(instance => renderer.getInstanceRenderData(instance.id))
            if (!assemblyReady) return false
          } else {
            waiting = true; abort = new AbortController()
            const token = generation
            Promise.resolve(renderer.whenReady(model, { signal: abort.signal })).then(() => {
              if (!disposed && token === generation) assemblyReady = true
            }, () => { if (token === generation) waiting = false })
          }
        }
        if (!assemblyReady) return false
      }
      if (!ready && frame === null) {
        const token = generation
        frame = requestFrame(() => {
          if (token !== generation) return
          frame = requestFrame(() => { if (token === generation) { frame = null; ready = true } })
        })
      }
      return ready
    },
    dispose() { disposed = true; reset() },
  }
}
