/** Repair transport returns data only. The controller owns context checks and publication. */
export class RepairRequestError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.detail ?? detail?.message ?? `Repair request failed (${status})`)
    this.name = 'RepairRequestError'; this.status = status; this.detail = detail
  }
}

const DRAFT = '/design/features/repair-draft'
const JOBS = '/design/features/evaluation/jobs'
const MAX_RAW_BYTES = 350000, MAX_HEADER_BYTES = 8192

export function createPartRepairEndpoints({ request, rawRequest = (...args) => fetch(...args), headersFor,
  acknowledge = () => true, apply = () => {}, uploadTimeoutMs = 20000 }) {
  async function json(method, path, body, { context, signal } = {}) {
    let failure
    const result = await request(method, path, body, { docId: context.docId, signal,
      suppressBusy: true, protectedRetry: false, skipSimulationPrepare: true,
      onError: (status, detail) => { failure = new RepairRequestError(status, detail) } })
    if (failure) throw failure
    if (result == null) throw new RepairRequestError(0, 'Repair request was cancelled or unavailable')
    return result
  }
  const jobPath = id => `${JOBS}/${encodeURIComponent(id)}`
  return {
    inspect: options => json('GET', DRAFT, undefined, options),
    inspectInputs: (body, options) => json('POST', '/design/features/repair-inputs', body, options),
    mutate: (body, options) => json('POST', DRAFT, body, options),
    evaluate: (body, options) => json('POST', `${DRAFT}/evaluate`, body, options),
    start: (body, options) => json('POST', JOBS, body, options),
    poll: (id, options) => json('GET', jobPath(id), undefined, options),
    cancel: (id, options) => json('DELETE', jobPath(id), undefined, options),
    commit: (id, options) => json('POST', `${jobPath(id)}/commit`, undefined, options),
    compare: (id, body, options) => json('POST', `${jobPath(id)}/comparison`, body, options),
    async refreshCommitted(receipt, options = {}) {
      const context = options.context
      if (receipt?.status !== 'committed' || typeof receipt.job_id !== 'string' || !receipt.job_id
          || receipt.design_id !== context?.designId || !Number.isSafeInteger(receipt.revision)
          || receipt.revision < context.revision || receipt.revision > context.revision + 1) {
        throw new RepairRequestError(409, 'The publication receipt belongs to another design or revision')
      }
      const changed = () => new RepairRequestError(409, 'The published result changed or expired. Refresh the current design before continuing')
      // These reads stay private. In particular, ordinary getGeometry() would
      // mutate global display state before the revision/session checks below.
      const design = await json('GET', '/design', undefined, options)
      if (design.design?.id !== receipt.design_id || design.revision !== receipt.revision
          || (design.design.active_loadout_id ?? null) !== context.loadoutId) throw changed()
      const geometry = await json('GET', '/design/geometry', undefined, options)
      if (!Array.isArray(geometry.nucleotides) || !Array.isArray(geometry.helix_axes) || geometry.partial_geometry) {
        throw new RepairRequestError(422, 'The published geometry response is incomplete')
      }
      const revision = await json('GET', '/design/revision', undefined, options)
      if (revision.design_id !== receipt.design_id || revision.revision !== receipt.revision || !revision.has_design
          || revision.doc_id !== (context.docId ?? '__default__')) throw changed()
      const status = await json('GET', jobPath(receipt.job_id), undefined, options)
      if (status.job_id !== receipt.job_id || status.status !== 'committed' || status.revision !== receipt.revision
          || status.stale !== false || status.source_busy !== false) throw changed()
      // Allow-list render fields: this read cannot replace the checked design,
      // receipt revision or proposal summary through an unrelated geometry key.
      return { ...design, nucleotides: geometry.nucleotides, helix_axes: geometry.helix_axes,
        ...(geometry.straight_positions_by_helix ? { straight_positions_by_helix: geometry.straight_positions_by_helix,
          straight_helix_axes: geometry.straight_helix_axes } : {}) }
    },
    inspectSource: (body, options) => json('POST', `${DRAFT}/source/inspect`, body, options),
    async uploadSource(receipt, file, { context, signal } = {}) {
      if (!file || !Number.isSafeInteger(file.size) || file.size < 1 || file.size > MAX_RAW_BYTES
          || file.size !== receipt?.source?.size_bytes) {
        throw new RepairRequestError(413, 'Choose the original source file with the exact declared byte count')
      }
      // ASCII JSON is required by the bounded HTTP header contract, including
      // Unicode authored IDs. Send the File itself: no base64 or full-buffer copy.
      const metadata = JSON.stringify(receipt).replace(/[^\x20-\x7e]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`)
      if (metadata.length > MAX_HEADER_BYTES) throw new RepairRequestError(413, 'Source metadata exceeds the upload limit')
      const abort = new AbortController()
      const forward = () => abort.abort(signal.reason)
      if (signal?.aborted) forward()
      else signal?.addEventListener('abort', forward, { once: true })
      const timer = setTimeout(() => abort.abort(new DOMException('Source upload timed out', 'TimeoutError')), uploadTimeoutMs)
      try {
        const response = await rawRequest(`/api${DRAFT}/source`, { method: 'POST', signal: abort.signal,
          headers: { ...headersFor(context.docId), 'Content-Type': 'application/octet-stream',
            'X-NADOC-Repair-Source': metadata }, body: file })
        const result = await response.json()
        if (!response.ok) throw new RepairRequestError(response.status, result.detail)
        return result
      } finally {
        clearTimeout(timer); signal?.removeEventListener('abort', forward)
      }
    },
    acknowledge, apply,
  }
}
