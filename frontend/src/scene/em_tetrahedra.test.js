import {it,expect} from 'vitest'
import {adaptiveEMGrid,tetraContour} from './em_tetrahedra.js'
import {createSmoothEMMeshes,smoothEMGrid} from './em_smooth.js'
const fixture=()=>({sampling:{layout:'octree'},sample_positions_nm:[[0,0,0],[.001,0,0],[0,.001,0],[0,0,.001]],
 display_tetrahedra:[[0,1,2,3]],intensity:[100,1,1,1],outside:[true,true,true,true],
 origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]]})
it('retains a tiny 100x sample exactly and interpolates its 99x contour without dilution',()=>{
 const source=fixture(),before=JSON.stringify(source),grid=adaptiveEMGrid(source)
 expect(Array.from(grid.values)).toEqual([100,1,1,1])
 const geometry=tetraContour(grid,99),p=geometry.attributes.position
 expect(p.count).toBe(3)
 for(let i=0;i<p.count;i++)expect(p.getX(i)+p.getY(i)+p.getZ(i)).toBeCloseTo(.001/99,10)
 expect(JSON.stringify(source)).toBe(before);geometry.dispose()
 const meshes=createSmoothEMMeshes(source,grid)
 expect(meshes).toHaveLength(32)
 expect(meshes.at(-1).material.emissive.r).toBeGreaterThan(.95)
 for(const mesh of meshes){mesh.geometry.dispose();mesh.material.dispose()}
})
it('masks vertices and accepts compact connectivity without changing sample positions',()=>{
 const source=fixture();source.outside[0]=false
 source.display_tetrahedra=new Uint32Array(source.display_tetrahedra.flat())
 source.sample_positions_nm=new Float64Array(source.sample_positions_nm.flat())
 const grid=adaptiveEMGrid(source)
 expect(grid.values[0]).toBe(0)
 const g=tetraContour(grid,3);expect(g.attributes.position.count).toBe(0);g.dispose()
})
it('retains all nodes of a 49 cubed uniform grid, including isolated peaks',()=>{
 const n=49,input={shape:[n,n,n],lower_nm:[0,0,0],upper_nm:[48,48,48],outside:new Uint8Array(n**3).fill(1),intensity:new Float64Array(n**3).fill(1)}
 input.intensity[13*n*n+13*n+13]=100
 const grid=smoothEMGrid(input)
 expect(grid.size).toBe(53)
 expect(grid.values.reduce((a,b)=>Math.max(a,b),0)).toBeCloseTo(Math.log10(101),6)
})
it('triangulates a two-high two-low contour with outward normals',()=>{
 const source=fixture();source.intensity=[100,100,0,0]
 const g=tetraContour(adaptiveEMGrid(source),50),p=g.attributes.position,n=g.attributes.normal
 expect(p.count).toBe(6)
 for(let i=0;i<p.count;i++){
  expect(p.getY(i)+p.getZ(i)).toBeCloseTo(.0005,9)
  expect(n.getY(i)+n.getZ(i)).toBeGreaterThan(1)
 }
 g.dispose()
})
