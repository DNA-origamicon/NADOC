import {it,expect} from 'vitest'
import {VR_VIEW_KEYS,encodeVRView} from './vr_view_tools.js'
it('retains desktop view toggles except Quick Expand',async()=>{
  const fs=await import('node:fs')
  const html=fs.readFileSync('index.html','utf8')
  expect([...new Set([...html.matchAll(/data-vt="([^"]+)"/g)].map(m=>m[1]).filter(k=>k!=='expanded'))]).toEqual(VR_VIEW_KEYS)
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
  expect(viewToolUnavailable('unfold',posed)).toContain('Turn Deform off')
  expect(viewToolUnavailable('unfold',{...posed,deformVisuActive:false})).toBe('')
  expect(viewToolUnavailable('deform',{...posed,unfoldActive:true})).toContain('Exit Unfold')
  expect(viewToolUnavailable('cadnano2d',{...straight,atomisticMode:'ball-and-stick'})).toContain('atomistic')
})
