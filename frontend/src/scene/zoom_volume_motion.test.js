// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createZoomLayerMotion, zoomMotionFrame, zoomLiveAtoms } from './zoom_volume_motion.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { buildHelixObjects } from './helix_renderer.js'
const n = {placement_source:'native-full-o5-v1',slab_position:[.67,0,0],slab_quaternion:[0,Math.SQRT1_2,Math.SQRT1_2,0],helix_id:'h',bp_index:0,direction:'FORWARD',strand_id:'s',strand_type:'staple',domain_index:0,backbone_position:[1,0,0],base_position:[.5,0,0],base_normal:[-1,0,0],axis_tangent:[0,0,1]}

it('uses displayed amplified positions, preserves measured orientation, and distinguishes loop copies',()=>{
  const copy={...n,copy_k:1}
  const frame=zoomMotionFrame([n,copy],[{...n,nx:0,ny:1,nz:0,backbone_position:[3,0,0],measured_base:true,base_position:[3,1,0]}],[{nuc:n,pos:new THREE.Vector3(5,0,0)},{nuc:copy,pos:new THREE.Vector3(8,0,0)}])
  expect(frame[0]).toMatchObject({backbone_position:[5,0,0],nx:0,ny:1,measured_base:true,base_position:[3,1,0]})
  expect(frame[1].backbone_position).toEqual([8,0,0])
  expect(n.backbone_position).toEqual([1,0,0])
})
it('moves existing Full bead/slab buffers on intermediate frames without rebuilding',()=>{
  const cg=buildHelixObjects([n],{helices:[],strands:[{id:'s',strand_type:'staple',domains:[]}]},new THREE.Scene())
  const entry={ready:true,cg,columns:new Map([['h:0','full']])}
  const motion=createZoomLayerMotion({entries:new Map([['z',entry]])},[n])
  const mesh=cg.backboneEntries[0].instMesh
  for (const x of [2,2.25,2.75,3]) {
    motion.apply(zoomMotionFrame([n],[{...n,backbone_position:[x,0,0]}]))
    expect(cg.backboneEntries[0].pos.x).toBe(x)
    expect(cg.backboneEntries[0].instMesh).toBe(mesh)
  }
  motion.apply(zoomMotionFrame([n],null))
  expect(cg.backboneEntries[0].pos.x).toBe(1)
})
it('copies exact live atom coordinates by nucleotide/name, independent of serial numbering',()=>{
  const source=initAtomisticRenderer(new THREE.Scene()), target=initAtomisticRenderer(new THREE.Scene())
  source.setMode('ballstick');target.setMode('ballstick')
  source.update({atoms:[{...n,serial:99,name:'P',element:'P',x:7,y:8,z:9}],bonds:[]})
  target.update({atoms:[{...n,serial:2,name:'P',element:'P',x:1,y:0,z:0}],bonds:[]})
  const motion=createZoomLayerMotion({entries:new Map([['z',{ready:true,kind:'atom',renderer:target}]])},[n])
  motion.apply(zoomMotionFrame([n],[{...n,backbone_position:[4,0,0]}]),zoomLiveAtoms(source))
  target.visitAtoms((a,p)=>expect(p.toArray()).toEqual([7,8,9]))
  for (const fraction of [.25,.5,.75,1]) {
    const point=[7+fraction,8+fraction*2,9-fraction]
    source.applyCompactFrame({serialMap:[99],dense:Float32Array.from(point)})
    motion.apply(zoomMotionFrame([n],[{...n,backbone_position:[4+fraction,0,0]}]),zoomLiveAtoms(source))
    target.visitAtoms((a,p)=>expect(p.toArray()).toEqual(point))
  }
  motion.apply(zoomMotionFrame([n],null))
  target.visitAtoms((a,p)=>expect(p.toArray()).toEqual([1,0,0]))
  source.dispose();target.dispose()
})
it('moves an independent surface with the shared playback skinning path',()=>{
  const mesh={vertices:[1,0,0,1,1,0,1,0,1],faces:[0,1,2]}
  const renderer={applyDeformedFrame:vi.fn()}
  const motion=createZoomLayerMotion({entries:new Map([['z',{ready:true,kind:'surface',motionMesh:mesh,renderer}]])},[n])
  motion.apply(zoomMotionFrame([n],[{...n,backbone_position:[4,0,0]}]))
  expect(Array.from(renderer.applyDeformedFrame.mock.calls[0][1])).toEqual([4,0,0,4,1,0,4,0,1])
  expect(mesh.vertices[0]).toBe(1)
})
