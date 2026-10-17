/** Seed the open document once; selecting an assembly part is read-only. */
export function initAnimationDefaults({ store, api, getContext, onError = () => {} }) {
  const attempted = new Map()
  function ensure() {
    const { assemblyMode, partMode } = getContext()
    // Merely showing a part's animation list must not rewrite its shared source
    // or rebuild assembly geometry. The explicit New animation action already
    // creates animation 1 when this context has no authored animations.
    if (partMode) return Promise.resolve()
    const source = assemblyMode ? store.getState().currentAssembly : store.getState().currentDesign
    if (!source?.id) return Promise.resolve()
    const key = `${assemblyMode ? 'assembly' : 'design'}:${source.id}`
    if (attempted.has(key)) return attempted.get(key)
    // Remember populated contexts too, so deleting their last animation is respected.
    attempted.set(key, Promise.resolve())
    if (source.animations?.length) return attempted.get(key)
    let request
    try {
      request = assemblyMode ? api.createAssemblyAnimation('animation 1') : api.ensureDefaultAnimation()
    } catch (error) { request = Promise.reject(error) }
    const pending = Promise.resolve(request).catch(onError)
    attempted.set(key, pending)
    return pending
  }
  return { ensure }
}
