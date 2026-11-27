export function sameTraceArray(a, b) {
  if (!a || !b || a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

/** BVH construction reorders indices. Compare the original connectivity, then
 * keep that reordered index while refreshing vertex attributes for refitting. */
export function reuseTraceGeometry(retained, incoming, originalIndex) {
  if (!retained || retained.attributes.position.count !== incoming.attributes.position.count ||
      !sameTraceArray(originalIndex, incoming.index?.array)) return null
  const moved = !sameTraceArray(retained.attributes.position.array, incoming.attributes.position.array)
  for (const [name, attribute] of Object.entries(incoming.attributes)) {
    const previous = retained.attributes[name]
    if (previous && previous.itemSize === attribute.itemSize && sameTraceArray(previous.array, attribute.array)) continue
    retained.setAttribute(name, attribute)
  }
  return { moved }
}
