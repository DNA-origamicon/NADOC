import { docHeaders } from '../shared/doc_id.js'
import { cloneRepairInput } from '../features/part_repair_model.js'
import { actionFromRepairUpgrade } from '../features/part_repair_fields.js'
import { RepairRequestError } from './part_repair_endpoints.js'

export const RECIPE_FILE_LIMIT = 1500000
export const RECIPE_RESPONSE_LIMIT = 16000000
const HEADER_LIMIT = 256000, TIMEOUT_MS = 190000
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)

export function requireRecipeFile(file) {
  if (!(file instanceof File) || !/\.nadoc$/i.test(file.name)) throw new Error('Choose a local .nadoc file')
  if (!Number.isSafeInteger(file.size) || file.size < 1 || file.size > RECIPE_FILE_LIMIT) {
    throw new Error('The original file must contain 1–1,500,000 bytes')
  }
}

/** Reuse the reviewed structural action grammar without an active document. */
export function recipeFileUpgrade(upgrade) {
  return actionFromRepairUpgrade({ version: 1, assessment: 'inputs_only', definition_supported: true,
    feature_id: upgrade?.action?.feature_id, child_id: null, upgrades: [upgrade] }, upgrade)
}

function recoveryRequest(request) {
  const value = cloneRepairInput(request)
  if (!value || Object.keys(value).length !== 3 || value.version !== 1 || !sha(value.expected_source_sha256)
      || !Array.isArray(value.actions) || value.actions.length < 1 || value.actions.length > 64) {
    throw new Error('Recovery needs an inspected source and 1–64 explicit structural repairs')
  }
  const seen = new Set()
  for (const action of value.actions) {
    recipeFileUpgrade({ action })
    if (seen.has(action.feature_id)) throw new Error('Choose each structural repair only once')
    seen.add(action.feature_id)
  }
  return value
}

function checkAbort(signal) { if (signal?.aborted) throw signal.reason ?? new DOMException('Cancelled', 'AbortError') }
const digestBytes = bytes => crypto.subtle.digest('SHA-256', bytes)
async function checksum(bytes, digest) {
  const result = [...new Uint8Array(await digest(bytes))].map(value => value.toString(16).padStart(2, '0')).join('')
  if (!sha(result)) throw new Error('Could not compute the file SHA-256')
  return result
}

export async function hashRecipeFile(file, { digest = digestBytes, signal } = {}) {
  requireRecipeFile(file); checkAbort(signal)
  // Read bytes only for the receipt. The upload body retains the original File;
  // neither original nor recovered design JSON is parsed in the browser.
  const bytes = await new Promise((resolve, reject) => {
    const reader = new FileReader()
    const abort = () => { reader.abort(); reject(signal.reason ?? new DOMException('Cancelled', 'AbortError')) }
    const finish = (callback, value) => { signal?.removeEventListener('abort', abort); callback(value) }
    reader.onload = () => finish(resolve, reader.result)
    reader.onerror = () => finish(reject, reader.error)
    reader.onabort = () => finish(reject, signal?.reason ?? new DOMException('Cancelled', 'AbortError'))
    signal?.addEventListener('abort', abort, { once: true })
    reader.readAsArrayBuffer(file)
  })
  checkAbort(signal)
  if (bytes.byteLength !== file.size) throw new Error('The original file changed while reading')
  const result = await checksum(bytes, digest); checkAbort(signal); return result
}

export async function hashRecipeText(text) { return checksum(new TextEncoder().encode(text), digestBytes) }

async function boundedResponse(response, signal) {
  if (Number(response.headers.get('Content-Length')) > RECIPE_RESPONSE_LIMIT) {
    await response.body?.cancel(); throw new Error('Recovery response exceeds its byte limit')
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('Recovery response is unavailable')
  const abort = () => { void reader.cancel().catch(() => {}) }
  signal.addEventListener('abort', abort, { once: true })
  const chunks = []; let size = 0
  try {
    while (true) {
      checkAbort(signal)
      const { value, done } = await reader.read()
      checkAbort(signal)
      if (done) break
      size += value.byteLength
      if (size > RECIPE_RESPONSE_LIMIT) throw new Error('Recovery response exceeds its byte limit')
      chunks.push(value)
    }
    const bytes = new Uint8Array(size); let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  } catch (error) {
    await reader.cancel().catch(() => {}); throw error
  } finally {
    signal.removeEventListener('abort', abort); reader.releaseLock()
  }
}

/** Data-only transport: respects tab policy, never reads or installs its Design. */
export function createRecipeFileRecoveryEndpoints({ rawRequest = (...args) => fetch(...args) } = {}) {
  async function send(file, header, { signal } = {}) {
    requireRecipeFile(file); checkAbort(signal)
    const metadata = new TextEncoder().encode(JSON.stringify(header))
    if (metadata.byteLength > HEADER_LIMIT) throw new Error('Recovery metadata exceeds its byte limit')
    const prefix = new Uint8Array(4); new DataView(prefix.buffer).setUint32(0, metadata.byteLength)
    const abort = new AbortController(), forward = () => abort.abort(signal.reason)
    signal?.addEventListener('abort', forward, { once: true })
    const timer = setTimeout(() => abort.abort(new DOMException('Recovery timed out', 'TimeoutError')), TIMEOUT_MS)
    try {
      const response = await rawRequest('/api/part-recipe/recovery', { method: 'POST',
        headers: { ...docHeaders(), 'Content-Type': 'application/octet-stream' }, signal: abort.signal,
        body: new Blob([prefix, metadata, file]) })
      const result = await boundedResponse(response, abort.signal)
      if (!response.ok) throw new RepairRequestError(response.status, result.detail)
      return result
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', forward) }
  }
  return { inspect: (file, options) => send(file, { version: 1, operation: 'inspect' }, options),
    recover: async (file, request, options) => send(file, { version: 1, operation: 'recover', request: recoveryRequest(request) }, options) }
}
