/** One background preparation at a time, in authored keyframe order.
 * Reordering changes pending priorities; an active request is allowed to finish.
 * Completed/duplicate work remains the display controller cache's responsibility.
 */
export function initTrajectoryPreparationQueue() {
  let pending = [], running = false, priorities = new Map()
  const sort = () => pending.sort((a, b) =>
    (priorities.get(a.key) ?? Infinity) - (priorities.get(b.key) ?? Infinity))
  async function pump() {
    if (running) return
    running = true
    try {
      while (pending.length) {
        const task = pending.shift()
        try { task.resolve(await task.run()) } catch (error) { task.reject(error) }
      }
    } finally { running = false }
  }
  return {
    prioritize(keys) { priorities = new Map(keys.map((key, i) => [key, i])); sort() },
    enqueue(key, run) {
      return new Promise((resolve, reject) => {
        pending.push({ key, run, resolve, reject }); sort()
        // Collect this turn's requests before choosing the first pending keyframe.
        queueMicrotask(pump)
      })
    },
  }
}
