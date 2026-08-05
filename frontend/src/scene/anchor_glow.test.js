/**
 * Tests for anchor_glow.js — purple highlight over oxDNA anchor (fixed) elements.
 *   resolveAnchorEntries — pure: overhang / domain / cluster / strand / base descriptors → entries.
 *   initAnchorGlow       — factory: setAnchors drives setAnchorGlow/clearAnchorGlow,
 *                          re-resolves on geometry change.
 */
import { describe, it, expect, vi } from 'vitest'
import { resolveAnchorEntries, initAnchorGlow } from './anchor_glow.js'

// Backbone entries carry .pos + .nuc (strand_id, domain_index, overhang_id, helix_id).
function entry(nuc) { return { pos: { x: 0, y: 0, z: 0 }, nuc } }
const ENTRIES = [
  entry({ strand_id: 's1', domain_index: 0, helix_id: 'h1', overhang_id: null, bp_index: 0, direction: 'forward' }),
  entry({ strand_id: 's1', domain_index: 1, helix_id: 'h1', overhang_id: null, bp_index: 1, direction: 'forward' }),
  entry({ strand_id: 's2', domain_index: 0, helix_id: 'h2', overhang_id: 'ov9', bp_index: 0, direction: 'reverse' }),
  entry({ strand_id: 's3', domain_index: 0, helix_id: 'h3', overhang_id: null, bp_index: 4, direction: 'forward' }),
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

  it('strand anchor → every entry of that strand', () => {
    const out = resolveAnchorEntries([{ kind: 'strand', id: 's1' }], ENTRIES, DESIGN)
    expect(out).toHaveLength(2)
    expect(out.every(e => e.nuc.strand_id === 's1')).toBe(true)
  })

  it('base anchor → only the entry at that helix/bp/direction', () => {
    const out = resolveAnchorEntries(
      [{ kind: 'base', helixId: 'h3', bp: 4, direction: 'forward' }], ENTRIES, DESIGN)
    expect(out).toHaveLength(1)
    expect(out[0].nuc.strand_id).toBe('s3')
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

// ── snake_case scopes (API / headless / saved manifests) ──────────────────────
// The shared scope format accepts both spellings and the BACKEND resolver honours both,
// so a run built from a script is correctly anchored. This resolver read only camelCase,
// so those jobs rendered their chips and highlighted nothing — which reads in the app as
// "the anchors were lost" even though NAMD was enforcing all of them.
describe('resolveAnchorEntries accepts snake_case scopes', () => {
  const entries = [
    { nuc: { helix_id: 'h0', bp_index: 7, direction: 'FORWARD', strand_id: 's1', domain_index: 0 } },
    { nuc: { helix_id: 'h0', bp_index: 8, direction: 'FORWARD', strand_id: 's1', domain_index: 1 } },
    { nuc: { helix_id: 'h1', bp_index: 7, direction: 'REVERSE', strand_id: 's2', domain_index: 0 } },
  ]

  it('resolves a base scope written as helix_id', () => {
    const snake = resolveAnchorEntries(
      [{ kind: 'base', helix_id: 'h0', bp: 7, direction: 'FORWARD' }], entries, null)
    const camel = resolveAnchorEntries(
      [{ kind: 'base', helixId: 'h0', bp: 7, direction: 'FORWARD' }], entries, null)
    expect(snake).toHaveLength(1)
    expect(snake).toEqual(camel)
  })

  it('accepts bp_index as an alias for bp', () => {
    expect(resolveAnchorEntries(
      [{ kind: 'base', helix_id: 'h1', bp_index: 7, direction: 'REVERSE' }], entries, null),
    ).toHaveLength(1)
  })

  it('resolves strand and domain scopes in either spelling', () => {
    expect(resolveAnchorEntries([{ kind: 'strand', strand_id: 's1' }], entries, null))
      .toHaveLength(2)
    expect(resolveAnchorEntries([{ kind: 'strand', id: 's1' }], entries, null))
      .toHaveLength(2)
    expect(resolveAnchorEntries(
      [{ kind: 'domain', strand_id: 's1', domain_index: 1 }], entries, null),
    ).toHaveLength(1)
  })

  it('still matches nothing for a genuinely absent helix', () => {
    expect(resolveAnchorEntries(
      [{ kind: 'base', helix_id: 'nope', bp: 7, direction: 'FORWARD' }], entries, null),
    ).toHaveLength(0)
  })
})
