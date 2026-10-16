/** Owned part edits: capture request context and acknowledge only adopted replies. */
const KINDS = new Set(['group-organize', 'group-create', 'group-update', 'group-dissolve',
  'placement-update', 'placements-update', 'visibility-update'])
const POSE_KINDS = new Set(['placement-update', 'placements-update'])

export function createGroupOrganizationEndpoint({ store, request, syncDesign, getDocId,
  currentRevision, documentRequests }) {
  return async function groupOrganizationCommand(kind, inputs) {
    const state = store.getState(), docId = getDocId(), designId = state.currentDesign?.id
    const revision = currentRevision(), generation = documentRequests.capture()
    const current = () => documentRequests.isCurrent(generation) && getDocId() === docId
      && store.getState().currentDesign?.id === designId && !store.getState().assemblyActive
    const fail = message => {
      if (current()) store.setState({ lastError: { code: 'group_edit_response', message } })
      return null
    }
    if (!designId || state.assemblyActive || !Number.isSafeInteger(revision) || revision < 0)
      return fail('Refresh the current part before editing groups or placements.')
    if (!KINDS.has(kind) || !inputs || typeof inputs !== 'object' || Array.isArray(inputs))
      return fail('Choose a supported group or placement operation.')
    let response
    try {
      response = await request('POST', '/design/group-organization/commands', {
        kind, inputs, expected_revision: revision,
      }, { docId, protectedRetry: false, skipSimulationPrepare: true })
    } catch (error) { return fail(error?.message ?? 'The group edit failed.') }
    if (!response || !current()) return null
    if (response.design?.id !== designId || !Number.isSafeInteger(response.revision)
        || response.revision < revision || response.revision < currentRevision())
      return fail('The group edit response is no longer current. Your current part was kept.')
    const pose = POSE_KINDS.has(kind)
    if (pose && (!Array.isArray(response.helix_axes)
        || (!Array.isArray(response.nucleotides) && !response.nucleotides_compact)
        || response.partial_geometry))
      return fail('The placement response has no complete matching geometry. Refresh before continuing.')
    try {
      await syncDesign(response, { skipGeometry: !pose })
    } catch (error) { return fail(error?.message ?? 'The group edit could not be displayed.') }
    // Shared synchronization can skip an older reply, and subscribers can replace
    // the document during adoption. Neither outcome is an accepted edit receipt.
    if (!current() || currentRevision() !== response.revision
        || store.getState().currentDesign !== response.design) return null
    return response
  }
}
