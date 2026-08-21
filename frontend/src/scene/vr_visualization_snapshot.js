export const VR_VISUALIZATION_POINT_LIMIT = 1_000_000

function _baseKey(update) {
  const helix = String(update?.helix_id ?? '')
  const bp = update?.bp_index
  const direction = String(update?.direction ?? '')
  if (!helix || bp == null || !direction) return null
  if (helix === '__xb__') return `__xb__:${bp}:${direction}`
  const copy = Number(update?.copy ?? 0)
  const key = `${helix}:${bp}:${direction}`
  return Number.isInteger(copy) && copy !== 0 ? `${key}:${copy}` : key
}

function _colorFor(colors, key) {
  if (!colors || !key) return null
  const get = colors instanceof Map ? value => colors.get(value) : value => colors[value]
  let color = get(key)
  if (color == null && /:\d+$/.test(key)) color = get(key.replace(/:\d+$/, ''))
  const value = Number(color)
  return Number.isInteger(value) && value >= 0 && value <= 0xFFFFFF ? value : null
}

function _finiteVec3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
}

function _atomBaseKey(atom) {
  if (typeof atom?.base_key === 'string' && atom.base_key) return atom.base_key
  const scalar = typeof atom?.scalar_key === 'string' ? atom.scalar_key : ''
  if (scalar.startsWith('__xb__:') || scalar.startsWith('__ext_')) {
    return scalar.endsWith(':0') ? scalar.slice(0, -2) : scalar
  }
  const helix = String(atom?.helix_id ?? '')
  const bp = atom?.bp_index
  const direction = String(atom?.direction ?? '')
  if (!helix || bp == null || !direction) return null
  const copy = Number(atom?.copy_k ?? atom?.copy ?? 0)
  const key = `${helix}:${bp}:${direction}`
  return Number.isInteger(copy) && copy !== 0 ? `${key}:${copy}` : key
}

// CHARMM/NAMD and NADOC's internal atomistic templates use different names for
// three chemically identical atoms. Normalize only the native-VR transport key;
// the desktop atom table and its recorded topology remain untouched.
function _vrAtomName(value) {
  const name = String(value ?? '')
  return ({ O1P: 'OP1', O2P: 'OP2', C5M: 'C7' })[name] ?? name
}

/** Convert the browser's active FEM/MD overlay into the compact native feed.
 * Owner tokens are identical to selection tokens already embedded in the VR scene,
 * so native rendering, hit testing, and glow all follow the displaced geometry. */
export function buildVRVisualizationSnapshot(
  positions, colors, mode = 'none', { slabFrames = null, atoms = null } = {},
) {
  const safeMode = String(mode || 'none').toLowerCase().replace(/[^a-z0-9_-]+/g, '_').slice(0, 32) || 'none'
  if ((!Array.isArray(positions) || !positions.length) &&
      (!Array.isArray(atoms) || !atoms.length)) {
    return { visualization_mode: 'none', visualization_points: [] }
  }
  const slabByKey = new Map(
    (Array.isArray(slabFrames) ? slabFrames : [])
      .filter(frame => typeof frame?.base_key === 'string')
      .map(frame => [frame.base_key, frame]),
  )
  const seen = new Set()
  const points = []
  for (const update of (Array.isArray(positions) ? positions : [])) {
    if (points.length >= VR_VISUALIZATION_POINT_LIMIT) break
    const key = _baseKey(update)
    const position = update?.backbone_position
    if (!key || !_finiteVec3(position)) continue
    const ownerToken = encodeURIComponent(JSON.stringify(['base', key]))
    if (seen.has(ownerToken)) continue
    seen.add(ownerToken)
    const point = {
      owner_token: ownerToken,
      position: position.map(Number),
      color: _colorFor(colors, key),
    }
    const frame = slabByKey.get(key)
    if (frame && _finiteVec3(frame.center) && _finiteVec3(frame.axis_x) &&
        _finiteVec3(frame.axis_y) && _finiteVec3(frame.axis_z)) {
      point.slab_center = frame.center.map(Number)
      point.slab_axis_x = frame.axis_x.map(Number)
      point.slab_axis_y = frame.axis_y.map(Number)
      point.slab_axis_z = frame.axis_z.map(Number)
    }
    points.push(point)
  }
  for (const entry of (Array.isArray(atoms) ? atoms : [])) {
    if (points.length >= VR_VISUALIZATION_POINT_LIMIT) break
    const atom = entry?.atom ?? entry
    const position = entry?.position ?? [atom?.x, atom?.y, atom?.z]
    const key = _atomBaseKey(atom)
    const name = _vrAtomName(atom?.name)
    if (!key || !name || !_finiteVec3(position)) continue
    const ownerToken = encodeURIComponent(JSON.stringify(['atom', key, name]))
    if (seen.has(ownerToken)) continue
    seen.add(ownerToken)
    points.push({
      owner_token: ownerToken,
      position: position.map(Number),
      color: _colorFor(colors, key),
    })
  }
  return {
    visualization_mode: points.length ? safeMode : 'none',
    visualization_points: points,
  }
}
