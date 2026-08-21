import { describe, expect, it } from 'vitest'

import {
  deformationPlaneFrame,
  deformationPlaneFramePair,
} from './deformation_plane_frame.js'

describe('desktop-authoritative deformation plane frame', () => {
  it('averages scoped straight helices and preserves global-bp stagger semantics', () => {
    const frame = deformationPlaneFrame(12, [
      { bpStart: 10, lengthBp: 20, start: [0, 0, 0], end: [0, 0, 10] },
      { bpStart: 0, lengthBp: 30, start: [4, 0, 0], end: [4, 0, 10] },
    ])
    expect(frame.center).toEqual([2, 0, (2 + 12) * 0.334 / 2])
    expect(frame.normal).toEqual([0, 0, 1])
    expect(frame.halfExtentNm).toBe(8)
  })

  it('uses the short final curved sample segment and averaged tangent', () => {
    const frame = deformationPlaneFrame(9, [
      {
        bpStart: 0, lengthBp: 11, start: [0, 0, 0], end: [3, 0, 7],
        samples: [[0, 0, 0], [0, 0, 7], [3, 0, 7]],
      },
    ])
    expect(frame.center).toEqual([2, 0, 7])
    expect(frame.normal).toEqual([1, 0, 0])
  })

  it('fails closed for malformed or cancelling axis frames', () => {
    expect(deformationPlaneFrame(2, [])).toBeNull()
    expect(deformationPlaneFrame(2, [
      { bpStart: 0, lengthBp: 4, start: [0, 0, 0], end: [0, 0, 0] },
    ])).toBeNull()
    expect(deformationPlaneFrame(2, [
      { bpStart: 0, lengthBp: 4, start: [0, 0, 0], end: [0, 0, 2] },
      { bpStart: 0, lengthBp: 4, start: [0, 0, 2], end: [0, 0, 0] },
    ])).toBeNull()
  })

  it('recomputes the Expanded center while preserving tangent and extent', () => {
    const helices = [
      { id: 'a', bpStart: 0, lengthBp: 20, start: [-1, 0, 0], end: [-1, 0, 10] },
      { id: 'b', bpStart: 0, lengthBp: 20, start: [1, 0, 0], end: [1, 0, 10] },
    ]
    const frames = deformationPlaneFramePair(5, helices, new Map([
      ['a', [-2, 1, 0]], ['b', [4, 1, 0]],
    ]))
    expect(frames.natural.center).toEqual([0, 0, 5 * 0.334])
    expect(frames.expanded.center).toEqual([1, 1, 5 * 0.334])
    expect(frames.expanded.normal).toEqual(frames.natural.normal)
    expect(frames.expanded.halfExtentNm).toBe(frames.natural.halfExtentNm)
    const missingOffset = new Map([['a', [0, 0, 0]]])
    expect(deformationPlaneFramePair(5, helices, missingOffset)).toBeNull()
  })
})
