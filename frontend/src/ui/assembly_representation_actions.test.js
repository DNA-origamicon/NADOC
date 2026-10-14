import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createAssemblyRepresentationActions } from './assembly_representation_actions.js'
import { recordAssemblyResponse } from '../api/assembly_response_authority.js'

const controllers = []
afterEach(() => { for (const controller of controllers.splice(0)) controller.dispose() })
const flush = async () => { for (let i = 0; i < 4; i++) await Promise.resolve() }
function fixture() {
  const rows = [{ id: 'a', representation: 'cylinders', visible: true }, { id: 'b', representation: 'beads' }]
  Object.defineProperty(rows[0], 'geometrySourceKey', { value: 'f:/part:2:', enumerable: false })
  const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'assembly', instances: rows } })
  const requests = [], errors = vi.fn()
  let revision = 0, docId = 'doc-a'
  const api = {
    batchPatchInstances: vi.fn((patches, options) => new Promise((resolve, reject) => requests.push({ patches, options, resolve, reject }))),
    _syncFromAssemblyResponse: vi.fn(json => {
      if (json.revision < revision) return json
      revision = json.revision
      recordAssemblyResponse(json.assembly, json)
      store.setState({ currentAssembly: json.assembly })
      return json
    }),
  }
  const actions = createAssemblyRepresentationActions({ store, api, documentId: () => docId, onError: errors })
  controllers.push(actions)
  const shown = () => store.getState().currentAssembly.instances.map(row => row.representation)
  const ack = (index, extra = {}) => requests[index].resolve({ revision: index + 1,
    assembly: { ...store.getState().currentAssembly, ...extra,
      instances: store.getState().currentAssembly.instances.map(row => ({ ...row,
        representation: requests[index].patches.find(patch => patch.id === row.id)?.representation ?? row.representation })) } })
  return { store, api, actions, requests, errors, shown, ack, setDocument: value => { docId = value }, setRevision: value => { revision = value } }
}

