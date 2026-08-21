import { describe, it, expect } from 'vitest'
import {
  clusterAlphaForNuc,
  clusterAlphaKeys,
  clusterBackboneEntries,
  clusterIdForNucleotide,
  clusterDisplaySignature,
  clusterMemberFilter,
  clusterNucKeys,
  clusterNucKeysFor,
  withClusterDisplay,
  isAutoCluster,
} from './cluster_entries.js'

const entry = (helix_id, strand_id, domain_index) => ({ nuc: { helix_id, strand_id, domain_index } })
const entries = [
  entry('h1', 's1', 0),
  entry('h2', 's1', 1),
  entry('h3', 's2', 0),
]

describe('clusterBackboneEntries', () => {
  it('plain cluster → all entries on its helix_ids', () => {
    const out = clusterBackboneEntries({ helix_ids: ['h1', 'h3'] }, {}, entries)
    expect(out.map(e => e.nuc.helix_id)).toEqual(['h1', 'h3'])
  })

  it('mixed cluster → bridge-domain entries + exclusively-owned helices', () => {
    // bridge domain s1/1 lives on h2, so h2 is NOT exclusive; h1 is exclusive.
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const out = clusterBackboneEntries(cluster, design, entries)
    // h1 entry (exclusive) + the s1:1 bridge entry (on h2); the h3 entry excluded.
    expect(out).toEqual([entry('h1', 's1', 0), entry('h2', 's1', 1)])
  })

  it('empty for missing helix_ids or no entries', () => {
    expect(clusterBackboneEntries({ helix_ids: [] }, {}, entries)).toEqual([])
    expect(clusterBackboneEntries({ helix_ids: ['h1'] }, {}, [])).toEqual([])
  })
})

// The predicate behind clusterBackboneEntries. It became a public export when
// three byte-identical copies (here, cluster_gizmo.js, assembly_renderer.js)
// were collapsed into one, so it needs pinning in its own right — in particular
// the null-vs-matches-nothing distinction its five callers branch on.
describe('clusterMemberFilter', () => {
  const nucOf = e => e.nuc

  it('returns null (not an always-false predicate) for a cluster with no helix_ids', () => {
    expect(clusterMemberFilter({ helix_ids: [] }, {})).toBeNull()
    expect(clusterMemberFilter(null, {})).toBeNull()
    expect(clusterMemberFilter(undefined, {})).toBeNull()
  })

  it('plain cluster → membership by helix_id alone', () => {
    const f = clusterMemberFilter({ helix_ids: ['h1', 'h3'] }, {})
    expect(entries.map(nucOf).map(f)).toEqual([true, false, true])
  })

  it('mixed cluster → bridge domains plus exclusively-owned helices', () => {
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const f = clusterMemberFilter(cluster, design)
    expect(f({ helix_id: 'h1', strand_id: 's1', domain_index: 0 })).toBe(true)   // exclusive helix
    expect(f({ helix_id: 'h2', strand_id: 's1', domain_index: 1 })).toBe(true)   // the bridge domain
    expect(f({ helix_id: 'h2', strand_id: 's2', domain_index: 0 })).toBe(false)  // h2 is shared, not exclusive
    expect(f({ helix_id: 'h3', strand_id: 's2', domain_index: 0 })).toBe(false)  // outside the cluster
  })

  it('tolerates a design whose strands are missing (unresolvable bridge domain)', () => {
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 'gone', domain_index: 0 }] }
    const f = clusterMemberFilter(cluster, {})
    // no bridge helix resolves → every listed helix stays exclusive
    expect(f({ helix_id: 'h1', strand_id: 's1', domain_index: 0 })).toBe(true)
    expect(f({ helix_id: 'h2', strand_id: 's1', domain_index: 0 })).toBe(true)
  })

  it('agrees with clusterBackboneEntries (the wrapper is just a filter over it)', () => {
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const f = clusterMemberFilter(cluster, design)
    expect(clusterBackboneEntries(cluster, design, entries)).toEqual(entries.filter(e => f(e.nuc)))
  })
})

