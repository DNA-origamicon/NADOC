import {describe,it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {initPreparationDetails} from './md_preparation_details.js'
describe('preparation details overlay',()=>{
  it('distinguishes liquid volume, slab faces and water margin without changing molecular entries',()=>{
    vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null)
    const scene=new THREE.Scene(),entry={pos:new THREE.Vector3(1,2,3)}
    const ui=initPreparationDetails({scene,getEntries:()=>[entry]})
    const detail={enabled:true,dimensions:[10,30,10],solvent:[10,10,10],boundary:'slab',normal_axis:1,numbers:{na:60,mg:0,cl:60},na:100,mg:0,temperature:300,temperatureLabel:'K'}
    window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail}))
    const group=scene.getObjectByName('NAMD box and solvent details')
    expect(group.visible).toBe(true)
    expect(group.children.filter(o=>o.userData.boundary==='slab')).toHaveLength(2)
    expect(group.children.filter(o=>o.userData.boundary==='periodic')).toHaveLength(4)
    expect(group.getObjectByName('Liquid compartment outline')).toBeTruthy()
    expect(group.getObjectByName('Cell dimension X').position.y).toBeLessThan(-15)
    expect(group.getObjectByName('Dimension extension X')).toBeTruthy()
    window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{...detail,boundary:'periodic',dimensions:[10,10,10]}}))
    expect(group.children.filter(o=>o.name==='Water margin highlight')).toHaveLength(6)
    expect(entry.pos.toArray()).toEqual([1,2,3])
    window.dispatchEvent(new CustomEvent('nadoc:box-solvent-details',{detail:{enabled:false}}))
    expect(group.visible).toBe(false)
    expect(group.children).toHaveLength(0)
    ui.dispose();expect(scene.children).toHaveLength(0)
    vi.restoreAllMocks()
  })
})
