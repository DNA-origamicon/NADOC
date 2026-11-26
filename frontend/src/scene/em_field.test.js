import {compactEMVolume} from '../ui/em_frame_cache.js'
import { expect, it } from 'vitest'
import * as THREE from 'three'
import { fieldSamples, createEMFieldOverlay } from './em_field.js'
const data = { shape:[2,2,2], lower_nm:[0,0,0], upper_nm:[1,1,1], origin_nm:[10,20,30],
 basis:[[0,1,0],[1,0,0],[0,0,-1]], intensity:[1,2,3,4,5,6,7,8], outside:[false,true,true,true,true,true,true,true],
 polarization_world:[0,1,0], propagation_world:[0,0,-1] }
it('maps local samples to world coordinates and masks metal without changing inputs',()=>{
 const before=JSON.stringify(data)
 const samples=fieldSamples(data,{mode:'volume',minimum:7})
 expect(Array.from(samples.positions)).toEqual([11,21,30,11,21,29])
 expect(samples.colors.length).toBe(6); expect(JSON.stringify(data)).toBe(before)
 expect(fieldSamples(data,{mode:'xy',slice:0}).positions.length).toBe(9)
})
it('cleans up scene resources after replacement and disposal',()=>{
 const scene=new THREE.Scene(), overlay=createEMFieldOverlay(scene)
 overlay.show(data,{mode:'volume',minimum:1,maximum:100})
 expect(scene.children[0].userData.sampleCount).toBe(7)
 expect(scene.children[0].children.every(o=>o.isPoints || o.name==='em-illumination')).toBe(true)
 overlay.clear(); expect(scene.children[0].children).toHaveLength(0)
 overlay.dispose();expect(scene.children).toHaveLength(0)
})
it('uses adaptive positions and cell intersections for physical slices', () => {
 const adaptive = {...data, shape:[3], sampling:{layout:'octree'}, lower_nm:[0,0,0], upper_nm:[2,2,2],
  sample_positions_nm:[[.5,.5,.5],[1.5,.5,.5],[1,1.5,1.5]], cell_sizes_nm:[[1,1,1],[1,1,1],[2,1,1]],
  intensity:[2,3,4], outside:[true,true,true]}
 expect(Array.from(fieldSamples(adaptive,{mode:'yz',slice:.5}).positions)).toEqual([10.5,21.5,29.5,11.5,21,28.5])
 expect(fieldSamples(adaptive,{mode:'xy',slice:1}).positions.length).toBe(3)
 expect(fieldSamples(adaptive,{minimum:3}).positions.length).toBe(6)
})
it('applies dot size in pixels to both cloud and slice materials', () => {
 const scene = new THREE.Scene(), overlay = createEMFieldOverlay(scene)
 for (const mode of ['volume', 'xy']) {
  overlay.show(data, {mode, minimum:1, maximum:100, dotSize:7.5})
  const points = scene.children[0].children.find(object => object.isPoints)
  expect(points.material.size).toBe(7.5)
  expect(points.material.sizeAttenuation).toBe(false)
 }
 overlay.dispose()
})

it('reuses render objects and keeps prepared frame arrays independent',()=>{
 const scene=new THREE.Scene(), overlay=createEMFieldOverlay(scene), options={mode:'volume',minimum:1}
 overlay.show(data,options)
 const points=scene.children[0].children[0], initial=Array.from(points.geometry.attributes.position.array)
 overlay.show({...data,origin_nm:[100,200,300]},options)
 expect(scene.children[0].children[0]).toBe(points)
 overlay.show(data,options)
 expect(Array.from(points.geometry.attributes.position.array)).toEqual(initial)
 overlay.dispose()
})

it('compact float64 fields preserve cloud and slice samples',()=>{
 const adaptive = {...data, shape:[2], sampling:{layout:'octree'},
  sample_positions_nm:[[.1,.2,.3],[.8,.7,.6]], cell_sizes_nm:[[.2,.2,.2],[.4,.4,.4]],
  intensity:[2.123456789012345,4], outside:[true,true]}
 const compact = compactEMVolume(structuredClone(adaptive))
 expect(compact.intensity[0]).toBe(adaptive.intensity[0])
 for(const mode of ['volume','xy','xz','yz'])
  expect(fieldSamples(compact,{mode,slice:.5})).toEqual(fieldSamples(adaptive,{mode,slice:.5}))
 const uniform = compactEMVolume({...data, intensity:[[[1,2],[3,4]],[[5,6],[7,8]]], outside:[[[false,true],[true,true]],[[true,true],[true,true]]]})
 expect(fieldSamples(uniform)).toEqual(fieldSamples(data))
})
it('crossfades unequal adaptive clouds with opacity-only subframes and exact endpoints',()=>{
 const scene=new THREE.Scene(),overlay=createEMFieldOverlay(scene),opts={mode:'volume',minimum:1}
 const b={...data,shape:[1],sampling:{layout:'octree'},sample_positions_nm:[[.5,.5,.5]],cell_sizes_nm:[[1,1,1]],intensity:[5],outside:[true]}
 overlay.showTransition(data,b,.25,opts)
 const root=scene.children[0],points=root.children[0],second=root.children.find(c=>c.name==='experimental-em-field').children[0]
 expect(points.geometry.attributes.position.count).toBe(7)
 expect(second.geometry.attributes.position.count).toBe(1)
 expect(points.material.opacity).toBeCloseTo(.24*.75)
 expect(second.material.opacity).toBeCloseTo(.24*.25)
 const version=points.geometry.attributes.position.version,otherVersion=second.geometry.attributes.position.version
 overlay.showTransition(data,b,.75,opts)
 expect(points.geometry.attributes.position.version).toBe(version)
 expect(second.geometry.attributes.position.version).toBe(otherVersion)
 expect(points.material.opacity).toBeCloseTo(.24*.25)
 overlay.showTransition(data,b,1,opts)
 expect(root.children[0].geometry.attributes.position.count).toBe(1)
 expect(root.children[0].material.opacity).toBe(.24)
 expect(root.userData.interpolation).toBeUndefined()
 overlay.dispose();expect(scene.children).toHaveLength(0)
})

it('crossfades illumination with the field and removes all lights on clear',()=>{
 const scene=new THREE.Scene(),overlay=createEMFieldOverlay(scene)
 const b={...data,intensity:data.intensity.map(v=>v*2)}
 overlay.showTransition(data,b,.25,{mode:'volume',minimum:1,lighting:'illuminate'})
 let count=0
 scene.traverse(o=>{if(o.userData.emLight){count++;const second=o.parent.parent.parent.name==='experimental-em-field';expect(o.intensity).toBeCloseTo(o.userData.emIntensity*(second ? .25 : .75))}})
 expect(count).toBe(16)
 overlay.clear();scene.traverse(o=>expect(o.isLight).not.toBe(true))
 overlay.dispose()
})