describe('clusterIdForNucleotide', () => {
  it('prefers the smallest non-default containing Cluster', () => {
    const design = {
      cluster_transforms: [
        { id: 'default', is_default: true, helix_ids: ['h1', 'h2', 'h3'] },
        { id: 'wide', helix_ids: ['h1', 'h2'] },
        { id: 'exact', helix_ids: ['h1'] },
      ],
    }
    expect(clusterIdForNucleotide(entries[0].nuc, design)).toBe('exact')
  })

  it('falls back to the default Cluster and respects mixed-domain membership', () => {
    const design = {
      strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }],
      cluster_transforms: [
        { id: 'mixed', helix_ids: ['h1', 'h2'], domain_ids: [
          { strand_id: 's1', domain_index: 1 },
        ] },
        { id: 'default', is_default: true, helix_ids: ['h1', 'h2', 'h3'] },
      ],
    }
    expect(clusterIdForNucleotide(entries[1].nuc, design)).toBe('mixed')
    expect(clusterIdForNucleotide(entries[2].nuc, design)).toBe('default')
    expect(clusterIdForNucleotide({ helix_id: 'gone' }, design)).toBeNull()
  })
})

// ── nucKey form ───────────────────────────────────────────────────────────────

const nkDesign = {
  strands: [
    { id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] },
    { id: 's2', domains: [{ helix_id: 'h3' }] },
  ],
  extensions: [
    { id: 'e1', strand_id: 's1', end: 'five_prime' },   // terminal domain on h1
    { id: 'e2', strand_id: 's2', end: 'three_prime' },  // terminal domain on h3
  ],
}

describe('clusterNucKeys', () => {
  it('plain cluster → whole-helix keys only', () => {
    const keys = clusterNucKeys({ helix_ids: ['h1', 'h2'] }, { strands: nkDesign.strands })
    expect([...keys].sort()).toEqual(['h:h1', 'h:h2'])
  })

  it('mixed cluster → a domain key per bridge, plus only the exclusively-owned helices', () => {
    // bridge domain s1/1 sits on h2, so h2 is covered by its domain key, not whole.
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const keys = clusterNucKeys(cluster, { strands: nkDesign.strands })
    expect([...keys].sort()).toEqual(['d:s1:1', 'h:h1'])
  })

  it('empty for a cluster with no helix_ids', () => {
    expect(clusterNucKeys({ helix_ids: [] }, nkDesign).size).toBe(0)
    expect(clusterNucKeys(null, nkDesign).size).toBe(0)
  })

  it('pulls in an extension whose host strand is covered by a domain key', () => {
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    expect(clusterNucKeys(cluster, nkDesign).has('h:__ext_e1')).toBe(true)
  })

  it('pulls in an extension whose terminal domain sits on a covered helix', () => {
    // h1 covered whole; e1 is 5' on s1 whose first domain is on h1.
    expect(clusterNucKeys({ helix_ids: ['h1'] }, nkDesign).has('h:__ext_e1')).toBe(true)
  })

  it('leaves out an extension on an uncovered strand and helix', () => {
    const keys = clusterNucKeys({ helix_ids: ['h1'] }, nkDesign)
    expect(keys.has('h:__ext_e2')).toBe(false)   // e2 lives on s2 / h3
  })

  it('uses the LAST domain for a 3-prime extension, not the first', () => {
    // s1 spans h1 → h2; a 3' extension must attach to h2.
    const d = { ...nkDesign, extensions: [{ id: 'e3', strand_id: 's1', end: 'three_prime' }] }
    expect(clusterNucKeys({ helix_ids: ['h2'] }, d).has('h:__ext_e3')).toBe(true)
    expect(clusterNucKeys({ helix_ids: ['h1'] }, d).has('h:__ext_e3')).toBe(false)
  })
})

