import { describe, expect, it, vi } from 'vitest'
import { initVisibilityController } from './visibility_controller.js'

const geometry = [
  { helix_id: 'h1', bp_index: 0, direction: 'FORWARD', strand_id: 's1', domain_index: 0 },
  { helix_id: 'h1', bp_index: 1, direction: 'FORWARD', strand_id: 's1', domain_index: 0 },
  { helix_id: 'h1', bp_index: 1, direction: 'FORWARD', copy_k: 1, strand_id: 's1', domain_index: 0 },
  { helix_id: 'h2', bp_index: 0, direction: 'REVERSE', strand_id: 's2', domain_index: 0 },
  { helix_id: '__ext_e1', bp_index: 0, direction: 'FORWARD', extension_id: 'e1' },
]

function setup() {
  const state = { currentGeometry: geometry, currentDesign: {
    cluster_transforms: [{ id: 'c1', helix_ids: ['h1'] }], strands: [],
    extensions: [{ id: 'e1', strand_id: 's1' }],
  } }
  const designRenderer = { setHiddenNucs: vi.fn(), setHiddenCrossovers: vi.fn() }
  const unfoldView = { setHiddenNucs: vi.fn(() => new Set()) }
  const api = initVisibilityController({ store: { getState: () => state }, designRenderer, unfoldView })
  return { api, designRenderer }
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
})
