/** Owns design-scene visibility and its crossover diagnostics. */
export function initDesignSceneVisibility({
  scene, store, designRenderer, bluntEnds, endExtrudeArrows,
  jointRenderer, unfoldView, overhangLinkArcs, surfaceStrandsOverlay,
}) {
  /**
   * Show or hide ALL design-level scene geometry.
   * Called when toggling assembly mode so the loaded design doesn't bleed through
   * while assembly instances are shown (or while the scene is empty).
   *
   * SCENE GEOMETRY RULE — every element that renders design data must be listed here:
   *   1. designRenderer  — _helixCtrl.root: beads, slabs, axis arrows, extension beads,
   *                        extra-base crossover beads+slabs (children of root — ONE scene object)
   *   2. bluntEnds       — helix-end rings + number-sprite axis labels
   *   3. endExtrudeArrows — drag-to-resize handles on helix ends
   *   4. jointRenderer   — cluster joint axis indicators
   *   5. unfoldView      — crossover arc LINE geometry (_arcGroup / 'xoverArcLines')
   *                        NB: arc lines are a SEPARATE scene object from root.
   *                        Extra-base beads+slabs are children of root (no separate call needed).
   *                        Arc lines require an explicit unfoldView.setArcsVisible() call.
   *
   * If you add a new scene module that renders design geometry, add its
   * setVisible() call here so assembly mode automatically suppresses it.
   * Use window.__nadocDebugXovers() in the browser console to verify.
   */
  function setVisible(visible) {
    designRenderer.setDesignVisible(visible)
    bluntEnds.setVisible(visible)
    endExtrudeArrows.setVisible(visible)
    jointRenderer.setVisible(visible)
    unfoldView.setArcsVisible(visible)  // arc lines (_arcGroup); LOD/rep gating is per-arc (refreshArcVisibility)
    unfoldView.refreshArcVisibility()
    overhangLinkArcs?.setVisible?.(visible)
    surfaceStrandsOverlay?.setVisible?.(visible)
  }

  /**
   * Browser console debug tool — inspect the visibility state of every
   * crossover-arc-related scene object.
   *
   * Usage: window.__nadocDebugXovers()
   *
   * Reports on four layers (design_renderer is now 1 scene object, not 2):
   *   'designRoot'       — _helixCtrl.root (beads, slabs, extra-base beads/slabs as children)
   *   'xoverExtraBeads'  — extra-base bead InstancedMesh (child of root, inherited visibility)
   *   'arcLines'         — unfoldView._arcGroup (LINE geometry; 'xoverArcLines')
   *   'bluntEnds'        — blunt-end rings + number labels
   */
  window.__nadocDebugXovers = function () {
    // Scan the live scene (including children) for objects by their debug names.
    const found = {}
    scene.traverse(obj => {
      if (obj.name) found[obj.name] = obj
    })

    const fmt = (obj, extra = {}) => obj
      ? { visible: obj.visible, parentVisible: obj.parent?.visible ?? null, ...extra }
      : 'NOT IN SCENE'

    const arcInfo = unfoldView.getArcDebugInfo()
    const root = designRenderer.getHelixCtrl()?.root

    const report = {
      // Layer 1 — design_renderer (single scene object; extra-base beads are children)
      designRoot: root
        ? { visible: root.visible, childCount: root.children.length }
        : 'no root (design not loaded)',
      xoverExtraBeads: found['xoverExtraBeads']
        ? fmt(found['xoverExtraBeads'], {
            count: found['xoverExtraBeads'].count,
            // 'crossoverConnections' group is the parent; root is grandparent
            groupVisible: found['crossoverConnections']?.visible ?? null,
          })
        : 'not built (design has no extra-base crossovers)',

      // Layer 5 — unfold_view arc lines (still a separate scene sibling)
      arcLines: {
        group:    fmt(found['xoverArcLines'], { childCount: found['xoverArcLines']?.children.length ?? 0 }),
        scaffold: found['xoverArcMerged_scaffold']
          ? fmt(found['xoverArcMerged_scaffold'], { arcCount: found['xoverArcMerged_scaffold'].userData.arcCount, xoverIds: found['xoverArcMerged_scaffold'].userData.arcXoverIds })
          : 'not built',
        staple:   found['xoverArcMerged_staple']
          ? fmt(found['xoverArcMerged_staple'],   { arcCount: found['xoverArcMerged_staple'].userData.arcCount,   xoverIds: found['xoverArcMerged_staple'].userData.arcXoverIds })
          : 'not built',
        perArcDetail: arcInfo,
      },
    }

    console.group('[NADOC] Crossover Arc Visibility Debug')
    console.log('assemblyActive:', store.getState().assemblyActive)
    console.log('──── Design root (single scene object):', report.designRoot)
    console.log('     extra-base beads (child of root):', report.xoverExtraBeads)
    console.log('──── Arc lines (_arcGroup, separate scene sibling):', report.arcLines.group)
    console.log('     scaffold merged:', report.arcLines.scaffold)
    console.log('     staple   merged:', report.arcLines.staple)
    console.log('──── Per-arc summary:',
      `total=${arcInfo.totalArcs}`,
      `hidden=${arcInfo.hiddenArcs}`,
      `scaffold=${arcInfo.arcsByType.scaffold}`,
      `staple=${arcInfo.arcsByType.staple}`,
    )
    if (arcInfo.arcs.length) console.table(arcInfo.arcs)
    console.groupEnd()

    return report
  }

  return { setVisible }
}
