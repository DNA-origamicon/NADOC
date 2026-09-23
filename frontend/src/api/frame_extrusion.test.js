import { describe, it, expect, vi } from 'vitest'
import { createFrameExtrusionAPI } from './frame_extrusion.js'

describe('frame extrusion API', () => {
  it('preflight leaves display alone; commit synchronizes the full response', async () => {
    const response = { design: { helices: ['new'] }, geometry: ['render'], revision: 7 }
    const request = vi.fn().mockResolvedValue(response)
    const sync = vi.fn(value => value)
    const api = createFrameExtrusionAPI({ request, sync })
    const body = { expected_revision: 6 }
    await api.validateFrameExtrusion(body)
    expect(sync).not.toHaveBeenCalled()
    expect(await api.addFrameExtrusion(body)).toBe(response)
    expect(sync).toHaveBeenCalledWith(response)
    expect(request).toHaveBeenLastCalledWith('POST', '/design/frame-extrusion', body)
  })
  it('does not replace displayed geometry after rejection', async () => {
    const sync = vi.fn()
    const api = createFrameExtrusionAPI({ request: async () => null, sync })
    expect(await api.addFrameExtrusion({})).toBeNull()
    expect(sync).not.toHaveBeenCalled()
  })
})

it('retries only the snapshot when autosave advances the same design revision', async () => {
  const request = vi.fn().mockResolvedValueOnce(null)
    .mockResolvedValueOnce({ design: { id:'part' }, revision:4 })
    .mockResolvedValueOnce({ published:true, scene_revision:4 })
  const api = createFrameExtrusionAPI({ request, sync:vi.fn() })
  expect(await api.refreshNativeVRScene({ expected_design_id:'part', expected_revision:3 }))
    .toEqual({ published:true, scene_revision:4 })
  expect(request.mock.calls).toEqual([
    ['POST','/vr/scene-refresh',{ expected_design_id:'part',expected_revision:3 }],
    ['GET','/design'],
    ['POST','/vr/scene-refresh',{ expected_design_id:'part',expected_revision:4 }],
  ])
})
it.each([{ id:'other', revision:4 }, { id:'part', revision:3 }])('does not retry changed identity or unchanged revision: %o', async current => {
  const request = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ design:{ id:current.id }, revision:current.revision })
  const api = createFrameExtrusionAPI({ request, sync:vi.fn() })
  expect(await api.refreshNativeVRScene({ expected_design_id:'part',expected_revision:3 })).toBeNull()
  expect(request).toHaveBeenCalledTimes(2)
})
