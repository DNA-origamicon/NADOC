import {expect,it} from 'vitest'
import * as THREE from 'three'
import {emLightAccumulator,setEMGlow,updateEMLights} from './em_lighting.js'
it('conserves illustrative energy and centroid under adaptive-cell subdivision',()=>{
 const a=emLightAccumulator([0,0,0],10), b=emLightAccumulator([0,0,0],10)
 a.add([2,2,2],[1,.2,0],100,8)
 for(const x of [1.5,2.5])for(const y of [1.5,2.5])for(const z of [1.5,2.5])b.add([x,y,z],[1,.2,0],100,1)
 for(let i=0;i<8;i++) {
  expect(b.finish()[i].position).toEqual(a.finish()[i].position)
  b.finish()[i].color.forEach((v,j)=>expect(v).toBeCloseTo(a.finish()[i].color[j],12))
  expect(b.finish()[i].intensity).toBeCloseTo(a.finish()[i].intensity,12)
 }
 expect(a.finish().reduce((sum,l)=>sum+l.intensity,0)).toBeCloseTo(30)
})
it('bounds actual lights independent of sample count and never adds shadows',()=>{
 const a=emLightAccumulator([0,0,0],10), root=new THREE.Group()
 for(let i=0;i<100000;i++)a.add([i%2 ? 2 : -2,2,2],[1,0,0],5,1)
 updateEMLights(root,a.finish(),true)
 expect(root.children[0].children).toHaveLength(8)
 expect(root.children[0].children.every(l=>!l.castShadow && l.userData.emLight)).toBe(true)
 updateEMLights(root,a.finish(),false)
 expect(root.children[0].visible).toBe(false)
 expect(root.children[0].children.every(l=>l.intensity===0)).toBe(true)
})
it('makes samples luminous without altering scientific colors or creating individual lights',()=>{
 const material=new THREE.PointsMaterial({vertexColors:true,depthWrite:false})
 setEMGlow(material,true)
 const shader={fragmentShader:'#include <opaque_fragment>'};material.onBeforeCompile(shader)
 expect(shader.fragmentShader).toContain('gl_PointCoord')
 expect(material.blending).toBe(THREE.NormalBlending)
 expect(material.depthWrite).toBe(false)
 setEMGlow(material,false);expect(material.blending).toBe(THREE.NormalBlending)
})
