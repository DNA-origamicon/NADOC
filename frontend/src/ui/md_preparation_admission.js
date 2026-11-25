/** Preparation capacity is checked for every target, including remote execution. */
export async function admitMdPreparation(payload, { plan, progress, notify }) {
  try {
    const result = await plan(payload)
    if (!result || result.ready !== true) {
      notify(result?.detail || 'Preparation resources could not be verified. Retry when the selected target is available.', 'error')
      return false
    }
    progress(result.detail)
    return true
  } catch (error) {
    notify(error?.message || 'Preparation resource check failed.', 'error')
    return false
  }
}
