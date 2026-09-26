import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {periodicOffsets,initPeriodicImages} from './md_periodic_images.js'

it('places only the six face neighbors at full cell translations',()=>{
  expect(periodicOffsets([10,20,30])).toEqual([[-10,0,0],[10,0,0],[0,-20,0],[0,20,0],[0,0,-30],[0,0,30]])
  expect(periodicOffsets([10,NaN,30])).toEqual([])
  expect(periodicOffsets([10,0,30])).toEqual([])
})

it('shares bounded geometry, cannot be picked, updates offsets and cleans up',()=>{
  const scene=new THREE.Scene(),entries=[{pos:new THREE.Vector3(1,2,3)},{pos:new THREE.Vector3(4,5,6)}]
  const ui=initPeriodicImages({scene,getEntries:()=>entries})
  const emit=detail=>window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail}))
  const group=scene.getObjectByName('NAMD periodic images')
  emit({enabled:false,periodicImages:true,dimensions:[10,20,30]})
  expect(group.visible).toBe(true);expect(group.children).toHaveLength(6)
  expect(new Set(group.children.map(c=>c.geometry)).size).toBe(1)
  expect(new Set(group.children.map(c=>c.material)).size).toBe(1)
  expect(group.children[0].geometry.attributes.position.count).toBe(2)
  const hits=[];group.children[0].raycast(null,hits);expect(hits).toEqual([])
  expect(entries[0].pos.toArray()).toEqual([1,2,3])
  entries[0].pos.set(7,8,9);entries[0].defaultColor=0xff0000
  group.children[0].onBeforeRender({info:{render:{frame:1}}})
  expect(Array.from(group.children[0].geometry.attributes.position.array).slice(0,3)).toEqual([7,8,9])
  expect(Array.from(group.children[0].geometry.attributes.color.array).slice(0,3)).toEqual([1,0,0])

  const old=group.children[0].geometry,dispose=vi.spyOn(old,'dispose')
  emit({periodicImages:true,dimensions:[15,25,35]})
  expect(dispose).toHaveBeenCalledTimes(1)
  expect(group.children[5].position.toArray()).toEqual([0,0,35])
  window.dispatchEvent(new CustomEvent('nadoc:representation-change',{detail:{representation:'beads'}}))
  expect(group.visible).toBe(false)
  emit({enabled:true,periodicImages:false,dimensions:[15,25,35]})
  expect(group.visible).toBe(false);expect(group.children).toHaveLength(0)
  ui.dispose();expect(scene.children).toHaveLength(0)
  emit({periodicImages:true,dimensions:[10,20,30]});expect(scene.children).toHaveLength(0)
})

it('caps large previews at 12000 points per image and hides unavailable geometry',()=>{
  const scene=new THREE.Scene(),entries=Array.from({length:25000},(_,i)=>({pos:new THREE.Vector3(i,0,0)}))
  const ui=initPeriodicImages({scene,getEntries:()=>entries})
  window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{periodicImages:true,dimensions:[10,20,30]}}))
  const group=scene.getObjectByName('NAMD periodic images')
  expect(group.children[0].geometry.attributes.position.count).toBeLessThanOrEqual(12000)
  window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{enabled:false}}))
  expect(group.visible).toBe(false)
  ui.dispose()
})

it('uploads only changed channels and compares stored float precision',()=>{
  const scene=new THREE.Scene(),entries=[{pos:new THREE.Vector3(.1,.2,.3),defaultColor:0xabcdef}]
  const ui=initPeriodicImages({scene,getEntries:()=>entries})
  window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{periodicImages:true,dimensions:[10,20,30]}}))
  const ghost=scene.getObjectByName('NAMD periodic images').children[0]
  const {position,color}=ghost.geometry.attributes
  const pv=position.version,cv=color.version
  ghost.onBeforeRender({info:{render:{frame:1}}})
  expect(position.version).toBe(pv);expect(color.version).toBe(cv)
  entries[0].pos.x=2;ghost.onBeforeRender({info:{render:{frame:2}}})
  expect(position.version).toBe(pv+1);expect(color.version).toBe(cv)
  entries[0].defaultColor=0xff0000;ghost.onBeforeRender({info:{render:{frame:3}}})
  expect(position.version).toBe(pv+1);expect(color.version).toBe(cv+1)
  ui.dispose()
})
