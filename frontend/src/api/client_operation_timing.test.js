import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { _syncFromDesignResponse, importDesign, getGeometry, getStraightGeometry, listActiveJobs, resetRevisionWatermark, resizeStrandEnds, addNick, forcedLigation, addDeformation, createSweep, editFeature, undo, redo, refreshNativeVRScene } from './client.js'
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
  ['sweep edit', options => editFeature(0, {}, options)],
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

 it.each(vrMutations.filter(([name]) => ['bend', 'twist', 'sweep', 'sweep edit'].includes(name)))('%s defers geometry and starts export before fetching desktop geometry', async (_, mutate) => {
  const events = []
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (options.method === 'POST') {
      expect(options.headers['X-NADOC-Skip-Geometry']).toBe('1')
      return response({ design: design(), revision: 7 })
    }
    expect(url).toContain('/design/geometry')
    events.push('geometry')
    return response({ nucleotides: [], helix_axes: [] })
  }))
  await mutate({ deferGeometry: true, onCommitted: () => events.push('committed') })
  expect(events).toEqual(['committed', 'geometry'])
 })

it('keeps untouched helices when Nick defers a partial geometry response', async () => {
  const untouched = { helix_id: 'other', bp_index: 1 }
  store.setState({ currentGeometry: [untouched, { helix_id: 'h', bp_index: 1 }] })
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (options.method === 'POST') return response({ design: design(), revision: 7, deferred_geometry_helix_ids: ['h'] })
    expect(url).toContain('/design/geometry?helix_ids=h')
    return response({ nucleotides: [{ helix_id: 'h', bp_index: 2 }], helix_axes: [], partial_geometry: true, changed_helix_ids: ['h'] })
  }))
  await addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, { deferGeometry: true })
  expect(store.getState().currentGeometry).toEqual([untouched, { helix_id: 'h', bp_index: 2 }])
  expect(store.getState().currentGeometry[0]).toBe(untouched)
  expect(store.getState().lastPartialChangedHelixIds).toEqual(['h'])
})

it('applies a deferred commit and its geometry together, with no intermediate stale scene', async () => {
  const previous = design(), oldGeometry = [{ helix_id: 'old' }]
  store.setState({ currentDesign: previous, currentGeometry: oldGeometry })
  let finishGeometry
  vi.stubGlobal('fetch', vi.fn(async (url, options) => options.method === 'POST'
    ? response({ design: { ...previous, name: 'committed' }, revision: 7 })
    : new Promise(resolve => { finishGeometry = resolve })))
  const changes = []
  const unsubscribe = store.subscribe((next, prev) => {
    if (next.currentDesign !== prev.currentDesign || next.currentGeometry !== prev.currentGeometry)
      changes.push({ design: next.currentDesign, geometry: next.currentGeometry })
  })
  try {
    const pending = addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, { deferGeometry: true })
    await vi.waitFor(() => expect(finishGeometry).toBeTypeOf('function'))
    expect(store.getState().currentDesign).toBe(previous)
    expect(changes).toHaveLength(0)
    finishGeometry(response({ nucleotides: [{ helix_id: 'new' }], helix_axes: [] }))
    await pending
    expect(changes).toHaveLength(1)
    expect(changes[0].design.name).toBe('committed')
    expect(changes[0].geometry).toEqual([{ helix_id: 'new' }])
  } finally { unsubscribe() }
})


it('discards a late deferred geometry update after a newer committed response', async () => {
  const previous = design()
  store.setState({ currentDesign: previous, currentGeometry: [] })
  let finishGeometry
  vi.stubGlobal('fetch', vi.fn(async (url, options) => options.method === 'POST'
    ? response({ design: previous, revision: 7 })
    : new Promise(resolve => { finishGeometry = resolve })))
  const pending = addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, { deferGeometry: true })
  await vi.waitFor(() => expect(finishGeometry).toBeTypeOf('function'))
  const newer = { ...previous, name: 'newer' }, newerGeometry = [{ helix_id: 'newer' }]
  await _syncFromDesignResponse({ design: newer, revision: 8, nucleotides: newerGeometry, helix_axes: [] })
  finishGeometry(response({ nucleotides: [{ helix_id: 'stale' }], helix_axes: [] }))
  await pending
  expect(store.getState().currentDesign).toBe(newer)
  expect(store.getState().currentGeometry).toBe(newerGeometry)
})

it('retains committed history when deferred geometry fails', async () => {
  const committed = { ...design(), feature_log: [{ id: 'committed-entry' }] }
  vi.stubGlobal('fetch', vi.fn(async (url, options) => options.method === 'POST'
    ? response({ design: committed, revision: 7 })
    : { ...response({ detail: 'geometry unavailable' }), ok: false, status: 500 }))
  await addNick({ helixId: 'h', bpIndex: 1, direction: 'FORWARD' }, { deferGeometry: true })
  expect(store.getState().currentDesign).toBe(committed)
  expect(traces().some(trace => trace.status === 'Failed')).toBe(true)
})
