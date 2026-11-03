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

describe('hidden content navigation', () => {
  const helix = (id, x, length) => ({ id, bp_start: 0, length_bp: length,
    axis_start: { x, y: 0, z: 0 }, axis_end: { x, y: 0, z: length - 1 } })
  const d = { helices: [helix('core', 10, 3), helix('arm', 0, 100)], strands: [] }
  const g = d.helices.flatMap(h => Array.from({ length: h.length_bp }, (_, bp) => ({
    helix_id: h.id, strand_id: h.id, strand_type: 'scaffold', domain_index: 0,
    bp_index: bp, direction: 'FORWARD', backbone_position: [h.axis_start.x, 0, bp],
  })))
  const state = { currentDesign: d, currentGeometry: g }
  const hidden = new Set(g.filter(n => n.helix_id === 'arm').map(n => `arm:${n.bp_index}:FORWARD`))

  it('excludes a hidden arm from fit geometry and orbit/zoom axes, without mutating topology', () => {
    expect(navigationGeometry(state, hidden)).toEqual(g.slice(0, 3))
    expect(navigationDesign(state, hidden).helices.map(h => h.id)).toEqual(['core'])
    expect(d.helices).toHaveLength(2)
  })

  it('trims hidden ends and gaps on a shared helix rather than retaining its full axis', () => {
    const keys = new Set(hidden)
    for (const bp of [20, 21, 30, 31]) keys.delete(`arm:${bp}:FORWARD`)
    expect(navigationDesign(state, keys).helices.filter(h => h.id === 'arm')
      .map(h => [h.axis_start.z, h.axis_end.z])).toEqual([[20, 21], [30, 31]])
  })

  it('invalidates cached navigation immediately when visibility changes', () => {
    const first = navigationDesign(state, hidden)
    expect(navigationDesign(state, hidden)).toBe(first)
    const shown = new Set(hidden); shown.delete('arm:99:FORWARD')
    expect(navigationDesign(state, shown).helices.at(-1).axis_end.z).toBe(99)
    expect(navigationDesign(state, new Set())).toBe(d)
    expect(navigationDesign({ ...state, currentGeometry: [] }, hidden).helices).toEqual([])
  })

  it('combines reference and staple hiding with explicit base hides', () => {
    const next = { currentDesign: { ...d, strands: [{ id: 'arm', is_reference: true }] },
      currentGeometry: g.map(n => ({ ...n, strand_type: n.helix_id === 'core' ? 'staple' : 'scaffold' })),
      showReferenceGeometry: false, staplesHidden: true }
    expect(navigationGeometry(next)).toEqual([])
    expect(navigationDesign(next).helices).toEqual([])
  })
})
