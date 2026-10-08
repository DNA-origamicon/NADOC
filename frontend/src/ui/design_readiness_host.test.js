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
  expect(badge.hidden).toBe(false)
  if (event === 'reset') window.dispatchEvent(new Event('nadoc:document-reset'))
  else mocks.broadcast({ type: 'session-closed' })
  expect(badge.hidden).toBe(true)
  finish()
  await vi.advanceTimersByTimeAsync(20000)
  expect(badge.hidden).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1)
  store.setState({ currentDesign: { id: 'new', helices: [{}] } })
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(false)
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
  const dismiss = badge.querySelector('[aria-label="Dismiss design readiness"]')
  dismiss.click()
  expect(badge.hidden).toBe(true)
  expect(badge.querySelector('.design-readiness__popover').hidden).toBe(true)
  store.setState({ [key]: { id: 'part', helices: [{ id: 'edited' }] } })
  window.dispatchEvent(new Event('focus'))
  window.dispatchEvent(new Event('nadoc:sim-jobs-changed'))
  await vi.advanceTimersByTimeAsync(20000)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(badge.hidden).toBe(true)

  fetch.mockResolvedValue({ ok: true, json: async () => ({ ...ready, state: 'ready', completed_steps: 2, simulation: { complete: true } }) })
  document.getElementById('menu-view-design-readiness').click()
  expect(badge.hidden).toBe(false)
  expect(badge.textContent).toContain('Checking')
  await vi.advanceTimersByTimeAsync(200)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(badge.hidden).toBe(false)
  expect(badge.textContent).toContain('Simulation complete')

  window.dispatchEvent(new Event('nadoc:document-reset'))
  store.setState({ [key]: null })
  document.getElementById('menu-view-design-readiness').click()
  await vi.advanceTimersByTimeAsync(200)
  expect(badge.hidden).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(2)
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
