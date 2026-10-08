import { describe, it, expect, vi, afterEach } from 'vitest'
import { createFeatureSeekFeedback, seekWithPreview } from './feature_seek.js'

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
afterEach(() => vi.unstubAllGlobals())
function setup() {
  vi.stubGlobal('requestAnimationFrame', fn => { fn(); return 1 })
  const ready = deferred()
  const api = { previewFeatures: vi.fn(async () => ({ preview_token: 'token' })),
    seekFeatures: vi.fn(() => ready.promise), currentDesignId: () => 'design' }
  const clear = vi.fn(), showPreview = vi.fn(() => clear)
  return { api, clear, showPreview, ready }
}

describe('feature stage preparation', () => {
  it('shows a preview while editable content is pending and restores display on completion', async () => {
    const s = setup()
    const work = seekWithPreview({ ...s, position: 4, subPosition: 2 })
    await vi.waitFor(() => expect(s.api.seekFeatures).toHaveBeenCalledWith(4, 2, { preview_token: 'token' }))
    expect(s.showPreview).toHaveBeenCalledOnce()
    expect(s.clear).not.toHaveBeenCalled()
    s.ready.resolve({ design: { id: 'design' } })
    await work
    expect(s.clear).toHaveBeenCalledOnce()
  })
  it('does not commit an obsolete queued stage', async () => {
    const s = setup()
    await seekWithPreview({ ...s, position: 3, isSuperseded: () => true })
    expect(s.showPreview).not.toHaveBeenCalled()
    expect(s.api.seekFeatures).not.toHaveBeenCalled()
  })
  it('clears the preview on commit failure', async () => {
    const s = setup()
    s.ready.resolve(null)
    await expect(seekWithPreview({ ...s, position: 3 })).rejects.toThrow('Could not load')
    expect(s.clear).toHaveBeenCalledOnce()
  })
  it('falls back to the ordinary seek when preview cannot be prepared', async () => {
    const s = setup()
    s.api.previewFeatures.mockResolvedValue(null)
    s.ready.resolve({ design: {} })
    await seekWithPreview({ ...s, position: 3 })
    expect(s.api.seekFeatures).toHaveBeenCalledWith(3, undefined, {})
    expect(s.showPreview).not.toHaveBeenCalled()
  })
  it('keeps readiness visible and editing locked until completion', () => {
    const thumb = document.createElement('div'), panel = document.createElement('div')
    const store = { setState: vi.fn() }
    const feedback = createFeatureSeekFeedback(thumb, panel, store)
    feedback.setBusy(true)
    expect(thumb.dataset.readiness).toBe('loading')
    expect(thumb.querySelector('[role=status]').style.display).toBe('')
    expect(store.setState).toHaveBeenLastCalledWith({ featureSeekPending: true })
    feedback.setBusy(false)
    expect(thumb.dataset.readiness).toBe('ready')
    expect(panel.getAttribute('aria-busy')).toBe('false')
    expect(store.setState).toHaveBeenLastCalledWith({ featureSeekPending: false })
  })
})
