import { expect, it, vi } from 'vitest'
import { createGroupPanelBindings } from './group_panel_bindings.js'
import { groupDesign } from '../test-helpers/part_groups.js'

it('wires typed groups and live previews to every existing renderer without changing placements', () => {
  const design = groupDesign(), before = JSON.stringify(design)
  const renderers = Array.from({ length: 5 }, () => ({ refreshClusterDisplay: vi.fn() }))
  const selectionManager = { togglePartGroup: vi.fn(), selectPartGroup: vi.fn() }
  const visibilityController = { hide: vi.fn(), show: vi.fn() }
  const binding = createGroupPanelBindings({ store: { getState: () => ({ currentDesign: design }) },
    selectionManager, visibilityController, designRenderer: renderers[0], unfoldView: renderers[1],
    overhangLinkArcs: renderers[2], flexibleArcs: renderers[3], getAtomSurface: () => renderers[4] })
  binding.onGroupClick({ id: 'same' }); binding.onGroupClick({ id: 'same', additive: true })
  expect(selectionManager.selectPartGroup).toHaveBeenCalledWith('same')
  expect(selectionManager.togglePartGroup).toHaveBeenCalledWith('same')
  binding.onGroupVisibilityChange('same', true)
  expect(visibilityController.hide).toHaveBeenCalledWith({ partGroupIds: ['same'] })
  binding.onGroupStylePreview('same', { opacity: 0.2 }, { opacity: 0.2, color: '#ffffff' })
  for (const renderer of renderers) {
    const preview = renderer.refreshClusterDisplay.mock.calls[0][0]
    expect(preview.cluster_transforms).toBe(design.cluster_transforms)
    expect(preview.group_organization.groups.find(g => g.id === 'same').opacity).toBe(0.2)
  }
  expect(JSON.stringify(design)).toBe(before)
})
