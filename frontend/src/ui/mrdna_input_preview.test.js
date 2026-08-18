import { describe, expect, it } from 'vitest'
import { buildMrdnaInputPreview } from './mrdna_input_preview.js'

const geometry = Array.from({ length: 12 }, (_, bp) => ({
  helix_id: 'h1', bp_index: bp, strand_id: 'scaffold', direction: 'FORWARD',
  axis_position: [0, 0, bp * 0.34],
}))

describe('mrDNA input preview', () => {
  it('builds a fine site for every base pair before simulation', () => {
    const preview = buildMrdnaInputPreview(geometry, 'fine')
    expect(preview.points).toHaveLength(12)
    expect(preview.edges).toHaveLength(11)
    expect(preview.points[2]).toEqual({ x: 0, y: 0, z: 0.68 })
  })

  it('builds the mrDNA-style coarse abstraction at five base pairs per bead', () => {
    const preview = buildMrdnaInputPreview(geometry, 'coarse')
    expect(preview.points).toHaveLength(3)
    expect(preview.edges).toEqual([[0, 1], [1, 2]])
    expect(preview.points[0].z).toBeCloseTo(0.68)
  })

  it('starts coarse five-base-pair groups at the design span rather than a global modulus', () => {
    const shifted = geometry.slice(0, 6).map(nucleotide => ({
      ...nucleotide, bp_index: nucleotide.bp_index + 7,
    }))
    const preview = buildMrdnaInputPreview(shifted, 'coarse')
    expect(preview.points).toHaveLength(2)
    expect(preview.points[0].z).toBeCloseTo(0.68)
  })

  it('averages paired nucleotide coordinates into one fine base-pair site', () => {
    const preview = buildMrdnaInputPreview([
      { helix_id: 'h', bp_index: 4, strand_id: 'a', backbone_position: [-1, 0, 2] },
      { helix_id: 'h', bp_index: 4, strand_id: 'b', backbone_position: [1, 0, 2] },
    ], 'fine')
    expect(preview.points).toEqual([{ x: 0, y: 0, z: 2 }])
  })
})
