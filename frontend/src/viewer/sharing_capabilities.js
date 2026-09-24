/** Every publication path must enforce the same prepared-view compatibility rules. */
const FEATURES = [
  ['requiresVisualizationLabelViewer', 'visualization-labels-v1', 'simulation view labels'],
  ['requiresSelectionViewer', 'selection-ping-v1', 'selections and pings'],
  ['requiresAnnotationsViewer', 'annotations-v1', 'annotations'],
  ['requiresViewToolsViewer', 'view-tools-v1', 'view tools'],
  ['requiresImpostorViewer', 'sphere-impostors-v1', 'optimized protein spheres'],
  ['requiresWideLineViewer', 'guest-visualizations-v1', 'nanopore ion paths'],
  ['requiresSectionViewer', 'editor-broadcast-v1', 'sectioned views'],
]
export function requireSharingCapabilities(result, capabilities = []) {
  for (const [flag, capability, feature] of FEATURES) {
    if (result?.[flag] && !capabilities?.includes(capability)) {
      throw new Error(`Restart presentation hosting after the current meeting to share ${feature}.`)
    }
  }
}
