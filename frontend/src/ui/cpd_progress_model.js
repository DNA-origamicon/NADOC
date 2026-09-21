export const STATUS = {
  pass: { color: '#35bd7c', label: 'Checks passed' },
  warning: { color: '#ff983f', label: 'One failed check' },
  fail: { color: '#ef5767', label: 'Multiple failed checks' },
  pending: { color: '#e5c34d', label: 'Validation incomplete' },
  unknown: { color: '#8391a5', label: 'No local evidence' },
}

export function elementStatus(checks = [], overall = true) {
  const failures = checks.filter(c => c.state === 'fail').length
  if (failures > 1) return 'fail'
  if (failures) return 'warning'
  if (!checks.length) return 'unknown'
  if (overall || checks.some(c => c.state === 'pending')) return 'pending'
  return checks.every(c => c.state === 'pass') ? 'pass' : 'unknown'
}

export function projectAtoms(atoms, yaw = 0, pitch = 0, zoom = 1, frame = {}) {
  if (!atoms.length) return []
  const center = frame.center ?? [0, 1, 2].map(i => atoms.reduce((s, a) => s + a.position[i], 0) / atoms.length)
  const radius = frame.radius ?? Math.max(1, ...atoms.map(a => Math.hypot(...a.position.map((v, i) => v - center[i]))))
  return atoms.map(a => {
    const [x, y, z] = a.position.map((v, i) => v - center[i])
    const xx = x * Math.cos(yaw) + z * Math.sin(yaw)
    const zz = -x * Math.sin(yaw) + z * Math.cos(yaw)
    const yy = y * Math.cos(pitch) - zz * Math.sin(pitch)
    return { ...a, x: 330 + xx * 230 / radius * zoom, y: 240 - yy * 230 / radius * zoom, z: y * Math.sin(pitch) + zz * Math.cos(pitch) }
  })
}

const subtract = (a, b) => a.map((v, i) => v - b[i])
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0)
const unit = a => a.map(v => v / Math.hypot(...a))
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

export function contextAtoms(model, torsions = [0, 0]) {
  const positions = new Map(model.atoms.map(a => [a.id, a.position]))
  return model.atoms.map(a => {
    if (a.region !== 'backbone') return a
    const origin = positions.get(`${a.endpoint}:N1`)
    const axis = unit(subtract(positions.get(`${a.endpoint}:C1'`), origin))
    const v = subtract(a.position, origin), angle = torsions[a.endpoint - 1] * Math.PI / 180
    const c = Math.cos(angle), s = Math.sin(angle), perpendicular = cross(axis, v)
    return { ...a, position: v.map((x, i) => origin[i] + x * c + perpendicular[i] * s + axis[i] * dot(axis, v) * (1 - c)) }
  })
}

export function attachmentDirections(atoms) {
  const map = new Map(atoms.map(a => [a.id, a.position]))
  return [1, 2].flatMap(endpoint => [['5′', 'P', "O5'"], ['3′', "O3'", "C3'"]].map(([label, anchor, previous]) => {
    const start = map.get(`${endpoint}:${anchor}`), direction = unit(subtract(start, map.get(`${endpoint}:${previous}`)))
    return { id: `${endpoint}:${label}`, endpoint, label: `${endpoint} · ${label}`, anchor: `${endpoint}:${anchor}`, position: start.map((v, i) => v + 2.4 * direction[i]) }
  }))
}

export function attachmentMetrics(atoms) {
  const map = new Map(atoms.map(a => [a.id, a.position]))
  const distance = name => Math.hypot(...subtract(map.get(`1:${name}`), map.get(`2:${name}`)))
  const directions = [1, 2].map(e => unit(subtract(map.get(`${e}:O3'`), map.get(`${e}:P`))))
  return { c1: distance("C1'"), o5: distance("O5'"), angle: Math.acos(Math.max(-1, Math.min(1, dot(...directions)))) * 180 / Math.PI }
}

export function validateSnapshot(data) {
  if (data?.schema !== 1 || !Array.isArray(data.models) || !data.models.length) throw new Error('Unsupported or empty CPD progress snapshot')
  if (data.isomers != null && !Array.isArray(data.isomers)) throw new Error('Invalid isomer catalog')
  const models = [...(data.isomers ?? []), ...data.models]
  if (new Set(models.map(m => m.id)).size !== models.length) throw new Error('Duplicate structure identity')
  for (const m of models) {
    const ids = new Set(m.atoms?.map(a => a.id))
    if (!m.atoms?.length || ids.size !== m.atoms.length || !Array.isArray(m.bonds)) throw new Error('Invalid molecular structure')
    for (const a of m.atoms) if (a.position?.length !== 3 || !a.position.every(Number.isFinite)) throw new Error('Invalid atomic coordinates')
    for (const b of m.bonds) if (b.atoms?.length !== 2 || !b.atoms.every(id => ids.has(id))) throw new Error('Invalid bond endpoints')
    if (data.isomers?.includes(m)) {
      for (const e of [1, 2]) for (const name of ['N1', "C1'", 'P', "O5'", "C5'", "C4'", "O4'", "C2'", "C3'", "O3'"]) {
        if (!ids.has(`${e}:${name}`)) throw new Error('Incomplete DNA attachment context')
      }
      if (m.atoms.some(a => ![1, 2].includes(a.endpoint) || !['base', 'backbone'].includes(a.region))) throw new Error('Invalid DNA attachment identity')
    }
  }
  return data
}
