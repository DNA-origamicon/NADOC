/**
 * Tests for anchor_glow.js — purple highlight over oxDNA anchor (fixed) elements.
 *   resolveAnchorEntries — pure: overhang / domain / cluster / strand / base descriptors → entries.
 *   initAnchorGlow       — factory: setAnchors drives setAnchorGlow/clearAnchorGlow,
 *                          re-resolves on geometry change.
 */
import { describe, it, expect, vi } from 'vitest'
import {
  resolveAnchorEntries, initAnchorGlow, buildAnchorAtomIndex, anchorAtomGlowScale,
} from './anchor_glow.js'

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

// ── Per-atom halo ────────────────────────────────────────────────────────────
// A NAMD anchor can hold only SOME atoms of its bases. With an atomistic rep on, the
// halo must sit on exactly those atoms, so what you see matches the marker PDB.

// One strand, two domains, one on each helix; s2 is an overhang. REVERSE stores
// start_bp > end_bp, which is the trap the bp walk has to survive.
const ATOM_DESIGN = {
  strands: [
    { id: 's1', domains: [
      { helix_id: 'h1', start_bp: 0, end_bp: 2, direction: 'FORWARD', overhang_id: null },
      { helix_id: 'h2', start_bp: 5, end_bp: 4, direction: 'REVERSE', overhang_id: null },
    ] },
    { id: 's2', domains: [
      { helix_id: 'h2', start_bp: 0, end_bp: 1, direction: 'FORWARD', overhang_id: 'ov9' },
    ] },
  ],
  cluster_transforms: [{ id: 'c1', helix_ids: ['h1'] }],
}

describe('buildAnchorAtomIndex', () => {
  it('ignores anchors that state no opinion about their atoms', () => {
    // An oxDNA anchor or an occupancy-scope pick has no `atoms` key and must keep the
    // per-nucleotide halo — this is what stops the feature leaking into other cards.
    expect(buildAnchorAtomIndex([{ kind: 'strand', id: 's1' }], ATOM_DESIGN).size).toBe(0)
  })

  it('a base anchor keys straight off the descriptor, no design walk', () => {
    const idx = buildAnchorAtomIndex(
      [{ kind: 'base', helixId: 'h7', bp: 3, direction: 'FORWARD', atoms: ['P'] }], null)
    expect([...idx.keys()]).toEqual(['h7:3:FORWARD'])
    expect(idx.get('h7:3:FORWARD')).toEqual(new Set(['P']))
  })

  it('normalises direction case, so a snake_case caller keys the same as the picker', () => {
    const idx = buildAnchorAtomIndex(
      [{ kind: 'base', helix_id: 'h7', bp_index: 3, direction: 'forward', atoms: ['P'] }], null)
    expect(idx.has('h7:3:FORWARD')).toBe(true)
  })

  it('a strand anchor covers every bp of every domain', () => {
    const idx = buildAnchorAtomIndex([{ kind: 'strand', id: 's1', atoms: ["C1'"] }], ATOM_DESIGN)
    expect([...idx.keys()].sort()).toEqual(
      ['h1:0:FORWARD', 'h1:1:FORWARD', 'h1:2:FORWARD', 'h2:4:REVERSE', 'h2:5:REVERSE'])
  })

  it('walks a REVERSE domain from low to high bp, not backwards into nothing', () => {
    const idx = buildAnchorAtomIndex(
      [{ kind: 'domain', strandId: 's1', domainIndex: 1, atoms: ['P'] }], ATOM_DESIGN)
    expect([...idx.keys()].sort()).toEqual(['h2:4:REVERSE', 'h2:5:REVERSE'])
  })

  it('an overhang anchor covers only domains carrying that overhang_id', () => {
    const idx = buildAnchorAtomIndex([{ kind: 'overhang', id: 'ov9', atoms: ['P'] }], ATOM_DESIGN)
    expect([...idx.keys()].sort()).toEqual(['h2:0:FORWARD', 'h2:1:FORWARD'])
  })

  it('a cluster anchor covers the helices that cluster owns', () => {
    const idx = buildAnchorAtomIndex([{ kind: 'cluster', id: 'c1', atoms: ['P'] }], ATOM_DESIGN)
    expect([...idx.keys()].sort()).toEqual(['h1:0:FORWARD', 'h1:1:FORWARD', 'h1:2:FORWARD'])
  })

  it('an unknown cluster covers nothing rather than throwing', () => {
    expect(buildAnchorAtomIndex([{ kind: 'cluster', id: 'nope', atoms: ['P'] }], ATOM_DESIGN).size)
      .toBe(0)
  })

  it('skips extra_base and extension scopes, as resolveAnchorEntries does', () => {
    const idx = buildAnchorAtomIndex([
      { kind: 'extra_base', crossoverId: 'xo1', atoms: ['P'] },
      { kind: 'extension', extensionId: 'e1', atoms: ['P'] },
    ], ATOM_DESIGN)
    expect(idx.size).toBe(0)
  })

  it('overlapping anchors UNION their atom sets', () => {
    // Overlap is normal — a base anchor inside an anchored strand. Union keeps the halo
    // from claiming to hold less than the marker PDB does.
    const idx = buildAnchorAtomIndex([
      { kind: 'strand', id: 's1', atoms: ['P'] },
      { kind: 'base', helixId: 'h1', bp: 0, direction: 'FORWARD', atoms: ["C1'"] },
    ], ATOM_DESIGN)
    expect(idx.get('h1:0:FORWARD')).toEqual(new Set(['P', "C1'"]))
    expect(idx.get('h1:1:FORWARD')).toEqual(new Set(['P']))
  })

  it('all-heavy-atoms absorbs the union, whichever order it arrives in', () => {
    const a = { kind: 'strand', id: 's1', atoms: ['P'] }
    const b = { kind: 'strand', id: 's1', atoms: null }
    expect(buildAnchorAtomIndex([a, b], ATOM_DESIGN).get('h1:0:FORWARD')).toBeNull()
    expect(buildAnchorAtomIndex([b, a], ATOM_DESIGN).get('h1:0:FORWARD')).toBeNull()
  })
})

