import { expect, it } from 'vitest'
import { decodeAssemblyGeometry, expandCompactNucleotides } from './geometry_codec.js'

const compact = () => ({ h1: { FORWARD: { bp: [7, 8], bb: [[1, 2, 3], [4, 5, 6]],
  bs: [[2, 3, 4], [5, 6, 7]], bn: [[1, 0, 0], [1, 0, 0]], at: [[0, 0, 1], [0, 0, 1]],
  sid: ['s1', 's1'], stype: ['SCAFFOLD', 'SCAFFOLD'], is5: [true, false], is3: [false, true],
  did: [2, 2], base: ['A', 'T'], ohid: ['oh1', null], extid: ['ext1', null],
  ismod: [true, false], mod: ['biotin', null] } } })

it('preserves scientific coordinates, ownership, ends and modification metadata without input mutation', () => {
  const source = compact()
  const before = JSON.stringify(source)
  const result = expandCompactNucleotides(source)
  expect(result).toHaveLength(2)
  expect(result[0]).toEqual({ helix_id: 'h1', bp_index: 7, direction: 'FORWARD',
    backbone_position: [1, 2, 3], base_position: [2, 3, 4], base_normal: [1, 0, 0], axis_tangent: [0, 0, 1],
    strand_id: 's1', strand_type: 'SCAFFOLD', is_five_prime: true, is_three_prime: false,
    domain_index: 2, overhang_id: 'oh1', extension_id: 'ext1', is_modification: true,
    modification: 'biotin', nucleobase: 'A' })
  expect(result[1].is_three_prime).toBe(true)
  expect(result[0].backbone_position).toBe(source.h1.FORWARD.bb[0])
  expect(JSON.stringify(source)).toBe(before)
})

it('decodes each assembly source once and retains reference sharing across instances', () => {
  const design = { id: 'd1' }
  const axes = { h1: { start: [0, 0, 0], end: [0, 0, 1] } }
  const result = decodeAssemblyGeometry({ sources: { shared: { nucleotides_compact: compact(), design, helix_axes: axes } },
    instances: { a: 'shared', b: 'shared', missing: 'unknown', failed: 'shared' }, errors: { failed: 'unavailable' } })
  expect(result.instances.a.nucleotides).toBe(result.instances.b.nucleotides)
  expect(result.instances.a.design).toBe(design)
  expect(result.instances.b.helix_axes).toBe(axes)
  expect(result.instances.missing).toEqual({ error: 'unknown source key unknown' })
  expect(result.instances.failed).toEqual({ error: 'unavailable' })
})

it('preserves legacy arrays and defaults sparse optional metadata', () => {
  const legacy = { instances: {} }
  expect(decodeAssemblyGeometry(legacy)).toBe(legacy)
  expect(decodeAssemblyGeometry(null)).toBeNull()
  const source = compact(); delete source.h1.FORWARD.sid; delete source.h1.FORWARD.did
  expect(expandCompactNucleotides(source)[0]).toMatchObject({ strand_id: null, domain_index: 0 })
  expect(expandCompactNucleotides(null)).toEqual([])
})
