import { describe, expect, it } from 'vitest'
import { crossoverDragEndpoints, crossoverDragFits } from './crossover_drag.js'

const domain = (start_bp, end_bp, helix_id = 'a') => ({ start_bp, end_bp, helix_id, direction: 'FORWARD' })

describe('joint crossover drag occupancy', () => {
  it('moves both ends of a shared domain and vacates the other selected domains', () => {
    const left = domain(0, 4), bridge = domain(4, 5, 'b'), right = domain(5, 150)
    const group = [{ d0: left, d1: bridge }, { d0: bridge, d1: right }]
    const edits = crossoverDragEndpoints(group)
    expect(crossoverDragFits([{ domains: [left, bridge, right] }], edits, 123)).toBe(true)
    expect(edits.get(bridge)).toEqual({ start: true, end: true })
  })

  it('rejects collisions in the final positions, including between selected domains', () => {
    const a = domain(0, 4), b = domain(4, 10, 'b')
    const c = domain(20, 25), d = domain(25, 30, 'b')
    const edits = crossoverDragEndpoints([{ d0: a, d1: b }, { d0: c, d1: d }])
    expect(crossoverDragFits([{ domains: [a, b, c, d] }], edits, 21)).toBe(false)
    expect(crossoverDragFits([{ domains: [a, b, domain(15, 20)] }], crossoverDragEndpoints([{ d0: a, d1: b }]), 21)).toBe(false)
  })

  it('handles any number of selected crossovers on independent tracks', () => {
    const group = Array.from({ length: 20 }, (_, i) => ({
      d0: domain(0, 4, `a${i}`), d1: domain(4, 150, `b${i}`),
    }))
    expect(crossoverDragFits([{ domains: group.flatMap(g => [g.d0, g.d1]) }], crossoverDragEndpoints(group), 123)).toBe(true)
  })
  it('ignores nonphysical reference overlays and preserves independent directions', () => {
    const a = domain(0, 4), b = domain(4, 150, 'b')
    const strands = [
      { domains: [a, b, { ...domain(0, 150), direction: 'REVERSE' }] },
      { is_reference: true, domains: [domain(0, 150)] },
    ]
    expect(crossoverDragFits(strands, crossoverDragEndpoints([{ d0: a, d1: b }]), 11)).toBe(true)
  })

})
