import { describe, expect, it, vi } from 'vitest'
import {
  buildVisibilityGeometryIndex, collectVisibilityBaseKeys, initVisibilityController,
} from './visibility_controller.js'

const geometry = [
  { helix_id: 'h1', bp_index: 0, direction: 'FORWARD', strand_id: 's1', domain_index: 0 },
  { helix_id: 'h1', bp_index: 1, direction: 'FORWARD', strand_id: 's1', domain_index: 0 },
  { helix_id: 'h1', bp_index: 1, direction: 'FORWARD', copy_k: 1, strand_id: 's1', domain_index: 0 },
  { helix_id: 'h2', bp_index: 0, direction: 'REVERSE', strand_id: 's2', domain_index: 0 },
  { helix_id: '__ext_e1', bp_index: 0, direction: 'FORWARD', extension_id: 'e1' },
]

function setup(visibilityState, onPersist) {
  const state = { currentGeometry: geometry, currentDesign: {
    cluster_transforms: [{ id: 'c1', helix_ids: ['h1'] }], strands: [],
    extensions: [{ id: 'e1', strand_id: 's1' }],
    visibility_state: visibilityState,
  } }
  const designRenderer = { setHiddenNucs: vi.fn(), setHiddenCrossovers: vi.fn() }
  const unfoldView = { setHiddenNucs: vi.fn(() => new Set()) }
  let subscriber
  const store = {
    getState: () => state,
    subscribe: vi.fn(fn => { subscriber = fn; return vi.fn() }),
  }
  const api = initVisibilityController({ store, designRenderer, unfoldView, onPersist })
  const replaceDesign = currentDesign => {
    state.currentDesign = currentDesign
    subscriber?.(state)
  }
  return { api, designRenderer, replaceDesign, state }
}

