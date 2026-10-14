/** Selected-part authoring context. Passive selection only reads source data. */
export function initAssemblyPartContext({ api, onChange, beforePatch }) {
  let current = null, requestGeneration = 0

  function publish(context, design) {
    if (current !== context || !design) return
    if (context.design === design && context.published) return
    context.design = design
    context.published = true
    onChange?.(context.id, design, context.patch)
  }

  function makeContext(id) {
    const context = { id, design: null, published: false, patch: null, loading: false, pending: null }
    context.patch = async modifier => {
      if (current !== context || context.loading || !context.design) return
      const original = JSON.stringify(context.design)
      const design = JSON.parse(original)
      modifier(design)
      const content = JSON.stringify(design)
      if (content === original) return
      beforePatch?.(id)
      publish(context, design)
      await api.patchInstanceDesign(id, content)
      if (current !== context) return
      try {
        const fresh = await api.getInstanceDesign(id)
        publish(context, fresh?.design)
      } catch { /* retain the optimistic edit, as before */ }
    }
    return context
  }

  async function select(instanceId, { force = false } = {}) {
    if (!instanceId) {
      requestGeneration++
      current = null
      onChange?.(null, null, null)
      return
    }
    // Repeated selection must not obsolete a refresh that is still fetching
    // this source. Share its completion before advancing the request generation.
    if (current?.id === instanceId && !force && (current.design || current.loading)) return current.pending
    const generation = ++requestGeneration
    const context = current?.id === instanceId ? current : makeContext(instanceId)
    current = context
    // A refreshed source may differ from the displayed Design. Retained panel
    // callbacks cannot author against that old snapshot while the read is pending.
    context.loading = true
    context.pending = (async () => {
      try {
        const result = await api.getInstanceDesign(instanceId)
        if (generation !== requestGeneration || current !== context) return
        if (!result?.design) {
          current = null
          onChange?.(null, null, null)
          return
        }
        context.loading = false
        publish(context, result.design)
      } catch {
        if (generation !== requestGeneration || current !== context) return
        current = null
        onChange?.(null, null, null)
      }
    })()
    return context.pending
  }

  return { select }
}
