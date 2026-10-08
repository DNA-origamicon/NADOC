/** Display-only historical topology. Positions alone cannot show deleted helices,
 * earlier routing, or a build started while the editor is scrubbed backwards.
 * Reuse the renderer's external-snapshot API without touching the editable store.
 */
export function createFeatureAnimationDisplay({ getDesignRenderer, getUnfoldView, getNanoparticleRenderer }) {
  let shown = null, signature = null
  function show(from, to, t) {
    // Prefer the larger topology during a grow/shrink tween so appearing sites
    // exist in the renderer. Exact endpoints always use their exact topology.
    const frame = t <= 0 ? from : t >= 1 ? to
      : from?.nucleotides?.length > to?.nucleotides?.length ? from : to
    if (!frame?.displayDesign || !getDesignRenderer?.()?.renderExternalGeometry) return false
    if (shown && signature === frame.topologySignature) return false
    getDesignRenderer().renderExternalGeometry(frame.displayDesign, frame.nucleotides,
      Object.fromEntries((frame.helixAxes ?? []).map(axis => [axis.helix_id, axis])))
    getUnfoldView?.()?.refreshExternalGeometry?.(frame.displayDesign)
    getNanoparticleRenderer?.()?.renderExternalGeometry?.(frame.displayDesign, frame.nucleotides)
    shown = frame
    signature = frame.topologySignature
    return true
  }
  function clear() {
    if (!shown) return
    getDesignRenderer?.()?.clearExternalGeometry?.()
    getNanoparticleRenderer?.()?.clearExternalGeometry?.()
    getUnfoldView?.()?.refreshExternalGeometry?.()
    shown = null; signature = null
  }
  return { show, clear, getDesign: () => shown?.displayDesign }
}

export function featureTopologySignature(design) {
  if (!design) return null
  return JSON.stringify([design.helices, design.strands, design.crossovers,
    design.forced_ligations, design.extensions, design.overhangs, design.loop_skips,
    design.nanoparticles, design.nanoparticle_conjugations, design.nanoparticle_connection_versions])
}
