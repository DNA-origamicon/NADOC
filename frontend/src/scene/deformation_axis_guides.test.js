import { describe, it, expect } from 'vitest'
import { deformationAxisPositions, buildDeformationAxisGuides } from './deformation_axis_guides.js'
import { segmentAxisSamples } from './native_axis_samples.js'

describe('private native sampled axis guides', () => {
  const helix = { id: 'h', bp_start: 10, length_bp: 22 }
  const samples = [[0, 0, 0], [7, 1, 0], [14, 2, 0], [21, 3, 0]]
  const segments = [
    { bp_lo: 10, bp_hi: 17, start: [0, 0, 0], end: [8, 1, 0], samples },
    { bp_lo: 24, bp_hi: 31, start: [14, 2, 0], end: [22, 3, 0], samples },
  ]
  const topology = { helices: [helix] }
  const axes = { h: { samples, segments } }
  it('clips helix-wide samples to each domain without connecting the gap', () => {
    expect(segmentAxisSamples(helix, segments[1], samples, segments[1].start, segments[1].end))
      .toEqual([[14, 2, 0], [21, 3, 0], [22, 3, 0]])
    expect([...deformationAxisPositions(topology, axes)]).toEqual([
      0, 0, 0, 7, 1, 0, 7, 1, 0, 8, 1, 0,
      14, 2, 0, 21, 3, 0, 21, 3, 0, 22, 3, 0,
    ])
  })
  it('updates owned buffers and bounds from new native samples', () => {
    const guides = buildDeformationAxisGuides(topology, axes)
    const attribute = guides.line.geometry.attributes.position
    const moved = structuredClone(axes)
    for (const segment of moved.h.segments) {
      segment.start[0] += 50; segment.end[0] += 50

    }
    for (const p of moved.h.samples) p[0] += 50
    guides.update(moved)
    expect(guides.line.geometry.attributes.position).toBe(attribute)
    expect(guides.line.geometry.boundingBox.min.x).toBe(50)
    expect(guides.line.geometry.boundingBox.max.x).toBe(72)
    guides.line.geometry.dispose(); guides.line.material.dispose()
  })
  it('omits native linker guides', () => {
    expect(deformationAxisPositions({ helices: [{ ...helix, id: '__lnk__x' }] }, {})).toHaveLength(0)
  })
  it('disposes the old GPU buffer owner when the sampled point count changes', () => {
    const guides = buildDeformationAxisGuides(topology, axes), old = guides.line.geometry
    let disposed = 0
    old.addEventListener('dispose', () => disposed++)
    const changed = structuredClone(axes)
    changed.h.segments.pop()
    guides.update(changed)
    expect(disposed).toBe(1)
    expect(guides.line.geometry).not.toBe(old)
    expect(guides.line.geometry.attributes.position.count).toBe(6)
    guides.line.geometry.dispose(); guides.line.material.dispose()
  })
})
