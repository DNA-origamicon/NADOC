/** Reactive bridges that keep the Move/Rotate tools aligned with store state. */
export function initMoveRotateSubscriptions({
  cancelTranslateRotateTool,
  clusterBackboneEntries,
  clusterGizmo,
  clusterGlowLayer,
  isTranslateRotateActive,
  nucleotideTransformTool,
  quatToEulerDeg,
  refreshCurrentSelection,
  setPivotOptions,
  setSelectedPivot,
  setTransformValues,
  store,
  translateRotateTool,
}) {
  store.subscribe((newState, previousState) => {
    if (newState.activeClusterId === previousState.activeClusterId) return
    if (!newState.activeClusterId || !newState.translateRotateActive) return
    if (clusterGizmo.isGroupActive?.()) return
    const cluster = newState.currentDesign?.cluster_transforms
      ?.find(item => item.id === newState.activeClusterId)
    if (!cluster) return
    const pending = clusterGizmo.getPendingTransform(newState.activeClusterId)
    const translation = pending?.translation ?? cluster.translation
    const rotation = pending?.rotation ?? cluster.rotation
    const [rx, ry, rz] = quatToEulerDeg(rotation)
    setTransformValues(
      translation[0], translation[1], translation[2], rx, ry, rz,
    )
    const joints = newState.currentDesign?.cluster_joints
      ?.filter(joint => joint.cluster_id === newState.activeClusterId) ?? []
    setPivotOptions(joints, newState.activeClusterId)
    setSelectedPivot('centroid')
    clusterGizmo.setConstraint('centroid', null)
  })

  store.subscribe((newState, previousState) => {
    if (!newState.translateRotateActive) return
    if (
      newState.selection === previousState.selection
      && newState.activeInstanceId === previousState.activeInstanceId
    ) return
    refreshCurrentSelection()
  })

  store.subscribe(async (newState, previousState) => {
    if (!newState.translateRotateActive || newState.selection === previousState.selection) return
    const selectedBases = (newState.selection?.items ?? [])
      .filter(reference => reference.kind === 'base')
    if (selectedBases.length !== 1 || !nucleotideTransformTool.canActivate()) return
    await translateRotateTool.cancel()
    nucleotideTransformTool.activate()
  })

  store.subscribe((newState, previousState) => {
    translateRotateTool.handleSelectionChange(newState, previousState)
  })
  store.subscribe((newState, previousState) => {
    translateRotateTool.handleMultiClusterSelectionChange(newState, previousState)
  })
  store.subscribe((newState, previousState) => {
    if (
      newState.deformToolActive
      && !previousState.deformToolActive
      && isTranslateRotateActive()
    ) cancelTranslateRotateTool()
  })

  store.subscribe((newState, previousState) => {
    if (!newState.translateRotateActive) {
      if (previousState.translateRotateActive) clusterGlowLayer.clear()
      return
    }
    const activeId = newState.activeClusterId
    if (!activeId) {
      if (previousState.activeClusterId) clusterGlowLayer.clear()
      return
    }
    if (
      activeId === previousState.activeClusterId
      && newState.currentGeometry === previousState.currentGeometry
      && previousState.translateRotateActive
    ) return
    const cluster = newState.currentDesign?.cluster_transforms
      ?.find(item => item.id === activeId)
    if (!cluster) {
      clusterGlowLayer.clear()
      return
    }
    clusterGlowLayer.setEntries(clusterBackboneEntries(cluster, newState.currentDesign))
  })

  store.subscribe((newState, previousState) => {
    nucleotideTransformTool.handleSelectionChange?.(newState, previousState)
  })
}
