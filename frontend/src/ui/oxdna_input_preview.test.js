import { describe, expect, it } from 'vitest'
import { activeDesignGeometry, buildOxdnaInputPreview, nadocToOxdnaFrames, oxdnaFramesToNadoc } from './oxdna_input_preview.js'

const geometry = [
  { helix_id: 'h0', bp_index: 10, direction: 'FORWARD', copy: 0, strand_id: 's0', domain_index: 0,
    backbone_position: [1, 2, 3], base_normal: [2, 0, 0], axis_tangent: [0, 0, 4], nucleobase: 'A' },
  { helix_id: 'h0', bp_index: 11, direction: 'FORWARD', copy: 0, strand_id: 's0', domain_index: 0,
    backbone_position: [1, 2, 3.34], base_normal: [0, 2, 0], axis_tangent: [0, 0, 4] },
  { helix_id: 'h0', bp_index: 10, direction: 'REVERSE', copy: 0, strand_id: 's1', domain_index: 0,
    backbone_position: [-1, 2, 3], base_normal: [-2, 0, 0], axis_tangent: [0, 0, 4] },
]

describe('oxDNA input preview mapping', () => {
  it('maps r/a1/a3 with oxDNA strand orientation and nucleotide topology', () => {
    const preview = buildOxdnaInputPreview(geometry)
    expect(preview.points).toEqual([
      { x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: 3.34 }, { x: -1, y: 2, z: 3 },
    ])
    expect(preview.frames[0].a1).toEqual([1, 0, 0])
    expect(preview.frames[0].a3).toEqual([0, 0, 1])
    expect(preview.frames[0].nucleobase).toBe('A')
    expect(preview.frames[2].a3).toEqual([0, 0, -1])
    expect(preview.edges).toEqual([[0, 1]])
  })

  it('round trips oxDNA frames back to NADOC position and orientation', () => {
    const decoded = oxdnaFramesToNadoc(nadocToOxdnaFrames(geometry))
    expect(decoded).toHaveLength(geometry.length)
    decoded.forEach((row, i) => {
      expect(row.backbone_position).toEqual(geometry[i].backbone_position)
      expect(row.base_normal).toEqual(geometry[i].base_normal.map(v => v / 2))
      expect(row.axis_tangent).toEqual([0, 0, 1])
      expect(row.direction).toBe(geometry[i].direction)
    })
  })

  it('rejects incomplete rigid frames rather than misaligning particle indices', () => {
    expect(nadocToOxdnaFrames([{ backbone_position: [0, 0, 0] }])).toEqual([])
    expect(buildOxdnaInputPreview(null)).toEqual({ frames: [], points: [], edges: [] })
  })

  it('excludes inactive reference strands from simulation representations', () => {
    const mixed = [...geometry, { ...geometry[0], strand_id: 'reference', bp_index: 99 }]
    const design = { strands: [{ id: 's0' }, { id: 's1' }, { id: 'reference', is_reference: true }] }
    expect(activeDesignGeometry(mixed, design)).toEqual(geometry)
    expect(activeDesignGeometry(mixed, design, false)).toEqual(mixed)
    expect(activeDesignGeometry(mixed, null)).toEqual(mixed)
  })
})
