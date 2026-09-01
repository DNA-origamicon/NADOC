import { describe, expect, it, vi } from 'vitest'
import { initDesignSceneVisibility } from './design_scene_visibility.js'

describe('design scene visibility', () => {
  it('hides the design-only surface-strands overlay in assembly mode', () => {
    const component = () => ({ setVisible: vi.fn() })
    const designRenderer = { setDesignVisible: vi.fn(), getHelixCtrl: vi.fn() }
    const bluntEnds = component()
    const endExtrudeArrows = component()
    const jointRenderer = component()
    const overhangLinkArcs = component()
    const surfaceStrandsOverlay = component()
    const unfoldView = { setArcsVisible: vi.fn(), refreshArcVisibility: vi.fn(), getArcDebugInfo: vi.fn() }
    const visibility = initDesignSceneVisibility({
      scene: { traverse: vi.fn() }, store: { getState: vi.fn(() => ({})) },
      designRenderer, bluntEnds, endExtrudeArrows, jointRenderer, unfoldView,
      overhangLinkArcs, surfaceStrandsOverlay,
    })

    visibility.setVisible(false)

    expect(surfaceStrandsOverlay.setVisible).toHaveBeenCalledWith(false)
  })
})
