import { describe, it, expect } from 'vitest'
import {
  isVisibleChain, backboneCandidates, xoverCandidates, flexCandidates, ssLinkCandidates,
  nearestCandidate, candidatesInRect,
} from './base_pick.js'

// ── Fakes ────────────────────────────────────────────────────────────────────
// Enough of a Three object to exercise the parent-chain walk and the InstancedMesh
// duck-typing. Positions never matter here — projection is injected.
const node = (visible = true, parent = null) => ({ visible, parent })
const instMesh = (name, count = 0, { visible = true, parent = null, userData = {} } = {}) =>
  ({ name, count, isInstancedMesh: true, visible, parent, userData })

const nuc = (o = {}) => ({
  helix_id: 'h1', bp_index: 0, direction: 'FORWARD',
  strand_id: 's1', strand_type: 'staple', ...o,
})

const ALL_TYPES = { scaffold: true, staples: true }

/** Project by a lookup table keyed on candidate key; missing = off-screen. */
const projectBy = (table) => (cand) => table[cand.key] ?? null

describe('isVisibleChain', () => {
  it('true when the leaf and every ancestor are visible', () => {
    const root = node(true)
    const mid = node(true, root)
    expect(isVisibleChain(node(true, mid))).toBe(true)
  })

  // The case `.filter(m => m.visible)` gets wrong — and the reason flexible/ss-linker
  // groups (scene children, not design-root children) need this at all.
  it('false when an ANCESTOR is hidden even though the leaf itself is visible', () => {
    const hiddenGroup = node(false)
    const leaf = node(true, hiddenGroup)
    expect(leaf.visible).toBe(true)
    expect(isVisibleChain(leaf)).toBe(false)
  })

  it('false when the leaf itself is hidden', () => {
    expect(isVisibleChain(node(false, node(true)))).toBe(false)
  })
})

describe('backboneCandidates', () => {
  const mesh = instMesh('backboneSpheres')

  it('keys ordinary beads, and folds fluoro entries into the same family', () => {
    const out = backboneCandidates(
      [{ instMesh: mesh, id: 3, nuc: nuc({ bp_index: 7 }) }],
      [{ instMesh: instMesh('extensionFluorophores'), id: 0, nuc: nuc({ helix_id: '__ext_a', bp_index: 2 }) }],
      ALL_TYPES,
    )
    expect(out.map(c => c.key)).toEqual(['h1:7:FORWARD', '__ext_a:2:FORWARD'])
    expect(out.every(c => c.family === 'backbone')).toBe(true)
    expect(out[0].id).toBe(3)
  })

  it('carries the loop-copy ordinal into the key so the two copies are distinct', () => {
    const out = backboneCandidates([
      { instMesh: mesh, id: 0, nuc: nuc({ bp_index: 5 }), _copy: 0 },
      { instMesh: mesh, id: 1, nuc: nuc({ bp_index: 5 }), _copy: 1 },
    ], [], ALL_TYPES)
    expect(out.map(c => c.key)).toEqual(['h1:5:FORWARD', 'h1:5:FORWARD:1'])
  })

  it('honours the scaffold/staple gates', () => {
    const entries = [
      { instMesh: mesh, id: 0, nuc: nuc({ strand_type: 'scaffold', bp_index: 1 }) },
      { instMesh: mesh, id: 1, nuc: nuc({ strand_type: 'staple', bp_index: 2 }) },
    ]
    expect(backboneCandidates(entries, [], { scaffold: true, staples: false }).map(c => c.key))
      .toEqual(['h1:1:FORWARD'])
    expect(backboneCandidates(entries, [], { scaffold: false, staples: true }).map(c => c.key))
      .toEqual(['h1:2:FORWARD'])
  })

  it('exempts overhang beads from the scaffold/staple gates (they are their own filter)', () => {
    const out = backboneCandidates(
      [{ instMesh: mesh, id: 0, nuc: nuc({ overhang_id: 'oh1', bp_index: 4 }) }],
      [], { scaffold: false, staples: false },
    )
    expect(out).toHaveLength(1)
  })

  it('drops beads with no strand and beads on a hidden subtree', () => {
    const hidden = instMesh('backboneSpheres', 0, { parent: node(false) })
    const out = backboneCandidates([
      { instMesh: mesh, id: 0, nuc: nuc({ strand_id: null }) },
      { instMesh: hidden, id: 1, nuc: nuc({ bp_index: 9 }) },
    ], [], ALL_TYPES)
    expect(out).toEqual([])
  })
})

describe('xoverCandidates', () => {
  const mesh = instMesh('xoverExtraBeads')

  // The trap: the geometric slot a click yields is NOT the 5′→3′ insert index that
  // __xb__:<xo>:<k> means. design_renderer applies simBeadIndex; we must key off simK.
  it('keys off simK (the simulation insert index), not the geometric slot', () => {
    const out = xoverCandidates([
      { xoId: 'xo1', i: 0, simK: 2, instMesh: mesh, id: 10 },
      { xoId: 'xo1', i: 1, simK: 1, instMesh: mesh, id: 11 },
      { xoId: 'xo1', i: 2, simK: 0, instMesh: mesh, id: 12 },
    ])
    expect(out.map(c => c.key)).toEqual(['__xb__:xo1:2', '__xb__:xo1:1', '__xb__:xo1:0'])
    expect(out[0].id).toBe(10)   // instance id still tracks the geometric slot
  })

  it('drops candidates on a hidden subtree', () => {
    const hidden = instMesh('xoverExtraBeads', 0, { parent: node(false) })
    expect(xoverCandidates([{ xoId: 'xo1', i: 0, simK: 0, instMesh: hidden, id: 0 }])).toEqual([])
  })
})

