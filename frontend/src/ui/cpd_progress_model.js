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

export function projectAtoms(atoms, yaw = 0, pitch = 0, zoom = 1) {
  if (!atoms.length) return []
  const center = [0, 1, 2].map(i => atoms.reduce((s, a) => s + a.position[i], 0) / atoms.length)
  const radius = Math.max(1, ...atoms.map(a => Math.hypot(...a.position.map((v, i) => v - center[i]))))
  return atoms.map(a => {
    const [x, y, z] = a.position.map((v, i) => v - center[i])
    const xx = x * Math.cos(yaw) + z * Math.sin(yaw)
    const zz = -x * Math.sin(yaw) + z * Math.cos(yaw)
    const yy = y * Math.cos(pitch) - zz * Math.sin(pitch)
    return { ...a, x: 330 + xx * 230 / radius * zoom, y: 240 - yy * 230 / radius * zoom, z: y * Math.sin(pitch) + zz * Math.cos(pitch) }
  })
}

export function validateSnapshot(data) {
  if (data?.schema !== 1 || !Array.isArray(data.models) || !data.models.length) throw new Error('Unsupported or empty CPD progress snapshot')
  for (const m of data.models) {
    const ids = new Set(m.atoms?.map(a => a.id))
    if (!m.atoms?.length || ids.size !== m.atoms.length || !Array.isArray(m.bonds)) throw new Error('Invalid molecular structure')
    for (const a of m.atoms) if (a.position?.length !== 3 || !a.position.every(Number.isFinite)) throw new Error('Invalid atomic coordinates')
    for (const b of m.bonds) if (b.atoms?.length !== 2 || !b.atoms.every(id => ids.has(id))) throw new Error('Invalid bond endpoints')
  }
  return data
}