describe('visibility controller', () => {
  it('matches synthetic extension helices through the prepared selector index', () => {
    expect(collectVisibilityBaseKeys(geometry, { extensionIds: new Set(['e1']) }))
      .toEqual(new Set(['__ext_e1:0:FORWARD']))
  })

  it('indexes strand base keys including loop copies', () => {
    expect(buildVisibilityGeometryIndex(geometry).baseKeysByStrand.get('s1')).toEqual([
      'h1:0:FORWARD', 'h1:1:FORWARD', 'h1:1:FORWARD:1',
    ])
  })
  it('expands a strand to individual base keys', () => {
    const { api, designRenderer } = setup()
    api.hide({ strandIds: ['s1'] })
    expect(designRenderer.setHiddenNucs.mock.calls.at(-1)[0]).toEqual(new Set([
      'h1:0:FORWARD', 'h1:1:FORWARD', 'h1:1:FORWARD:1', '__ext_e1:0:FORWARD',
    ]))
    expect(api.isStrandShown('s1')).toBe(false)
    expect(api.isStrandShown('s2')).toBe(true)
  })

  it('folds cluster visibility into the same base-level set and clears all', () => {
    const { api, designRenderer } = setup()
    api.setHiddenClusters(new Set(['c1']))
    expect(api.isStrandShown('s1')).toBe(false)
    api.unhideAll()
    expect(designRenderer.setHiddenNucs.mock.calls.at(-1)[0]).toEqual(new Set())
    expect(api.isStrandShown('s1')).toBe(true)
  })

  it('keeps a partly hidden strand shown', () => {
    const { api } = setup()
    api.hide({ baseKeys: ['h1:0:FORWARD'] })
    expect(api.isStrandShown('s1')).toBe(true)
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(false)
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(true)
  })

  it('exposes effective attachment visibility including hidden clusters and shown exceptions', () => {
    const { api } = setup({
      hidden_base_keys: [], hidden_cluster_ids: ['c1'], shown_base_keys: ['h1:0:FORWARD'],
    })
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(false)
    api.show({ baseKeys: ['h1:1:FORWARD'] })
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(true)
    api.undo()
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(false)
  })

  it('undoes and redoes visibility-only edits without the design log', () => {
    const { api } = setup()
    api.hide({ strandIds: ['s1'] })
    expect(api.isStrandShown('s1')).toBe(false)
    expect(api.undo()).toBe(true)
    expect(api.isStrandShown('s1')).toBe(true)
    expect(api.redo()).toBe(true)
    expect(api.isStrandShown('s1')).toBe(false)
  })

  it('hydrates persisted state and persists hide, undo, and redo in order', async () => {
    const persist = vi.fn(async () => {})
    const { api, designRenderer } = setup({
      hidden_base_keys: ['h1:0:FORWARD'],
      shown_base_keys: [],
      hidden_cluster_ids: [],
    }, persist)
    expect(designRenderer.setHiddenNucs.mock.calls.at(-1)[0]).toEqual(new Set(['h1:0:FORWARD']))

    api.hide({ baseKeys: ['h1:1:FORWARD'] })
    api.undo()
    api.redo()
    await api.flushPersistence()
    expect(persist.mock.calls.map(([state]) => state.hidden_base_keys)).toEqual([
      ['h1:0:FORWARD', 'h1:1:FORWARD'],
      ['h1:0:FORWARD'],
      ['h1:0:FORWARD', 'h1:1:FORWARD'],
    ])
  })

  it('loads visibility when a new design is installed in the store', () => {
    const { api, replaceDesign, state } = setup()
    replaceDesign({ ...state.currentDesign, id: 'loaded', visibility_state: {
      hidden_base_keys: ['h2:0:REVERSE'], shown_base_keys: [], hidden_cluster_ids: [],
    } })
    expect(api.isStrandShown('s2')).toBe(false)
  })

  it('does not notify not-yet-created UI consumers during initial hydration', () => {
    const onChange = vi.fn()
    const state = { currentGeometry: geometry, currentDesign: {
      cluster_transforms: [], strands: [], extensions: [],
      visibility_state: {
        hidden_base_keys: ['h1:0:FORWARD'], shown_base_keys: [], hidden_cluster_ids: [],
      },
    } }
    const store = { getState: () => state, subscribe: vi.fn(() => vi.fn()) }
    const designRenderer = { setHiddenNucs: vi.fn(), setHiddenCrossovers: vi.fn() }
    initVisibilityController({
      store, designRenderer, unfoldView: { setHiddenNucs: vi.fn(() => new Set()) }, onChange,
    })
    expect(designRenderer.setHiddenNucs).toHaveBeenCalledWith(new Set(['h1:0:FORWARD']))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('re-expands persisted hidden clusters when loaded geometry arrives', () => {
    const { designRenderer, state, replaceDesign } = setup({
      hidden_base_keys: [], shown_base_keys: [], hidden_cluster_ids: ['c1'],
    })
    state.currentGeometry = []
    replaceDesign({ ...state.currentDesign })
    state.currentGeometry = geometry
    replaceDesign(state.currentDesign)
    expect(designRenderer.setHiddenNucs.mock.calls.at(-1)[0]).toEqual(new Set([
      'h1:0:FORWARD', 'h1:1:FORWARD', 'h1:1:FORWARD:1',
    ]))
  })
})

describe('organization persistent visibility', () => {
  function organized(options = {}) {
    const state = { currentGeometry: geometry, currentDesign: {
      id: 'design', cluster_transforms: [{ id: 'same', helix_ids: ['h2'] }],
      strands: [{ id: 's1', domains: [{ helix_id: 'h1' }] },
        { id: 's2', domains: [{ helix_id: 'h2' }] }], extensions: [],
      group_organization: { version: 1, groups: [
        { id: 'same', helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 0 }] },
        { id: 'whole', helix_ids: ['h1'], domain_ids: [] },
        { id: 'empty', helix_ids: [], domain_ids: [] },
      ] },
    } }
    let listener
    const onChange = vi.fn(), onPersist = vi.fn(async () => {})
    const renderer = { setHiddenNucs: vi.fn(), setHiddenCrossovers: vi.fn() }
    const api = initVisibilityController({
      store: { getState: () => state, subscribe: fn => { listener = fn; return vi.fn() } },
      designRenderer: renderer, onChange, onPersist, ...options,
    })
    return { api, state, onChange, onPersist, renderer, change: patch => {
      Object.assign(state, patch); listener(state)
    } }
  }

  it('persists group identity without aliasing same-text placement IDs', async () => {
    const { api, onPersist, onChange } = organized()
    api.hide({ partGroupIds: ['same'] })
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(false)
    expect(api.isBaseShown('h1:1:FORWARD:1')).toBe(false)
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(true)
    expect(api.isPartGroupShown('same')).toBe(false)
    expect(api.isPartGroupShown('whole')).toBe(false)
    expect(api.isPartGroupShown('empty')).toBe(true)
    expect(onChange.mock.calls.at(-1)[2]).toEqual(new Set(['same', 'whole']))
    await api.flushPersistence()
    expect(onPersist.mock.calls.at(-1)[0]).toEqual({
      hidden_base_keys: [], hidden_part_group_ids: ['same'],
      shown_base_keys: [], hidden_cluster_ids: [],
    })
    api.setHiddenClusters(['same'])
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(false)
  })

  it('derived group visibility follows union hiding and explicit show exceptions through undo/redo', () => {
    const { api, onChange } = organized()
    api.hide({ partGroupIds: ['same', 'empty'] })
    api.show({ baseKeys: ['h1:0:FORWARD'] })
    expect(api.isPartGroupShown('same')).toBe(true)
    expect(onChange.mock.calls.at(-1)[2]).toEqual(new Set(['empty']))
    api.undo()
    expect(api.isPartGroupShown('same')).toBe(false)
    api.redo()
    expect(api.isPartGroupShown('same')).toBe(true)
    api.show({ partGroupIds: ['same'] })
    expect(api.isBaseShown('h1:1:FORWARD:1')).toBe(true)
  })

  it('follows edited membership, becomes dormant on dissolution and resumes after undo/reload', async () => {
    const { api, state, change, onPersist } = organized()
    api.hide({ partGroupIds: ['same'] })
    await api.flushPersistence()
    const saved = onPersist.mock.calls.at(-1)[0]
    change({ currentDesign: { ...state.currentDesign, visibility_state: saved,
      group_organization: { version: 1, groups: [
        { id: 'same', helix_ids: ['h2'], domain_ids: [] },
      ] } } })
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(false)
    expect(api.isPartGroupShown('same')).toBe(false)
    const beforeDissolve = JSON.parse(JSON.stringify(state.currentDesign))
    change({ currentDesign: { ...state.currentDesign,
      group_organization: { version: 1, groups: [] } } })
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(true)
    expect(api.isPartGroupShown('same')).toBe(true)
    change({ currentDesign: beforeDissolve })
    expect(api.isPartGroupShown('same')).toBe(false)
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(false)
  })

  it('rebuilds cached group base membership only when design or geometry changes', () => {
    const { api, state, change } = organized()
    api.hide({ partGroupIds: ['same'] })
    expect(api.isPartGroupShown('same')).toBe(false)
    const old = state.currentGeometry
    const extended = [...old, { helix_id: 'h1', strand_id: 's1', domain_index: 0,
      bp_index: 2, direction: 'FORWARD' }]
    change({ currentGeometry: extended })
    expect(api.isPartGroupShown('same')).toBe(false)
    expect(api.isBaseShown('h1:2:FORWARD')).toBe(false)
  })

  it('retains legacy base hiding when membership changes without inferring group intent', () => {
    const { api, state, change } = organized()
    const saved = { hidden_base_keys: ['h1:0:FORWARD', 'h1:1:FORWARD', 'h1:1:FORWARD:1'],
      shown_base_keys: [], hidden_cluster_ids: [] }
    change({ currentDesign: { ...state.currentDesign, visibility_state: saved } })
    expect(api.isPartGroupShown('same')).toBe(false)
    change({ currentDesign: { ...state.currentDesign,
      group_organization: { version: 1, groups: [{ id: 'same', helix_ids: ['h2'] }] } } })
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(false)
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(true)
    expect(api.isPartGroupShown('same')).toBe(true)
  })

  it('shows one group without deleting another hide rule; explicit shown bases keep precedence', async () => {
    const { api, onPersist, state, change } = organized()
    api.hide({ partGroupIds: ['same', 'whole'] })
    api.show({ partGroupIds: ['same'] })
    await api.flushPersistence()
    const saved = onPersist.mock.calls.at(-1)[0]
    expect(saved.hidden_part_group_ids).toEqual(['whole'])
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
    change({ currentDesign: { ...state.currentDesign, visibility_state: saved },
      currentGeometry: [...geometry, { ...geometry[0], bp_index: 2 }] })
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
    expect(api.isBaseShown('h1:2:FORWARD')).toBe(false)
    api.unhideAll()
    await api.flushPersistence()
    expect(onPersist.mock.calls.at(-1)[0].hidden_part_group_ids).toEqual([])
    expect(api.isBaseShown('h1:2:FORWARD')).toBe(true)
  })

  it('hides new terminal extensions and loop copies through the current domain membership', async () => {
    const { api, state, change, onPersist } = organized()
    api.hide({ partGroupIds: ['same'] })
    await api.flushPersistence()
    change({ currentDesign: { ...state.currentDesign,
      visibility_state: onPersist.mock.calls.at(-1)[0],
      extensions: [{ id: 'e1', strand_id: 's1', end: 'three_prime' }] },
      currentGeometry: [...geometry] })
    expect(api.isBaseShown('__ext_e1:0:FORWARD')).toBe(false)
    expect(api.isBaseShown('h1:1:FORWARD:1')).toBe(false)
    expect(api.isStrandShown('s1')).toBe(false)
    expect(api.isStrandShown('s2')).toBe(true)
  })

  it('uses the cached effective mask for repeated strand queries and unrelated store notifications', () => {
    const { api, state, change } = organized()
    api.setHiddenClusters(['same'])
    api.hide({ partGroupIds: ['whole'] })
    let scans = 0
    const indexedGeometry = [...geometry]
    indexedGeometry[Symbol.iterator] = function* () { scans++; yield* geometry }
    change({ currentGeometry: indexedGeometry })
    const prepared = scans
    for (let i = 0; i < 20; i++) {
      expect(api.isStrandShown('s1')).toBe(false)
      expect(api.isStrandShown('s2')).toBe(false)
      change({ currentDesign: state.currentDesign })
    }
    expect(scans).toBe(prepared)
  })

  it.each(['null', 'throw'])('rolls back failed %s persistence including visibility undo', async failure => {
    const persist = vi.fn(async () => {
      if (failure === 'throw') throw new Error('publication refused')
      return null
    })
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const { api, onChange, renderer } = organized({ onPersist: persist, getRevision: () => 4 })
      api.hide({ partGroupIds: ['same'] })
      expect(api.isPartGroupShown('same')).toBe(false)
      await api.flushPersistence()
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
      expect(api.isPartGroupShown('same')).toBe(true)
      expect(renderer.setHiddenNucs.mock.calls.at(-1)[0]).toEqual(new Set())
      expect(onChange.mock.calls.at(-1)[2]).toEqual(new Set())
      expect(api.undo()).toBe(false)
      expect(persist).toHaveBeenCalledTimes(1)
      api.destroy()
    } finally { log.mockRestore() }
  })

  it('does not overwrite a newer local visibility edit when an earlier save fails', async () => {
    let finish
    const first = new Promise(resolve => { finish = resolve })
    const persist = vi.fn().mockReturnValueOnce(first).mockResolvedValue(undefined)
    const { api } = organized({ onPersist: persist, getRevision: () => 4 })
    api.hide({ partGroupIds: ['same'] })
    await Promise.resolve()
    api.show({ baseKeys: ['h1:0:FORWARD'] })
    finish(null)
    await api.flushPersistence()
    expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(false)
    expect(persist).toHaveBeenCalledTimes(2)
    api.destroy()
  })

  it.each(['null', 'throw'])('restores acknowledged visibility when both queued saves fail (%s)', async failure => {
    let finish
    const first = new Promise((resolve, reject) => {
      finish = () => failure === 'throw' ? reject(new Error('first refused')) : resolve(null)
    })
    const persist = vi.fn().mockReturnValueOnce(first).mockImplementationOnce(async () => {
      if (failure === 'throw') throw new Error('second refused')
      return null
    })
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { api, state, onChange } = organized({ onPersist: persist, getRevision: () => 4 })
    try {
      const original = JSON.stringify(state.currentDesign)
      api.hide({ partGroupIds: ['same'] })
      await Promise.resolve()
      api.hide({ baseKeys: ['h2:0:REVERSE'] })
      finish()
      await api.flushPersistence()
      expect(persist).toHaveBeenCalledTimes(2)
      expect(JSON.stringify(state.currentDesign)).toBe(original)
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
      expect(api.isBaseShown('h2:0:REVERSE')).toBe(true)
      expect(api.isPartGroupShown('same')).toBe(true)
      expect(onChange.mock.calls.at(-1)[2]).toEqual(new Set())
      expect(api.undo()).toBe(false)
      expect(api.redo()).toBe(false)
    } finally { api.destroy(); log.mockRestore() }
  })

  it('keeps intermediate gesture undo when a later complete save succeeds after the first refusal', async () => {
    let finish, revision = 4
    const first = new Promise(resolve => { finish = resolve })
    const persist = vi.fn().mockReturnValueOnce(first)
    const { api, state, change } = organized({ onPersist: persist, getRevision: () => revision })
    persist.mockImplementation(async visibility => {
      revision++
      const currentDesign = { ...state.currentDesign, visibility_state: visibility }
      change({ currentDesign })
      return { design: currentDesign, revision }
    })
    try {
      api.hide({ partGroupIds: ['same'] })
      await Promise.resolve()
      api.show({ baseKeys: ['h1:0:FORWARD'] })
      finish(null)
      await api.flushPersistence()
      expect(revision).toBe(5)
      expect(state.currentDesign.visibility_state.hidden_part_group_ids).toEqual(['same'])
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
      expect(api.isBaseShown('h1:1:FORWARD')).toBe(false)
      expect(api.undo()).toBe(true)
      await api.flushPersistence()
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(false)
      expect(state.currentDesign.visibility_state.shown_base_keys).toEqual([])
      expect(api.undo()).toBe(true)
      await api.flushPersistence()
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(true)
      expect(state.currentDesign.visibility_state.hidden_part_group_ids).toEqual([])
      expect(api.undo()).toBe(false)
      expect(api.redo()).toBe(true)
      await api.flushPersistence()
      expect(api.isBaseShown('h1:0:FORWARD')).toBe(false)
    } finally { api.destroy() }
  })

  it('rolls back only the latest queued edit after the earlier save installs its revision', async () => {
    let finish, revision = 4
    const first = new Promise(resolve => { finish = resolve })
    const persist = vi.fn().mockResolvedValue(undefined)
    const { api, state, change } = organized({ onPersist: persist, getRevision: () => revision })
    persist.mockImplementationOnce(async visibility => {
      await first
      revision++
      const currentDesign = { ...state.currentDesign, visibility_state: visibility }
      change({ currentDesign })
      return { design: currentDesign, revision }
    }).mockResolvedValueOnce(null)
    api.hide({ baseKeys: ['h1:0:FORWARD'] })
    await Promise.resolve()
    api.hide({ baseKeys: ['h1:1:FORWARD'] })
    finish()
    await api.flushPersistence()
    expect(revision).toBe(5)
    expect(api.getHiddenBaseKeys()).toEqual(new Set(['h1:0:FORWARD']))
    expect(api.isBaseShown('h1:1:FORWARD')).toBe(true)
    expect(api.undo()).toBe(true)
    expect(api.undo()).toBe(false)
    await api.flushPersistence()
    expect(persist).toHaveBeenCalledTimes(3)
    api.destroy()
  })

  it.each(['revision', 'design', 'reset', 'destroy'])('ignores a failed save after %s changes its origin', async changeKind => {
    let finish, revision = 4
    const pending = new Promise(resolve => { finish = resolve })
    const events = new EventTarget()
    const { api, state, change, renderer } = organized({
      onPersist: () => pending, getRevision: () => revision, eventTarget: events,
    })
    api.hide({ partGroupIds: ['same'] })
    await Promise.resolve()
    if (changeKind === 'revision') revision++
    if (changeKind === 'design') change({ currentDesign: { ...state.currentDesign } })
    if (changeKind === 'reset') events.dispatchEvent(new Event('nadoc:document-reset'))
    if (changeKind === 'destroy') api.destroy()
    await Promise.resolve()
    const calls = renderer.setHiddenNucs.mock.calls.length
    finish(null)
    await api.flushPersistence()
    expect(renderer.setHiddenNucs.mock.calls.length).toBe(calls)
    api.destroy()
  })

  it('does not send an old queued visibility request after a same-ID document reset', async () => {
    let finish
    const pending = new Promise(resolve => { finish = resolve })
    const persist = vi.fn().mockReturnValueOnce(pending).mockResolvedValue(undefined)
    const events = new EventTarget()
    const { api } = organized({ onPersist: persist, eventTarget: events })
    api.hide({ partGroupIds: ['same'] })
    await Promise.resolve()
    api.show({ partGroupIds: ['same'] })
    events.dispatchEvent(new Event('nadoc:document-reset'))
    finish(null)
    await api.flushPersistence()
    expect(persist).toHaveBeenCalledTimes(1)
    api.destroy()
  })

  it('hydrates a same-ID replacement while an old-generation visibility save is still held', async () => {
    let finish
    const pending = new Promise(resolve => { finish = resolve })
    const events = new EventTarget()
    const persist = vi.fn().mockReturnValueOnce(pending).mockResolvedValue(undefined)
    const { api, state, change } = organized({ onPersist: persist, eventTarget: events })
    api.hide({ partGroupIds: ['same'] })
    await Promise.resolve()
    events.dispatchEvent(new Event('nadoc:document-reset'))
    change({ currentDesign: { ...state.currentDesign, visibility_state: {
      hidden_base_keys: ['h2:0:REVERSE'], shown_base_keys: [], hidden_cluster_ids: [],
    } } })
    expect(api.getHiddenBaseKeys()).toEqual(new Set(['h2:0:REVERSE']))
    expect(api.isPartGroupShown('same')).toBe(true)
    expect(api.undo()).toBe(false)
    persist.mockImplementationOnce(async visibility => {
      const currentDesign = { ...state.currentDesign, visibility_state: visibility }
      change({ currentDesign })
      return { design: currentDesign }
    })
    // Queue a new-generation save before the obsolete one drains. Its success
    // must preserve its own visibility undo even while adopting a design reply.
    api.show({ baseKeys: ['h2:0:REVERSE'] })
    finish(null)
    await api.flushPersistence()
    expect(api.isBaseShown('h2:0:REVERSE')).toBe(true)
    expect(api.undo()).toBe(true)
    expect(api.getHiddenBaseKeys()).toEqual(new Set(['h2:0:REVERSE']))
    await api.flushPersistence()
    api.destroy()
  })
})
