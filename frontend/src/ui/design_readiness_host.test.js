import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'

const mocks = vi.hoisted(() => ({ run: vi.fn(), broadcast: null }))
vi.mock('./design_readiness_actions.js', () => ({
  createDesignReadinessActions: () => ({ run: mocks.run, decorate: report => report, dispose: vi.fn() }),
}))
vi.mock('../shared/broadcast.js', () => ({
  nadocBroadcast: {
    onMessage: callback => { mocks.broadcast = callback; return () => {} },
    isSameDoc: () => true,
  },
}))
import { initDesignReadinessHost } from './design_readiness_host.js'
import { initAssemblySourceReadiness } from '../scene/assembly_source_readiness.js'

let host
const ready = { available: true, completed_steps: 0, total_steps: 2, steps: [] }
beforeEach(() => {
  vi.useFakeTimers()
  document.body.innerHTML = '<div id="canvas-area"></div>'
  history.replaceState({}, '', '/?readiness=simulation')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ready }))
})
afterEach(() => {
  host?.dispose()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  document.body.innerHTML = ''
  history.replaceState({}, '', '/')
})

it.each(['reset', 'session close'])('does not resurrect readiness after %s during pending navigation', async event => {
  let finish
  mocks.run.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const store = createMockStore({ currentDesign: { id: 'old', helices: [{}] } })
  host = initDesignReadinessHost({ store })
  await vi.advanceTimersByTimeAsync(200)
  expect(mocks.run).toHaveBeenCalledWith('simulation')
  const badge = document.querySelector('[data-role="design-readiness"]')
  expect(badge.hidden).toBe(true)
  if (event === 'reset') window.dispatchEvent(new Event('nadoc:document-reset'))
  else mocks.broadcast({ type: 'session-closed' })
  expect(badge.hidden).toBe(true)
  finish()
  await vi.advanceTimersByTimeAsync(20000)
  expect(badge.hidden).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1)
  store.setState({ currentDesign: { id: 'new', helices: [{}] } })
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(true)
  expect(mocks.run).toHaveBeenCalledTimes(1)
})

it.each(['3d', 'cadnano'])('dismisses until View > Design Readiness requests a fresh check in %s', async mode => {
  history.replaceState({}, '', '/')
  document.body.innerHTML = '<button id="menu-view-design-readiness">Design Readiness</button><div id="canvas-area"></div><div id="pathview-container"></div>'
  const key = mode === 'cadnano' ? 'design' : 'currentDesign'
  const store = createMockStore({ [key]: { id: 'part', helices: [{}] } })
  host = initDesignReadinessHost({ store, mode })
  await vi.advanceTimersByTimeAsync(200)
  const badge = document.querySelector('[data-role="design-readiness"]')
  expect(badge.hidden).toBe(true)
  store.setState({ [key]: { id: 'part', helices: [{ id: 'loaded' }] } })
  window.dispatchEvent(new Event('focus'))
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(true)
  document.getElementById('menu-view-design-readiness').click()
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(false)
  fetch.mockClear()
  const dismiss = badge.querySelector('[aria-label="Dismiss design readiness"]')
  dismiss.click()
  expect(badge.hidden).toBe(true)
  expect(badge.querySelector('.design-readiness__popover').hidden).toBe(true)
  store.setState({ [key]: { id: 'part', helices: [{ id: 'edited' }] } })
  window.dispatchEvent(new Event('focus'))
  window.dispatchEvent(new Event('nadoc:sim-jobs-changed'))
  await vi.advanceTimersByTimeAsync(20000)
  expect(fetch).toHaveBeenCalledTimes(0)
  expect(badge.hidden).toBe(true)

  fetch.mockResolvedValue({ ok: true, json: async () => ({ ...ready, state: 'ready', completed_steps: 2, simulation: { complete: true } }) })
  document.getElementById('menu-view-design-readiness').click()
  expect(badge.hidden).toBe(false)
  expect(badge.textContent).toContain('Checking')
  await vi.advanceTimersByTimeAsync(200)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(badge.hidden).toBe(false)
  expect(badge.textContent).toContain('Simulation complete')

  window.dispatchEvent(new Event('nadoc:document-reset'))
  store.setState({ [key]: { id: 'new', helices: [{}] } })
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(true)
  store.setState({ [key]: null })
  fetch.mockClear()
  document.getElementById('menu-view-design-readiness').click()
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(true)
  expect(fetch).not.toHaveBeenCalled()
})

