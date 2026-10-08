// Selection transport is independent of molecular geometry. A complete bounded
// state allows late guests and reconnects to catch up without replaying history.
export const SELECTION_UPDATE_LIMIT = 4 * 1024 * 1024
const id = value => typeof value === 'string' && /^[a-zA-Z0-9-]{1,64}$/.test(value)
const vector = (value, max) => Array.isArray(value) && value.length <= max && value.length % 3 === 0 && value.every(n => Number.isFinite(n) && Math.abs(n) <= 1e20)
export function validateSelectionUpdate(value) {
  const fail = () => { throw new Error('Invalid selection update') }
  if (!value || !/^[a-f0-9]{64}$/.test(value.revision ?? '') || !id(value.id) ||
      Object.keys(value).some(k => !['revision', 'id', 'selection', 'points', 'corners', 'tints'].includes(k)) ||
      !vector(value.points, 60000) || !vector(value.corners, 144000) || !Array.isArray(value.tints) || value.tints.length > 10000) fail()
  const s = value.selection
  if (s !== null) {
    if (!s || !id(s.target) || typeof s.label !== 'string' || s.label.length > 500 ||
        !Number.isSafeInteger(s.revision) || s.revision < 0 || Object.keys(s).some(k => !['target', 'label', 'revision', 'ping'].includes(k))) fail()
    if (s.ping != null && (!id(s.ping.id) || !Number.isSafeInteger(s.ping.createdAt) || s.ping.createdAt < 0 || Object.keys(s.ping).some(k => !['id', 'createdAt'].includes(k)))) fail()
  } else if (value.points.length) fail()
  const targets = new Set(); let count = 0
  for (const tint of value.tints) {
    if (!tint || !id(tint.target) || targets.has(tint.target) || Object.keys(tint).some(k => !['target', 'ids'].includes(k)) || !Array.isArray(tint.ids)) fail()
    targets.add(tint.target); count += tint.ids.length
    if (count > 500000 || tint.ids.some((n, i) => !Number.isSafeInteger(n) || n < 0 || n >= 5000000 || (i > 0 && n <= tint.ids[i - 1]))) fail()
  }
  return value
}

const attributes = new WeakMap()
function cached(attribute, key, read) {
  const previous = attributes.get(attribute)
  if (previous?.version === attribute.version && previous.key === key && previous.array === attribute.array) return previous.value
  const value = read(); attributes.set(attribute, { version: attribute.version, array: attribute.array, key, value }); return value
}

export function captureSelectionUpdate({ scene, view }) {
  const selection = view?.selection ? JSON.parse(JSON.stringify(view.selection)) : null
  const tints = []; let points = [], corners = []
  scene.traverseVisible(o => {
    const role = o.userData.presentationSelection
    if (role) {
      const attr = o.geometry?.attributes.position
      if (!attr) return
      o.updateWorldMatrix(true, false)
      const matrix = o.matrixWorld.elements
      const start = o.geometry.drawRange.start
      const end = Math.min(attr.count, start + o.geometry.drawRange.count)
      const values = cached(attr, `${matrix.join(',')}:${start}:${end}`, () => {
        const out = []
        for (let i = start; i < end; i++) {
          const x = attr.getX(i), y = attr.getY(i), z = attr.getZ(i)
          out.push(matrix[0]*x + matrix[4]*y + matrix[8]*z + matrix[12], matrix[1]*x + matrix[5]*y + matrix[9]*z + matrix[13], matrix[2]*x + matrix[6]*y + matrix[10]*z + matrix[14])
        }
        return out
      })
      if (role === 'points') points = values
      if (role === 'corners') corners = values
    }
    const attr = o.geometry?.attributes.instanceSelection
    if (!o.isMesh || !attr) return
    const count = o.isInstancedMesh ? o.count : attr.count
    const ids = cached(attr, count, () => {
      if (!o.isInstancedMesh) return attr.array.some(v => v !== 0) ? [0] : []
      const selected = []; for (let i = 0; i < count; i++) if (attr.getX(i)) selected.push(i)
      return selected
    })
    if (ids.length) tints.push({ target: o.uuid, ids })
  })
  const payload = { selection, points: selection ? points : [], corners, tints }
  const signature = JSON.stringify({ ...payload, selection: selection ? { ...selection, ping: null } : null })
  // Oversized selections use the existing snapshot path; they are never truncated.
  let supported = signature.length <= SELECTION_UPDATE_LIMIT / 2
  try { validateSelectionUpdate({ ...payload, revision: '0'.repeat(64), id: 'capture' }) } catch { supported = false }
  return { payload, signature, supported }
}
