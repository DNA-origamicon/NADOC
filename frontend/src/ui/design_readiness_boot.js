/** Explicit same-document 2D → 3D handoff; ordinary startup remains unchanged. */
export function readinessBootDocument(href, mode = '3d') {
  const url = new URL(href)
  if (mode !== '3d' || url.searchParams.get('readiness') !== 'simulation'
    || !url.searchParams.get('doc')
    || ['new', 'open', 'part-instance'].some(key => url.searchParams.has(key))) return null
  return url.searchParams.get('doc')
}

/** Only GETs the document already selected by the API client's doc headers. */
export async function restoreReadinessDocument({
  api, store, href, mode = '3d', onRestored,
  document = globalThis.document, isDisposed = () => false,
} = {}) {
  if (!readinessBootDocument(href, mode)) return false
  if (store.getState().currentDesign || store.getState().assemblyActive) return false
  if (!api?.getDesign || !api?.getGeometry) throw new Error('The 3D editor cannot load this document yet.')
  const response = await api.getDesign()
  if (isDisposed()) return false
  if (!response?.design) throw new Error('This document is no longer available. Open it from the file library to continue.')
  const stillCurrent = () => !store.getState().assemblyActive
    && store.getState().currentDesign?.id === response.design.id
  if (!stillCurrent()) throw new Error('The open document changed while loading. Continue in the current editor.')
  const geometry = await api.getGeometry()
  if (isDisposed()) return false
  if (!geometry) throw new Error('The design loaded, but its 3D geometry could not be retrieved. Reload this tab to try again.')
  if (!stillCurrent()) throw new Error('The open document changed while loading. Continue in the current editor.')
  await onRestored?.(response.design)
  if (isDisposed()) return false
  document.title = `NADOC 3D — ${response.design.metadata?.name || 'Untitled'}`
  return true
}
