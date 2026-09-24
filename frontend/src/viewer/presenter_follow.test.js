import { it, expect, vi } from 'vitest'
import { createPresenterFollow } from './presenter_follow.js'
const start = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
it('starts at the local pose, eases along the saved-view path, then follows live updates', () => {
  let time = 0
  const viewer = { captureCamera: () => start, applyCamera: vi.fn() }, follow = createPresenterFollow({ viewer, now: () => time })
  const destination = { ...start, position: [20, 0, 0] }
  follow.start(); expect(viewer.applyCamera).not.toHaveBeenCalled()
  time = 450; follow.frame(destination)
  const pose = viewer.applyCamera.mock.calls[0][0]
  expect(pose.position[0]).toBeGreaterThan(0); expect(pose.position[0]).toBeLessThan(20)
  expect(Math.hypot(...pose.position)).toBeCloseTo(20)
  time = 1000; follow.frame(destination); expect(viewer.applyCamera.mock.calls[1][0]).toBe(destination)
  follow.stop()
})
