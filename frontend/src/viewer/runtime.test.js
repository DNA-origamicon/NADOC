import { it, expect, vi, afterEach } from 'vitest'
vi.mock('three', async importOriginal => {
  const actual = await importOriginal()
  return { ...actual, WebGLRenderer: vi.fn(function () {
    this.xr = { isPresenting: false }; this.setSize = vi.fn(); this.setPixelRatio = vi.fn(); this.setClearColor = vi.fn()
    this.setAnimationLoop = vi.fn(); this.dispose = vi.fn(); this.render = vi.fn()
  }) }
})
import { initScene } from './runtime.js'
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
it('stops rendering, controls, resize observer and pending camera animation on disposal', async () => {
  const disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect = disconnect })
  document.body.innerHTML = '<div><canvas></canvas></div>'
  const runtime = initScene(document.querySelector('canvas'))
  expect(runtime.isStandardRender()).toBe(true)
  runtime.setRenderFn(() => {})
  expect(runtime.isStandardRender()).toBe(false)
  runtime.resetRenderFn()
  expect(runtime.isStandardRender()).toBe(true)
  const controls = runtime.getActiveControls(), stopControls = vi.spyOn(controls, 'dispose')
  const work = runtime.animateCameraTo({ position: [3, 2, 1], target: [0, 0, 0], up: [0, 1, 0], duration: 1000 })
  runtime.dispose(); runtime.dispose()
  await work
  expect(runtime.renderer.setAnimationLoop).toHaveBeenLastCalledWith(null)
  expect(runtime.renderer.dispose).toHaveBeenCalledTimes(1)
  expect(stopControls).toHaveBeenCalledTimes(1)
  expect(disconnect).toHaveBeenCalledTimes(1)
})

it('caps mobile resolution and skips rendering while the document is hidden', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  document.body.innerHTML = '<div><canvas></canvas></div>'
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  const runtime = initScene(document.querySelector('canvas'), { pixelRatioCap: 1, pauseWhenHidden: true })
  const frame = runtime.renderer.setAnimationLoop.mock.calls[0][0]
  expect(runtime.renderer.setPixelRatio.mock.calls[0][0]).toBeLessThanOrEqual(1)
  frame(); expect(runtime.renderer.render).not.toHaveBeenCalled()
  hidden.mockReturnValue(false); frame(); expect(runtime.renderer.render).toHaveBeenCalledOnce()
  runtime.dispose(); hidden.mockRestore()
})
