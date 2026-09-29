import { Vector3 } from 'three'

// Planar homography with an approximate pinhole camera. Marker axes: right,
// up, out of paper. QR corners exclude the four-module printed quiet zone.
export function estimateQRPose(code, width, height, { printedSize = .04, verticalFov = 60 } = {}) {
  if (!code?.location || !Number.isInteger(code.version) || code.version < 1 || code.version > 40 || ![width, height, printedSize, verticalFov].every(Number.isFinite) || width <= 0 || height <= 0 || printedSize <= 0 || verticalFov < 20 || verticalFov > 120) return null
  const n = 17 + 4 * code.version, size = printedSize * n / (n + 8), half = size / 2
  const points = ['topLeftCorner', 'topRightCorner', 'bottomRightCorner', 'bottomLeftCorner'].map(k => code.location[k])
  if (points.some(p => !p || !Number.isFinite(p.x) || !Number.isFinite(p.y))) return null
  const area = Math.abs(points.reduce((sum, p, i) => { const q = points[(i + 1) % 4]; return sum + p.x * q.y - p.y * q.x }, 0)) / 2
  if (area < 400) return null
  const focal = height / (2 * Math.tan(verticalFov * Math.PI / 360))
  const rows = []
  const xy = [[-half, half], [half, half], [half, -half], [-half, -half]]
  for (let i = 0; i < 4; i++) {
    const [x, y] = xy[i], u = (points[i].x - width / 2) / focal, v = (points[i].y - height / 2) / focal
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u], [0, 0, 0, x, y, 1, -v * x, -v * y, v])
  }
  for (let col = 0; col < 8; col++) {
    let pivot = col
    for (let j = col + 1; j < 8; j++) if (Math.abs(rows[j][col]) > Math.abs(rows[pivot][col])) pivot = j
    if (Math.abs(rows[pivot][col]) < 1e-10) return null
    ;[rows[col], rows[pivot]] = [rows[pivot], rows[col]]
    const scale = rows[col][col]
    for (let k = col; k <= 8; k++) rows[col][k] /= scale
    for (let j = 0; j < 8; j++) if (j !== col) {
      const factor = rows[j][col]
      for (let k = col; k <= 8; k++) rows[j][k] -= factor * rows[col][k]
    }
  }
  const h = rows.map(r => r[8]), a = new Vector3(h[0], h[3], h[6]), b = new Vector3(h[1], h[4], h[7])
  const scale = 2 / (a.length() + b.length()), translation = new Vector3(h[2], h[5], 1).multiplyScalar(scale)
  if (Math.abs(a.length() / b.length() - 1) > .3 || Math.abs(a.dot(b) / (a.length() * b.length())) > .3) return null
  const right = a.normalize(), up = b.addScaledVector(right, -b.dot(right)).normalize(), normal = right.clone().cross(up)
  const position = [-right.dot(translation), -up.dot(translation), -normal.dot(translation)]
  if (!position.every(Number.isFinite) || position[2] <= 0 || position[2] > 20) return null
  let error = 0
  for (let i = 0; i < 4; i++) {
    const p = translation.clone().addScaledVector(right, xy[i][0]).addScaledVector(up, xy[i][1])
    if (p.z <= 0) return null
    error += (focal * p.x / p.z + width / 2 - points[i].x) ** 2 + (focal * p.y / p.z + height / 2 - points[i].y) ** 2
  }
  const reprojectionError = Math.sqrt(error / 4)
  if (reprojectionError > 8) return null
  return { position, forward: [right.z, up.z, normal.z], up: [-right.y, -up.y, -normal.y], reprojectionError, corners: points }
}
