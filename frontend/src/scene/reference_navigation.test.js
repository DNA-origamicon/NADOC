import { describe, expect, it } from 'vitest'
import {
  navigationDesign,
  navigationGeometry,
  referenceGeometryHidden,
  referenceStrandInteractionHidden,
} from './reference_navigation.js'

const design = {
  helices: [{ id: 'real-h' }, { id: 'ref-h' }, { id: 'shared-h' }],
  strands: [
    { id: 'real', domains: [{ helix_id: 'real-h' }, { helix_id: 'shared-h' }] },
    { id: 'ref', is_reference: true, domains: [{ helix_id: 'ref-h' }, { helix_id: 'shared-h' }] },
  ],
}
const geometry = [
  { strand_id: 'real', backbone_position: [1, 2, 3] },
  { strand_id: 'ref', backbone_position: [100, 200, 300] },
]

describe('reference navigation projection', () => {
  it('treats the Simulation tab as reference-hidden', () => {
    expect(referenceGeometryHidden({ simulationTabActive: true, showReferenceGeometry: true })).toBe(true)
  })

  it('makes only reference strands non-interactive while the Simulation tab is open', () => {
    const state = { currentDesign: design, simulationTabActive: true, showReferenceGeometry: true }
    expect(referenceStrandInteractionHidden(state, 'ref')).toBe(true)
    expect(referenceStrandInteractionHidden(state, 'real')).toBe(false)
    expect(referenceStrandInteractionHidden({ ...state, simulationTabActive: false }, 'ref')).toBe(false)
  })

  it('removes reference nucleotides from navigation bounds only while hidden', () => {
    expect(navigationGeometry({ currentDesign: design, currentGeometry: geometry })).toBe(geometry)
    expect(navigationGeometry({ currentDesign: design, currentGeometry: geometry, simulationTabActive: true }))
      .toEqual([geometry[0]])
  })

  it('removes reference-only axes but retains axes shared with real strands', () => {
    const projected = navigationDesign({ currentDesign: design, simulationTabActive: true })
    expect(projected.helices.map(h => h.id)).toEqual(['real-h', 'shared-h'])
    expect(design.helices).toHaveLength(3)
    expect(navigationDesign({ currentDesign: design, simulationTabActive: true })).toBe(projected)
  })
})
