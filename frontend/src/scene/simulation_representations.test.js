import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { simulationGeometry, createSimulationRepresentations, simulationRepresentationAllowed } from './simulation_representations.js'
const geometry = [0,1,2,3,4,5].map(bp => ({ helix_id:'h', bp_index:bp, direction:'FORWARD', strand_id:'s', copy:0,
  backbone_position:[0,0,bp], axis_position:[0,0,bp], base_normal:[1,0,0], axis_tangent:[0,0,1] }))
const positions = geometry.map(n => ({helix_id:'h',bp_index:n.bp_index,direction:'FORWARD',backbone_position:[10,20,n.bp_index],nx:1,ny:0,nz:0,tx:0,ty:0,tz:1}))
it('projects only matched Physical positions without mutating authored geometry', () => {
  const original = JSON.stringify(geometry)
  expect(simulationGeometry(geometry,positions)[2].axis_position).toEqual([10,20,2])
  expect(JSON.stringify(geometry)).toBe(original)
  expect(simulationRepresentationAllowed('surface')).toBe(false)
  expect(simulationRepresentationAllowed('mrdna-fine')).toBe(true)
})
it('renders both mrDNA resolutions at simulated positions, keeps scalar colours and follows frame updates', async () => {
  const scene = new THREE.Scene(), visible = vi.fn()
  let updates=positions, listener, repr='mrdna-coarse'
  const renderer = {getFemPositions:()=>updates,getScalarColors:()=>new Map(geometry.map(n=>[`h:${n.bp_index}:FORWARD`,0xff0000])),
    subscribeSimulation: fn => {listener=fn} }
  const view = createSimulationRepresentations({scene,store:{getState:()=>({currentGeometry:geometry,currentDesign:{strands:[]}})},
    designRenderer:renderer,setCGVisible:visible,getRepresentation:()=>repr})
  for (const [mode,count] of [['mrdna-coarse',2],['mrdna-fine',6]]) {
    repr=mode;expect(view.apply()).toBe(true)
    const mesh=scene.children.find(m=>m.geometry?.type==='SphereGeometry')
    expect(mesh.count).toBe(count)
    const m=new THREE.Matrix4();mesh.getMatrixAt(0,m);expect(m.elements[12]).toBe(10)
    const color=new THREE.Color();mesh.getColorAt(0,color);expect(color.getHex()).toBe(0xff0000)
  }
  updates=positions.map(n=>({...n,backbone_position:[30,40,50]}));listener();await Promise.resolve()
  const m=new THREE.Matrix4();scene.children.find(m=>m.geometry?.type==='SphereGeometry').getMatrixAt(0,m)
  expect(m.elements[12]).toBe(30)
  expect(visible).toHaveBeenLastCalledWith(false)
  updates=null;listener();await Promise.resolve()
  expect(scene.children).toHaveLength(0)
  view.dispose()
  updates=positions;listener();await Promise.resolve()
  expect(scene.children).toHaveLength(0)
})
