import { afterEach, describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { store } from '../state/store.js'
import { initOverhangLinkArcs, linkerLengthToBases, resolveLinkerAttachAnchor } from './overhang_link_arcs.js'

describe('overhang ss linker helpers', () => {
  it('converts persisted linker length to rendered base count', () => {
    expect(linkerLengthToBases({ length_value: 12, length_unit: 'bp' })).toBe(12)
    expect(linkerLengthToBases({ length_value: 4.0, length_unit: 'nm' })).toBe(12)
    expect(linkerLengthToBases({ length_value: 0, length_unit: 'bp' })).toBe(0)
  })

  it('anchors to the linker complement nucleotide when geometry contains it', () => {
    const nucs = [
      {
        overhang_id: 'oh_a_5p',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [1, 2, 3],
        is_five_prime: true,
      },
      {
        strand_id: '__lnk__conn1__a',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [9, 8, 7],
      },
    ]

    const anchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')

    expect(anchor.usedLinkerComplement).toBe(true)
    expect(anchor.pos.toArray()).toEqual([9, 8, 7])
  })

  it('falls back to the overhang nucleotide before linker complement geometry exists', () => {
    const nucs = [{
      overhang_id: 'oh_a_5p',
      helix_id: 'oh_helix',
      bp_index: 0,
      backbone_position: [1, 2, 3],
      is_five_prime: true,
    }]

    const anchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')

    expect(anchor.usedLinkerComplement).toBe(false)
    expect(anchor.pos.toArray()).toEqual([1, 2, 3])
  })

  it('ss linker: anchors on the single __s strand instead of __a/__b', () => {
    // Single-strand ss topology (Phase 7): the complement nucleotides live
    // on `__lnk__{conn}__s`, NOT on per-side __a / __b. The anchor lookup
    // must reach them when caller passes linkerType='ss'.
    const nucs = [
      {
        overhang_id: 'oh_a_5p',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [1, 2, 3],
        is_five_prime: true,
      },
      {
        // ss-style strand id — complement on side A's helix at same bp.
        strand_id: '__lnk__conn1__s',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [9, 8, 7],
      },
    ]

    // Default (linkerType='ds') misses the __s strand → falls back to OH nuc.
    const dsAnchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')
    expect(dsAnchor.usedLinkerComplement).toBe(false)
    expect(dsAnchor.pos.toArray()).toEqual([1, 2, 3])

    // Passing linkerType='ss' finds the __s complement.
    const ssAnchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end', 'ss')
    expect(ssAnchor.usedLinkerComplement).toBe(true)
    expect(ssAnchor.pos.toArray()).toEqual([9, 8, 7])
  })
})

// ── Per-cluster colour + opacity ──────────────────────────────────────────────
// A link arc joins two overhangs that may sit in different clusters. Before this
// it honoured neither cluster colour nor cluster opacity (nor the cluster
// visibility toggle), so a faded cluster kept fully-opaque white linkers hanging
// off it.

describe('overhang link arcs — per-cluster display', () => {
  const NUCS = [
    { overhang_id: 'oh_a', helix_id: 'h_a', bp_index: 7, backbone_position: [0, 0, 0], is_five_prime: true },
    { overhang_id: 'oh_b', helix_id: 'h_b', bp_index: 3, backbone_position: [4, 0, 0], is_five_prime: true },
  ]
  const design = (clusters = []) => ({
    strands: [{ id: '__lnk__conn1__s', is_reference: false, domains: [] }],
    overhang_connections: [{
      id: 'conn1', linker_type: 'ss',
      overhang_a_id: 'oh_a', overhang_a_attach: 'free_end',
      overhang_b_id: 'oh_b', overhang_b_attach: 'free_end',
      length_value: 4, length_unit: 'bp',
    }],
    cluster_transforms: clusters,
  })
  const CLUSTERS = (over = {}) => [
    { id: 'cA', helix_ids: ['h_a'], ...over.a },
    { id: 'cB', helix_ids: ['h_b'], ...over.b },
  ]

  function build(d) {
    const scene = new THREE.Scene()
    const arcs = initOverhangLinkArcs(scene)
    arcs.rebuild(d, NUCS)
    return arcs
  }
  /** Every material under the arc group. */
  function mats(arcs) {
    const out = []
    arcs.group.traverse(o => { if (o.material && !Array.isArray(o.material)) out.push(o.material) })
    return out
  }

  afterEach(() => {
    store.setState({
      coloringMode: 'strand', currentDesign: null,
      showReferenceGeometry: true, simulationTabActive: false,
    })
  })

  it('fades a reference linker and hides it while Simulations is active', () => {
    const d = design(CLUSTERS())
    store.setState({ currentDesign: d, showReferenceGeometry: true, simulationTabActive: false })
    const arcs = build(d)
    const base = mats(arcs)[0].opacity
    const reference = {
      ...d,
      strands: d.strands.map(s => ({ ...s, is_reference: true })),
    }

    store.setState({ currentDesign: reference })
    for (const m of mats(arcs)) {
      expect(m.opacity).toBeCloseTo((m.userData.baseOpacity ?? base) * 0.4, 5)
      expect(m.visible).toBe(true)
    }

    store.setState({ simulationTabActive: true })
    for (const m of mats(arcs)) {
      expect(m.opacity).toBe(0)
      expect(m.visible).toBe(false)
      expect(m.depthWrite).toBe(false)
    }

    store.setState({ simulationTabActive: false })
    for (const m of mats(arcs)) expect(m.visible).toBe(true)
  })

  it('renders the connection at full opacity when nothing is faded', () => {
    const arcs = build(design(CLUSTERS()))
    const ms = mats(arcs)
    expect(ms.length).toBeGreaterThan(0)
    // Materials keep their own base opacity (arcs ship at 0.85, slabs at 0.90).
    for (const m of ms) expect(m.opacity).toBeGreaterThan(0.8)
  })

  it('fades to its cluster opacity, MULTIPLYING each material’s base opacity', () => {
    // The arc is already 0.85; a 0.5 cluster must dim it to 0.425, not reset it
    // to a flat 0.5 (which would make the linkers *more* opaque than before).
    const opaque = mats(build(design(CLUSTERS())))
    const faded  = mats(build(design(CLUSTERS({ a: { opacity: 0.5 } }))))
    expect(faded.length).toBe(opaque.length)
    for (let i = 0; i < faded.length; i++) {
      expect(faded[i].opacity).toBeCloseTo(opaque[i].opacity * 0.5, 5)
      expect(faded[i].transparent).toBe(true)
    }
  })

  it('takes the LOWEST of its two anchors’ opacities', () => {
    const both = mats(build(design(CLUSTERS({ a: { opacity: 0.8 }, b: { opacity: 0.3 } }))))
    const only = mats(build(design(CLUSTERS({ a: { opacity: 0.3 } }))))
    expect(both[0].opacity).toBeCloseTo(only[0].opacity, 5)
  })

  it('keeps writing depth — a faded linker still casts the photo key shadow', () => {
    for (const m of mats(build(design(CLUSTERS({ a: { opacity: 0.3 } }))))) {
      expect(m.userData.photoForceDepthWrite).toBe(true)
    }
  })

  it('takes the A-side cluster colour in cluster-coloring mode', () => {
    store.setState({ coloringMode: 'cluster' })
    const arcs = build(design(CLUSTERS({ a: { color: '#ff8800' }, b: { color: '#00ffcc' } })))
    for (const m of mats(arcs)) expect(m.color.getHex()).toBe(0xff8800)
  })

  it('leaves the linker’s own colour alone in other coloring modes', () => {
    store.setState({ coloringMode: 'strand' })
    const arcs = build(design(CLUSTERS({ a: { color: '#ff8800' } })))
    for (const m of mats(arcs)) expect(m.color.getHex()).not.toBe(0xff8800)
  })

  it('…but still fades in other coloring modes', () => {
    store.setState({ coloringMode: 'strand' })
    const faded = mats(build(design(CLUSTERS({ a: { opacity: 0.4 } }))))
    const plain = mats(build(design(CLUSTERS())))
    expect(faded[0].opacity).toBeLessThan(plain[0].opacity)
  })

  it('refreshClusterDisplay repaints without a rebuild', () => {
    const arcs = build(design(CLUSTERS()))
    const before = mats(arcs)[0].opacity
    arcs.refreshClusterDisplay(design(CLUSTERS({ a: { opacity: 0.5 } })))
    expect(mats(arcs)[0].opacity).toBeCloseTo(before * 0.5, 5)
  })

  it('does not compound the fade when refreshed repeatedly', () => {
    // The base opacity is captured once; re-applying 0.5 three times must still
    // land on 0.5×base, not 0.125×base.
    const arcs = build(design(CLUSTERS()))
    const base = mats(arcs)[0].opacity
    for (let i = 0; i < 3; i++) {
      arcs.refreshClusterDisplay(design(CLUSTERS({ a: { opacity: 0.5 } })))
    }
    expect(mats(arcs)[0].opacity).toBeCloseTo(base * 0.5, 5)
  })

  it('restores full opacity when the fade is cleared', () => {
    const arcs = build(design(CLUSTERS()))
    const base = mats(arcs)[0].opacity
    arcs.refreshClusterDisplay(design(CLUSTERS({ a: { opacity: 0.4 } })))
    arcs.refreshClusterDisplay(design(CLUSTERS()))
    expect(mats(arcs)[0].opacity).toBeCloseTo(base, 5)
  })
})
