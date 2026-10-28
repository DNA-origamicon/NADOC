// Diagnostic-only: explicit GC samples are retention evidence, not latency.
// Weak references keep this probe from retaining the contexts being measured.
export async function installRetentionProbe(page) {
  await page.addInitScript(() => {
    const contexts = new Set(), seen = new WeakSet()
    let comparisonSeen = 0
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (...args) {
      const context = original.apply(this, args)
      if (context?.isContextLost && context?.getExtension && !seen.has(context)) {
        seen.add(context)
        contexts.add({ reference: new WeakRef(context), comparison: false })
      }
      return context
    }
    window.__historyRetention = () => {
      let live = 0, comparisonLive = 0
      const renderers = new Set()
      for (const entry of contexts) {
        const context = entry.reference.deref()
        if (!entry.comparison && context?.canvas?.getAttribute('aria-label')?.startsWith('Private authored geometry comparison')) {
          entry.comparison = true
          comparisonSeen++
        }
        if (context && !context.isContextLost()) {
          live++
          if (entry.comparison) comparisonLive++
          const info = context.getExtension('WEBGL_debug_renderer_info')
          renderers.add(info ? context.getParameter(info.UNMASKED_RENDERER_WEBGL) : context.getParameter(context.RENDERER))
        } else contexts.delete(entry) // Stop observing a released native wrapper.
      }
      return { live, comparisonLive, comparisonSeen, renderers: [...renderers],
        attachedElements: document.querySelectorAll('*').length }
    }
  })
  const session = await page.context().newCDPSession(page)
  return {
    async detachedNodes() {
      await session.send('HeapProfiler.collectGarbage')
      const { detachedNodes } = await session.send('DOM.getDetachedDomNodes')
      return detachedNodes.filter(({ treeNode }) => treeNode.nodeName === 'CANVAS'
        && treeNode.attributes?.some(value => value.startsWith('Private authored geometry comparison')))
        .map(({ treeNode, retainedNodeIds }) => ({
        name: treeNode.nodeName, attributes: treeNode.attributes,
        descendants: treeNode.childNodeCount, retained: retainedNodeIds.length,
      }))
    },
    async sample() {
      await session.send('HeapProfiler.collectGarbage')
      const [heap, dom, webgl] = await Promise.all([
        session.send('Runtime.getHeapUsage'), session.send('Memory.getDOMCounters'),
        page.evaluate(() => window.__historyRetention()),
      ])
      return { heap, dom, webgl }
    },
  }
}
