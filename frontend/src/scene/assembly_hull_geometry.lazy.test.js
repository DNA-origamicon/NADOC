import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'

const builders = vi.hoisted(() => ({
  buildExtrusionBoxes: vi.fn(), scanExtrusionGroup: vi.fn(), dsTrimmedAxes: vi.fn(),
  dsBpByHelix: vi.fn(), dsBpRangeByHelix: vi.fn(), buildOverhangMarkers: vi.fn(),
  buildClusteredOccupancyHull: vi.fn(), usesOccupancyHull: vi.fn(),
}))
vi.mock('./joint_renderer.js', () => builders)
import { _hullGeoForSource } from './assembly_hull_geometry.js'

const design = () => ({ helices: [{ id: 'h1' }], cluster_transforms: [] })
function solid() {
  const group = new THREE.Group()
  group.add(new THREE.Mesh(new THREE.BoxGeometry(2, 3, 4), new THREE.MeshBasicMaterial()))
  return group
}
const scanAxes = { h1: { start: [0, 0, 0], end: [0, 0, 3] } }
const helixBp = new Map([['h1', 10]])

beforeEach(() => {
  vi.resetAllMocks()
  builders.usesOccupancyHull.mockReturnValue(true)
  builders.dsTrimmedAxes.mockReturnValue(scanAxes)
  builders.dsBpByHelix.mockReturnValue({ helixBp, totalBp: 10 })
  builders.buildClusteredOccupancyHull.mockImplementation(solid)
})

describe('assembly hull input preparation', () => {
  it('builds an occupancy solid without duplicate nucleotide indexes', () => {
    const result = _hullGeoForSource(design(), [], scanAxes)
    expect(result.solid.getAttribute('position').count).toBe(36)
    expect(result.markers).toBeNull()
    expect(builders.dsTrimmedAxes).not.toHaveBeenCalled()
    expect(builders.dsBpByHelix).not.toHaveBeenCalled()
    expect(builders.dsBpRangeByHelix).not.toHaveBeenCalled()
    result.solid.dispose()
  })

  it('shares the same scan inputs between fallback geometry and overhang markers', () => {
    builders.buildClusteredOccupancyHull.mockReturnValue(null)
    builders.scanExtrusionGroup.mockImplementation(solid)
    builders.buildOverhangMarkers.mockImplementation(solid)
    const part = { ...design(), overhangs: [{ id: 'oh1' }] }
    const nucs = []
    const result = _hullGeoForSource(part, nucs, scanAxes)
    expect(builders.dsTrimmedAxes).toHaveBeenCalledTimes(1)
    expect(builders.dsBpByHelix).toHaveBeenCalledTimes(1)
    expect(builders.scanExtrusionGroup).toHaveBeenCalledWith(['h1'], scanAxes, helixBp,
      undefined, undefined, null)
    expect(builders.buildOverhangMarkers).toHaveBeenCalledWith(part, scanAxes,
      [{ helix_ids: ['h1'] }], nucs, helixBp, expect.any(Array))
    expect(result.markers.getAttribute('position').count).toBe(36)
    result.solid.dispose(); result.markers.dispose()
  })

  it('retains occupied bp ranges for the forced legacy extrusion path', () => {
    const ranges = new Map([['h1', { lo: 0, hi: 9 }]])
    builders.dsBpRangeByHelix.mockReturnValue(ranges)
    builders.buildExtrusionBoxes.mockImplementation(solid)
    const part = design(), nucs = []
    const result = _hullGeoForSource(part, nucs, scanAxes, { forceLegacy: true })
    expect(builders.buildClusteredOccupancyHull).not.toHaveBeenCalled()
    expect(builders.buildExtrusionBoxes).toHaveBeenCalledWith(part, scanAxes, 1,
      { clusters: [], dsBpRange: ranges })
    expect(builders.dsTrimmedAxes).not.toHaveBeenCalled()
    result.solid.dispose()
  })
})