describe('flexCandidates', () => {
  const resolve = () => (anc) => anc ? `${anc.helix}:${anc.bp}:FORWARD` : null
  const design = {
    flexible_connections: [
      { id: 'c1', segment_bead_keys: [{ helix: 'hA', bp: 3 }, { helix: 'hA', bp: 4 }] },
    ],
  }

  it('maps instance i to segment_bead_keys[i]', () => {
    const beads = instMesh('flexSegmentBeads', 2, { userData: { connectionId: 'c1' } })
    const group = { children: [beads] }
    const out = flexCandidates(group, design, resolve())
    expect(out.map(c => c.key)).toEqual(['hA:3:FORWARD', 'hA:4:FORWARD'])
    expect(out.map(c => c.id)).toEqual([0, 1])
    expect(out[0].family).toBe('flex')
  })

  it('ignores the slab mesh, which carries the SAME userData.connectionId', () => {
    const group = { children: [
      instMesh('flexSegmentSlabs', 2, { userData: { connectionId: 'c1' } }),
    ] }
    expect(flexCandidates(group, design, resolve())).toEqual([])
  })

  it('skips beads whose anchor does not resolve rather than inventing a key', () => {
    const beads = instMesh('flexSegmentBeads', 2, { userData: { connectionId: 'c1' } })
    const out = flexCandidates({ children: [beads] }, design, () => null)
    expect(out).toEqual([])
  })

  it('skips a mesh with more instances than the connection has anchors', () => {
    const beads = instMesh('flexSegmentBeads', 5, { userData: { connectionId: 'c1' } })
    expect(flexCandidates({ children: [beads] }, design, resolve())).toHaveLength(2)
  })

  it('returns empty without a group, design or resolver', () => {
    expect(flexCandidates(null, design, resolve())).toEqual([])
    expect(flexCandidates({ children: [] }, null, resolve())).toEqual([])
    expect(flexCandidates({ children: [] }, design, null)).toEqual([])
  })
})

describe('ssLinkCandidates', () => {
  /** Minimal traversable group: parent group holds connId, child holds the beads. */
  const linkGroup = (connId, count, { visible = true } = {}) => {
    const connGroup = { name: 'overhangSsLinkerBases', userData: { connId, baseCount: count }, visible }
    const beads = instMesh('overhangSsLinkerBeads', count, { parent: connGroup })
    const root = { traverse: (fn) => { fn(connGroup); fn(beads) } }
    return root
  }

  it('keys each display slot against the synthetic __lnk__ helix', () => {
    const out = ssLinkCandidates(linkGroup('c9', 3))
    expect(out.map(c => c.key)).toEqual([
      '__lnk__c9:0:FORWARD', '__lnk__c9:1:FORWARD', '__lnk__c9:2:FORWARD',
    ])
    expect(out.every(c => c.family === 'sslink')).toBe(true)
  })

  it('drops beads whose connection group is hidden', () => {
    expect(ssLinkCandidates(linkGroup('c9', 3, { visible: false }))).toEqual([])
  })

  it('returns empty without a group', () => {
    expect(ssLinkCandidates(null)).toEqual([])
  })
})

describe('nearestCandidate — the 80px hover magnet', () => {
  const cands = [{ key: 'a' }, { key: 'b' }, { key: 'c' }]
  const project = projectBy({ a: { x: 0, y: 0 }, b: { x: 30, y: 40 }, c: { x: 200, y: 0 } })

  it('picks the closest candidate inside the radius', () => {
    expect(nearestCandidate(cands, 0, 0, 80, project).key).toBe('a')
    expect(nearestCandidate(cands, 28, 40, 80, project).key).toBe('b')
  })

  it('returns null when everything is outside the radius', () => {
    expect(nearestCandidate(cands, 500, 500, 80, project)).toBeNull()
  })

  it('excludes at exactly the radius (strict <, matching the existing magnets)', () => {
    // 'b' is exactly 50px from the origin
    expect(nearestCandidate([{ key: 'b' }], 0, 0, 50, project)).toBeNull()
    expect(nearestCandidate([{ key: 'b' }], 0, 0, 51, project).key).toBe('b')
  })

  it('skips candidates the projector rejects (behind the camera)', () => {
    expect(nearestCandidate([{ key: 'zz' }], 0, 0, 80, project)).toBeNull()
  })

  it('handles an empty candidate list', () => {
    expect(nearestCandidate([], 0, 0, 80, project)).toBeNull()
  })
})

describe('candidatesInRect — the lasso', () => {
  const cands = [{ key: 'in' }, { key: 'edge' }, { key: 'out' }, { key: 'behind' }]
  const project = projectBy({
    in: { x: 50, y: 50 }, edge: { x: 10, y: 100 }, out: { x: 500, y: 50 },
  })
  const rect = { x1: 10, y1: 10, x2: 100, y2: 100 }

  it('captures candidates inside the rect', () => {
    expect(candidatesInRect(cands, rect, project).map(c => c.key)).toContain('in')
  })

  it('is INCLUSIVE on the boundary, matching the existing lasso loops', () => {
    expect(candidatesInRect([{ key: 'edge' }], rect, project).map(c => c.key)).toEqual(['edge'])
  })

  it('excludes candidates outside and candidates the projector rejects', () => {
    const keys = candidatesInRect(cands, rect, project).map(c => c.key)
    expect(keys).not.toContain('out')
    expect(keys).not.toContain('behind')
  })

  it('returns empty without a rect', () => {
    expect(candidatesInRect(cands, null, project)).toEqual([])
  })
})
