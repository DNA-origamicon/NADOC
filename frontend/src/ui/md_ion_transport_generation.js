import { getMdIonTransportProgress } from '../api/client.js'
import { initIonTransportProgress } from './ion_transport_progress.js'

/** Request-scoped progress for Generate; displaying cached plots remains separate. */
export function initMdIonTransportGeneration(status) {
  const host = document.createElement('div')
  host.dataset.ionTransportProgress = ''
  host.style.display = 'none'
  status?.after(host)
  const progress = initIonTransportProgress(host)
  let active = null
  function cancel() { active = null; progress.reset(); host.style.display = 'none' }
  async function run(id, generate) {
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
    active = requestId
    progress.reset()
    progress.update({ stage: 'validate', state: 'running' })
    let polling = null
    const poll = () => {
      if (polling || active !== requestId) return polling
      polling = (async () => {
        try {
          const snapshot = await getMdIonTransportProgress(id, requestId)
          if (active === requestId && snapshot?.request_id === requestId) progress.snapshot(snapshot)
        } catch { /* Analysis owns errors; progress polling retries. */ }
        finally { polling = null }
      })()
      return polling
    }
    const timer = setInterval(poll, 300)
    try {
      const result = await generate(id, { requestId })
      if (!result) throw new Error('Ion-transport analysis failed.')
      if (polling) await polling
      await poll()
      if (active === requestId) {
        progress.completeAnalysis()
        progress.update({ stage: 'receive', done: 1, total: 1 })
      }
      return result
    } catch (error) {
      if (active === requestId) progress.fail(error?.message || 'Ion-transport analysis failed.')
      throw error
    } finally { clearInterval(timer); if (active === requestId) active = null }
  }
  return { run, cancel }
}
