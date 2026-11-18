/** Publish a coupled rigid preview as one display frame, after every body moved. */
export function createClusterPreview({ renderer, getBluntEnds, getJoints, overhangLocations, selectionManager }) {
  let depth=0, dirty=false
  function flush() {
    if (!dirty) return
    dirty=false
    selectionManager.refreshBaseGlow()
    renderer.refreshClusterSelection()
  }
  return {
    frame(update) {
      depth++
      try { return renderer.getDisplayGeometry().transaction('cluster-preview',update) }
      finally { if (!--depth) flush() }
    },
    paint(helixIds,center,position,rotation,scope) {
      renderer.getHelixCtrl()?.applyClusterTransform(helixIds,center,position,rotation,scope)
      getBluntEnds()?.applyClusterTransform(helixIds,center,position,rotation,scope)
      if (!scope?.length) {
        getJoints()?.applyClusterTransform(helixIds,center,position,rotation)
        overhangLocations.applyClusterTransform(helixIds,center,position,rotation)
      }
      dirty=true
      if (!depth) flush()
    },
    capture(helixIds,scope,append=false) {
      renderer.getHelixCtrl()?.captureClusterBase(helixIds,scope,append)
      getBluntEnds()?.captureClusterBase(helixIds,append,scope)
      if (!scope?.length) {
        getJoints()?.captureClusterBase(helixIds,append)
        overhangLocations.captureClusterBase(helixIds,append)
      }
    },
  }
}
