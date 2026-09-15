import {it,expect} from 'vitest'
import * as THREE from 'three'
import {initTwoElectrodePreview} from './namd_two_electrode_preview.js'
it('draws two schematic surfaces with correctly signed symbols outside the compartment on every axis',()=>{
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(55,1.5,.1,2000)
 camera.position.set(6,3,7)
 const controls={target:new THREE.Vector3(),update(){camera.lookAt(this.target)}}
 const preview=initTwoElectrodePreview({scene,camera,controls})
 const send=detail=>window.dispatchEvent(new CustomEvent('nadoc:two-electrode-setup',{detail}))
 for(const normal of ['x','y','z']){
  const axis={x:0,y:1,z:2}[normal]
  send({enabled:true,spec:{normal,gap_nm:10,width_nm:8,depth_nm:6,working_charge_C_m2:-.04,counter_charge_C_m2:.04}})
  const group=scene.children[0]
  expect(group.visible).toBe(true)
  expect(camera.position.length()).toBeGreaterThan(20)
  expect(group.children.filter(c=>c.isMesh)).toHaveLength(2)
  const symbols=group.children.filter(c=>c.userData.chargeSign)
  expect(symbols).toHaveLength(32)
  for(const symbol of symbols){expect(Math.abs(symbol.position.getComponent(axis))).toBeGreaterThan(5);expect(Math.sign(symbol.position.getComponent(axis))).toBe(symbol.userData.chargeSign)}
 }
 send({enabled:false});expect(scene.children[0].visible).toBe(false);expect(scene.children[0].children).toHaveLength(0)
 preview.dispose();expect(scene.children).toHaveLength(0)
})
