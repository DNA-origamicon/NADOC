/** Temporary display filter, independent of saved Hide/Show and molecular state. */
export function createSubmodelVisibility() {
  let hidden = new Set()
  const listeners = new Set()
  return {
    get: () => hidden,
    set(keys = []) {
      const next = new Set(keys)
      if(next.size === hidden.size && [...next].every(k => hidden.has(k)))return
      hidden = next
      for(const listener of listeners)listener(hidden)
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}
const shared = createSubmodelVisibility()
export const submodelHiddenKeys = shared.get
export const setSubmodelHiddenKeys = shared.set
export const subscribeSubmodelVisibility = shared.subscribe
