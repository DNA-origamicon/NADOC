// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createZoomLayerMotion, zoomMotionFrame, zoomLiveAtoms, zoomExactAtoms, measuredResidueFrame } from './zoom_volume_motion.js'
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
it('maps NAMD measured-base frames from the same atom-defined frame on rest atoms',()=>{
  // Design bead/base_normal deliberately disagree with the P/ring frame (as in real
  // geometry: ~0.16 nm and ~35°), which previously rotated every residue about the wrong point.
  const nuc={...n,backbone_position:[1.1,0.2,0],base_normal:[-0.8,0.6,0]}
  const ring=[['N1',[0.2,0,0]],['C2',[0.13,0.12,0.01]],['N3',[-0.01,0.12,0]],['C4',[-0.08,0,-0.01]],['C5',[-0.01,-0.12,0]],['C6',[0.13,-0.12,0.01]]]
  const rest=[['P',[1,0,0]],["O3'",[0.9,0.3,0.25]],["C1'",[0.45,0.05,0.05]],...ring]
  const R=new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0.4,-0.7,1.1)).setPosition(3,-2,5)
  const moved=new Map(rest.map(([name,p])=>[name,new THREE.Vector3(...p).applyMatrix4(R).toArray()]))
  const target=initAtomisticRenderer(new THREE.Scene()); target.setMode('ballstick')
  target.update({atoms:rest.map(([name,p],i)=>({...nuc,serial:i,name,element:name[0],x:p[0],y:p[1],z:p[2]})),bonds:[]})
  const motion=createZoomLayerMotion({entries:new Map([['z',{ready:true,kind:'atom',renderer:target}]])},[nuc])
  const live=new THREE.Matrix4().copy(R).multiply(measuredResidueFrame(new Map(rest)))
  const x=new THREE.Vector3(),y=new THREE.Vector3(),z=new THREE.Vector3(); live.extractBasis(x,y,z)
  const update={...nuc,backbone_position:moved.get('P'),measured_base:true,nx:x.x,ny:x.y,nz:x.z,tx:z.x,ty:z.y,tz:z.z}
  motion.apply(zoomMotionFrame([nuc],[update],[{nuc,pos:new THREE.Vector3(...moved.get('P'))}]))
  target.visitAtoms((a,p)=>p.toArray().forEach((v,i)=>expect(v).toBeCloseTo(moved.get(a.name)[i],5)))
  // Non-measured sources keep the design-frame mapping.
  motion.apply(zoomMotionFrame([nuc],null))
  target.visitAtoms((a,p)=>p.toArray().forEach((v,i)=>expect(v).toBeCloseTo(new Map(rest).get(a.name)[i],5)))
  target.dispose()
})
it('places inset atoms exactly from Display-MD inset atoms, matching CHARMM names to design names',()=>{
  const target=initAtomisticRenderer(new THREE.Scene()); target.setMode('ballstick')
  target.update({atoms:[{...n,serial:1,name:'OP1',element:'O',x:1,y:0,z:0},{...n,serial:2,name:'C7',element:'C',x:2,y:0,z:0}],bonds:[]})
  const motion=createZoomLayerMotion({entries:new Map([['z',{ready:true,kind:'atom',renderer:target}]])},[n])
  const inset=new Map([['h:0:FORWARD:OP1',[5,6,7]],['h:0:FORWARD:C7',[8,9,10]]])
  motion.apply(zoomMotionFrame([n],[{...n,backbone_position:[4,0,0]}]),zoomExactAtoms(null,inset))
  const got=new Map(); target.visitAtoms((a,p)=>got.set(a.name,p.toArray()))
  expect(got).toEqual(new Map([['OP1',[5,6,7]],['C7',[8,9,10]]]))
  // An atomistic main viewport (CHARMM names) takes precedence over the inset stream.
  const main=initAtomisticRenderer(new THREE.Scene()); main.setMode('ballstick')
  main.update({atoms:[{...n,serial:9,name:'O1P',element:'O',x:3,y:3,z:3}],bonds:[]})
  expect(zoomExactAtoms(main,inset).get('h:0:FORWARD:OP1')).toEqual([3,3,3])
  expect(zoomExactAtoms(main,null).get('h:0:FORWARD:OP1')).toEqual([3,3,3])
  target.dispose();main.dispose()
})