// Behaviour-preservation pin for the extraction. clusterNucKeys is ADAPTED from
// main.js's inline visibility loop (one flat loop over all hidden clusters →
// a per-cluster function), not a verbatim lift, so "green first run" proves
// nothing on its own. This reference implementation is that loop, transcribed
// from main.js before the extraction; both must agree on every fixture.
function _mainJsReferenceExpansion(currentDesign, hiddenClusterIds) {
  const clusters = currentDesign?.cluster_transforms ?? []
  const nucKeys = new Set()
  const hiddenStrandIds = new Set()
  const hiddenHelixIds = new Set()
  const strandMap = new Map((currentDesign?.strands ?? []).map(s => [s.id, s]))
  for (const c of clusters) {
    if (!hiddenClusterIds.has(c.id)) continue
    if (c.domain_ids?.length) {
      const bridgeHelixIds = new Set()
      for (const d of c.domain_ids) {
        const dom = strandMap.get(d.strand_id)?.domains?.[d.domain_index]
        if (dom) bridgeHelixIds.add(dom.helix_id)
        nucKeys.add(`d:${d.strand_id}:${d.domain_index}`)
        hiddenStrandIds.add(d.strand_id)
      }
      for (const hid of c.helix_ids) {
        if (!bridgeHelixIds.has(hid)) { nucKeys.add(`h:${hid}`); hiddenHelixIds.add(hid) }
      }
    } else {
      for (const hid of c.helix_ids) { nucKeys.add(`h:${hid}`); hiddenHelixIds.add(hid) }
    }
  }
  for (const ext of currentDesign?.extensions ?? []) {
    if (hiddenStrandIds.has(ext.strand_id)) {
      nucKeys.add('h:__ext_' + ext.id)
    } else if (hiddenHelixIds.size) {
      const strand = currentDesign.strands.find(s => s.id === ext.strand_id)
      const termDom = strand && (ext.end === 'five_prime'
        ? strand.domains[0]
        : strand.domains[strand.domains.length - 1])
      if (termDom && hiddenHelixIds.has(termDom.helix_id)) nucKeys.add('h:__ext_' + ext.id)
    }
  }
  return nucKeys
}

describe('clusterNucKeysFor matches the pre-extraction main.js expansion', () => {
  const sorted = s => [...s].sort()
  const design = {
    ...nkDesign,
    cluster_transforms: [
      { id: 'cA', helix_ids: ['h1', 'h2'] },
      { id: 'cB', helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] },
      { id: 'cC', helix_ids: ['h3'] },
    ],
  }

  for (const ids of [['cA'], ['cB'], ['cC'], ['cA', 'cC'], ['cB', 'cC'], ['cA', 'cB', 'cC'], []]) {
    it(`agrees for {${ids.join(',') || '∅'}}`, () => {
      const set = new Set(ids)
      expect(sorted(clusterNucKeysFor(design, set)))
        .toEqual(sorted(_mainJsReferenceExpansion(design, set)))
    })
  }
})

describe('clusterAlphaKeys', () => {
  const withOpacity = (...ops) => ({
    ...nkDesign,
    cluster_transforms: ops.map((opacity, i) => ({
      id: `c${i}`, helix_ids: ['h1'], ...(opacity === undefined ? {} : { opacity }),
    })),
  })

  it('is EMPTY when every cluster is opaque — the zero-cost path', () => {
    expect(clusterAlphaKeys(withOpacity(1, 1)).size).toBe(0)
    expect(clusterAlphaKeys(withOpacity(undefined)).size).toBe(0)
    expect(clusterAlphaKeys({}).size).toBe(0)
  })

  it('maps every key of a faded cluster to its alpha', () => {
    const design = {
      ...nkDesign,
      cluster_transforms: [{
        id: 'c0', opacity: 0.3, helix_ids: ['h1', 'h2'],
        domain_ids: [{ strand_id: 's1', domain_index: 1 }],
      }],
    }
    const m = clusterAlphaKeys(design)
    expect(m.get('d:s1:1')).toBe(0.3)
    expect(m.get('h:h1')).toBe(0.3)
    expect(m.get('h:__ext_e1')).toBe(0.3)
  })

  it('takes the LOWEST opacity where clusters overlap', () => {
    // The VoltronCoreScad case: two clusters claiming the same helices.
    const m = clusterAlphaKeys(withOpacity(0.8, 0.35))
    expect(m.get('h:h1')).toBe(0.35)
    const flipped = clusterAlphaKeys(withOpacity(0.35, 0.8))
    expect(flipped.get('h:h1')).toBe(0.35)
  })

  it('does not let an opaque cluster erase an overlapping fade', () => {
    expect(clusterAlphaKeys(withOpacity(0.35, 1)).get('h:h1')).toBe(0.35)
  })

  it('keeps non-overlapping clusters independent', () => {
    const design = {
      ...nkDesign,
      cluster_transforms: [
        { id: 'c0', opacity: 0.2, helix_ids: ['h1'] },
        { id: 'c1', opacity: 0.9, helix_ids: ['h3'] },
      ],
    }
    const m = clusterAlphaKeys(design)
    expect(m.get('h:h1')).toBe(0.2)
    expect(m.get('h:h3')).toBe(0.9)
  })
})

