import { expect, it } from 'vitest'
import { normalizeBoxAngle, rotatedBoxSize, resizeAnnotationBox, rotatedAnnotationLeader } from './annotation_box_math.js'
it('normalizes angles and computes the occupied rectangle for rotated boxes', () => {
  expect(normalizeBoxAngle(450)).toBe(90)
  expect(rotatedBoxSize(200, 100, 90).w).toBeCloseTo(100)
  expect(rotatedBoxSize(200, 100, 90).h).toBeCloseTo(200)
})
it('resizes in local axes, anchors the opposite edge, and optionally preserves aspect ratio', () => {
  const start = { w: 200, h: 100, cx: 300, cy: 300, angle: 90 }
  expect(resizeAnnotationBox(start, 'e', 0, 100)).toMatchObject({ w: 300, h: 100, cx: 300, cy: 350 })
  const locked = resizeAnnotationBox(start, 'se', -30, 100, true)
  expect(locked.w / locked.h).toBe(2)
  expect(resizeAnnotationBox(start, 'e', 0, -1000).w).toBe(32)
})

it('anchors leaders to a rotated box edge', () => {
  const points = rotatedAnnotationLeader('line', { x: 50, y: 0, w: 100, h: 200 }, { w: 200, h: 100 }, 90, { x: 300, y: 100 })
  expect(points[0].x).toBeCloseTo(150)
  expect(points[0].y).toBeCloseTo(100)
})
