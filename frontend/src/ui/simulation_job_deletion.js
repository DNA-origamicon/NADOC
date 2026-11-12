// The panel confirms deletion before calling onDeleting. Keep tombstones for this
// UI's lifetime so even a list request started before deletion cannot revive a job.
export function createOptimisticJobDeletion({ getNodes, update, deselect, onError }) {
  const hidden = new Set()
  const pending = new Set()
  let generation = 0
  const key = node => `${node.engine}:${node.job_id}`
  const filter = nodes => nodes.filter(node => !hidden.has(key(node)))
  async function remove(node, panel) {
    const id = key(node)
    if (pending.has(id)) return
    pending.add(id)
    const startedGeneration = generation
    let removed = []
    let keys = []
    let ok = false
    try {
      ok = await panel.deleteSelected({ onDeleting: ids => {
        if (generation !== startedGeneration) return
        keys = ids.map(job_id => key({ engine: node.engine, job_id }))
        removed = getNodes().filter(candidate => keys.includes(key(candidate)))
        keys.forEach(id => hidden.add(id))
        removed.forEach(deselect)
        update(filter(getNodes()))
      } })
    } catch (error) {
      onError(error)
    } finally {
      pending.delete(id)
      if (!ok && keys.length) {
        keys.forEach(id => hidden.delete(id))
        const current = getNodes()
        // A document switch must not receive rows from the old document.
        if (generation === startedGeneration) update(current.concat(removed.filter(candidate =>
          !current.some(saved => key(saved) === key(candidate)))))
      }
    }
  }
  return { filter, remove, reset: () => { generation++ } }
}
