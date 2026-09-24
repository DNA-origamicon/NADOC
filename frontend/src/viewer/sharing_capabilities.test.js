import { it, expect } from 'vitest'
import { requireSharingCapabilities } from './sharing_capabilities.js'
it.each([
  ['requiresHullCutoutViewer', 'hull-cutouts-v1'],
  ['requiresOverlayViewer', 'multi-overlay-v1'],
  ['requiresVisualizationLabelViewer', 'visualization-labels-v1'],
  ['requiresSelectionViewer', 'selection-ping-v1'],
  ['requiresAnnotationsViewer', 'annotations-v1'],
  ['requiresViewToolsViewer', 'view-tools-v1'],
  ['requiresImpostorViewer', 'sphere-impostors-v1'],
  ['requiresWideLineViewer', 'guest-visualizations-v1'],
  ['requiresSectionViewer', 'editor-broadcast-v1'],
])('enforces %s for all publication paths', (flag, capability) => {
  expect(() => requireSharingCapabilities({ [flag]: true }, [])).toThrow('Restart presentation hosting')
  expect(() => requireSharingCapabilities({ [flag]: true }, [capability])).not.toThrow()
  expect(() => requireSharingCapabilities({ [flag]: false }, [])).not.toThrow()
})
