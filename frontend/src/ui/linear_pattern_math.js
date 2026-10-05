export function linearDirection(direction, vector) {
  const axes = ['X', 'Y', 'Z']
  if (axes.includes(direction)) return axes.map(axis => Number(axis === direction))
  if (direction !== 'Custom' || !Array.isArray(vector) || vector.length !== 3 || !vector.every(Number.isFinite)) return null
  const length = Math.hypot(...vector)
  return Number.isFinite(length) && length >= 1e-8 ? vector.map(v => v / length) : null
}

export function linearPatternOffsets({ instances, spacing, direction, vector, two_dimensional = false, instances2 = 2, spacing2 = 10, direction2 = 'Y', vector2 }) {
  const valid = (n, s) => Number.isInteger(n) && n >= 1 && n <= 128 && Number.isFinite(s) && s !== 0
  const first = linearDirection(direction, vector)
  if (!valid(instances, spacing) || !first) return null
  const second = two_dimensional ? linearDirection(direction2, vector2) : [0, 0, 0]
  if (two_dimensional) {
    if (!valid(instances2, spacing2) || !second) return null
    const [a, b, c] = first, [x, y, z] = second
    if (Math.hypot(b * z - c * y, c * x - a * z, a * y - b * x) < 1e-8) return null
  }
  const rows = two_dimensional ? instances2 : 1
  if (instances * rows > 128) return null
  const offsets = []
  for (let j = 0; j < rows; j++) for (let i = 0; i < instances; i++) {
    const point = first.map((v, axis) => v * (i * spacing) + second[axis] * (j * (two_dimensional ? spacing2 : 0)))
    if (!point.every(Number.isFinite)) return null
    offsets.push(point.map(v => v === 0 ? 0 : v))
  }
  return offsets
}
