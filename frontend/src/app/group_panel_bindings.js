import { withClusterDisplay } from '../scene/cluster_entries.js'

/** Cluster sidebar wiring; previews never write canonical design or placement. */
export function createGroupPanelBindings({ store,
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
    onStylePreview: (id, patch, uiState) => preview(withClusterDisplay, id, patch, uiState),
  }
}