describe('assembly representation actions', () => {
  it('shows a CG choice synchronously, preserving source version and all other row fields', async () => {
    const f = fixture(), original = f.store.getState().currentAssembly
    const saved = f.actions.choose('full')
    const row = f.store.getState().currentAssembly.instances[0]
    expect(f.shown()).toEqual(['full', 'full'])
    expect(row.visible).toBe(true)
    expect(Object.getOwnPropertyDescriptor(row, 'geometrySourceKey')).toEqual(Object.getOwnPropertyDescriptor(original.instances[0], 'geometrySourceKey'))
    expect(f.requests[0].options).toEqual({ skipSync: true, suppressBusy: true })
    expect(f.api._syncFromAssemblyResponse).not.toHaveBeenCalled()
    f.ack(0, { name: 'Server metadata' })
    expect(await saved).toBe(true)
    expect(f.api._syncFromAssemblyResponse).toHaveBeenCalledOnce()
    expect(f.store.getState().currentAssembly.name).toBe('Server metadata')
  })

  it('coalesces unsent choices and reapplies the latest display before the next microtask', async () => {
    const f = fixture()
    const first = f.actions.choose('full')
    const intermediate = f.actions.choose('beads')
    const last = f.actions.choose('hull-prism')
    expect(await intermediate).toBe(false)
    expect(f.requests).toHaveLength(1)
    expect(f.shown()).toEqual(['hull-prism', 'hull-prism'])
    const frames = []
    f.store.subscribe(() => queueMicrotask(() => frames.push(f.shown())))
    f.ack(0)
    await flush()
    expect(await first).toBe(true)
    expect(f.requests).toHaveLength(2)
    expect(f.requests[1].patches.every(row => row.representation === 'hull-prism')).toBe(true)
    expect(frames.every(frame => frame.every(rep => rep === 'hull-prism'))).toBe(true)
    f.ack(1)
    expect(await last).toBe(true)
  })

  it('rolls back a failed latest choice to the most recently confirmed representations', async () => {
    const f = fixture()
    const first = f.actions.choose('full')
    const last = f.actions.choose('beads')
    f.ack(0, { name: 'Confirmed metadata' })
    await first
    f.requests[1].resolve(null)
    expect(await last).toBe(false)
    expect(f.shown()).toEqual(['full', 'full'])
    expect(f.store.getState().currentAssembly.name).toBe('Confirmed metadata')
    expect(f.errors).toHaveBeenCalledOnce()
  })

  it('retains a newer display when an older write fails, then restores the original mixed view if both fail', async () => {
    const f = fixture()
    const first = f.actions.choose('full'), last = f.actions.choose('beads')
    f.requests[0].reject(new Error('offline'))
    expect(await first).toBe(false)
    expect(f.shown()).toEqual(['beads', 'beads'])
    f.requests[1].resolve(null)
    expect(await last).toBe(false)
    expect(f.shown()).toEqual(['cylinders', 'beads'])
  })

  it('keeps heavy choices in write order without displaying them before acknowledgement', async () => {
    const f = fixture()
    const heavy = f.actions.choose('surface')
    expect(f.requests[0].options.suppressBusy).toBe(false)
    expect(f.shown()).toEqual(['cylinders', 'beads'])
    const light = f.actions.choose('full')
    expect(f.shown()).toEqual(['full', 'full'])
    f.ack(0)
    await heavy
    expect(f.shown()).toEqual(['full', 'full'])
    f.ack(1)
    expect(await light).toBe(true)
  })

  it('coalesces an unsent heavy choice when a newer CG choice supersedes it', async () => {
    const f = fixture(), first = f.actions.choose('full')
    const heavy = f.actions.choose('surface'), last = f.actions.choose('cylinders')
    expect(await heavy).toBe(false)
    f.ack(0)
    await first
    expect(f.requests).toHaveLength(2)
    expect(f.requests[1].patches.every(row => row.representation === 'cylinders')).toBe(true)
    f.ack(1)
    expect(await last).toBe(true)
  })

  it('does not mistake copied optimistic rows for confirmation when newer poses or source geometry arrive', async () => {
    const f = fixture(), saved = f.actions.choose('full')
    const transform = { values: [1, 2, 3] }, source = { type: 'inline', design: { id: 'new-shape' } }
    const assembly = f.store.getState().currentAssembly
    const rows = assembly.instances.map(row => ({ ...row, transform, source }))
    Object.defineProperty(rows[0], 'geometrySourceKey', { value: 'f:/part:99:', enumerable: false })
    f.store.setState({ currentAssembly: { ...assembly, instances: rows, name: 'Updated shape' } })
    f.requests[0].resolve(null)
    expect(await saved).toBe(false)
    expect(f.shown()).toEqual(['cylinders', 'beads'])
    const current = f.store.getState().currentAssembly
    expect(current.name).toBe('Updated shape')
    expect(current.instances[0].transform).toBe(transform)
    expect(current.instances[0].source).toBe(source)
    expect(current.instances[0].geometrySourceKey).toBe('f:/part:99:')
  })

  it.each(['reset', 'assembly', 'document', 'membership', 'dispose'])('retires queued writes and late acknowledgements after %s changes', async reason => {
    const f = fixture()
    const first = f.actions.choose('full'), queued = f.actions.choose('beads')
    if (reason === 'reset') {
      window.dispatchEvent(new Event('nadoc:document-reset'))
      f.store.setState({ currentAssembly: { id: 'assembly', name: 'Reopened same ID',
        instances: [{ id: 'a', representation: 'cylinders' }, { id: 'b', representation: 'cylinders' }] } })
    }
    if (reason === 'assembly') f.store.setState({ currentAssembly: { id: 'other', instances: [{ id: 'z', representation: 'cylinders' }] } })
    if (reason === 'document') f.setDocument('doc-b')
    if (reason === 'membership') f.store.setState({ currentAssembly: { ...f.store.getState().currentAssembly, instances: [] } })
    if (reason === 'dispose') f.actions.dispose()
    const state = f.store.getState().currentAssembly
    f.ack(0)
    expect(await first).toBe(false)
    expect(await queued).toBe(false)
    expect(f.api._syncFromAssemblyResponse).not.toHaveBeenCalled()
    expect(f.requests).toHaveLength(1)
    expect(f.store.getState().currentAssembly).toBe(state)
  })

  it('does not save a choice confirmed after its original document was closed', async () => {
    const f = fixture(), context = f.actions.capture()
    window.dispatchEvent(new Event('nadoc:document-reset'))
    expect(await f.actions.choose('surface', context)).toBe(false)
    expect(f.requests).toHaveLength(0)
  })

  it('preserves external metadata and obeys the normal revision guard when an acknowledgement is stale', async () => {
    const f = fixture(), saved = f.actions.choose('full')
    f.api._syncFromAssemblyResponse({ revision: 10, assembly: { ...f.store.getState().currentAssembly, name: 'Newer server edit',
      instances: f.store.getState().currentAssembly.instances.map(row => ({ ...row, representation: 'beads', visible: false })) } })
    expect(f.shown()).toEqual(['full', 'full'])
    f.ack(0)
    await saved
    expect(f.shown()).toEqual(['beads', 'beads'])
    expect(f.store.getState().currentAssembly.name).toBe('Newer server edit')
    expect(f.store.getState().currentAssembly.instances[0].visible).toBe(false)
  })

  it('does not promote a delayed older optimistic clone when both queued saves fail', async () => {
    const f = fixture(), first = f.actions.choose('full')
    const delayed = { ...f.store.getState().currentAssembly, name: 'Delayed local metadata',
      instances: f.store.getState().currentAssembly.instances.map(row => ({ ...row })) }
    const latest = f.actions.choose('beads')
    f.store.setState({ currentAssembly: delayed })
    expect(f.shown()).toEqual(['beads', 'beads'])
    f.requests[0].resolve(null)
    await first
    f.requests[1].resolve(null)
    await latest
    expect(f.shown()).toEqual(['cylinders', 'beads'])
    expect(f.store.getState().currentAssembly.name).toBe('Delayed local metadata')
  })

  it('reads accepted acknowledgement values even if publication immediately creates a local clone', async () => {
    const f = fixture(), first = f.actions.choose('full')
    let copied = false
    const unsubscribe = f.store.subscribe(state => {
      if (copied) return
      copied = true
      f.store.setState({ currentAssembly: { ...state.currentAssembly, name: 'Local annotation',
        instances: state.currentAssembly.instances.map(row => ({ ...row, representation: 'beads' })) } })
    })
    f.ack(0)
    await first
    unsubscribe()
    expect(f.shown()).toEqual(['full', 'full'])
    expect(f.store.getState().currentAssembly.name).toBe('Local annotation')
    const failed = f.actions.choose('hull-prism')
    f.requests[1].resolve(null)
    await failed
    expect(f.shown()).toEqual(['full', 'full'])
  })

  it.each(['stale acknowledgement', 'failed acknowledgement'])('retains equal-value authoritative Full after a %s', async outcome => {
    const f = fixture(), saved = f.actions.choose('full')
    const authoritative = { ...f.store.getState().currentAssembly, name: 'Confirmed newer pose',
      instances: f.store.getState().currentAssembly.instances.map(row => ({ ...row, transform: { translation: [10, 0, 0] } })) }
    // The revision-accepted server pose already contains the displayed Full
    // values. Equal values still confirm them; local optimistic clones do not.
    f.api._syncFromAssemblyResponse({ assembly: authoritative, revision: 10 })
    if (outcome === 'stale acknowledgement') f.ack(0)
    else f.requests[0].resolve(null)
    await saved
    expect(f.shown()).toEqual(['full', 'full'])
    expect(f.store.getState().currentAssembly.name).toBe('Confirmed newer pose')
    expect(f.store.getState().currentAssembly.instances[0].transform.translation).toEqual([10, 0, 0])
  })
})
