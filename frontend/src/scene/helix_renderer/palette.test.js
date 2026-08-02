/**
 * buildStapleColorMap — staple palette stability.
 *
 * The bug this pins: staple colours were derived from each strand's *array
 * position* in design.strands on every rebuild, so any edit that reshuffles the
 * array (a scaffold nick/crossover, a forced-ligation delete that splits a strand
 * and appends the fragments) silently recoloured untouched staples. The fix pins
 * a palette slot per strand.id on first encounter (keyed by design.id).
 */
import { describe, it, expect, beforeEach } from 'vitest'
import {
  buildStapleColorMap,
  buildClusterColorLookup,
  buildClusterLookup,
  STAPLE_PALETTE,
  _resetStapleColorPins,
} from './palette.js'

// Minimal strand/nuc factories. A nuc only needs strand_id + strand_type here.
function strand(id, type = 'staple') {
  return { id, strand_type: type, domains: [] }
}
function geomFor(strands) {
  // One nucleotide per strand, in strand-array order (matches how geometry is
  // emitted — staples in design.strands order).
  return strands.map(s => ({ strand_id: s.id, strand_type: s.strand_type }))
}

beforeEach(() => _resetStapleColorPins())

describe('buildStapleColorMap', () => {
  it('first encounter: staple slot = its index in design.strands (initial-load parity)', () => {
    const strands = [strand('scaf', 'scaffold'), strand('A'), strand('B'), strand('C')]
    const design = { id: 'D1', strands, crossovers: [] }
    const map = buildStapleColorMap(geomFor(strands), design)
    // scaffold at index 0 is skipped (no palette entry); A/B/C keep their array slot.
    expect(map.get('A')).toBe(STAPLE_PALETTE[1])
    expect(map.get('B')).toBe(STAPLE_PALETTE[2])
    expect(map.get('C')).toBe(STAPLE_PALETTE[3])
    expect(map.has('scaf')).toBe(false)
  })

  it('reshuffling design.strands (FL delete / scaffold edit) does NOT recolour untouched staples', () => {
    const scaf = strand('scaf', 'scaffold')
    const A = strand('A'), B = strand('B'), C = strand('C')
    const before = buildStapleColorMap(geomFor([scaf, A, B, C]), { id: 'D2', strands: [scaf, A, B, C], crossovers: [] })

    // Simulate delete_forced_ligation: the scaffold strand splits and the two
    // fragments are appended at the END → every staple's array index shifts down.
    const scafA = strand('scafA', 'scaffold'), scafB = strand('scafB', 'scaffold')
    const reshuffled = [A, B, C, scafA, scafB]
    const after = buildStapleColorMap(geomFor(reshuffled), { id: 'D2', strands: reshuffled, crossovers: [] })

    // A/B/C are topologically untouched → same colours as before, NOT palette[0/1/2].
    expect(after.get('A')).toBe(before.get('A'))
    expect(after.get('B')).toBe(before.get('B'))
    expect(after.get('C')).toBe(before.get('C'))
  })

  it('a genuinely new strand gets a fresh palette slot (not a pinned one)', () => {
    const A = strand('A'), B = strand('B')
    buildStapleColorMap(geomFor([A, B]), { id: 'D3', strands: [A, B], crossovers: [] })
    const N = strand('N')
    const map = buildStapleColorMap(geomFor([A, B, N]), { id: 'D3', strands: [A, B, N], crossovers: [] })
    expect(map.get('A')).toBe(STAPLE_PALETTE[0])   // pinned
    expect(map.get('B')).toBe(STAPLE_PALETTE[1])   // pinned
    expect(map.get('N')).toBe(STAPLE_PALETTE[2])   // new → slot 2
  })

  it('pins are isolated per design.id (assembly parts keep independent palettes)', () => {
    const strands = [strand('A'), strand('B')]
    const m1 = buildStapleColorMap(geomFor(strands), { id: 'partX', strands, crossovers: [] })
    // Same strand ids, different design → its own first-encounter assignment,
    // unaffected by partX's pins.
    const m2 = buildStapleColorMap(geomFor(strands), { id: 'partY', strands, crossovers: [] })
    expect(m2.get('A')).toBe(m1.get('A'))   // both slot 0, but independently pinned
    expect(m2.get('B')).toBe(m1.get('B'))
  })
})

// ── buildClusterColorLookup ───────────────────────────────────────────────────
// The cluster-coloring lookup, once a cluster can carry a user-set `color`.
// Two things must hold: an unstyled design renders EXACTLY as it did before this
// existed, and a colour the user actually picked is never silently overridden by
// an unstyled cluster that happens to overlap it.

