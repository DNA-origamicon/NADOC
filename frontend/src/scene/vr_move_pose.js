/** Final pose belongs to this transaction, never to a later polling event. */
export async function commitVRMovePose(adapter, ref, matrix, isCurrent = () => true) {
  if (!Array.isArray(matrix) || matrix.length !== 16 || !matrix.every(Number.isFinite)) {
    return { accepted: false, reason: 'invalid_transform' }
  }
  if (!isCurrent()) return { accepted: false, reason: 'selection_changed' }
  const started = await adapter.beginVRPreview(ref.kind === 'cluster' ? ref.id : ref)
  if (!started?.accepted) return started
  if (!isCurrent()) {
    await adapter.cancelVRPreview?.()
    return { accepted: false, reason: 'selection_changed' }
  }
  if (!adapter.applyVRPreviewMatrix(matrix)) {
    return { accepted: false, reason: 'selection_changed' }
  }
  return adapter.confirmVRPreview()
}
