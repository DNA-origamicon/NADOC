import {it,expect} from 'vitest'
import * as THREE from 'three'
import {createVRUI} from './vr_ui.js'
import {validateVRUI} from './vr_ui_protocol.js'
// Valid 1x1 RGBA PNG; protocol bounds are checked before browser image decoding.
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='
const panel=()=>({id:'left-menu',png,corners:[0,1,0,0,0,0,1,1,0,1,0,0]})
const packet=()=>({lines:[0,0,0,1,0,0,1,1,1,0,1,0],panels:[panel()]})
it('accepts copied native drawings and rejects malformed, external or unbounded payloads',()=>{
  const p=packet(),copy=validateVRUI(p);p.lines[0]=10;expect(copy.lines[0]).toBe(0)
  for(const change of [p=>p.lines.push(1),p=>p.lines[0]=NaN,p=>p.panels.push(panel()),p=>p.panels[0].png='https://example.com/a.png',p=>p.panels[0].corners[0]=Infinity,p=>p.panels[0].id='script',p=>p.lines=Array(32770*6).fill(0)]){
    const value=packet();change(value);expect(()=>validateVRUI(value)).toThrow()
  }
  expect(validateVRUI(undefined)).toBeUndefined()
})
it('renders native coordinates, caches unchanged textures and disposes closed/replaced panels',()=>{
  const root=new THREE.Group(),images=[],ui=createVRUI(root,{imageFactory:()=>{const image={};images.push(image);return image}})
  const p=packet();ui.update(p);images.at(-1).onload()
  const mesh=root.getObjectByName('vr-left-menu');expect(mesh.visible).toBe(true)
  expect([...mesh.geometry.getAttribute('position').array]).toEqual(p.panels[0].corners)
  const texture=mesh.material.map,count=images.length
  ui.update(structuredClone(p));expect(images).toHaveLength(count);expect(mesh.material.map).toBe(texture)
  let freed=false;texture.addEventListener('dispose',()=>freed=true)
  ui.update({lines:[],panels:[]});expect(root.getObjectByName('vr-left-menu')).toBeUndefined();expect(freed).toBe(true)
  ui.update(p);const late=images.at(-1).onload;ui.dispose();late();expect(root.children).toHaveLength(0)
})

import {encodeVRUIState,decodeVRUIState} from './vr_ui_stream.js'
it('sends images once per ordered guest stream and restores full state after reconnect',()=>{
  const write=new Map(),read=new Map(),state={avatar:{pose:{ui:packet()}}}
  const full=encodeVRUIState(state,write);expect(full.avatar.pose.ui.panels[0].png).toBe(png)
  expect(decodeVRUIState(full,read)).toEqual(state)
  const delta=encodeVRUIState(state,write);expect(delta.avatar.pose.ui.panels[0].png).toBeUndefined()
  expect(decodeVRUIState(delta,read)).toEqual(state)
  expect(()=>decodeVRUIState(delta,new Map())).toThrow('Missing VR menu texture')
  expect(encodeVRUIState(state,new Map())).toEqual(state)
  encodeVRUIState({avatar:null},write);decodeVRUIState({avatar:null},read)
  expect(write.size).toBe(0);expect(read.size).toBe(0)
})

it('treats X11 desktop RGB as opaque even when its unused alpha channel is zero',()=>{
  const root=new THREE.Group(),ui=createVRUI(root,{imageFactory:()=>({})})
  ui.update({lines:[],panels:[{...panel(),id:'desktop'}]})
  const material=root.getObjectByName('vr-desktop').material
  expect(material.transparent).toBe(false);expect(material.alphaTest).toBe(0)
  ui.dispose()
})
