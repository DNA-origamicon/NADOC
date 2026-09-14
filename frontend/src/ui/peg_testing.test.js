import { afterEach, expect, it, vi } from 'vitest'
import { showPegTesting } from './peg_testing.js'

let modal
const entry = (n, id) => ({ n, id, completed: true, label: `N${n} replica 1`, frames: 3,
  particles: 1, chains: 1, kind: 'GPU chain', temperature: 294, replica: 1,
  validationPassed: n === 36, sampling: 'md', dtFs: 1, steps: [0, 1000, 2000],
  rmsRgNm: [1, 2, 3], availableFrames: 3, radiusNm: 4, url: `/${id}` })
const get = name => document.querySelector(`[data-peg="${name}"]`)
afterEach(() => { modal?.close(); modal = null; vi.unstubAllGlobals() })

it('selects lengths, scrubs exact frames, plays/pauses and disposes on close', async () => {
  let tick
  vi.stubGlobal('requestAnimationFrame', callback => { tick = callback; return 1 })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const view = { load: vi.fn(), setFrame: vi.fn(), render: vi.fn(), dispose: vi.fn() }
  const fetchData = vi.fn(async url => ({ ok: true,
    json: async () => ({ version: 1, entries: [entry(36, 'a'), entry(76, 'b')] }),
    arrayBuffer: async () => new Float32Array([0, 1, 2, 3, 4, 5, 6, 7, 8]).buffer }))
  modal = showPegTesting({ fetchData, createView: () => view })
  await vi.waitFor(() => expect(get('play').disabled).toBe(false))
  expect(get('n').value).toBe('36')
  get('slider').value = '1'; get('slider').dispatchEvent(new Event('input'))
  expect(get('frame').textContent).toBe('2 / 3')
  expect([...view.setFrame.mock.lastCall[0]]).toEqual([3, 4, 5])
  get('play').click(); expect(get('play').textContent).toBe('Pause')
  tick(performance.now() + 1000)
  expect(get('frame').textContent).toBe('3 / 3')
  expect(get('play').textContent).toBe('Play')
  get('play').click(); expect(get('frame').textContent).toBe('1 / 3')
  get('play').click(); expect(get('play').textContent).toBe('Play')
  get('n').value = '76'; get('n').dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(get('verdict').textContent).toContain('unresolved'))
  expect(get('frame').textContent).toBe('1 / 3')
  modal.close(); expect(view.dispose).toHaveBeenCalledOnce()
})

it('reports missing data without enabling playback', async () => {
  const view = { render() {}, dispose() {} }
  modal = showPegTesting({ createView: () => view, fetchData: async () => ({ ok: false }) })
  await vi.waitFor(() => expect(get('status').textContent).toContain('catalog is unavailable'))
  expect(get('play').disabled).toBe(true)
})

it('aborts an in-flight catalog request when closed', async () => {
  let signal
  modal = showPegTesting({ createView: () => ({ render() {}, dispose() {} }),
    fetchData: (_url, options) => { signal = options.signal; return new Promise(() => {}) } })
  modal.close()
  expect(signal.aborted).toBe(true)
})
