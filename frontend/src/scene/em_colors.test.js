import {expect,it} from 'vitest'
import {emColorFraction,emColorRGB,normalizeEMColors} from './em_colors.js'
import {colormapRGB} from '../ui/colormaps.js'
import {fieldSamples} from './em_field.js'
import {smoothEMGrid,createSmoothEMMeshes} from './em_smooth.js'
it('maps intensity decades evenly with saturated bounds',()=>{
 expect(emColorFraction(.1)).toBe(0);expect(emColorFraction(1)).toBeCloseTo(1/3)
 expect(emColorFraction(10)).toBeCloseTo(2/3);expect(emColorFraction(1000)).toBe(1)
 expect(emColorFraction(10,{colorMinimum:1,maximum:100})).toBe(.5)
 expect(emColorRGB(10,{colorMinimum:1,maximum:100,colormap:'magma'})).toEqual(colormapRGB('magma',.5))
})
it('rejects invalid stored ranges and preserves valid preferences',()=>{
 for(const invalid of [NaN,Infinity,-1,0]){
  const settings=normalizeEMColors({colorMinimum:invalid,maximum:invalid,colormap:'missing'})
  expect(settings.colorMinimum).toBe(.1);expect(settings.maximum).toBe(100);expect(settings.colormap).toBe('viridis')
 }
 expect(normalizeEMColors({colorMinimum:10,maximum:1}).maximum).toBeGreaterThan(10)
})
it('uses the same mapping for points and smooth contour materials without changing positions',()=>{
 const data={shape:[3,3,3],intensity:Array(27).fill(10),outside:Array(27).fill(true),origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],lower_nm:[0,0,0],upper_nm:[2,2,2]}
 const options={colorMinimum:3,maximum:100,colormap:'magma',minimum:3}
 const points=fieldSamples(data,options)
 expect(Array.from(points.colors.slice(0,3))).toEqual(colormapRGB('magma',emColorFraction(10,options)).map(Math.fround))
 const grid=smoothEMGrid(data),a=createSmoothEMMeshes(data,grid,options),b=createSmoothEMMeshes(data,grid,{...options,colormap:'gray'})
 expect(a[0].geometry.attributes.position.array).toEqual(b[0].geometry.attributes.position.array)
 expect(a[0].material.opacity).toBe(b[0].material.opacity)
 expect(a[0].material.emissive.equals(b[0].material.emissive)).toBe(false)
 for(const mesh of [...a,...b]){mesh.geometry.dispose();mesh.material.dispose()}
})
it('recolors an existing smooth field without rebuilding its contour geometry',async()=>{
 const {Scene}=await import('three'),{createEMFieldOverlay}=await import('./em_field.js')
 const scene=new Scene(),overlay=createEMFieldOverlay(scene)
 const data={shape:[3,3,3],intensity:Array(27).fill(10),outside:Array(27).fill(true),origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],lower_nm:[0,0,0],upper_nm:[2,2,2]}
 overlay.show(data,{mode:'smooth',minimum:3,colormap:'jet'})
 const mesh=scene.children[0].children.find(o=>o.isMesh),geometry=mesh.geometry,color=mesh.material.uniforms.palette.value.image.data.slice()
 overlay.show(data,{mode:'smooth',minimum:3,colormap:'magma'})
 expect(scene.children[0].children.find(o=>o.isMesh).geometry).toBe(geometry)
 expect(mesh.material.uniforms.palette.value.image.data).not.toEqual(color)
 overlay.dispose()
})
