import { describe, it, expect } from 'vitest'
import { expandStampFrames, stampTopologyMatches } from './atomistic_stamp.js'

// Two nucleotides, 2 rigid atoms each, plus one non-rigid atom (serial 4).
// nuc 0: identity frame at origin (0,0,0); nuc 1: 90° rot about z, origin (10,0,0).
const IDENT = [
  0, 0, 0, /*R*/ 1, 0, 0, 0, 1, 0, 0, 0, 1,     // nuc 0
  10, 0, 0, /*R = Rz(90°)*/ 0, -1, 0, 1, 0, 0, 0, 0, 1, // nuc 1
]

const descriptor = {
  topology_hash: 'h1',
  n_atoms: 5,
  //          s0   s1   s2   s3   s4(non-rigid)
  atom_nuc: [ 0,   0,   1,   1,   -1 ],
  atom_local: [
    1, 0, 0,   // s0 local (1,0,0)
    0, 2, 0,   // s1 local (0,2,0)
    1, 0, 0,   // s2 local (1,0,0)
    0, 0, 3,   // s3 local (0,0,3)
    0, 0, 0,   // s4 unused
  ],
  nonrigid_serials: [4],
}

const framePayload = {
  ready: true,
  topology_hash: 'h1',
  frames: IDENT,
  nonrigid_xyz: [7, 8, 9],   // s4 world
}

describe('expandStampFrames', () => {
  it('stamps rigid atoms as origin + R·local and copies non-rigid through', () => {
    const out = expandStampFrames(descriptor, framePayload)
    expect(out).toBeInstanceOf(Float32Array)
    expect(out.length).toBe(5 * 3)

    // s0: identity, local (1,0,0) → (1,0,0)
    expect([out[0], out[1], out[2]]).toEqual([1, 0, 0])
    // s1: identity, local (0,2,0) → (0,2,0)
    expect([out[3], out[4], out[5]]).toEqual([0, 2, 0])
    // s2: nuc1 Rz(90°) at (10,0,0), local (1,0,0) → R·(1,0,0)=(0,1,0) + origin → (10,1,0)
    expect([out[6], out[7], out[8]]).toEqual([10, 1, 0])
    // s3: nuc1, local (0,0,3) → R·(0,0,3)=(0,0,3) + origin → (10,0,3)
    expect([out[9], out[10], out[11]]).toEqual([10, 0, 3])
    // s4: non-rigid, straight through
    expect([out[12], out[13], out[14]]).toEqual([7, 8, 9])
  })

  it('returns null on missing or not-ready input', () => {
    expect(expandStampFrames(null, framePayload)).toBeNull()
    expect(expandStampFrames(descriptor, null)).toBeNull()
    expect(expandStampFrames(descriptor, { ...framePayload, ready: false })).toBeNull()
    expect(expandStampFrames({ atom_nuc: null }, framePayload)).toBeNull()
  })

  it('leaves atoms untouched (0,0,0) when a rigid atom maps to no frame gracefully', () => {
    // atom_nuc index -1 (non-rigid but not in nonrigid list) → stays zero.
    const d = { ...descriptor, atom_nuc: [-1, 0, 1, 1, -1], nonrigid_serials: [4] }
    const out = expandStampFrames(d, framePayload)
    expect([out[0], out[1], out[2]]).toEqual([0, 0, 0])
  })
})

describe('stampTopologyMatches', () => {
  it('matches equal topology hashes and rejects mismatches', () => {
    expect(stampTopologyMatches(descriptor, framePayload)).toBe(true)
    expect(stampTopologyMatches(descriptor, { ...framePayload, topology_hash: 'other' })).toBe(false)
    expect(stampTopologyMatches(null, framePayload)).toBe(false)
  })
})
