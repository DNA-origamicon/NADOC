import { it, expect, vi, afterEach } from 'vitest'
vi.mock('three', async importOriginal => {
  const actual = await importOriginal()
  return { ...actual, WebGLRenderer: vi.fn(function () {
    this.xr = { isPresenting: false }; this.setSize = vi.fn(); this.setPixelRatio = vi.fn(); this.setClearColor = vi.fn()
    this.setAnimationLoop = vi.fn(); this.dispose = vi.fn(); this.render = vi.fn()
  }) }
})
import { initScene } from './runtime.js'
import { requestTrajectoryFrame } from '../ui/trajectory_render_clock.js'
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
  hidden.mockReturnValue(true); runtime.renderer.xr.isPresenting = true
  const trajectory = vi.fn(); requestTrajectoryFrame(trajectory)
  frame()
  expect(trajectory).toHaveBeenCalledOnce()
  expect(runtime.renderer.render).toHaveBeenCalledTimes(2)
  runtime.dispose(); hidden.mockRestore()
})

it('yields background desktop draws to native VR while keeping synchronization alive', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  document.body.innerHTML = '<div><canvas></canvas></div>'
  const focused = vi.spyOn(document, 'hasFocus').mockReturnValue(false)
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  const runtime = initScene(document.querySelector('canvas'))
  const frame = runtime.renderer.setAnimationLoop.mock.calls[0][0]
  const synchronize = vi.fn(), trajectory = vi.fn(), customDraw = vi.fn()
  runtime.addFrameCallback(synchronize)
  frame()
  expect(runtime.renderer.render).toHaveBeenCalledOnce()
  runtime.setNativeVRActive(true)
  requestTrajectoryFrame(trajectory)
  frame()
  expect(trajectory).toHaveBeenCalledOnce()
  expect(synchronize).toHaveBeenCalledTimes(2)
  expect(runtime.renderer.render).toHaveBeenCalledOnce()
  runtime.setRenderFn(customDraw)
  frame(); expect(customDraw).not.toHaveBeenCalled()
  focused.mockReturnValue(true)
  frame(); expect(customDraw).toHaveBeenCalledOnce()
  hidden.mockReturnValue(true)
  frame(); expect(customDraw).toHaveBeenCalledOnce()
  runtime.renderer.xr.isPresenting = true
  frame(); expect(customDraw).toHaveBeenCalledTimes(2)
  runtime.renderer.xr.isPresenting = false
  runtime.setNativeVRActive(false)
  frame(); expect(customDraw).toHaveBeenCalledTimes(3)
  runtime.dispose(); focused.mockRestore(); hidden.mockRestore()
})

it('can suppress focused desktop drawing without stopping transactions or trajectory updates, and resumes after VR', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  document.body.innerHTML = '<div><canvas></canvas></div>'
  const focused = vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  const runtime = initScene(document.querySelector('canvas'))
  const frame = runtime.renderer.setAnimationLoop.mock.calls[0][0]
  const synchronize = vi.fn(), trajectory = vi.fn(), draw = vi.fn()
  runtime.addFrameCallback(synchronize)
  runtime.setRenderFn(draw)
  runtime.setNativeVRDesktopEnabled(false)
  frame(); expect(draw).toHaveBeenCalledOnce()
  runtime.setNativeVRActive(true)
  requestTrajectoryFrame(trajectory)
  frame()
  expect(trajectory).toHaveBeenCalledOnce()
  expect(synchronize).toHaveBeenCalledTimes(2)
  expect(draw).toHaveBeenCalledOnce()
  runtime.setNativeVRDesktopEnabled(true)
  frame(); expect(draw).toHaveBeenCalledTimes(2)
  runtime.setNativeVRDesktopEnabled(false)
  runtime.renderer.xr.isPresenting = true
  frame(); expect(draw).toHaveBeenCalledTimes(3)
  runtime.renderer.xr.isPresenting = false
  runtime.setNativeVRActive(false)
  frame(); expect(draw).toHaveBeenCalledTimes(4)
  runtime.dispose(); focused.mockRestore()
})
