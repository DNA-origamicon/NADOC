/** Hide immediately; keep pending deletions out of playback and interim refreshes.
 * Never mutate the document optimistically: failure re-renders its latest state.
 */
export function afterDeletionPaint() {
  return new Promise(resolve => {
    let first, second
    const done = () => { clearTimeout(timer); cancelAnimationFrame(first); cancelAnimationFrame(second); resolve() }
    const timer = setTimeout(done, 100) // Also complete when a background tab stops painting.
    first = requestAnimationFrame(() => { second = requestAnimationFrame(done) })
  })
}

export function createKeyframeDeletion({ getScope, refresh, stopPlayback, onError, afterPaint = afterDeletionPaint }) {
  const pending = new Set()
  const tails = new Map()
  const key = (scope, animationId, id) => JSON.stringify([scope, animationId, id])
  function filter(animation) {
    if (!animation || !pending.size) return animation
    const scope = getScope()
    return { ...animation, keyframes: (animation.keyframes ?? []).filter(k => !pending.has(key(scope, animation.id, k.id))) }
  }
  async function remove({ animationId, keyframeId, row, commit }) {
    const scope = getScope(), id = key(scope, animationId, keyframeId)
    if (pending.has(id)) return
    pending.add(id)
    row.remove()
    // Reserve request order immediately, including when several rows are clicked.
    const previous = tails.get(scope) ?? Promise.resolve()
    let release
    const gate = new Promise(resolve => { release = resolve })
    const queued = previous.then(() => gate)
    tails.set(scope, queued)
    void queued.then(() => { if (tails.get(scope) === queued) tails.delete(scope) })
    try {
      await afterPaint()
      if (getScope() !== scope) return
      // Releasing trajectory caches can be expensive. Let the removed row paint first.
      stopPlayback(animationId)
      refresh()
      await previous
      if (getScope() !== scope) return
      const result = await commit()
      if (result === null || result === false) throw new Error('Keyframe deletion failed. The keyframe has been restored.')
    } catch (error) {
      onError(error)
    } finally {
      pending.delete(id)
      release()
      if (getScope() === scope) refresh()
    }
  }
  return { filter, remove }
}
