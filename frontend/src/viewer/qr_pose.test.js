import { it, expect } from 'vitest'
import { estimateQRPose } from './qr_pose.js'
function projected({ x = 0, y = 0, z = .3, angle = 0 } = {}) {
  const size = .04 * 21 / 29, f = 480 / (2 * Math.tan(Math.PI / 6)), c = Math.cos(angle), s = Math.sin(angle)
  const location = Object.fromEntries(['topLeftCorner', 'topRightCorner', 'bottomRightCorner', 'bottomLeftCorner'].map((k, i) => {
    const a = (i === 0 || i === 3 ? -1 : 1) * size / 2 - x, b = (i < 2 ? 1 : -1) * size / 2 - y
    const X = c * a + s * z, Z = -s * a + c * z
    return [k, { x: 320 + f * X / Z, y: 240 - f * b / Z }]
  }))
  return { version: 1, location }
}
it.each([{ x: 0, y: 0, z: .3 }, { x: .02, y: -.01, z: .2, angle: .3 }])('recovers a known camera in marker coordinates: %j', camera => {
  const pose = estimateQRPose(projected(camera), 640, 480)
  expect(pose).not.toBeNull()
  pose.position.forEach((v, i) => expect(v).toBeCloseTo([camera.x, camera.y, camera.z][i], 5))
  expect(pose.reprojectionError).toBeLessThan(.001)
  expect(Math.hypot(...pose.forward)).toBeCloseTo(1)
})
it('rejects missing, degenerate, tiny and uncalibrated inputs', () => {
  expect(estimateQRPose(null, 640, 480)).toBeNull()
  expect(estimateQRPose(projected({ z: 10 }), 640, 480)).toBeNull()
  expect(estimateQRPose(projected(), 640, 480, { verticalFov: 0 })).toBeNull()
  const code = projected(); Object.values(code.location).forEach(p => { p.y = 100 })
  expect(estimateQRPose(code, 640, 480)).toBeNull()
})
it('scales metric position with the measured print size', () => {
  expect(estimateQRPose(projected(), 640, 480, { printedSize: .08 }).position[2]).toBeCloseTo(.6)
})
