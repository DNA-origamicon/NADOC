import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  computeInstanceBluntEnds,
  _tipAtBpMax,
  _overhangJunctionBps,
  _coverageByHelixAndDirection,
  _strandTerminusBps,
} from './blunt_end_connectors.js'

const RISE = 0.334
const I4 = new THREE.Matrix4()

// Straight helix along +z at (x, 0), spanning bp_start … bp_start+len-1.
function helix(id, bpStart, len, x = 0) {
  return {
    id,
    bp_start: bpStart,
    axis_start: { x, y: 0, z: bpStart * RISE },
    axis_end:   { x, y: 0, z: (bpStart + len - 1) * RISE },
  }
}
function axis(h, extra = {}) {
  return {
    start: [h.axis_start.x, h.axis_start.y, h.axis_start.z],
    end:   [h.axis_end.x,   h.axis_end.y,   h.axis_end.z],
    ...extra,
  }
}
function dom(helixId, startBp, endBp, direction = 'forward', extra = {}) {
  return { helix_id: helixId, start_bp: startBp, end_bp: endBp, direction, overhang_id: null, ...extra }
}
const labels = res => res.map(r => r.label)
const byLabel = (res, label) => res.find(r => r.label === label)

describe('_tipAtBpMax — walks ovhg_axes `end` back off the extent convention', () => {
  it('returns the bp_max base position, one rise short of `end`', () => {
    // Domain bp 10..14 on a helix whose bases sit at z = bp*RISE.
    // Backend emits end = position of bp 15 (extent), not bp 14.
    const s = new THREE.Vector3(0, 0, 10 * RISE)
    const e = new THREE.Vector3(0, 0, 15 * RISE)
    const tip = _tipAtBpMax(s, e, 10, 14)
    expect(tip.z).toBeCloseTo(14 * RISE, 6)
    expect(tip.z).not.toBeCloseTo(e.z, 3)
  })

  it('collapses a single-base domain onto start', () => {
    const s = new THREE.Vector3(0, 0, 1)
    const e = new THREE.Vector3(0, 0, 1 + RISE)
    expect(_tipAtBpMax(s, e, 7, 7).z).toBeCloseTo(1, 6)  // no divide-by-zero
  })

  it('is exact for a 2-base domain (midpoint)', () => {
    const s = new THREE.Vector3(0, 0, 0)
    const e = new THREE.Vector3(0, 0, 2)
    expect(_tipAtBpMax(s, e, 3, 4).z).toBeCloseTo(1, 6)
  })
})

describe('_overhangJunctionBps — the overhang-side foot of each overhang↔main crossover', () => {
  it("takes the overhang domain's start_bp when the strand runs main → overhang (3')", () => {
    const strands = [{ domains: [dom('h_main', 5, 10), dom('h_stub', 10, 14, 'forward', { overhang_id: 'o1' })] }]
    expect([..._overhangJunctionBps(strands)]).toEqual(['h_stub:10'])
  })

  it("takes the overhang domain's end_bp when the strand runs overhang → main (5')", () => {
    const strands = [{ domains: [dom('h_stub', 10, 14, 'forward', { overhang_id: 'o1' }), dom('h_main', 10, 20)] }]
    expect([..._overhangJunctionBps(strands)]).toEqual(['h_stub:14'])
  })

  it('ignores shared-inline overhangs (same helix — no stub root exists)', () => {
    const strands = [{ domains: [dom('h_a', 0, 9), dom('h_a', 10, 14, 'forward', { overhang_id: 'o1' })] }]
    expect(_overhangJunctionBps(strands).size).toBe(0)
  })

  it('ignores plain crossovers between two non-overhang domains', () => {
    const strands = [{ domains: [dom('h_a', 0, 9), dom('h_b', 9, 20)] }]
    expect(_overhangJunctionBps(strands).size).toBe(0)
  })
})

