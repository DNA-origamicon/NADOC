import { describe, it, expect } from 'vitest'
import { adjacentBpFree, oneNtResizableEnd } from './strand_end_resize.js'

describe('adjacentBpFree', () => {
  const stub = { helix_id: 'h0', direction: 'FORWARD', bp_index: 16, strand_id: 'stub' }

  it('blocked when another strand covers the target bp', () => {
    const strands = [{ id: 'x', domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 15, direction: 'FORWARD' }] }]
    expect(adjacentBpFree(stub, strands, false)).toBe(false)  // toward bp 15 → occupied
    expect(adjacentBpFree(stub, strands, true)).toBe(true)    // toward bp 17 → free
  })

  it('ignores the stub’s own strand and other directions/helices', () => {
    const strands = [
      { id: 'stub', domains: [{ helix_id: 'h0', start_bp: 16, end_bp: 16, direction: 'FORWARD' }] },
      { id: 'rev',  domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 15, direction: 'REVERSE' }] },
    ]
    expect(adjacentBpFree(stub, strands, false)).toBe(true)   // REVERSE domain doesn't block FORWARD
  })

  it('handles missing strands', () => {
    expect(adjacentBpFree(stub, undefined, false)).toBe(true)
  })
})

describe('oneNtResizableEnd', () => {
  const fwdStub = { helix_id: 'h0', direction: 'FORWARD', bp_index: 16, strand_id: 'stub' }

  it('picks 3′ when the 5′ side is pinned (FORWARD stub, block at bp-1)', () => {
    const strands = [{ id: 'xo', domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 15, direction: 'FORWARD' }] }]
    expect(oneNtResizableEnd(fwdStub, strands)).toBe('3p')
  })

  it('picks 5′ when the 3′ side is pinned (FORWARD stub, block at bp+1)', () => {
    const strands = [{ id: 'xo', domains: [{ helix_id: 'h0', start_bp: 17, end_bp: 30, direction: 'FORWARD' }] }]
    expect(oneNtResizableEnd(fwdStub, strands)).toBe('5p')
  })

  it('defaults to 5′ when both sides are free', () => {
    expect(oneNtResizableEnd(fwdStub, [])).toBe('5p')
  })

  it('REVERSE stub: 5′ is the high-bp side → block above pins 5′, pick 3′', () => {
    const rev = { helix_id: 'h0', direction: 'REVERSE', bp_index: 16, strand_id: 'stub' }
    const strands = [{ id: 'xo', domains: [{ helix_id: 'h0', start_bp: 17, end_bp: 30, direction: 'REVERSE' }] }]
    expect(oneNtResizableEnd(rev, strands)).toBe('3p')
  })
})

// Regression: the two stubs from workspace/crossover_edge_cases.nadoc that could
// not be resized because the picker defaulted to the crossover-pinned 5′ end.
describe('oneNtResizableEnd — crossover_edge_cases.nadoc stuck stubs', () => {
  it('helix 0 (REVERSE cell → FORWARD staple) stub at bp 16, 5′ pinned by crossover at bp 15 → 3p', () => {
    const stub = { helix_id: 'h_XY_0_1', direction: 'FORWARD', bp_index: 16, strand_id: 'stubA' }
    const strands = [
      { id: 'stubA', domains: [{ helix_id: 'h_XY_0_1', start_bp: 16, end_bp: 16, direction: 'FORWARD' }] },
      // stpl_XY_0_1's first domain occupies h_XY_0_1 FORWARD 0..15 (crossover exits at bp 15)
      { id: 'stpl_XY_0_1', domains: [{ helix_id: 'h_XY_0_1', start_bp: 0, end_bp: 15, direction: 'FORWARD' }] },
    ]
    expect(oneNtResizableEnd(stub, strands)).toBe('3p')
  })

  it('helix 1 (FORWARD cell → REVERSE staple) stub at bp -1, 5′ pinned by crossover at bp 0 → 3p', () => {
    const stub = { helix_id: 'h_XY_0_2', direction: 'REVERSE', bp_index: -1, strand_id: 'stubB' }
    const strands = [
      { id: 'stubB', domains: [{ helix_id: 'h_XY_0_2', start_bp: -1, end_bp: -1, direction: 'REVERSE' }] },
      // stpl_XY_0_1's REVERSE domain occupies h_XY_0_2 15..0 (crossover exits at bp 0)
      { id: 'stpl_XY_0_1', domains: [{ helix_id: 'h_XY_0_2', start_bp: 15, end_bp: 0, direction: 'REVERSE' }] },
    ]
    expect(oneNtResizableEnd(stub, strands)).toBe('3p')
  })
})
