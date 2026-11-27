import { docHeadersFor, getDocId } from '../shared/doc_id.js'
import { _request, _syncFromDesignResponse, currentRevisionWatermark, lastErrorMessage } from './client.js'

export function captureBevelSource(design) {
  return { docId: getDocId(), expected_design_id: design.id, expected_revision: currentRevisionWatermark() }
}

export async function previewBevel(source, parameters, { signal, onEvent }) {
  const { docId, featureId, ...identity } = source
  const query = featureId ? `?feature_id=${encodeURIComponent(featureId)}` : ''
  const response = await fetch(`/api/design/bevel/preview${query}`, { method: 'POST', signal,
    headers: { ...docHeadersFor(docId), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...identity, ...parameters }) })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Bevel preview failed (${response.status}).`)
  onEvent({ type: 'guide', guide: body.guide })
  onEvent({ type: 'ready', candidate: body.candidate, preview_token: body.preview_token })
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
