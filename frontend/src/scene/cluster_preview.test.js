import { it, expect, vi } from 'vitest'
import { createClusterPreview } from './cluster_preview.js'
import { createDisplayGeometry } from './display_geometry.js'
it('publishes all moving bodies once and refreshes selection after the complete frame', () => {
  const display=createDisplayGeometry(), observed=[], moved=[]
  const ctrl=display.observe({applyClusterTransform: id=>moved.push(id),captureClusterBase:vi.fn()})
  display.register('connections',{update:()=>observed.push([...moved])})
  const refresh=vi.fn(), renderer={getHelixCtrl:()=>ctrl,getDisplayGeometry:()=>display,refreshClusterSelection:refresh}
  const preview=createClusterPreview({renderer,getBluntEnds:()=>null,getJoints:()=>null,
    overhangLocations:{applyClusterTransform:vi.fn()},selectionManager:{refreshBaseGlow:vi.fn()}})
  preview.frame(()=>{preview.paint('a');preview.paint('b')})
  expect(observed).toEqual([['a','b']])
  expect(refresh).toHaveBeenCalledTimes(1)
})
