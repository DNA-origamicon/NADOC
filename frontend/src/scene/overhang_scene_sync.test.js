import { expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
const layers=vi.hoisted(()=>({
  locations:{isVisible:()=>false,rebuild:vi.fn()},
  links:{rebuild:vi.fn(),applyFemPositions:vi.fn()},
  flex:{rebuild:vi.fn()},markers:{rebuild:vi.fn()},
}))
vi.mock('./overhang_locations.js',()=>({initOverhangLocations:()=>layers.locations}))
vi.mock('./overhang_link_arcs.js',()=>({initOverhangLinkArcs:()=>layers.links}))
vi.mock('./flexible_arcs.js',()=>({initFlexibleArcs:()=>layers.flex}))
vi.mock('./unligated_crossover_markers.js',()=>({initUnligatedCrossoverMarkers:()=>layers.markers}))
vi.mock('./overhang_maps.js',()=>({buildSpecMap:()=>new Map(),buildDomainMapFromDesign:()=>new Map(),buildJunctionMapFromDomains:()=>new Map(),buildRootMap:()=>new Map()}))
import { initOverhangSceneSync } from './overhang_scene_sync.js'

it('annotation edits retain live connector buffers; geometry edits still rebuild them',()=>{
  const design={id:'d',annotations:[]}, geometry=[{id:'base'}]
  const store=createMockStore({currentDesign:design,currentGeometry:geometry})
  let frame
  initOverhangSceneSync({scene:{},store,designRenderer:{getHelixCtrl:()=>null,subscribeSimulation:fn=>{frame=fn}},assemblyRenderer:{onRebuildComplete:vi.fn()}})
  frame([{backbone_position:[8,0,0]}],1)
  vi.clearAllMocks()
  store.setState({currentDesign:{...design,annotations:[{id:'note',highlight_type:'silhouette'}]}})
  store.setState({currentDesign:{...store.getState().currentDesign,annotations_enabled:false}})
  for(const layer of [layers.links,layers.flex,layers.markers]) expect(layer.rebuild).not.toHaveBeenCalled()
  store.setState({currentGeometry:[{id:'moved-base'}]})
  for(const layer of [layers.links,layers.flex,layers.markers]) expect(layer.rebuild).toHaveBeenCalledOnce()
})
