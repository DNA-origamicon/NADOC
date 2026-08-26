import { describe, expect, it } from 'vitest'

import {
  buildExtraBaseClusterGroup,
  buildExtraBaseComparisonGroup,
  buildExtraBaseSampleGroup,
} from './extra_base_cluster_viewer.js'

const cluster = {
  center_A: [0, 1, -5],
  spread_A: 2.1,
  medoid: {
    frame: 220,
    interhelix_A: 25,
    atoms_A: {
      P: [-3, -2, -7],
      "C5'": [-1, -1, -6],
      "C3'": [0, 0, -5.5],
      "C1'": [1, 1, -5],
      base: [3, 1.5, -5],
    },
    base_orientation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    atomistic: {
      atoms: [
        { name: "C1'", element: 'C', position_A: [1, 1, -5], coordinate_source: 'measured' },
        { name: "C2'", element: 'C', position_A: [0.5, 0.2, -5], coordinate_source: 'rigid_template_fit' },
        { name: "C3'", element: 'C', position_A: [0, 0, -5.5], coordinate_source: 'measured' },
        { name: "C4'", element: 'C', position_A: [-0.2, 0.8, -5.2], coordinate_source: 'rigid_template_fit' },
        { name: "O4'", element: 'O', position_A: [0.5, 1.2, -5.1], coordinate_source: 'rigid_template_fit' },
      ],
      bonds: [["C1'", "C2'"], ["C2'", "C3'"], ["C3'", "C4'"], ["C4'", "O4'"], ["O4'", "C1'"]],
      ribose_ring: ["C1'", "C2'", "C3'", "C4'", "O4'"],
    },
  },
}

describe('extra-base cluster medoid scene', () => {
  it('shows the paired helices, active HJ level, nucleotide and spread', () => {
    const group = buildExtraBaseClusterGroup(cluster, 'i')
    expect(group.getObjectByName('helix-0')).not.toBeNull()
    expect(group.getObjectByName('helix-1')).not.toBeNull()
    expect(group.getObjectByName('crossover-i')).not.toBeNull()
    expect(group.getObjectByName("extra-base-C1'")).not.toBeNull()
    expect(group.getObjectByName('extra-base-ring')).not.toBeNull()
    expect(group.getObjectByName('cluster-position-spread')).not.toBeNull()
    expect(group.getObjectByName('helix-pair-frame-axes')).not.toBeNull()
    expect(group.userData).toMatchObject({ side: 'i', spacing_A: 25, medoidFrame: 220 })
  })

  it('renders the fitted deoxyribose ring in atomistic mode', () => {
    const group = buildExtraBaseClusterGroup(cluster, 'i+1', 'atomistic')
    for (const name of ["C1'", "C2'", "C3'", "C4'", "O4'"]) {
      expect(group.getObjectByName(`atomistic-${name}`)?.userData.ribose).toBe(true)
    }
    expect(group.getObjectByName("atomistic-bond-C4'-O4'")).not.toBeNull()
    expect(group.userData.representation).toBe('atomistic')
    expect(group.getObjectByName('extra-base-ring')).toBeUndefined()
  })

  it('places i and i+1 medoids together without realigning their coordinates', () => {
    const shifted = structuredClone(cluster)
    shifted.medoid.frame = 440
    shifted.medoid.atoms_A["C1'"] = [4, 5, -5]
    shifted.medoid.atomistic.atoms.forEach(atom => { atom.position_A[0] += 3; atom.position_A[1] += 4 })
    const group = buildExtraBaseComparisonGroup(cluster, shifted, 'atomistic')
    expect(group.getObjectByName("atomistic-i-C1'")?.position.toArray()).toEqual([1, 1, -5])
    expect(group.getObjectByName("atomistic-i+1-C1'")?.position.toArray()).toEqual([4, 5, -5])
    expect(group.getObjectByName('cluster-position-spread-i')).not.toBeUndefined()
    expect(group.getObjectByName('cluster-position-spread-i+1')).not.toBeUndefined()
    expect(group.userData).toMatchObject({
      representation: 'atomistic',
      c1Separation_A: 5,
      medoidFrames: [220, 440],
    })
  })

  it('renders actual sampled reciprocal poses and their directed normals together', () => {
    const lower = { ...structuredClone(cluster.medoid), side: 'i', frame: 220,
      crossover_id: 'lower-xo', insert_k: 0 }
    const upper = { ...structuredClone(cluster.medoid), side: 'i+1', frame: 220,
      crossover_id: 'upper-xo', insert_k: 0 }
    upper.atoms_A["C1'"] = [4, 5, -5]
    const group = buildExtraBaseSampleGroup([lower, upper])
    expect(group.getObjectByName("sample-i-lower-xo-0-C1'")).not.toBeNull()
    expect(group.getObjectByName("sample-i+1-upper-xo-0-C1'")).not.toBeNull()
    expect(group.getObjectByName('sample-i-lower-xo-0-directed-slab-normal')).not.toBeNull()
    expect(group.getObjectByName('sample-i+1-upper-xo-0-directed-slab-normal')).not.toBeNull()
    expect(group.userData).toMatchObject({ frame: 220, representation: 'atomistic' })
  })
})
