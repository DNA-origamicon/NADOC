import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { importDesign, getGeometry, getStraightGeometry, listActiveJobs, resetRevisionWatermark, resizeStrandEnds, addNick, forcedLigation, addDeformation, createSweep, undo, redo, refreshNativeVRScene } from './client.js'
import { store } from '../state/store.js'
import { activeOperationTiming, beginOperationTiming, finishOperationTiming, markOperationTiming, finishOperationAfterRender } from '../perf/operation_timing.js'
import { clearProcessLog, processLogSnapshot } from '../perf/process_log.js'

let frames
const design = () => ({ id: 'timing-test', helices: [], strands: [], feature_log: [], deformations: [], extensions: [], overhangs: [] })
const response = payload => ({ ok: true, status: 200, headers: new Headers(), json: async () => payload })
const traces = () => processLogSnapshot().entries.filter(e => e.kind === 'Design operation')

const vrMutations = [
  ['resize', options => resizeStrandEnds([], options)],
  ['nick', options => addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, options)],
  ['ligate', options => forcedLigation('a', 'b', false, options)],
  ['bend', options => addDeformation('bend', 0, 10, {}, [], false, [], options)],
  ['twist', options => addDeformation('twist', 0, 10, {}, [], false, [], options)],
  ['sweep', options => createSweep({}, options)],
  ['undo', options => undo(options)], ['redo', options => redo(options)],
]
it.each(vrMutations)('%s starts VR export from the committed revision before desktop synchronization', async (_, mutate) => {
  const payload = { design: design(), revision: 7, nucleotides: [], helix_axes: [] }
  vi.stubGlobal('fetch', vi.fn(async () => response(payload)))
  const onCommitted = vi.fn(value => {
    expect(value).toBe(payload)
    expect(store.getState().currentDesign).toBeNull()
    // A pending export must not block synchronization of the desktop response.
    return new Promise(() => {})
  })
  await mutate({ onCommitted })
  expect(onCommitted).toHaveBeenCalledOnce()
  expect(store.getState().currentDesign.id).toBe(payload.design.id)
})

it.each(vrMutations)('%s does not start VR export after a rejected mutation', async (_, mutate) => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ...response({ detail: 'stale' }), ok: false, status: 409 })))
  const onCommitted = vi.fn()
  expect(await mutate({ onCommitted })).toBeNull()
  expect(onCommitted).not.toHaveBeenCalled()
})
it('never exports a transient deformation preview', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ design: design(), revision: 7, nucleotides: [], helix_axes: [] })))
  const onCommitted = vi.fn()
  await addDeformation('bend', 0, 10, {}, [], true, [], { onCommitted })
  expect(onCommitted).not.toHaveBeenCalled()
})
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

it('returns a geometry-free Nick commit before fetching complete desktop geometry', async () => {
  const events = []
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (url.endsWith('/design/nick')) {
      expect(options.headers['X-NADOC-Skip-Geometry']).toBe('1')
      return response({ design: design(), revision: 7 })
    }
    expect(url).toContain('/design/geometry')
    expect(options.headers['X-NADOC-Skip-Geometry']).toBeUndefined()
    events.push('geometry')
    return response({ nucleotides: [], helix_axes: [] })
  }))
  await addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, {
    deferGeometry: true, onCommitted: () => events.push('committed'),
  })
  expect(events).toEqual(['committed', 'geometry'])
  expect(store.getState().currentGeometry).toEqual([])
})


it('dispatches VR export immediately, before synchronous desktop rebuild work can run', async () => {
  const fetch = vi.fn(async () => response({ published: true }))
  vi.stubGlobal('fetch', fetch)
  const result = refreshNativeVRScene({ expected_design_id: 'd', expected_revision: 7 })
  // No microtask/frame barrier: an unnecessary await here serializes export
  // behind the caller's synchronous scene/store subscribers.
  expect(fetch).toHaveBeenCalledOnce()
  expect(await result).toEqual({ published: true })
})
