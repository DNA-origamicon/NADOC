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

it('publishes trajectory changes without waiting for control polls and coalesces a busy upload', async()=>{
 const {vi}=await import('vitest'),{createVRViewTools}=await import('./vr_view_tools.js'),THREE=await import('three')
 const view={flags:2048,triangles:new Float32Array(),lines:new Float32Array(),sprites:new Float32Array(),pixels:new Uint8Array(),width:0,height:0}
 const capture=vi.fn(async()=>view);let release
 const request=vi.fn(async()=>({ok:true}))
 vi.stubGlobal('fetch',request);vi.stubGlobal('requestAnimationFrame',fn=>setTimeout(fn,0));vi.useFakeTimers()
 const trace=[];window.__nadocVRPlaybackTrace=event=>trace.push(event)
 document.documentElement.dataset.vrSimulationTrajectory='true'
 const state={},tools=createVRViewTools({scene:new THREE.Scene(),getState:()=>state,capture})
 try {
  await tools.publish();await vi.advanceTimersByTimeAsync(1300)
  const initial=tools.publish();await vi.advanceTimersByTimeAsync(20);await initial
  request.mockImplementationOnce(()=>new Promise(r=>{release=r}))
  tools.refresh();await vi.advanceTimersByTimeAsync(20)
  expect(request).toHaveBeenCalledTimes(2)
  tools.refresh();tools.refresh();await vi.advanceTimersByTimeAsync(100)
  expect(request).toHaveBeenCalledTimes(2)
  release({ok:true});await vi.advanceTimersByTimeAsync(20)
  expect(request).toHaveBeenCalledTimes(3)
  const starts=trace.filter(e=>e.stage==='upload_start')
  expect(starts).toHaveLength(3)
  expect(starts.map(e=>e.version)).toEqual([starts[0].version,starts[0].version+1,starts[0].version+2])
  expect(trace.filter(e=>e.stage==='capture_start')).toHaveLength(3)
 }finally{delete window.__nadocVRPlaybackTrace;delete document.documentElement.dataset.vrSimulationTrajectory;vi.useRealTimers();vi.unstubAllGlobals()}
})
