import { docHeaders } from '../shared/doc_id.js'

/** One reconstruction and one replaceable queued frame; MD keeps its engine owner. */
export function createSimulationAtomistic({ renderer, getDesign, setCGVisible, request = fetch }) {
  let pending = null, queued = null, generation = 0, signature = '', cached = null
  const status = building => window.dispatchEvent(new CustomEvent('nadoc:md-heavy-status', { detail: { kind: 'atomistic', building, mode: 'simulation' } }))
  function cancel() { generation++; queued = null; status(false) }
  async function drain() {
    try {
      while (queued) {
        const frame = queued; queued = null
        const key = JSON.stringify([frame.design, frame.updates])
        try {
          if (key !== signature || !cached) {
            const response = await request('/api/design/atomistic/visualized', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' },
              body: JSON.stringify({ design: frame.design, positions: frame.updates }) })
            if (!response.ok) throw new Error('Could not reconstruct the simulation atomistic view')
            cached = await response.json(); signature = key
          }
          if (frame.token !== generation) continue
          renderer.update(cached); renderer.applyScalarColors(frame.colors); setCGVisible(false)
        } catch (error) { if (frame.token === generation) throw error }
      }
    } finally { pending = null; status(false) }
  }
  function apply(updates, colors) {
    queued = { updates, colors, design: getDesign(), token: ++generation }
    status(true)
    // Share the promise and keep only the newest queued frame. A slow build
    // cannot retain an unbounded sequence of coordinate arrays or HTTP requests.
    if (!pending) pending = Promise.resolve().then(drain)
    return pending
  }
  return { apply, cancel }
}
