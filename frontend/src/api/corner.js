import { docHeadersFor, getDocId } from '../shared/doc_id.js'
import { _request, _syncFromDesignResponse, currentRevisionWatermark } from './client.js'

export function captureCornerSource(design) {
  return { docId: getDocId(), expected_design_id: design.id, expected_revision: currentRevisionWatermark() }
}

export async function readCornerStream(response, onEvent) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `Corner preview failed (${response.status}).`)
  }
  if (!response.body) throw new Error('Corner preview stream is unavailable.')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let pending = '', ready = false
  function accept(line) {
    if (!line.trim()) return
    const event = JSON.parse(line)
    if (event.type === 'error') throw new Error(event.message)
    if (event.type === 'ready') ready = true
    onEvent(event)
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      let newline
      while ((newline = pending.indexOf('\n')) !== -1) {
        accept(pending.slice(0, newline)); pending = pending.slice(newline + 1)
      }
    }
    pending += decoder.decode()
    if (pending.trim()) accept(pending)
    if (!ready) throw new Error('Corner preview ended before the Full geometry was ready.')
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}

export async function previewCorner(source, parameters, { signal, onEvent }) {
  const { docId, featureId, ...identity } = source
  const query = featureId ? `?feature_id=${encodeURIComponent(featureId)}` : ''
  const response = await fetch(`/api/design/corner/preview${query}`, { method: 'POST', signal,
    headers: { ...docHeadersFor(docId), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...identity, ...parameters }) })
  return readCornerStream(response, onEvent)
}

export async function applyCorner(source, parameters) {
  const { docId, featureId, ...identity } = source
  const response = await _request(featureId ? 'PATCH' : 'POST',
    featureId ? `/design/corner/${encodeURIComponent(featureId)}` : '/design/corner',
    { ...identity, ...parameters }, { docId })
  if (!response) throw new Error('Corner could not be applied.')
  if (getDocId() === docId) await _syncFromDesignResponse(response)
  return response
}
