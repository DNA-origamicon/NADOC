/** Join calculated fields to the molecular player's existing buffering clock. */
export function createEMPlaybackPreparation({batch, live, onError = () => {}}) {
  return async indices => {
    try {
      if (indices.some(index => !batch.byIndex.has(index))) return false
      while (live() && indices.some(index => !batch.ready.includes(index))) {
        if (batch.complete) return false
        await new Promise(resolve => setTimeout(resolve,100))
      }
      if (!live()) return false
      return await batch.cache.ensure(batch.ready,indices) && live()
    } catch (error) { if (live()) onError(error); return false }
  }
}
