import { expect, it, vi } from 'vitest'
import { validateBundleContinuation } from './client.js'

it('passes an explicit source frame through the read-only continuation preflight', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok:true, status:200,
    headers:{ get:() => null }, json:async () => ({ status:'ok' }) })))
  try {
    await validateBundleContinuation({ cells:[[0,0]], lengthBp:21, sourceFrameId:'rotated-frame', expectedDesignId:'doc', expectedRevision:7 })
    expect(JSON.parse(fetch.mock.calls[0][1].body).source_frame_id).toBe('rotated-frame')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ expected_design_id:'doc',expected_revision:7 })
    await validateBundleContinuation({ cells:[[0,0]], lengthBp:21 })
    expect(JSON.parse(fetch.mock.calls[1][1].body)).not.toHaveProperty('source_frame_id')
  } finally { vi.unstubAllGlobals() }
})