describe('clusterDisplaySignature', () => {
  const base = {
    cluster_transforms: [
      { id: 'cA', color: '#ff8800', opacity: 0.4, translation: [0, 0, 0] },
      { id: 'cB', translation: [0, 0, 0] },
    ],
  }

  it('is STABLE across a pose-only change (the 60 Hz gizmo-drag anti-thrash pin)', () => {
    const moved = {
      cluster_transforms: [
        { ...base.cluster_transforms[0], translation: [5, 6, 7], rotation: [0, 0, 1, 0], pivot: [1, 1, 1] },
        { ...base.cluster_transforms[1], translation: [9, 9, 9] },
      ],
    }
    expect(clusterDisplaySignature(moved)).toBe(clusterDisplaySignature(base))
  })

  it('moves when a colour changes', () => {
    const recoloured = {
      cluster_transforms: [{ ...base.cluster_transforms[0], color: '#00ffcc' }, base.cluster_transforms[1]],
    }
    expect(clusterDisplaySignature(recoloured)).not.toBe(clusterDisplaySignature(base))
  })

  it('moves when an opacity changes', () => {
    const faded = {
      cluster_transforms: [{ ...base.cluster_transforms[0], opacity: 0.9 }, base.cluster_transforms[1]],
    }
    expect(clusterDisplaySignature(faded)).not.toBe(clusterDisplaySignature(base))
  })

  it('moves when a cluster is added, removed or reordered', () => {
    const sig = clusterDisplaySignature(base)
    expect(clusterDisplaySignature({ cluster_transforms: [base.cluster_transforms[0]] })).not.toBe(sig)
    expect(clusterDisplaySignature({
      cluster_transforms: [...base.cluster_transforms, { id: 'cC' }],
    })).not.toBe(sig)
    expect(clusterDisplaySignature({
      cluster_transforms: [base.cluster_transforms[1], base.cluster_transforms[0]],
    })).not.toBe(sig)
  })

  it('treats an unset colour/opacity the same as the defaults', () => {
    expect(clusterDisplaySignature({ cluster_transforms: [{ id: 'cA' }] }))
      .toBe(clusterDisplaySignature({ cluster_transforms: [{ id: 'cA', color: null, opacity: 1 }] }))
  })
})

describe('withClusterDisplay', () => {
  const design = {
    strands: [],
    cluster_transforms: [{ id: 'cA', opacity: 1 }, { id: 'cB', opacity: 1 }],
  }

  it('does not mutate the input', () => {
    const snapshot = JSON.stringify(design)
    withClusterDisplay(design, 'cA', { opacity: 0.5 })
    expect(JSON.stringify(design)).toBe(snapshot)
  })

  it('returns a new design with only the named cluster changed', () => {
    const out = withClusterDisplay(design, 'cA', { opacity: 0.5, color: '#ff8800' })
    expect(out).not.toBe(design)
    expect(out.cluster_transforms[0]).toEqual({ id: 'cA', opacity: 0.5, color: '#ff8800' })
    expect(out.cluster_transforms[1]).toBe(design.cluster_transforms[1])   // identity-equal
  })

  it("treats color:'' as clear-to-auto-palette, like the PATCH sentinel", () => {
    const coloured = withClusterDisplay(design, 'cA', { color: '#ff8800' })
    expect(withClusterDisplay(coloured, 'cA', { color: '' }).cluster_transforms[0].color).toBeNull()
  })

  it('leaves an omitted field alone', () => {
    const out = withClusterDisplay(
      withClusterDisplay(design, 'cA', { color: '#ff8800' }), 'cA', { opacity: 0.5})
    expect(out.cluster_transforms[0]).toEqual({ id: 'cA', color: '#ff8800', opacity: 0.5 })
  })

  it('passes a design with no clusters straight through', () => {
    const bare = { strands: [] }
    expect(withClusterDisplay(bare, 'cA', { opacity: 0.5 })).toBe(bare)
  })
})

