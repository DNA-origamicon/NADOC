import {expect,it} from 'vitest'
import * as THREE from 'three'
import {smoothEMGrid,createSmoothEMMeshes,emContourOpacity} from './em_smooth.js'
import {createEMFieldOverlay} from './em_field.js'
const field=(value=10)=>({shape:[3,3,3],lower_nm:[-1,-1,-1],upper_nm:[1,1,1],origin_nm:[10,20,30],basis:[[0,1,0],[1,0,0],[0,0,-1]],intensity:Array(27).fill(value),outside:Array(27).fill(true)})
it('interpolates constant fields without changing input, masks invalid values and bounds the grid',()=>{
 const input=field(),before=JSON.stringify(input),g=smoothEMGrid(input)
 expect(g.values[g.values.length>>1]).toBeCloseTo(Math.log10(11),5)
 expect(g.size).toBeLessThanOrEqual(37)
 expect(JSON.stringify(input)).toBe(before)
 expect(Array.from(smoothEMGrid({...input,outside:Array(27).fill(false)}).values).every(x=>x===0)).toBe(true)
})
it('cuts off empty fields and creates finite smooth world-space meshes',()=>{
 const input=field(),grid=smoothEMGrid(input)
 expect(createSmoothEMMeshes(input,grid,{minimum:11})).toHaveLength(0)
 expect(createSmoothEMMeshes(field(1),smoothEMGrid(field(1)),{minimum:1})).toHaveLength(0)
 const meshes=createSmoothEMMeshes(input,grid,{minimum:2})
 expect(meshes.length).toBeGreaterThan(1)
 for(const m of meshes){
  expect(m.isMesh).toBe(true);expect(m.userData.emSmooth).toBe(true)
  expect(Array.from(m.geometry.attributes.position.array).every(Number.isFinite)).toBe(true)
  m.geometry.computeBoundingBox();expect(m.geometry.boundingBox.min.x).toBeGreaterThanOrEqual(8.8)
  expect(m.geometry.boundingBox.max.x).toBeLessThanOrEqual(11.2)
  m.geometry.dispose();m.material.dispose()
 }
})
it('switches points / smooth glow, crossfades mesh opacity, and releases overlays',()=>{
 const scene=new THREE.Scene(),overlay=createEMFieldOverlay(scene),a=field(),b=field(20),opts={mode:'smooth',minimum:2}
 overlay.show(a,opts);const root=scene.children[0],mesh=root.children.find(x=>x.isMesh)
 expect(mesh).toBeTruthy();const opacity=mesh.material.opacity
 overlay.weight(.5);expect(mesh.material.opacity).toBeCloseTo(opacity*.5)
 overlay.showTransition(a,b,.4,opts);expect(root.userData.interpolation).toBe(.4)
 overlay.show(a,{mode:'volume'});expect(root.children.some(x=>x.isPoints)).toBe(true)
 expect(root.children.some(x=>x.userData.emSmooth)).toBe(false)
 overlay.dispose();expect(scene.children).toHaveLength(0)
})

it('places a cutoff contour at the analytic radius of a smooth radial field',()=>{
 const n=25,input={...field(),shape:[n,n,n],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:[],outside:Array(n**3).fill(true)}
 for(let x=0;x<n;x++)for(let y=0;y<n;y++)for(let z=0;z<n;z++)input.intensity.push(10**(2-([x,y,z].reduce((s,v)=>s+(-1+2*v/(n-1))**2,0)))-1)
 const meshes=createSmoothEMMeshes(input,smoothEMGrid(input),{minimum:10**1.5-1})
 const position=meshes[0].geometry.attributes.position
 for(let i=0;i<position.count;i++)expect(Math.hypot(position.getX(i),position.getY(i),position.getZ(i))).toBeCloseTo(Math.sqrt(.5),1)
 for(const mesh of meshes){mesh.geometry.dispose();mesh.material.dispose()}
})

it('keeps weak foreground bands transparent and allocates glow to hotspots without layer-count dependence',()=>{
 expect(emContourOpacity(0,1)).toBe(0)
 const trans=(low,high,n)=>{let t=1;for(let i=0;i<n;i++){
  const a=low+(high-low)*i/n,b=low+(high-low)*(i+1)/n;t*=(1-emContourOpacity(a,b))**2
 }return t}
 expect(trans(1,3,32)).toBeGreaterThan(.95)
 expect(trans(1,100,32)).toBeCloseTo(trans(1,100,128),12)
 expect(emContourOpacity(1,3)).toBeLessThan(emContourOpacity(50,100)/10)
 expect(trans(1,100,32)).toBeCloseTo(Math.exp(-1.6),12)
})