describe('buildClusterColorLookup', () => {
  const strands = [
    { id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] },
    { id: 's2', domains: [{ helix_id: 'h2' }] },
  ]
  const nuc = (helix_id, strand_id, domain_index) => ({ helix_id, strand_id, domain_index })

  it('falls back to the auto palette slot, byte-identical to buildClusterLookup', () => {
    const design = {
      strands,
      cluster_transforms: [{ id: 'cA', helix_ids: ['h1'] }, { id: 'cB', helix_ids: ['h2'] }],
    }
    const colorFn = buildClusterColorLookup(design)
    const idxFn = buildClusterLookup(design)
    for (const n of [nuc('h1', 's1', 0), nuc('h2', 's1', 1), nuc('h2', 's2', 0)]) {
      const ci = idxFn(n)
      expect(colorFn(n)).toBe(STAPLE_PALETTE[ci % STAPLE_PALETTE.length])
    }
  })

  it('uses a cluster’s explicit colour when it has one', () => {
    const colorFn = buildClusterColorLookup({
      strands, cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], color: '#ff8800' }],
    })
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0xff8800)
  })

  it('accepts uppercase hex', () => {
    const colorFn = buildClusterColorLookup({
      strands, cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], color: '#FF8800' }],
    })
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0xff8800)
  })

  for (const bad of ['red', '#fff', 'ff8800', '', null, undefined, 123, '#gg0000']) {
    it(`falls back to the palette for a malformed colour (${JSON.stringify(bad)})`, () => {
      const colorFn = buildClusterColorLookup({
        strands, cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], color: bad }],
      })
      const c = colorFn(nuc('h1', 's1', 0))
      expect(c).toBe(STAPLE_PALETTE[0])
      expect(Number.isNaN(c)).toBe(false)
    })
  }

  it('returns undefined for a nucleotide in no cluster', () => {
    const colorFn = buildClusterColorLookup({
      strands, cluster_transforms: [{ id: 'cA', helix_ids: ['h1'] }],
    })
    expect(colorFn(nuc('h9', 's9', 0))).toBeUndefined()
  })

  it('returns undefined when the design has no clusters at all', () => {
    expect(buildClusterColorLookup({ strands })(nuc('h1', 's1', 0))).toBeUndefined()
    expect(buildClusterColorLookup(null)(nuc('h1', 's1', 0))).toBeUndefined()
  })

  // ── overlap resolution ──────────────────────────────────────────────────────

  it('an EXPLICIT colour beats an overlapping unstyled cluster with a higher index', () => {
    // The VoltronCoreScad case: "Scaffold Cluster 1" and "Geometry Cluster 1" both
    // claim every helix. Colouring the first must be visible, even though the
    // last-listed cluster would otherwise win.
    const colorFn = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'scaffold', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
        { id: 'geometry', helix_ids: ['h1', 'h2'] },
      ],
    })
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0xff00ff)
  })

  it('…and still wins when the explicit cluster is the later entry', () => {
    const colorFn = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'geometry', helix_ids: ['h1', 'h2'] },
        { id: 'scaffold', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
      ],
    })
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0xff00ff)
  })

  it('when BOTH overlapping clusters are explicit, the later entry wins', () => {
    const colorFn = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'scaffold', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
        { id: 'geometry', helix_ids: ['h1', 'h2'], color: '#00ffcc' },
      ],
    })
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0x00ffcc)
  })

  it('when NEITHER is explicit, the later entry wins (unchanged behaviour)', () => {
    const design = {
      strands,
      cluster_transforms: [
        { id: 'scaffold', helix_ids: ['h1', 'h2'] },
        { id: 'geometry', helix_ids: ['h1', 'h2'] },
      ],
    }
    expect(buildClusterColorLookup(design)(nuc('h1', 's1', 0)))
      .toBe(STAPLE_PALETTE[buildClusterLookup(design)(nuc('h1', 's1', 0))])
  })

  // ── tier precedence (domain beats helix), unchanged ─────────────────────────

  it('a domain-level entry beats the helix-level fallback', () => {
    const colorFn = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'whole', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
        { id: 'bridge', helix_ids: ['h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }], color: '#00ffcc' },
      ],
    })
    expect(colorFn(nuc('h2', 's1', 1))).toBe(0x00ffcc)   // the bridge domain
    expect(colorFn(nuc('h1', 's1', 0))).toBe(0xff00ff)   // elsewhere
  })

  it('tier wins over explicitness — an UNSTYLED domain entry still beats a coloured helix', () => {
    // Explicitness is only the tiebreak WITHIN a tier; making it outrank the tier
    // would change how existing designs render.
    const design = {
      strands,
      cluster_transforms: [
        { id: 'whole', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
        { id: 'bridge', helix_ids: ['h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] },
      ],
    }
    expect(buildClusterColorLookup(design)(nuc('h2', 's1', 1))).toBe(STAPLE_PALETTE[1])
  })

  it('a fully-covered helix is owned by the domain cluster, a partly-covered one is not', () => {
    // h2 carries s1:1 and s2:0. Covering only s1:1 leaves h2 a bridge, so the
    // helix-level fallback there stays with the other cluster.
    const partial = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'whole', helix_ids: ['h2'], color: '#ff00ff' },
        { id: 'bridge', helix_ids: ['h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }], color: '#00ffcc' },
      ],
    })
    expect(partial(nuc('h2', 's2', 0))).toBe(0xff00ff)

    const full = buildClusterColorLookup({
      strands,
      cluster_transforms: [
        { id: 'whole', helix_ids: ['h2'], color: '#ff00ff' },
        {
          id: 'bridge', helix_ids: ['h2'], color: '#00ffcc',
          domain_ids: [{ strand_id: 's1', domain_index: 1 }, { strand_id: 's2', domain_index: 0 }],
        },
      ],
    })
    expect(full(nuc('h2', 's2', 0))).toBe(0x00ffcc)
  })

  // ── 5′/3′ extension beads ───────────────────────────────────────────────────
  // Extensions render on SYNTHETIC helices ('__ext_<id>') that appear in no
  // cluster's helix_ids, and their domain_index is a sentinel (-1 for 5′,
  // len(domains) for 3′). So neither tier resolves them without explicit help —
  // the symptom was an extension keeping its strand colour while the helix it grows
  // out of took the cluster colour.

  describe('extension beads', () => {
    const extDesign = (clusterOverrides = {}, extras = {}) => ({
      strands,
      extensions: [
        { id: 'e1', strand_id: 's1', end: 'five_prime' },    // terminal domain on h1
        { id: 'e2', strand_id: 's2', end: 'three_prime' },   // terminal domain on h2
      ],
      cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], ...clusterOverrides }],
      ...extras,
    })
    // The real sentinel shape: strand_id is the HOST strand, domain_index is out of range.
    const extNuc = (id, strand_id, domain_index) => ({
      helix_id: `__ext_${id}`, strand_id, domain_index, extension_id: id,
    })

    it('an extension inherits the colour of the cluster owning its terminal helix', () => {
      const colorFn = buildClusterColorLookup(extDesign({ color: '#ff8800' }))
      expect(colorFn(extNuc('e1', 's1', -1))).toBe(0xff8800)
    })

    it('…and the auto palette slot when that cluster has no explicit colour', () => {
      const colorFn = buildClusterColorLookup(extDesign())
      expect(colorFn(extNuc('e1', 's1', -1))).toBe(STAPLE_PALETTE[0])
    })

    it('resolves DESPITE the out-of-range domain_index sentinel', () => {
      // -1 and len(domains) must both work; neither can match a real domain key.
      const colorFn = buildClusterColorLookup(extDesign({ helix_ids: ['h1', 'h2'], color: '#ff8800' }))
      expect(colorFn(extNuc('e1', 's1', -1))).toBe(0xff8800)
      expect(colorFn(extNuc('e2', 's2', 1))).toBe(0xff8800)
    })

    it('follows its HOST STRAND when a domain-level cluster owns that strand', () => {
      const colorFn = buildClusterColorLookup({
        strands,
        extensions: [{ id: 'e1', strand_id: 's1', end: 'five_prime' }],
        cluster_transforms: [
          { id: 'whole', helix_ids: ['h1', 'h2'], color: '#ff00ff' },
          {
            id: 'bridge', helix_ids: ['h2'], color: '#00ffcc',
            domain_ids: [{ strand_id: 's1', domain_index: 1 }],
          },
        ],
      })
      // s1 is owned by the domain cluster, so its extension goes with it.
      expect(colorFn(extNuc('e1', 's1', -1))).toBe(0x00ffcc)
    })

    it('stays undefined when no cluster covers its strand or terminal helix', () => {
      const colorFn = buildClusterColorLookup({
        strands,
        extensions: [{ id: 'e2', strand_id: 's2', end: 'three_prime' }],
        cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], color: '#ff8800' }],
      })
      // s2 lives on h2 only; cA owns h1.
      expect(colorFn(extNuc('e2', 's2', 1))).toBeUndefined()
    })

    it('obeys the same explicit-wins overlap rule as everything else', () => {
      const colorFn = buildClusterColorLookup({
        strands,
        extensions: [{ id: 'e1', strand_id: 's1', end: 'five_prime' }],
        cluster_transforms: [
          { id: 'scaffold', helix_ids: ['h1'], color: '#ff00ff' },
          { id: 'geometry', helix_ids: ['h1'] },
        ],
      })
      expect(colorFn(extNuc('e1', 's1', -1))).toBe(0xff00ff)
    })

    it('is a no-op for a design with no extensions', () => {
      const colorFn = buildClusterColorLookup({
        strands, cluster_transforms: [{ id: 'cA', helix_ids: ['h1'], color: '#ff8800' }],
      })
      expect(colorFn({ helix_id: 'h1', strand_id: 's1', domain_index: 0 })).toBe(0xff8800)
    })
  })
})

