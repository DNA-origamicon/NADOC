import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { importDesign, getGeometry, getStraightGeometry, listActiveJobs, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'
import { activeOperationTiming, beginOperationTiming, finishOperationTiming, markOperationTiming, finishOperationAfterRender } from '../perf/operation_timing.js'
import { clearProcessLog, processLogSnapshot } from '../perf/process_log.js'

let frames
const design = () => ({ id: 'timing-test', helices: [], strands: [], feature_log: [], deformations: [], extensions: [], overhangs: [] })
const response = payload => ({ ok: true, status: 200, headers: new Headers(), json: async () => payload })
const traces = () => processLogSnapshot().entries.filter(e => e.kind === 'Design operation')
function flushFrames() { while (frames.length) frames.shift()() }
beforeEach(() => {
  frames = []
  vi.stubGlobal('requestAnimationFrame', callback => { frames.push(callback); return frames.length })
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  resetRevisionWatermark()
  store.setState({ currentDesign: null, currentGeometry: null })
  clearProcessLog()
})
afterEach(() => {
  while (activeOperationTiming()) finishOperationTiming(activeOperationTiming(), { status: 'Failed' })
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers()
  localStorage.clear()
})
it('finishes both overlapping imports and child geometry with no renderer subscriber', async () => {
  const pending = []
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.includes('/design/geometry')) return Promise.resolve(response({ nucleotides: [], helix_axes: [] }))
    return new Promise(resolve => pending.push(resolve))
  }))
  const a = importDesign('first'), b = importDesign('second')
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  pending[0](response({ design: design(), revision: 1 }))
  await a
  pending[1](response({ design: design(), revision: 2 }))
  await b
  expect(traces()).toHaveLength(4)
  flushFrames()
  expect(traces().every(trace => trace.status === 'Completed')).toBe(true)
  expect(activeOperationTiming()).toBeNull()
})
it('closes a stale import as superseded without claiming it rendered', async () => {
  const pending = []
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => pending.push(resolve))))
  const a = importDesign('old'), b = importDesign('new')
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  pending[1](response({ design: design(), revision: 2, nucleotides: [] }))
  await b
  pending[0](response({ design: design(), revision: 1, nucleotides: [] }))
  await a
  flushFrames()
  expect(traces().map(trace => trace.status)).toEqual(['Superseded', 'Completed'])
  expect(activeOperationTiming()).toBeNull()
})
it('marks application errors failed even when the HTTP request succeeded', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ nucleotides: [], helix_axes: {} })))
  await expect(getGeometry()).rejects.toThrow()
  expect(traces()[0].status).toBe('Failed')
  expect(activeOperationTiming()).toBeNull()
})
it('does not claim an import succeeded when its required geometry request fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => url.includes('/geometry')
    ? { ...response({ detail: 'geometry unavailable' }), ok: false, status: 500 }
    : response({ design: design(), revision: 1 })))
  await importDesign('design')
  expect(traces().map(trace => trace.status)).toEqual(['Failed', 'Failed'])
  expect(activeOperationTiming()).toBeNull()
})
it('completes after application even when a renderer tries finishing too early', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ nucleotides: [], helix_axes: [] })))
  const unsubscribe = store.subscribe((next, prev) => {
    if (next.currentGeometry !== prev.currentGeometry) {
      markOperationTiming('test-renderer')
      finishOperationAfterRender()
      expect(frames).toHaveLength(0)
    }
  })
  try { await getGeometry() } finally { unsubscribe() }
  expect(traces()[0].detail).toContain('test-renderer')
  flushFrames()
  expect(traces()[0].status).toBe('Completed')
})
it('reports applied rather than running forever when frames are suspended', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('requestAnimationFrame', callback => { frames.push(callback); return frames.length })
  vi.stubGlobal('fetch', vi.fn(async () => response({ nucleotides: [], helix_axes: [] })))
  await getGeometry()
  await vi.advanceTimersByTimeAsync(2000)
  expect(traces()[0].status).toBe('Applied')
  expect(traces()[0].detail).toContain('render-unconfirmed')
  flushFrames()
  expect(traces()[0].status).toBe('Applied')
  expect(activeOperationTiming()).toBeNull()
})
it('logs straight geometry as an API request without waiting for a scene rebuild', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ nucleotides: [], helix_axes: [] })))
  await getStraightGeometry()
  expect(traces()).toHaveLength(0)
  expect(processLogSnapshot().entries.at(-1).status).toBe('Completed')
})

it('does not indefinitely reuse activity status when an operation stays pending', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async () => response({ jobs: [], count: 0 })))
  await listActiveJobs()
  beginOperationTiming('pending operation')
  await listActiveJobs()
  expect(fetch).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(4001)
  const refresh = listActiveJobs()
  await vi.advanceTimersByTimeAsync(2000)
  await refresh
  expect(fetch).toHaveBeenCalledTimes(2)
})
