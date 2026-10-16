/** Data-only transport. Publication adoption belongs to the source-bound controller. */
export class DeformationPreviewRequestError extends Error {
  constructor(status, detail) {
    const message = typeof detail === 'string' ? detail : detail?.detail ?? detail?.message
    super(typeof message === 'string' ? message : `Deformation preview request failed (${status})`)
    this.name = 'DeformationPreviewRequestError'
    this.status = status; this.detail = detail; this.code = detail?.code ?? null
  }
}

const PATH = '/design/features/deformation-preview'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ORIGIN = ['preview_id', 'expected_design_id', 'expected_revision', 'feature_id']
const RECEIPT = [...ORIGIN, 'lease_id', 'doc_id', 'deformation_id', 'request_sequence', 'design_id', 'revision']
export const previewOrigin = value => Object.fromEntries(ORIGIN.map(key => [key, value[key]]))
const textId = value => typeof value === 'string' && value.length > 0 && value.length <= 256
const changed = () => new DeformationPreviewRequestError(409,
  'The published result changed or expired. Refresh the current design before continuing')

/** Keep only scalar publication identity, never a response's geometry or validation graph. */
export function previewPublicationReceipt(value, context, expected = null) {
  if (value?.status !== 'applied' || !UUID.test(value.preview_id ?? '') || !UUID.test(value.lease_id ?? '')
      || !textId(value.feature_id) || !textId(value.deformation_id)
      || value.expected_design_id !== context?.designId || value.design_id !== context?.designId
      || value.expected_revision !== context?.revision || value.revision !== context?.revision + 1
      || value.doc_id !== (context?.docId ?? '__default__')
      || !Number.isSafeInteger(value.request_sequence) || value.request_sequence < 1
      || (expected && RECEIPT.some(key => value[key] !== expected[key]))) throw changed()
  return { status: 'applied', ...Object.fromEntries(RECEIPT.map(key => [key, value[key]])) }
}

export function createDeformationPreviewEndpoints({ request }) {
  async function json(method, path, body, { context, signal } = {}) {
    if (!context || !Object.hasOwn(context, 'docId')
        || !(context.docId === null || typeof context.docId === 'string')) {
      throw new DeformationPreviewRequestError(422, 'An explicit document context is required')
    }
    let failure, result
    try {
      result = await request(method, path, body, { docId: context.docId, signal,
        suppressBusy: true, protectedRetry: false, skipSimulationPrepare: true,
        onError: (status, detail) => { failure = new DeformationPreviewRequestError(status, detail) } })
    } catch (error) {
      if (error instanceof DeformationPreviewRequestError) throw error
      throw new DeformationPreviewRequestError(0, error?.message ?? 'Preview transport unavailable')
    }
    if (failure) throw failure
    if (result == null) throw new DeformationPreviewRequestError(0, 'Preview request was cancelled or unavailable')
    return result
  }
  return {
    prepare: (body, options) => json('POST', PATH, body, options),
    evaluate: (body, options) => json('POST', `${PATH}/evaluate`, body, options),
    apply: (body, options) => json('POST', `${PATH}/apply`, body, options),
    cancel: (body, options) => json('POST', `${PATH}/cancel`, body, options),
    status: (body, options) => json('POST', `${PATH}/status`, body, options),
    async refreshCommitted(receipt, options = {}) {
      const context = options.context
      const expected = previewPublicationReceipt(receipt, context)
      const body = { ...previewOrigin(expected), lease_id: expected.lease_id }
      const check = value => previewPublicationReceipt(value, context, expected)
      // Each read remains private until both session-bound checks and the
      // controller's final local document/epoch check have passed.
      check(await json('POST', `${PATH}/status`, body, options))
      const design = await json('GET', '/design', undefined, options)
      if (design.design?.id !== expected.design_id || design.revision !== expected.revision
          || (design.design.active_loadout_id ?? null) !== (context.loadoutId ?? null)) throw changed()
      const geometry = await json('GET', '/design/geometry', undefined, options)
      if (!Array.isArray(geometry.nucleotides) || !Array.isArray(geometry.helix_axes) || geometry.partial_geometry) {
        throw new DeformationPreviewRequestError(422, 'The published geometry response is incomplete')
      }
      const revision = await json('GET', '/design/revision', undefined, options)
      if (revision.design_id !== expected.design_id || revision.revision !== expected.revision
          || revision.doc_id !== expected.doc_id || revision.has_design !== true) throw changed()
      check(await json('POST', `${PATH}/status`, body, options))
      return { ...design, nucleotides: geometry.nucleotides, helix_axes: geometry.helix_axes,
        ...(geometry.straight_positions_by_helix ? { straight_positions_by_helix: geometry.straight_positions_by_helix,
          straight_helix_axes: geometry.straight_helix_axes } : {}) }
    },
  }
}