// Shared by the helix meshes AND the crossover extra-base meshes, which are driven
// from different modules — a second copy of this rule would let the two disagree
// about which cluster an inserted base belongs to.
describe('clusterAlphaForNuc', () => {
  const nuc = (helix_id, strand_id, domain_index) => ({ helix_id, strand_id, domain_index })

  it('is opaque for an empty map (the zero-cost path)', () => {
    expect(clusterAlphaForNuc(new Map(), nuc('h1', 's1', 0))).toBe(1)
    expect(clusterAlphaForNuc(null, nuc('h1', 's1', 0))).toBe(1)
  })

  it('is opaque for a nucleotide no key covers', () => {
    expect(clusterAlphaForNuc(new Map([['h:h9', 0.3]]), nuc('h1', 's1', 0))).toBe(1)
  })

  it('reads the helix-level key', () => {
    expect(clusterAlphaForNuc(new Map([['h:h1', 0.3]]), nuc('h1', 's1', 0))).toBe(0.3)
  })

  it('prefers the domain-level key over the helix-level one', () => {
    const m = new Map([['h:h1', 0.3], ['d:s1:0', 0.8]])
    expect(clusterAlphaForNuc(m, nuc('h1', 's1', 0))).toBe(0.8)
    expect(clusterAlphaForNuc(m, nuc('h1', 's1', 1))).toBe(0.3)   // falls back
  })

  it('resolves extension beads by their synthetic helix id', () => {
    // Their domain_index is an out-of-range sentinel (-1 / len(domains)), so the
    // domain tier can never match — the __ext_ key is the only way in.
    const m = new Map([['h:__ext_e1', 0.35]])
    expect(clusterAlphaForNuc(m, nuc('__ext_e1', 's1', -1))).toBe(0.35)
  })

  it('tolerates a null nucleotide', () => {
    expect(clusterAlphaForNuc(new Map([['h:h1', 0.3]]), null)).toBe(1)
  })
})

// ── Cluster provenance ───────────────────────────────────────────────────────
// A cluster the USER built outranks one the app made by itself when resolving COLOUR.
// Auto clusters routinely blanket every helix — an imported design gets a "Scaffold
// Cluster" and a "Geometry Cluster" each covering all of them — so without this an auto
// cluster could silently win the colour on a nucleotide the user had deliberately
// clustered. That was the unreproducible "weirdness in colour assignment".

describe('isAutoCluster', () => {
  it('trusts the backend flag when present', () => {
    expect(isAutoCluster({ name: 'Cluster 3', auto_created: true })).toBe(true)
    // …even against a name that would otherwise infer auto — an explicit false wins.
    expect(isAutoCluster({ name: 'Scaffold Cluster 1', auto_created: false })).toBe(false)
  })

  it('infers from the autodetect name prefixes on legacy designs', () => {
    expect(isAutoCluster({ name: 'Scaffold Cluster 1' })).toBe(true)
    expect(isAutoCluster({ name: 'Geometry Cluster 2' })).toBe(true)
  })

  it('treats the catch-all and overhang-duplex children as auto', () => {
    expect(isAutoCluster({ name: 'Cluster 1', is_default: true })).toBe(true)
    expect(isAutoCluster({ name: 'Duplex 1', overhang_duplex_driver_id: 'oh1' })).toBe(true)
  })

  it('does NOT infer auto from a bare "Cluster N" name', () => {
    // The load-bearing limit of the name fallback: cluster_autodetect also emits plain
    // "Cluster N", exactly like a user-created one, so the name cannot separate them.
    // Guessing "auto" here would demote real user clusters.
    expect(isAutoCluster({ name: 'Cluster 3' })).toBe(false)
    expect(isAutoCluster({ name: 'My bar' })).toBe(false)
    expect(isAutoCluster({})).toBe(false)
  })
})
