import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { extraBasePickEntries, extraBaseAtomEntry, pickEntryKey } from './extra_base_pick.js'
import { junctionFixture } from '../test-helpers/strand_junction_fixture.js'

const strand = { id: 's', strand_type: 'staple', domains: [
  { helix_id: 'a', start_bp: 0, end_bp: 2, direction: 'FORWARD' },
  { helix_id: 'b', start_bp: 2, end_bp: 0, direction: 'REVERSE' },
] }
const design = { strands: [strand], forced_ligations: [{ id: 'fl:1', extra_bases: 'AT',
  three_prime_helix_id: 'a', three_prime_bp: 2, three_prime_direction: 'FORWARD',
  five_prime_helix_id: 'b', five_prime_bp: 2, five_prime_direction: 'REVERSE' }] }

describe('extra-base drill targets', () => {
  it('resolves strand ownership without substituting an anchor base, and uses simulation index', () => {
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial(), 2)
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(1, 2, 3))
    const [entry] = extraBasePickEntries([{ instMesh: mesh, id: 0, xoId: 'fl:1', i: 0, simK: 1 }], design)
    expect(entry.nuc.strand_id).toBe('s')
    expect(pickEntryKey(entry)).toBe('__xb__:fl:1:1')
    expect(entry.pos.toArray()).toEqual([1, 2, 3])
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(4, 5, 6))
    expect(entry.pos.toArray()).toEqual([4, 5, 6])
    expect(extraBasePickEntries([{ instMesh: mesh, id: 0, xoId: 'gone', simK: 0 }], design)).toEqual([])
  })
  it('preserves atomistic extra-base identity and ordinary loop-copy identity', () => {
    const entry = extraBaseAtomEntry({ crossover_id: 'fl:1', extra_base_k: 0 }, design)
    expect(entry.nuc.strand_id).toBe('s')
    expect(pickEntryKey(entry)).toBe('__xb__:fl:1:0')
    expect(extraBaseAtomEntry({ helix_id: 'a', bp_index: 2 }, design)).toBeNull()
    expect(pickEntryKey({ nuc: { helix_id: 'a', bp_index: 2, direction: 'FORWARD' }, _copy: 1 })).toBe('a:2:FORWARD:1')
  })

  it('owns a B→A ordinary crossover and rejects a different receiving endpoint', () => {
    const { design } = junctionFixture()
    expect(extraBaseAtomEntry({ crossover_id: 'xo', extra_base_k: 3 }, design)?.nuc.strand_id).toBe('s')
    design.crossovers[0].half_a.index = 1
    expect(extraBaseAtomEntry({ crossover_id: 'xo', extra_base_k: 3 }, design)).toBeNull()
  })

  it('retains ownership when native ligation merges neighboring domains', () => {
    const { strand, design } = junctionFixture(true)
    strand.domains = [{ helix_id: 'a', start_bp: 0, end_bp: 5, direction: 'FORWARD' }]
    Object.assign(design.forced_ligations[0], {
      five_prime_helix_id: 'a', five_prime_bp: 3, five_prime_direction: 'FORWARD',
    })
    expect(extraBaseAtomEntry({ crossover_id: 'fl:1', extra_base_k: 3 }, design)?.nuc.strand_id).toBe('s')
  })
})
