export const VR_VISUALIZATION_POINT_LIMIT = 200_000

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

/** Convert the browser's active FEM/MD overlay into the compact native feed.
 * Owner tokens are identical to selection tokens already embedded in the VR scene,
 * so native rendering, hit testing, and glow all follow the displaced geometry. */
export function buildVRVisualizationSnapshot(positions, colors, mode = 'none') {
  const safeMode = String(mode || 'none').toLowerCase().replace(/[^a-z0-9_-]+/g, '_').slice(0, 32) || 'none'
  if (!Array.isArray(positions) || !positions.length) {
    return { visualization_mode: 'none', visualization_points: [] }
  }
  const seen = new Set()
  const points = []
  for (const update of positions) {
    if (points.length >= VR_VISUALIZATION_POINT_LIMIT) break
    const key = _baseKey(update)
    const position = update?.backbone_position
    if (!key || !Array.isArray(position) || position.length !== 3 ||
        !position.every(Number.isFinite)) continue
    const ownerToken = encodeURIComponent(JSON.stringify(['base', key]))
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
