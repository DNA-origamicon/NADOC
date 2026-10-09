/** Start canonical VR export before desktop response synchronization finishes.
 * Each operation owns one refresh. Capture rejection immediately: a later
 * desktop synchronization error must never leave an unhandled background task.
 */
export function createVRCommitRefresh({ api, getState }) {
  let pending
  function onCommitted(response) {
    if (pending || !response?.design?.id || !Number.isSafeInteger(response.revision)) return
    try {
      pending = Promise.resolve(api.refreshNativeVRScene({
        expected_design_id: response.design.id,
        expected_revision: response.revision,
      })).then(result => ({ result }), error => ({ error }))
    } catch (error) { pending = Promise.resolve({ error }) }
  }
  async function complete() {
    // Some existing mutation responses (notably compact Undo) omit the full
    // design. Synchronization then supplies the checked current revision.
    if (!pending) onCommitted({ design: getState().currentDesign, revision: api.currentRevisionWatermark() })
    if (!pending) throw new Error('No committed design revision for VR refresh')
    const outcome = await pending
    if ('error' in outcome) throw outcome.error
    return outcome.result
  }
  return { onCommitted, complete }
}
