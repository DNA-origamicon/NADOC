import { describe, expect, it, vi } from 'vitest'
import { initVisibilityController } from './visibility_controller.js'

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