describe('_strandTerminusBps — real free DNA ends', () => {
  it("collects both the strand's 5' start and its 3' end", () => {
    const strands = [{ domains: [dom('h_a', 5, 9), dom('h_b', 9, 20)] }]
    expect([..._strandTerminusBps(strands)].sort()).toEqual(['h_a:5', 'h_b:20'])
  })

  it('reads a REVERSE terminal domain by its own start_bp, not min/max', () => {
    const strands = [{ domains: [dom('h_s', 55, 40, 'reverse', { overhang_id: 'o1' }), dom('h_m', 40, 47)] }]
    expect(_strandTerminusBps(strands).has('h_s:55')).toBe(true)
  })
})

describe('computeInstanceBluntEnds — stub shared by two antiparallel overhangs', () => {
  // 2x2_OH_test's h_XY_2_0: two staples both 5'-end on one stub, running
  // opposite ways, each crossing off where the other begins.  So bp 40 and bp
  // 55 are each simultaneously one staple's crossover foot and the other's
  // free tip — and a tip must never be suppressed as a foot.
  const hStub = helix('h_s', 40, 16, 2.5)
  const hM1   = helix('h_m1', 0, 60, 0)
  const hM2   = helix('h_m2', 0, 60, 5.0)
  const design = {
    helices: [hStub, hM1, hM2],
    strands: [
      { domains: [dom('h_s', 55, 40, 'reverse', { overhang_id: 'oA' }), dom('h_m1', 40, 47)] },
      { domains: [dom('h_s', 40, 55, 'forward', { overhang_id: 'oB' }), dom('h_m2', 39, 32, 'reverse')] },
    ],
  }
  const axes = { h_s: axis(hStub), h_m1: axis(hM1), h_m2: axis(hM2) }
  const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')

  it('keeps BOTH stub ends — each is a free 5\' tip', () => {
    expect(labels(res)).toEqual(expect.arrayContaining(['blunt:h_s:start', 'blunt:h_s:end']))
  })
})

describe('_coverageByHelixAndDirection — polarity-aware coverage', () => {
  it('keeps antiparallel domains on the same helix in separate sets', () => {
    const strands = [
      { domains: [dom('h_a', 5, 9, 'forward')] },
      { domains: [dom('h_a', 0, 14, 'reverse')] },
    ]
    const cov = _coverageByHelixAndDirection(strands)
    expect(cov.get('h_a:forward').has(4)).toBe(false)
    expect(cov.get('h_a:reverse').has(4)).toBe(true)
  })
})

describe('computeInstanceBluntEnds — extrude stub root is not a blunt end', () => {
  // h_stub is extruded off h_main at bp 10, into the neighbouring lattice cell
  // (x = 2.5 nm).  Its root touches no other helix ENDPOINT, so the old
  // free-endpoint test called both of its ends free.
  const hMain = helix('h_main', 0, 20, 0)
  const hStub = helix('h_stub', 10, 5, 2.5)
  const design = {
    helices: [hMain, hStub],
    strands: [{
      domains: [
        dom('h_main', 5, 10),
        dom('h_stub', 10, 14, 'forward', { overhang_id: 'ovhg_1' }),
      ],
    }],
  }
  const axes = { h_main: axis(hMain), h_stub: axis(hStub) }
  const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')

  it('drops the spurious connector at the stub root', () => {
    expect(labels(res)).not.toContain('blunt:h_stub:start')
  })

  it('keeps the connector at the stub free tip', () => {
    expect(labels(res)).toContain('blunt:h_stub:end')
  })

  it('still emits the junction connector on the main helix', () => {
    expect(labels(res)).toContain('blunt:h_main:bp10')
  })

  it("leaves the main helix's own two ends alone", () => {
    expect(labels(res)).toEqual(expect.arrayContaining(['blunt:h_main:start', 'blunt:h_main:end']))
  })
})

