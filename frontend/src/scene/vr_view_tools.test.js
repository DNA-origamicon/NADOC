import {it,expect} from 'vitest'
import {VR_VIEW_KEYS,encodeVRView} from './vr_view_tools.js'
it('retains desktop view toggles except screen-only layouts',async()=>{
  const fs=await import('node:fs')
  const html=fs.readFileSync('index.html','utf8')
  expect([...new Set([...html.matchAll(/data-vt="([^"]+)"/g)].map(m=>m[1]).filter(k=>!['expanded','unfold'].includes(k)))]).toEqual(VR_VIEW_KEYS)
})
it('encodes a bounded binary scene with separate geometry and sprite counts',()=>{
  const blob=encodeVRView({flags:256,triangles:new Float32Array(27),lines:new Float32Array(18),sprites:new Float32Array(15),pixels:new Uint8Array(16),width:2,height:2},9)
  expect(blob.size).toBe(48+60*4+16)
})

it('explains the same layout prerequisites as the desktop',async()=>{
  const {viewToolUnavailable}=await import('./vr_view_tools.js')
  const straight={currentDesign:{},atomisticMode:'off'}
  expect(viewToolUnavailable('deform',straight)).toContain('already straight')
  const posed={...straight,deformVisuActive:true,currentDesign:{cluster_transforms:[{translation:[1,0,0]}]}}
  expect(viewToolUnavailable('unfold',posed)).toContain('not available in VR')
  expect(viewToolUnavailable('deform',{...posed,unfoldActive:true})).toContain('desktop 2D')
})

it('encodes lit surfaces with normals and unlit lines as schema 5',async()=>{
  const vertices=new Float32Array([1,2,3,1,.5,.2,1,-1,-1,0,1,0])
  const blob=encodeVRView({schema:5,flags:257,triangles:new Float32Array([...vertices,...vertices,...vertices]),lines:new Float32Array(),sprites:new Float32Array(),pixels:new Uint8Array(16),width:2,height:2},10)
  const buffer=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsArrayBuffer(blob)}),header=new Uint32Array(buffer,8,10)
  expect([...header.slice(0,5)]).toEqual([5,10,257,3,0])
  expect([...new Float32Array(buffer,48+9*4,3)]).toEqual([0,1,0])
})

it('encodes trajectory geometry with normals while reusing the native atlas',async()=>{
  const blob=encodeVRView({schema:6,flags:2048,triangles:new Float32Array(36),lines:new Float32Array(),sprites:new Float32Array(),pixels:new Uint8Array(),width:0,height:0},11)
  const buffer=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsArrayBuffer(blob)})
  const header=new Uint32Array(buffer,8,10)
  expect([...header.slice(0,8)]).toEqual([6,11,2048,3,0,0,0,0])
  expect(blob.size).toBe(48+36*4)
})
