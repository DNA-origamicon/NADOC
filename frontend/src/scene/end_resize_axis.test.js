import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createEndResizeAxis, projectRayToResizeAxis } from './end_resize_axis.js'
import { BDNA_RISE_PER_BP as RISE } from '../constants.js'

const helix = { bp_start: 10, length_bp: 17, axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 16 * RISE } }
const bent = { start: [0, 0, 0], end: [9 * RISE, 0, 7 * RISE],
  samples: [[0, 0, 0], [0, 0, 7 * RISE], [7 * RISE, 0, 7 * RISE], [9 * RISE, 0, 7 * RISE]] }
const close = (actual, expected) => actual.toArray().forEach((v, i) => expect(v).toBeCloseTo(expected[i], 8))

describe('transformed end resize path', () => {
  it('follows a bent axis through its short final sample interval and beyond the end tangent', () => {
    const axis = createEndResizeAxis(helix, bent, 26, new THREE.Vector3(9 * RISE, 1, 7 * RISE))
    close(axis.point(25), [8 * RISE, 1, 7 * RISE])
    close(axis.point(30), [13 * RISE, 1, 7 * RISE])
    close(axis.point(13), [0, 1, 3 * RISE])
    expect(axis.path(26, 13).map(p => p.bp)).toEqual([26, 24, 17, 13])
    close(axis.tangent(26), [1, 0, 0])
    close(axis.tangent(13), [0, 0, 1])
  })

  it('projects the cursor onto the curve instead of its endpoint chord', () => {
    const axis = createEndResizeAxis(helix, bent, 26, new THREE.Vector3(...bent.end))
    const ray = new THREE.Ray(new THREE.Vector3(4 * RISE, 10, 7 * RISE), new THREE.Vector3(0, -1, 0))
    expect(projectRayToResizeAxis(ray, axis, 10, 40)).toBeCloseTo(21)
    expect(projectRayToResizeAxis(ray, axis, 40, 10)).toBeCloseTo(21)
  })

  it('follows a twisted helix in three dimensions', () => {
    const samples = [[2, 0, 0], [0, 2, 7 * RISE], [-2, 0, 14 * RISE], [-1, -1, 16 * RISE]]
    const axis = createEndResizeAxis(helix, { start: samples[0], end: samples.at(-1), samples }, 17, new THREE.Vector3(0, 2, 7 * RISE))
    close(axis.point(20.5), [-1, 1, 10.5 * RISE])
    close(axis.point(25), [-1.5, -.5, 15 * RISE])
  })

  it('keeps zero-delta previews at the bead and cadnano resizing on its flat track', () => {
    const bead = new THREE.Vector3(4, 5, 26 * RISE)
    const axis = createEndResizeAxis(helix, bent, 26, bead, true)
    close(axis.point(26), bead.toArray())
    close(axis.point(30), [4, 5, 30 * RISE])
    close(axis.tangent(26), [0, 0, 1])
  })

  it('uses the straight two-sample mapping for a transformed rigid helix', () => {
    const axis = createEndResizeAxis(helix, { start: [3, 4, 5], end: [3 + 16 * RISE, 4, 5], samples: [[3, 4, 5], [3 + 16 * RISE, 4, 5]] }, 10, new THREE.Vector3(3, 4, 6))
    close(axis.point(18), [3 + 8 * RISE, 4, 6])
    close(axis.point(8), [3 - 2 * RISE, 4, 6])
  })
})
