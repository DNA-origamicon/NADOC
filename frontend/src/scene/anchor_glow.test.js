/**
 * Tests for anchor_glow.js — purple highlight over oxDNA anchor (fixed) elements.
 *   resolveAnchorEntries — pure: overhang / domain / cluster descriptors → entries.
 *   initAnchorGlow       — factory: setAnchors drives setAnchorGlow/clearAnchorGlow,
 *                          re-resolves on geometry change.
 */
import { describe, it, expect, vi } from 'vitest'
import { resolveAnchorEntries, initAnchorGlow } from './anchor_glow.js'

// Backbone entries carry .pos + .nuc (strand_id, domain_index, overhang_id, helix_id).
function entry(nuc) { return { pos: { x: 0, y: 0, z: 0 }, nuc } }
const ENTRIES = [
  entry({ strand_id: 's1', domain_index: 0, helix_id: 'h1', overhang_id: null }),
  entry({ strand_id: 's1', domain_index: 1, helix_id: 'h1', overhang_id: null }),
  entry({ strand_id: 's2', domain_index: 0, helix_id: 'h2', overhang_id: 'ov9' }),
  entry({ strand_id: 's3', domain_index: 0, helix_id: 'h3', overhang_id: null }),
]
const DESIGN = { cluster_transforms: [{ id: 'c1', helix_ids: ['h1', 'h2'] }] }

describe('resolveAnchorEntries', () => {
  it('overhang anchor → entries carrying that overhang_id', () => {
    const out = resolveAnchorEntries([{ kind: 'overhang', id: 'ov9' }], ENTRIES, DESIGN)
    expect(out).toHaveLength(1)
    expect(out[0].nuc.overhang_id).toBe('ov9')
  })

  it('domain anchor → entries of that strand+domain only', () => {
    const out = resolveAnchorEntries([{ kind: 'domain', strandId: 's1', domainIndex: 1 }], ENTRIES, DESIGN)
    expect(out).toHaveLength(1)
    expect(out[0].nuc.domain_index).toBe(1)
  })

  it('cluster anchor → all entries on the cluster helices', () => {
    const out = resolveAnchorEntries([{ kind: 'cluster', id: 'c1' }], ENTRIES, DESIGN)
    // h1 (2 entries) + h2 (1 entry) = 3
    expect(out).toHaveLength(3)
    expect(out.every(e => ['h1', 'h2'].includes(e.nuc.helix_id))).toBe(true)
  })

  it('de-duplicates entries matched by multiple anchors', () => {
    const out = resolveAnchorEntries(
      [{ kind: 'cluster', id: 'c1' }, { kind: 'domain', strandId: 's1', domainIndex: 0 }],
      ENTRIES, DESIGN)
    expect(out).toHaveLength(3)   // the s1:0 entry isn't double-counted
  })

  it('returns [] for empty anchors or entries', () => {
    expect(resolveAnchorEntries([], ENTRIES, DESIGN)).toEqual([])
    expect(resolveAnchorEntries([{ kind: 'overhang', id: 'ov9' }], [], DESIGN)).toEqual([])
  })

  it('unknown cluster id resolves to nothing (no throw)', () => {
    expect(resolveAnchorEntries([{ kind: 'cluster', id: 'nope' }], ENTRIES, DESIGN)).toEqual([])
  })
})

describe('initAnchorGlow', () => {
  function makeDeps(geometry = []) {
    let _geo = geometry
    const subs = []
    const designRenderer = {
      getBackboneEntries: vi.fn(() => ENTRIES),
      setAnchorGlow: vi.fn(),
      clearAnchorGlow: vi.fn(),
    }
    const store = {
      getState: () => ({ currentDesign: DESIGN, currentGeometry: _geo }),
      subscribe: (fn) => subs.push(fn),
      _fireGeometry: (g) => { _geo = g; subs.forEach(fn => fn()) },
    }
    return { designRenderer, store }
  }

  it('setAnchors resolves + calls setAnchorGlow; empty clears', () => {
    const { designRenderer, store } = makeDeps()
    const glow = initAnchorGlow({ designRenderer, store })
    glow.setAnchors([{ kind: 'cluster', id: 'c1' }])
    expect(designRenderer.setAnchorGlow).toHaveBeenCalledTimes(1)
    expect(designRenderer.setAnchorGlow.mock.calls[0][0]).toHaveLength(3)

    glow.setAnchors([])
    expect(designRenderer.clearAnchorGlow).toHaveBeenCalled()
  })

  it('clear() drops the glow', () => {
    const { designRenderer, store } = makeDeps()
    const glow = initAnchorGlow({ designRenderer, store })
    glow.setAnchors([{ kind: 'overhang', id: 'ov9' }])
    glow.clear()
    expect(designRenderer.clearAnchorGlow).toHaveBeenCalled()
  })

  it('re-resolves when the geometry changes (rebuild)', () => {
    const { designRenderer, store } = makeDeps([])
    const glow = initAnchorGlow({ designRenderer, store })
    glow.setAnchors([{ kind: 'overhang', id: 'ov9' }])
    designRenderer.setAnchorGlow.mockClear()
    store._fireGeometry([{ changed: true }])     // new geometry array → rebuild
    expect(designRenderer.setAnchorGlow).toHaveBeenCalledTimes(1)
  })
})
