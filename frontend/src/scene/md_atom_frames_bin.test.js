import { it, expect } from 'vitest'
import { parseMdAtomFrames, parseMdAtomModel, expandMdAtomFrame } from './md_atom_frames_bin.js'
it('retains exact float64 coordinates and original frame indices',()=>{
  const b=new ArrayBuffer(16+8+24*2),v=new DataView(b)
  ;[0x4D444146,1,1,2,249,0].forEach((x,i)=>v.setUint32(i*4,x,true))
  const values=new Float64Array(b,24);values[3]=1/3;values[4]=1e-12
  const r=parseMdAtomFrames(b)
  expect(r['249'][3]).toBe(1/3);expect(r['249'][4]).toBe(1e-12)
  expect(()=>parseMdAtomFrames(b.slice(0,-1))).toThrow('Truncated')
})
it('expands sparse v2 serials without rounding or substituting atoms',()=>{
  const b=new ArrayBuffer(32+8+48),h=new DataView(b)
  ;[0x4D444146,2,1,7,2,0,1,6,249,0].forEach((x,i)=>h.setUint32(i*4,x,true))
  const coordinates=new Float64Array(b,40); coordinates.set([1/3,2,3,4,1e-12,6])
  const frames=parseMdAtomFrames(b)
  expect(frames[249].length).toBe(21)
  expect(frames[249][3]).toBe(1/3)
  expect(frames[249][19]).toBe(1e-12)
  expect(frames[249][0]).toBe(0)
})
it('decodes columnar topology with sparse serials and insertion copies',()=>{
  const header=new TextEncoder().encode(JSON.stringify({count:2,n_serials:8,columns:[
    {name:'x',dtype:'<f8',offset:0,count:2},
    {name:'serial',dtype:'<u4',offset:16,count:2},
    {name:'copyK',dtype:'<i4',offset:24,count:2},
  ]}))
  const start=16+Math.ceil(header.length/8)*8,b=new ArrayBuffer(start+32),h=new DataView(b)
  ;[0x4D44414D,1,header.length,0].forEach((x,i)=>h.setUint32(i*4,x,true))
  new Uint8Array(b,16,header.length).set(header)
  new Float64Array(b,start,2).set([1/3,2])
  new Uint32Array(b,start+16,2).set([2,7])
  new Int32Array(b,start+24,2).set([0,3])
  const model=parseMdAtomModel(b)
  expect(model.columnar).toBe(true)
  expect([...model.serial]).toEqual([2,7])
  expect([...model.copyK]).toEqual([0,3])
  expect(model.x[0]).toBe(1/3)
  expect(model.auxHelixTable).toEqual([''])
})

it('caches dense float64 frames and expands exact sparse coordinates only for display',()=>{
  const b=new ArrayBuffer(32+8+48),h=new DataView(b)
  ;[0x4D444146,2,1,7,2,0,1,6,249,0].forEach((x,i)=>h.setUint32(i*4,x,true))
  new Float64Array(b,40).set([1/3,2,3,4,1e-12,6])
  const compact=parseMdAtomFrames(b,{compact:true})[249]
  expect(compact.byteLength).toBe(48)
  const sparse=expandMdAtomFrame(compact)
  expect(sparse).toEqual(parseMdAtomFrames(b)[249])
  sparse[0]=123
  expect(expandMdAtomFrame(compact,sparse)).toBe(sparse)
  expect(sparse[0]).toBe(0)
  expect(expandMdAtomFrame(sparse)).toBe(sparse)
})