describe('anchorAtomGlowScale', () => {
  it('shrinks the halo for atomistic reps so each ATOM reads as its own sphere', () => {
    // The CG value over ~20 heavy atoms of one base is a single blob.
    expect(anchorAtomGlowScale('ballstick')).toBeLessThan(anchorAtomGlowScale('vdw'))
    expect(anchorAtomGlowScale('vdw')).toBeLessThan(anchorAtomGlowScale('off'))
  })

  it('falls back to the coarse-grained bead scale for anything not atomistic', () => {
    expect(anchorAtomGlowScale('off')).toBe(3.6)
    expect(anchorAtomGlowScale(undefined)).toBe(3.6)
  })
})

describe('initAnchorGlow with an atomistic renderer', () => {
  function makeAtomDeps(atomEntries) {
    const subs = []
    const designRenderer = {
      getBackboneEntries: vi.fn(() => ENTRIES),
      setAnchorGlow: vi.fn(),
      clearAnchorGlow: vi.fn(),
    }
    const store = {
      getState: () => ({ currentDesign: { ...DESIGN, ...ATOM_DESIGN }, currentGeometry: [] }),
      subscribe: (fn) => subs.push(fn),
    }
    const atomCbs = []
    const atomisticRenderer = {
      getMode: () => 'ballstick',
      anchorAtomEntries: vi.fn(() => atomEntries),
      onAtomsChanged: (cb) => atomCbs.push(cb),
      _fireAtoms: () => atomCbs.forEach(cb => cb()),
    }
    return { designRenderer, store, atomisticRenderer }
  }

  const ATOM_ENTRIES = [{ scale: 1.4, pos: { x: 1, y: 0, z: 0 } }]

  it('draws the per-atom entries when the renderer can serve them', () => {
    const d = makeAtomDeps(ATOM_ENTRIES)
    initAnchorGlow(d).setAnchors([{ kind: 'strand', id: 's1', atoms: ['P'] }])
    expect(d.designRenderer.setAnchorGlow).toHaveBeenCalledTimes(1)
    expect(d.designRenderer.setAnchorGlow.mock.calls[0][0]).toEqual(ATOM_ENTRIES)
    // and it asked with the ballstick scale, not the coarse bead one
    expect(d.atomisticRenderer.anchorAtomEntries.mock.calls[0][1].scale)
      .toBe(anchorAtomGlowScale('ballstick'))
  })

  it('falls back to the bead halo when the renderer returns null', () => {
    // null = rep off / atoms not loaded / a payload with no atom names.
    const d = makeAtomDeps(null)
    initAnchorGlow(d).setAnchors([{ kind: 'strand', id: 's1', atoms: ['P'] }])
    const drawn = d.designRenderer.setAnchorGlow.mock.calls[0][0]
    expect(drawn.length).toBeGreaterThan(0)
    expect(drawn.every(e => e.nuc)).toBe(true)          // backbone entries, not atoms
  })

  it('keeps opinion-less anchors on the bead halo alongside the per-atom ones', () => {
    const d = makeAtomDeps(ATOM_ENTRIES)
    initAnchorGlow(d).setAnchors([
      { kind: 'strand', id: 's1', atoms: ['P'] },
      { kind: 'overhang', id: 'ov9' },                  // an occupancy-style scope
    ])
    const drawn = d.designRenderer.setAnchorGlow.mock.calls[0][0]
    expect(drawn).toHaveLength(ATOM_ENTRIES.length + 1)
    expect(drawn.filter(e => e.nuc?.overhang_id === 'ov9')).toHaveLength(1)
  })

  it('never consults the atomistic renderer when no anchor names its atoms', () => {
    const d = makeAtomDeps(ATOM_ENTRIES)
    initAnchorGlow(d).setAnchors([{ kind: 'overhang', id: 'ov9' }])
    expect(d.atomisticRenderer.anchorAtomEntries).not.toHaveBeenCalled()
  })

  it('repaints when the atom set or mode changes, not on every frame', () => {
    // The signature guard lives in the renderer; the glow just has to be subscribed.
    const d = makeAtomDeps(ATOM_ENTRIES)
    initAnchorGlow(d).setAnchors([{ kind: 'strand', id: 's1', atoms: ['P'] }])
    d.designRenderer.setAnchorGlow.mockClear()
    d.atomisticRenderer._fireAtoms()
    expect(d.designRenderer.setAnchorGlow).toHaveBeenCalledTimes(1)
  })

  it('works with no atomistic renderer at all (the other six cards)', () => {
    const d = makeAtomDeps(ATOM_ENTRIES)
    const glow = initAnchorGlow({ designRenderer: d.designRenderer, store: d.store })
    glow.setAnchors([{ kind: 'strand', id: 's1', atoms: ['P'] }])
    expect(d.designRenderer.setAnchorGlow).toHaveBeenCalledTimes(1)
  })
})
