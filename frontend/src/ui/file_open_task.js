/** Cooperative cancellation. The active server command must settle before its
 * document is discarded, so a late import cannot overwrite a subsequent open.
 * This does not claim to preempt Python computation or synchronous mesh building.
 */
export function createFileOpenTasks({ setCancel = () => {}, progress, log, discard, reset, hide, welcome }) {
  let active = null
  return {
    begin() {
      if (active) return null
      const task = { cancelled: false }
      active = task
      setCancel(() => {
        task.cancelled = true
        progress(0, 'Cancelling — waiting for the current step to finish…')
        log('Cancellation requested. The current server or rendering step must settle before releasing this document.')
      })
      return task
    },
    async cancelled(task) {
      if (!task.cancelled) return false
      await discard()
      reset()
      hide()
      welcome()
      return true
    },
    finish(task) {
      if (active === task) { active = null; setCancel(null) }
    },
  }
}
