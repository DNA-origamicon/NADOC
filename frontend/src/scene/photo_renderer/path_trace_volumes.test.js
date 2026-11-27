import {it,expect} from 'vitest'
import * as T from 'three'
import {createEMFieldOverlay} from '../em_field.js'
import {nativeTraceVolumes} from './path_trace_volumes.js'
it('transports original adaptive cells, palette, cutoff and crossfade without camera geometry',()=>{
 const scene=new T.Scene(),overlay=createEMFieldOverlay(scene)
 const data={sampling:{layout:'octree'},sample_positions_nm:[[1,0,0],[0,1,0],[0,0,1],[0,0,0]],display_tetrahedra:[[0,1,2,3]],intensity:[119,4,3,2],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]]}
 try{
  overlay.show(data,{mode:'smooth',minimum:3});overlay.weight(.37)
  const [v]=nativeTraceVolumes(scene)
  expect(v.weight).toBe(.37);expect(v.minimum).toBe(3)
  expect(Array.from(new Float32Array(v.values.buffer,v.values.byteOffset,4))).toEqual(data.intensity)
  expect(v.palette.byteLength).toBe(4096)
  overlay.clear();expect(nativeTraceVolumes(scene)).toEqual([])
 }finally{overlay.dispose()}
})
