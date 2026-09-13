import { describe, it, expect, vi } from 'vitest'
import { initAnimationDefaults } from './animation_defaults.js'

function setup(context = {}) {
  const state = { currentDesign: { id: 'd', animations: [] }, currentAssembly: { id: 'a', animations: [] } }
  const api = { createAnimation: vi.fn(), createAssemblyAnimation: vi.fn() }
  const onError = vi.fn()
  const defaults = initAnimationDefaults({ store: { getState: () => state }, api, getContext: () => context, onError })
  return { state, api, defaults, onError }
}
describe('initial animation', () => {
  it('creates animation 1 once despite repeated updates and concurrent views', async () => {
    const { defaults, api } = setup()
    await Promise.all([defaults.ensure(), defaults.ensure(), defaults.ensure()])
    expect(api.createAnimation).toHaveBeenCalledExactlyOnceWith('animation 1')
    expect(api.createAssemblyAnimation).not.toHaveBeenCalled()
  })
  it('preserves existing animations and respects later deletion', async () => {
    const { defaults, state, api } = setup()
    state.currentDesign.animations = [{ id: 'kept', name: 'My movie' }]
    await defaults.ensure()
    state.currentDesign = { id: 'd', animations: [] }
    await defaults.ensure()
    expect(api.createAnimation).not.toHaveBeenCalled()
    state.currentDesign = { id: 'next', animations: [] }
    await defaults.ensure()
    expect(api.createAnimation).toHaveBeenCalledOnce()
  })
  it('uses separate assembly and embedded-part contexts', async () => {
    const context = { assemblyMode: true }
    const { defaults, api } = setup(context)
    await defaults.ensure()
    expect(api.createAssemblyAnimation).toHaveBeenCalledExactlyOnceWith('animation 1')
    context.partMode = true
    context.partDesign = { id: 'd' }
    context.partInstanceId = 'p1'
    context.partPatchFn = vi.fn(fn => fn(context.partDesign))
    await defaults.ensure()
    expect(context.partDesign.animations[0]).toMatchObject({ name: 'animation 1', keyframes: [], fps: 30, loop: false })
    expect(context.partDesign.animations[0].id).toBeTruthy()
    expect(api.createAnimation).not.toHaveBeenCalled()
  })
  it('waits for a document and reports failures without a retry loop', async () => {
    const { defaults, state, api, onError } = setup()
    state.currentDesign = null
    await defaults.ensure()
    expect(api.createAnimation).not.toHaveBeenCalled()
    state.currentDesign = { id: 'd' }
    api.createAnimation.mockRejectedValue(new Error('offline'))
    await defaults.ensure(); await defaults.ensure()
    expect(onError).toHaveBeenCalledOnce()
    expect(api.createAnimation).toHaveBeenCalledOnce()
  })
})
