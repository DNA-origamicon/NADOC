import { docHeaders } from '../shared/doc_id.js'

/** Open the saved feature in the native editor without changing the document. */
export async function openVRSweepEdit({ entry, index, api, getState, request = fetch }) {
  const design = getState().currentDesign
  if (design?.feature_log?.[index]?.id !== entry.id || entry.op_kind !== 'sweep') throw new Error('Sweep feature changed; reopen the Feature Log.')
  const response = await request('/api/vr/sweep-edit', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ index, feature_id: entry.id, expected_design_id: design.id, expected_revision: api.currentRevisionWatermark() }) })
  const result = await response.json()
  if (!response.ok || !result.published) throw new Error(result.detail || 'Could not open the VR Sweep editor')
  return result
}
