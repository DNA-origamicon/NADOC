import { it, expect } from 'vitest'
import { drawingPoints, sameDrawingView, drawingOpacity } from './meeting_drawing_protocol.js'
const pose = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
it('matches a perspective across viewport sizes, but rejects changed camera or zoom', () => {
  expect(sameDrawingView(pose, { ...pose, aspect: 2 })).toBe(true)
  expect(sameDrawingView(pose, { ...pose, position: [0, 0, 19] })).toBe(false)
  expect(sameDrawingView(pose, { ...pose, fov: 56 })).toBe(false)
})
it('holds for two seconds then fades and expires', () => {
  expect(drawingOpacity(2000)).toBe(1)
  expect(drawingOpacity(2250)).toBe(.5)
  expect(drawingOpacity(2500)).toBe(0)
})
it('bounds point counts and rejects malformed coordinates', () => {
  expect(drawingPoints([[0, .3]])).toEqual([[0, .3]])
  for (const value of [[], [[Infinity, 0]], [[9, 0]], Array(33).fill([0, 0])]) expect(() => drawingPoints(value)).toThrow()
})
