/** Atom serials are local to a topology. Never interpolate one atom into a
 * different atom merely because the two historical models reuse its serial.
 */
export function createFeatureAtomisticDisplay(getRenderer) {
  let currentSignature = null
  const signatures = new WeakMap()
  const signature = frame => {
    if (!frame?.atoms) return null
    if (!signatures.has(frame)) signatures.set(frame, JSON.stringify([
      frame.atoms.map(a => [a.serial, a.name, a.element, a.residue, a.strand_id,
        a.helix_id, a.bp_index, a.direction, a.crossover_id, a.extra_base_k]), frame.bonds,
    ]))
    return signatures.get(frame)
  }
  function show(from, to, t, clusterTransforms, clusterHelixIds, sweepReveal = null) {
    const renderer = getRenderer?.()
    if (!renderer || !from || !to) return
    const fromSignature = signature(from), toSignature = signature(to)
    if (fromSignature == null || toSignature == null) {
      renderer.applyPositionLerp(from, to, t, from, clusterTransforms, clusterHelixIds)
      return
    }
    const sameTopology = fromSignature === toSignature
    const frame = sweepReveal && t > 0 && t < 1
      ? (from.atoms.length > to.atoms.length ? from : to) : t < 0.5 ? from : to
    const nextSignature = signature(frame)
    if (nextSignature !== currentSignature) {
      renderer.update(frame)
      currentSignature = nextSignature
    }
    if (sameTopology) renderer.applyPositionLerp(from.positions, to.positions, t, from.positions, clusterTransforms, clusterHelixIds)
    else if (sweepReveal) renderer.applyPositionLerp(frame.positions, frame.positions, 0, null, [], null, sweepReveal.scale)
    else renderer.applyPositionLerp(frame.positions, frame.positions, 0)
  }
  return { show, clear() { currentSignature = null } }
}
