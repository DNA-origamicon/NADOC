/** Fixed numerical-operation polling; no publication, retries, or server-owned clocks. */
const MAX_MS = 180000
const POLL_MS = 500
const MAX_POLLS = 360
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ORIGIN = ['preview_id', 'expected_design_id', 'expected_revision', 'feature_id']
const FIELDS = ['version', 'operation', 'request_sequence', 'elapsed_seconds', 'remaining_seconds']
const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const seconds = (value, max) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max

export function validatePreviewComputation(value, { body, context, operation, identity, expectedIdentity = null, lease = body.lease_id, error }) {
  const sequence = operation === 'prepare' ? 0 : body.request_sequence
  if (!plain(value) || ORIGIN.some(key => value[key] !== body[key])
      || value.doc_id !== (context.docId ?? '__default__') || !UUID.test(value.lease_id ?? '')
      || (lease && value.lease_id !== lease) || value.request_sequence !== sequence) {
    throw error(409, 'The computation belongs to another preview or revision')
  }
  const role = identity(value, expectedIdentity)
  const c = value.computation
  if (!plain(c) || Object.keys(c).length !== FIELDS.length || FIELDS.some(key => !Object.hasOwn(c, key))
      || c.version !== 1 || c.operation !== operation || c.request_sequence !== sequence
      || !seconds(c.elapsed_seconds, Number.MAX_VALUE) || !seconds(c.remaining_seconds, 180)
      || (c.remaining_seconds > 0 && c.elapsed_seconds + c.remaining_seconds > 180.001)) {
    throw error(422, 'The computation response is invalid')
  }
  return role
}

function interrupted(signal, error) {
  return signal.reason instanceof Error ? signal.reason : error(0, 'Preview computation was interrupted')
}
function waitFor(signal, work, error) {
  if (signal.aborted) return Promise.reject(interrupted(signal, error))
  return new Promise((resolve, reject) => {
    const stop = () => { signal.removeEventListener('abort', stop); reject(interrupted(signal, error)) }
    signal.addEventListener('abort', stop, { once: true })
    Promise.resolve().then(() => {
      if (signal.aborted) throw interrupted(signal, error)
      return work()
    }).then(value => {
      signal.removeEventListener('abort', stop)
      if (signal.aborted) reject(interrupted(signal, error)); else resolve(value)
    }, failure => { signal.removeEventListener('abort', stop); reject(failure) })
  })
}
function delay(signal, milliseconds, error) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(interrupted(signal, error)); return }
    const stop = () => { clearTimeout(timer); signal.removeEventListener('abort', stop); reject(interrupted(signal, error)) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve() }, milliseconds)
    signal.addEventListener('abort', stop, { once: true })
  })
}

export async function pollPreviewComputation({ initial, started, read, body, context, operation, signal,
  onComputation, onReadTiming, identity, error, expectedIdentity = null }) {
  const abort = new AbortController()
  const stop = () => abort.abort(error(0, 'Preview computation was interrupted'))
  let timer, outcomeKnown = false
  if (signal?.aborted) stop()
  else signal?.addEventListener('abort', stop, { once: true })
  try {
    const role = validatePreviewComputation(initial, { body, context, operation, identity, expectedIdentity, error })
    const lease = initial.lease_id
    const expected = { body, context, operation, identity, expectedIdentity: role, lease, error }
    const deadline = Math.min(started + MAX_MS, performance.now() + initial.computation.remaining_seconds * 1000)
    timer = setTimeout(() => abort.abort(error(0, 'Preview computation timed out; check its status before retrying')),
      Math.max(0, deadline - performance.now()))
    let value = initial, readStarted = started, polls = 0
    while (true) {
      if (abort.signal.aborted) throw interrupted(abort.signal, error)
      validatePreviewComputation(value, expected)
      const pending = operation === 'prepare' ? 'preparing' : 'applying'
      if (value.status === pending || (operation === 'apply' && value.status === 'committing')) {
        onComputation?.({ ...value, computation: { ...value.computation } })
      } else if (value.status === 'ready' || value.status === 'failed') {
        if (!seconds(value.remaining_seconds, 60)) throw error(422, 'Invalid completed preview lease')
        const timing = { elapsedMs: Math.max(0, performance.now() - readStarted), renewed: true, response: value }
        if (Object.hasOwn(value, 'failure')) {
          const failure = value.failure
          if (!plain(failure) || Object.keys(failure).length !== 2 || !Number.isInteger(failure.status)
              || failure.status < 400 || failure.status > 599
              || !(plain(failure.detail) || (typeof failure.detail === 'string' && failure.detail.length <= 32000))
              || value.status !== (operation === 'prepare' ? 'failed' : 'ready') || Object.hasOwn(value, 'result')) {
            throw error(422, 'Invalid computation failure')
          }
          onReadTiming?.(timing)
          const problem = error(failure.status, failure.detail)
          problem.computationFailure = true
          outcomeKnown = true
          throw problem
        }
        if (operation !== 'prepare' || value.status !== 'ready' || !plain(value.result)) {
          throw error(422, 'The computation result is missing')
        }
        const packet = value.result
        if ([...ORIGIN, 'doc_id', 'lease_id', 'request_sequence'].some(key => packet[key] !== value[key])
            || packet.remaining_seconds !== value.remaining_seconds) throw error(409, 'The prepared result belongs to another preview')
        identity(packet, role)
        onReadTiming?.(timing)
        return packet
      } else if (operation === 'apply' && value.status === 'applied') {
        // Full scalar receipt validation remains with the controller/publication reader.
        return value
      } else throw error(422, 'Unknown computation state')
      if (++polls > MAX_POLLS || performance.now() >= deadline) throw error(0, 'Preview computation polling expired')
      await delay(abort.signal, Math.min(POLL_MS, Math.max(0, deadline - performance.now())), error)
      readStarted = performance.now()
      value = await waitFor(abort.signal, () => read({ ...Object.fromEntries(ORIGIN.map(key => [key, body[key]])),
        lease_id: lease }, abort.signal), error)
      // Published receipts intentionally retain the existing receipt schema.
      if (operation === 'apply' && value?.status === 'applied' && !Object.hasOwn(value, 'computation')) {
        if ([...ORIGIN, 'doc_id', 'lease_id', 'request_sequence'].some(key => value[key] !== initial[key])) {
          throw error(409, 'The publication belongs to another computation')
        }
        identity(value, role)
        return value
      }
    }
  } catch (failure) {
    if (operation === 'apply' && !outcomeKnown) failure.publicationUnknown = true
    throw failure
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', stop)
    abort.abort(error(0, 'Preview computation read completed'))
  }
}
