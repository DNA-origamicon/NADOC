import {expect,it,vi} from 'vitest'
import * as THREE from 'three'
import {registerEMExport,settleEMExport,prepareEMExportSize,hasVisibleEM} from './em_export.js'
it('awaits every active optical provider, propagates failures and unregisters independently',async()=>{
 const scene={}, other={}, order=[];let release
 const stop=registerEMExport(scene,async()=>{await new Promise(r=>{release=r});order.push('ready')})
 const fail=registerEMExport(scene,()=>{throw new Error('missing frame')})
 const pending=settleEMExport(scene)
 expect(order).toEqual([])
 await settleEMExport(other)
 release();await expect(pending).rejects.toThrow('missing frame')
 expect(order).toEqual(['ready']);stop();fail()
 await expect(settleEMExport(scene)).resolves.toBeUndefined()
})
it('scales EM points only, including both crossfade clouds, and restores sizes',()=>{
 const scene=new THREE.Scene()
 const fields=[3,7].map(size=>new THREE.Points(new THREE.BufferGeometry(),new THREE.PointsMaterial({size})))
 for(const p of fields){p.userData.emSamples=true;scene.add(p)}
 const other=new THREE.Points();scene.add(other)
 const restore=prepareEMExportSize(scene,4)
 expect(fields.map(p=>p.material.size)).toEqual([12,28]);expect(other.material.size).toBe(1)
 restore();expect(fields.map(p=>p.material.size)).toEqual([3,7])
})

it('requests an EM palette only for populated visible fields',()=>{
 const scene=new THREE.Scene(),root=new THREE.Group(),points=new THREE.Points()
 root.add(points);scene.add(root);points.userData.emSamples=true
 expect(hasVisibleEM(scene)).toBe(false)
 points.geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0],3))
 expect(hasVisibleEM(scene)).toBe(true)
 root.visible=false;expect(hasVisibleEM(scene)).toBe(false)
})
