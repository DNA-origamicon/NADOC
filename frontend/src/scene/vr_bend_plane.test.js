import { describe, it, expect } from 'vitest'
import { store } from '../state/store.js'
import { nearestVRDeformationPlane, extremeVRDeformationPlane } from './deformation_editor.js'

describe('VR bend controller projection', () => {
  it('rounds bp indices on the selected element and clamps outside its span', () => {
    store.setState({ currentDesign: {
      helices: [{ id: 'a', bp_start: -10, length_bp: 101 }, { id: 'b', bp_start: 50, length_bp: 101 }],
      cluster_transforms: [{ id: 'one', helix_ids: ['a'] }, { id: 'two', helix_ids: ['b'] }],
    }, currentHelixAxes: {
      a: { start: [0,0,0], end: [0,0,33.4] },
      b: { start: [10,0,0], end: [10,0,33.4] },
    } })
    expect(extremeVRDeformationPlane('a', ['one']).bp).toBe(-10)
    expect(extremeVRDeformationPlane('b', ['one']).bp).toBe(90)
    expect(extremeVRDeformationPlane('a', ['two']).bp).toBe(50)
    expect(extremeVRDeformationPlane('b', ['two']).bp).toBe(150)
    expect(extremeVRDeformationPlane('a', [])).toBeNull()
    expect(nearestVRDeformationPlane([0,0,3.34], ['one'])).toMatchObject({ bp: 0, helixId: 'a' })
    expect(nearestVRDeformationPlane([10,0,3.34], ['two'])).toMatchObject({ bp: 60, helixId: 'b' })
    expect(nearestVRDeformationPlane([0,0,-10], ['one']).bp).toBe(-10)
    expect(nearestVRDeformationPlane([0,0,100], ['one']).bp).toBe(90)
    expect(nearestVRDeformationPlane([0,0,100], ['one'], null, { max: 20 }).bp).toBe(20)
    expect(nearestVRDeformationPlane([0,0,-10], ['one'], null, { min: 0 }).bp).toBe(0)
    expect(nearestVRDeformationPlane([0,0,3.34], [], ['b']).helixId).toBe('b')
  })
  it('follows sampled bent axes instead of projecting onto the end-to-end chord', () => {
    store.setState({ currentDesign: { helices: [{ id: 'a', bp_start: 0, length_bp: 15 }], cluster_transforms: [] },
      currentHelixAxes: { a: { start: [0,0,0], end: [7,0,7], samples: [[0,0,0],[0,0,7],[7,0,7]] } } })
    expect(nearestVRDeformationPlane([3,0,7], []).bp).toBe(10)
    expect(nearestVRDeformationPlane([NaN,0,0], [])).toBeNull()
  })
})
