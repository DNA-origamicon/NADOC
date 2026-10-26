import { expect, it, vi } from 'vitest'
import { createGroupPanelBindings } from './group_panel_bindings.js'
import { groupDesign } from '../test-helpers/part_groups.js'

it('previews cluster style in every renderer without changing the source', () => {
  const design = groupDesign(); delete design.group_organization
  const before = JSON.stringify(design)
  const renderers = Array.from({ length: 5 }, () => ({ refreshClusterDisplay: vi.fn() }))
  const binding = createGroupPanelBindings({ store: { getState: () => ({ currentDesign: design }) },
    designRenderer: renderers[0], unfoldView: renderers[1],
    overhangLinkArcs: renderers[2], flexibleArcs: renderers[3], getAtomSurface: () => renderers[4] })
  binding.onStylePreview('same', { opacity: 0.2 }, { opacity: 0.2, color: '#ffffff' })
  for (const renderer of renderers) {
    const preview = renderer.refreshClusterDisplay.mock.calls[0][0]
    expect(preview.cluster_transforms.find(g => g.id === 'same').opacity).toBe(0.2)
  }
  expect(JSON.stringify(design)).toBe(before)
})
