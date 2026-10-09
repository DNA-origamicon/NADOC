import { describe, it, expect, vi } from 'vitest'
import { createVRCommitRefresh } from './vr_commit_refresh.js'

function setup(refresh = async () => ({ published: true })) {
  const api = { refreshNativeVRScene: vi.fn(refresh), currentRevisionWatermark: () => 8 }
  return { api, refresh: createVRCommitRefresh({ api, getState: () => ({ currentDesign: { id: 'current' } }) }) }
}
describe('VR export overlap', () => {
  it('starts on the committed response before desktop state changes and waits for export', async () => {
    let finish
    const h = setup(() => new Promise(resolve => { finish = resolve }))
    h.refresh.onCommitted({ design: { id: 'committed' }, revision: 7 })
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledExactlyOnceWith({ expected_design_id: 'committed', expected_revision: 7 })
    let done = false
    const result = h.refresh.complete().then(value => { done = true; return value })
    await Promise.resolve(); expect(done).toBe(false)
    finish({ published: true, scene_revision: 8 })
    expect(await result).toEqual({ published: true, scene_revision: 8 })
    h.refresh.onCommitted({ design: { id: 'newer' }, revision: 9 })
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledOnce()
  })
  it('falls back once after compact response synchronization', async () => {
    const h = setup()
    h.refresh.onCommitted({ revision: 7 })
    expect(h.api.refreshNativeVRScene).not.toHaveBeenCalled()
    expect(await h.refresh.complete()).toEqual({ published: true })
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledExactlyOnceWith({ expected_design_id: 'current', expected_revision: 8 })
  })
  it('retains an early rejection until the caller checks completion', async () => {
    const h = setup(async () => { throw new Error('stale revision') })
    h.refresh.onCommitted({ design: { id: 'd' }, revision: 7 })
    await new Promise(resolve => setTimeout(resolve, 0))
    await expect(h.refresh.complete()).rejects.toThrow('stale revision')
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledOnce()
  })
})
