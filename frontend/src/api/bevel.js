import { docHeadersFor, getDocId } from '../shared/doc_id.js'
import { _request, _syncFromDesignResponse, currentRevisionWatermark, lastErrorMessage } from './client.js'
import { expandCompactNucleotides } from '../viewer/geometry_codec.js'

export function captureBevelSource(design) {
  return { docId: getDocId(), expected_design_id: design.id, expected_revision: currentRevisionWatermark() }
}

export async function previewBevel(source, parameters, { signal, onEvent, prepareOnly = false }) {
  const { docId, featureId, ...identity } = source
  signal?.throwIfAborted()
  const preparationId = crypto.randomUUID().replaceAll('-', '')
  const query = `?prepare_only=${prepareOnly}&preparation_id=${preparationId}${featureId ? `&feature_id=${encodeURIComponent(featureId)}` : ''}`
  // Some HTTP proxies keep the upstream request alive after fetch aborts.
  const cancel = () => { void fetch(`/api/design/bevel/preparations/${preparationId}/cancel`, {
    method: 'POST', headers: docHeadersFor(docId), keepalive: true,
  }).catch(() => {}) }
  signal?.addEventListener('abort', cancel, { once: true })
  try {
    const response = await fetch(`/api/design/bevel/preview${query}`, { method: 'POST', signal,
      headers: { ...docHeadersFor(docId), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...identity, ...parameters }) })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Bevel preview failed (${response.status}).`)
    onEvent({ type: 'guide', guide: body.guide })
    onEvent({ type: 'ready', candidate: body.candidate, preview_token: body.preview_token })
  } finally { signal?.removeEventListener('abort', cancel) }
}

export async function applyBevel(source, parameters, previewToken) {
  const { docId, featureId, ...identity } = source
  const response = await _request(featureId ? 'PATCH' : 'POST',
    featureId ? `/design/bevel/${encodeURIComponent(featureId)}` : '/design/bevel',
    { ...identity, ...parameters, preview_token: previewToken }, { docId })
  if (!response) throw new Error(lastErrorMessage() || 'Bevel could not be applied.')
  if (getDocId() === docId) await _syncFromDesignResponse(response)
  return response
}

export async function loadBevelSource(source, parameters, { signal, includeGeometry = true } = {}) {
  const { docId, featureId, ...identity } = source
  const query = `?include_geometry=${includeGeometry}&compact_geometry=true${featureId ? `&feature_id=${encodeURIComponent(featureId)}` : ''}`
  const response = await fetch(`/api/design/bevel/source${query}`, { method: 'POST', signal,
    headers: { ...docHeadersFor(docId), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...identity, ...parameters }) })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Bevel input could not be loaded.')
  if (body.component?.nucleotides_compact) {
    body.component.nucleotides = expandCompactNucleotides(body.component.nucleotides_compact)
    delete body.component.nucleotides_compact
  }
  return body
}
