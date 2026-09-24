/** Source-space rigid placement, never tracking metres or a display scale. */
export function normalizeFreeformPlacement(value) {
  if (value === undefined) return undefined
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      Object.keys(value).sort().join(',') !== 'rotation_xyzw,translation_nm') return null
  const { translation_nm:t,rotation_xyzw:q } = value
  if (!Array.isArray(t) || t.length!==3 || !t.every(v=>Number.isFinite(v) && Math.abs(v)<=1e6) ||
      !Array.isArray(q) || q.length!==4 || !q.every(Number.isFinite)) return null
  const norm = Math.hypot(...q)
  if (Math.abs(norm-1)>1e-3) return null
  return { translation_nm:[...t],rotation_xyzw:q.map(v=>v/norm) }
}