describe('computeInstanceBluntEnds — connector sits on bp_max, not one rise past it', () => {
  const hStub = helix('h_stub', 10, 5, 2.5)
  const design = { helices: [hStub], strands: [] }
  // Backend convention: start = position of bp_min, end = position of bp_max+1.
  const axes = {
    h_stub: axis(hStub, {
      ovhgAxes: {
        ovhg_1: { bp_min: 10, bp_max: 14, start: [2.5, 0, 10 * RISE], end: [2.5, 0, 15 * RISE] },
      },
    }),
  }
  const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')

  it('places the tip on the terminal base', () => {
    const tip = byLabel(res, 'blunt:h_stub:end')
    expect(tip).toBeTruthy()
    expect(tip.localPos[2]).toBeCloseTo(14 * RISE, 5)
    // the old code used `end` verbatim — a full rise too far out
    expect(Math.abs(tip.localPos[2] - 15 * RISE)).toBeGreaterThan(0.3)
  })
})

describe('computeInstanceBluntEnds — normals on a stub patched by two different domains', () => {
  // Stub carries two overhang domains rotated in different directions.  Both
  // stub endpoints get overwritten with per-domain rotated positions, so
  // `end - start` is the line between two unrelated domains, not an axis.
  const hStub = helix('h_stub', 10, 5, 0)
  const design = { helices: [hStub], strands: [] }
  const axes = {
    h_stub: axis(hStub, {
      ovhgAxes: {
        // bp 10..11, rotated to lie along +x
        ovhg_lo: { bp_min: 10, bp_max: 11, start: [1, 0, 0], end: [3, 0, 0] },
        // bp 13..14, rotated to lie along +z, far away
        ovhg_hi: { bp_min: 13, bp_max: 14, start: [0, 0, 3], end: [0, 0, 5] },
      },
    }),
  }
  const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')

  it('takes the start normal from the domain that positioned it (-x, outward at bp_min)', () => {
    const n = byLabel(res, 'blunt:h_stub:start').localNorm
    expect(n[0]).toBeCloseTo(-1, 5)
    expect(n[2]).toBeCloseTo(0, 5)
  })

  it('takes the end normal from its own domain (+z, outward at bp_max)', () => {
    const n = byLabel(res, 'blunt:h_stub:end').localNorm
    expect(n[2]).toBeCloseTo(1, 5)
    expect(n[0]).toBeCloseTo(0, 5)
  })

  it('positions each end on its own domain, tip walked back off the extent', () => {
    expect(byLabel(res, 'blunt:h_stub:start').localPos).toEqual([1, 0, 0])
    const hi = byLabel(res, 'blunt:h_stub:end').localPos
    expect(hi[2]).toBeCloseTo(4, 5)   // bp14 = lerp([0,0,3],[0,0,5], 1/2)
  })
})

describe('computeInstanceBluntEnds — overlapping overhangs do not steal each other\'s position', () => {
  // Two overhangs occupying the SAME bp range on one helix, rotated apart.
  // Keyed by bp alone, the second silently overwrote the first.
  const h = helix('h_c', 0, 20, 0)
  const design = {
    helices: [h],
    strands: [{ domains: [dom('h_c', 5, 9, 'forward', { overhang_id: 'ovhg_A' })] }],
  }
  const axes = {
    h_c: axis(h, {
      ovhgAxes: {
        ovhg_A: { bp_min: 5, bp_max: 9, start: [10, 0, 0], end: [10, 0, 5 * RISE] },
        ovhg_B: { bp_min: 5, bp_max: 9, start: [-10, 0, 0], end: [-10, 0, 5 * RISE] },
      },
    }),
  }
  const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')

  it("resolves the terminus to its own overhang's rotated axis", () => {
    const c = byLabel(res, 'blunt:h_c:bp5')
    expect(c).toBeTruthy()
    expect(c.localPos[0]).toBeCloseTo(10, 5)    // ovhg_A's shaft…
    expect(c.localPos[0]).not.toBeCloseTo(-10, 1)  // …not ovhg_B's
  })
})

