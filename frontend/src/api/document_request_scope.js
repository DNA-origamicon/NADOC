/** Retire display reads on document reset, without interrupting saves or jobs. */
export function createDocumentRequestScope(window = globalThis.window) {
  let generation = 0
  const reads = new Set()
  const reset = () => {
    generation++
    for (const controller of reads) controller.abort(new DOMException('Document closed or replaced', 'AbortError'))
    reads.clear()
  }
  window?.addEventListener('nadoc:document-reset', reset)
  return {
    capture: () => generation,
    isCurrent: version => version === generation,
    track(controller) { reads.add(controller); return () => reads.delete(controller) },
    dispose() { reset(); window?.removeEventListener('nadoc:document-reset', reset) },
  }
}
