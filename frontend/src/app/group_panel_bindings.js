import { withClusterDisplay } from '../scene/cluster_entries.js'
import { withPartGroupDisplay } from '../scene/part_group_display.js'

/** Shared sidebar wiring; previews never write canonical design or placement. */
export function createGroupPanelBindings({ store, selectionManager, visibilityController,
  designRenderer, unfoldView, overhangLinkArcs, flexibleArcs, getAtomSurface }) {
  const preview = (project, id, patch, uiState) => {
    const design = project(store.getState().currentDesign, id, uiState ?? patch)
    designRenderer.refreshClusterDisplay(design,
      { color: patch.color !== undefined, opacity: patch.opacity !== undefined })
    unfoldView.refreshClusterDisplay(design)
    overhangLinkArcs.refreshClusterDisplay(design)
    flexibleArcs.refreshClusterDisplay(design)
    getAtomSurface()?.refreshClusterDisplay(design)
  }
  return {
    onGroupClick: ({ id, additive = false }) => additive
      ? selectionManager.togglePartGroup(id) : selectionManager.selectPartGroup(id),
    onGroupVisibilityChange: (id, hidden) => visibilityController?.[hidden ? 'hide' : 'show']({ partGroupIds: [id] }),
    onGroupStylePreview: (id, patch, uiState) => preview(withPartGroupDisplay, id, patch, uiState),
    onStylePreview: (id, patch, uiState) => preview(withClusterDisplay, id, patch, uiState),
  }
}
