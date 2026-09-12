/** Seed each loaded authoring context once; duplicate panel views share this owner. */
export function initAnimationDefaults({ store, api, getContext, onError = () => {} }) {
  const attempted = new Map()
  function ensure() {
    const { assemblyMode, partMode, partDesign, partPatchFn, partInstanceId } = getContext()
    const source = partMode ? partDesign : assemblyMode ? store.getState().currentAssembly : store.getState().currentDesign
    if (!source?.id) return Promise.resolve()
    const key = `${partMode ? `part:${partInstanceId}` : assemblyMode ? 'assembly' : 'design'}:${source.id}`
    if (attempted.has(key)) return attempted.get(key)
    // Remember populated contexts too, so deleting their last animation is respected.
    attempted.set(key, Promise.resolve())
    if (source.animations?.length) return attempted.get(key)
    let request
    try {
      if (partMode) {
        request = partPatchFn(d => {
          if (d.animations?.length) return
          d.animations = [{ id: crypto.randomUUID(), name: 'animation 1', keyframes: [], fps: 30, loop: false }]
        })
      } else {
        request = (assemblyMode ? api.createAssemblyAnimation : api.createAnimation)('animation 1')
      }
    } catch (error) { request = Promise.reject(error) }
    const pending = Promise.resolve(request).catch(onError)
    attempted.set(key, pending)
    return pending
  }
  return { ensure }
}