// ── Provenance: a hand-made cluster outranks an auto one ─────────────────────
// The VoltronCoreScad shape, which is what produced the unreproducible colour
// weirdness: two AUTO clusters ("Scaffold Cluster 1", "Geometry Cluster 1") each blanket
// all the helices, and the user's own clusters overlap them. Before this the auto
// clusters could win by being later in the array, or by carrying an explicit colour.

describe('buildClusterColorLookup — manual beats auto', () => {
  const strands = [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }]
  const nuc = (helix_id, strand_id, domain_index) => ({ helix_id, strand_id, domain_index })
  const build = (cts) => buildClusterColorLookup({ strands, cluster_transforms: cts })

  it('a manual cluster wins over a LATER auto cluster', () => {
    const fn = build([
      { id: 'mine', helix_ids: ['h1'], auto_created: false, color: '#ff00ff' },
      { id: 'auto', helix_ids: ['h1'], auto_created: true,  color: '#00ffcc' },
    ])
    expect(fn(nuc('h1', 's1', 0))).toBe(0xff00ff)
  })

  it('…and over an auto cluster that has an EXPLICIT colour while the manual one does not', () => {
    // Provenance outranks the explicit-colour tiebreak: the manual cluster falls back to
    // its auto palette slot rather than surrendering the nucleotide.
    const fn = build([
      { id: 'auto', helix_ids: ['h1'], auto_created: true, color: '#00ffcc' },
      { id: 'mine', helix_ids: ['h1'], auto_created: false },
    ])
    expect(fn(nuc('h1', 's1', 0))).toBe(STAPLE_PALETTE[1])
  })

  it('legacy designs infer provenance from the autodetect name prefix', () => {
    const fn = build([
      { id: 'mine', name: 'Cluster 3', helix_ids: ['h1'], color: '#ff00ff' },
      { id: 'auto', name: 'Scaffold Cluster 1', helix_ids: ['h1'], color: '#00ffcc' },
    ])
    expect(fn(nuc('h1', 's1', 0))).toBe(0xff00ff)
  })

  it('between two AUTO clusters the old rules still decide', () => {
    const fn = build([
      { id: 'a', name: 'Scaffold Cluster 1', helix_ids: ['h1'], color: '#ff00ff' },
      { id: 'b', name: 'Geometry Cluster 1', helix_ids: ['h1'] },
    ])
    expect(fn(nuc('h1', 's1', 0))).toBe(0xff00ff)   // explicit beats auto-palette
  })

  it('between two MANUAL clusters the old rules still decide', () => {
    const fn = build([
      { id: 'a', helix_ids: ['h1'], auto_created: false, color: '#ff00ff' },
      { id: 'b', helix_ids: ['h1'], auto_created: false, color: '#00ffcc' },
    ])
    expect(fn(nuc('h1', 's1', 0))).toBe(0x00ffcc)   // later entry wins
  })

  it('an unstyled design still renders identically to the auto palette', () => {
    // The no-regression pin: with no provenance difference and no colours set, the
    // output must match what buildClusterLookup would have produced.
    const design = { strands, cluster_transforms: [
      { id: 'a', helix_ids: ['h1'] }, { id: 'b', helix_ids: ['h2'] },
    ] }
    const fn = buildClusterColorLookup(design)
    const idx = buildClusterLookup(design)
    for (const n of [nuc('h1', 's1', 0), nuc('h2', 's1', 1)]) {
      expect(fn(n)).toBe(STAPLE_PALETTE[idx(n) % STAPLE_PALETTE.length])
    }
  })
})