it('ignores an in-flight readiness response after dismissal', async () => {
  history.replaceState({}, '', '/')
  let finish
  fetch.mockReturnValue(new Promise(resolve => { finish = resolve }))
  host = initDesignReadinessHost({ store: createMockStore({ currentDesign: { id: 'part', helices: [{}] } }) })
  await vi.advanceTimersByTimeAsync(200)
  const badge = document.querySelector('[data-role="design-readiness"]')
  badge.querySelector('[aria-label="Dismiss design readiness"]').click()
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
  finish({ ok: true, json: async () => ready })
  await vi.advanceTimersByTimeAsync(20000)
  expect(badge.hidden).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('keeps assembly readiness unknown until the renderer is ready, then assesses it on the backend', async () => {
  history.replaceState({}, '', '/')
  let finish
  const waitForAssemblyReady = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const assembly = { id: 'assembly', instances: [{ id: 'part' }] }
  host = initDesignReadinessHost({ store: createMockStore({ assemblyActive: true, currentAssembly: assembly }), waitForAssemblyReady })
  await vi.advanceTimersByTimeAsync(200)
  expect(waitForAssemblyReady).toHaveBeenCalledWith(assembly, { signal: expect.any(AbortSignal) })
  expect(fetch).not.toHaveBeenCalled()
  expect(document.querySelector('[data-role="design-readiness"]').textContent).toContain('Checking')
  finish(); await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledOnce()
  expect(fetch.mock.calls[0][0]).toBe('/api/design/readiness?assembly=true')
})

it('aborts a stale assembly wait without issuing its readiness request after document switch', async () => {
  history.replaceState({}, '', '/')
  let finish, signal
  const waitForAssemblyReady = vi.fn((_, options) => {
    signal = options.signal
    return new Promise(resolve => { finish = resolve })
  })
  const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'old', instances: [{ id: 'a' }] } })
  host = initDesignReadinessHost({ store, waitForAssemblyReady })
  await vi.advanceTimersByTimeAsync(200)
  store.setState({ assemblyActive: false, currentAssembly: null, currentDesign: { id: 'new', helices: [{}] } })
  expect(signal.aborted).toBe(true)
  finish(); await vi.advanceTimersByTimeAsync(200)
  expect(fetch).toHaveBeenCalledOnce()
  expect(fetch.mock.calls[0][0]).toBe('/api/design/readiness')
})

it('keeps a failed geometry load unavailable on polls and explicit Show, then recovers after a renderer retry', async () => {
  history.replaceState({}, '', '/')
  let rendered = false
  const gate = initAssemblySourceReadiness({ isReady: () => rendered })
  const assembly = { id: 'assembly', instances: [{ id: 'part' }] }
  host = initDesignReadinessHost({ store: createMockStore({ assemblyActive: true, currentAssembly: assembly }),
    waitForAssemblyReady: gate.whenReady })
  await vi.advanceTimersByTimeAsync(200)
  gate.fail(new Error('Geometry unavailable'))
  await vi.advanceTimersByTimeAsync(0)
  const badge = document.querySelector('[data-role="design-readiness"]')
  expect(badge.dataset.state).toBe('unavailable')
  await vi.advanceTimersByTimeAsync(10000)
  expect(badge.dataset.state).toBe('unavailable')
  expect(fetch).not.toHaveBeenCalled()
  host.show()
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.dataset.state).toBe('unavailable')
  expect(badge.hasAttribute('aria-busy')).toBe(false)
  gate.begin()
  host.show()
  await vi.advanceTimersByTimeAsync(200)
  rendered = true
  gate.notify()
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledOnce()
  expect(badge.dataset.state).not.toBe('loading')
})