describe('computeInstanceBluntEnds — nick suppression no longer eats real termini', () => {
  it('does not let an antiparallel domain suppress a free strand end', () => {
    // A forward staple starting at bp 5, with a reverse domain covering 0..14
    // beneath it.  Helix-wide coverage made bp 4 and bp 6 both look "covered".
    const h = helix('h_n', 0, 20, 0)
    const design = {
      helices: [h],
      strands: [
        { domains: [dom('h_n', 5, 9, 'forward')] },
        { domains: [dom('h_n', 0, 14, 'reverse')] },
      ],
    }
    const res = computeInstanceBluntEnds(design, { h_n: axis(h) }, I4, 'i1', 'Part')
    expect(labels(res)).toContain('blunt:h_n:bp5')
  })

  it('keeps the free tip of an overhang that abuts the next overhang on the same stub', () => {
    // Stub carrying two contiguous overhang domains (40..55, 56..71) — the
    // pattern in Voltron_Core_Arm_V6 / Hinge.  The 5' tip at bp 56 is flanked
    // by overhang A's body at 55 and its own at 57.
    const hStub = helix('h_s', 40, 32, 2.5)
    const hMain = helix('h_main', 40, 32, 0)
    const design = {
      helices: [hStub, hMain],
      strands: [
        { domains: [dom('h_s', 40, 55, 'forward', { overhang_id: 'ovhg_A' }), dom('h_main', 55, 60)] },
        { domains: [dom('h_s', 56, 71, 'forward', { overhang_id: 'ovhg_B' }), dom('h_main', 61, 66)] },
      ],
    }
    const axes = { h_s: axis(hStub), h_main: axis(hMain) }
    const res = computeInstanceBluntEnds(design, axes, I4, 'i1', 'Part')
    expect(labels(res)).toContain('blunt:h_s:bp56')
  })

  it('still suppresses a genuine same-polarity internal nick', () => {
    // Two forward staples butting up against each other at bp 9/10 — the nick
    // rule exists for exactly this, and must keep firing.
    const h = helix('h_k', 0, 20, 0)
    const design = {
      helices: [h],
      strands: [
        { domains: [dom('h_k', 0, 9, 'forward')] },
        { domains: [dom('h_k', 10, 19, 'forward')] },
      ],
    }
    const res = computeInstanceBluntEnds(design, { h_k: axis(h) }, I4, 'i1', 'Part')
    // bp 9 is flanked by 8 (own body) and 10 (next staple) → internal nick
    expect(labels(res)).not.toContain('blunt:h_k:bp9')
  })
})

describe('computeInstanceBluntEnds — degenerate input', () => {
  it('returns [] with no helices', () => {
    expect(computeInstanceBluntEnds({ helices: [] }, {}, I4, 'i1', 'P')).toEqual([])
    expect(computeInstanceBluntEnds(null, null, I4, 'i1', 'P')).toEqual([])
  })

  it('falls back to model axes when helix_axes is empty', () => {
    const h = helix('h_a', 0, 10, 0)
    const res = computeInstanceBluntEnds({ helices: [h], strands: [] }, {}, I4, 'i1', 'P')
    expect(labels(res).sort()).toEqual(['blunt:h_a:end', 'blunt:h_a:start'])
  })

  it('applies the instance world matrix to positions and normals', () => {
    const h = helix('h_a', 0, 10, 0)
    const m = new THREE.Matrix4().makeTranslation(5, 0, 0)
    const res = computeInstanceBluntEnds({ helices: [h], strands: [] }, {}, m, 'i1', 'P')
    const s = byLabel(res, 'blunt:h_a:start')
    expect(s.worldPos[0]).toBeCloseTo(5, 6)
    expect(s.localPos[0]).toBeCloseTo(0, 6)
    expect(s.worldNorm[2]).toBeCloseTo(-1, 6)  // translation leaves normals alone
  })
})
