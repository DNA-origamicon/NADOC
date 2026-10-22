import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createVRViewTools, captureVRView, VR_VIEW_KEYS } from './vr_view_tools.js'
import { broadcastFingerprint } from '../viewer/broadcast_fingerprint.js'

vi.mock('../viewer/broadcast_fingerprint.js', () => ({ broadcastFingerprint: vi.fn(() => 'same-scene') }))
let state, controller
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.stubGlobal('requestAnimationFrame', callback => setTimeout(callback, 0))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })))
  vi.mocked(broadcastFingerprint).mockClear()
  document.body.innerHTML = VR_VIEW_KEYS.map(key => `<button data-vt="${key}" class="${key === 'deform' ? 'active' : ''}"></button>`).join('')
  const context = { clearRect() {}, fillRect() {}, strokeRect() {}, fillText() {}, drawImage() {},
    measureText: text => ({ width: text.length * 8 }),
    getImageData: (_x,_y,w,h) => ({ data: new Uint8ClampedArray(w*h*4) }) }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
  state = { currentGeometry: [], currentDesign: { deformations: [{}] } }
  controller = createVRViewTools({ scene: new THREE.Scene(), getState: () => state })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })
async function publishSettled() {
  // First poll discovers a changed input; second runs after the normal debounce.
  const first = controller.publish()
  await vi.runAllTimersAsync(); await first
  await vi.advanceTimersByTimeAsync(1600)
  const second = controller.publish()
  await vi.runAllTimersAsync(); await second
}

it('keeps the unchanged canonical-mode tablet across geometry and metadata edits', async () => {
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(1)
  for (let i = 0; i < 3; i++) {
    state = { currentGeometry: [{ x: i }], currentDesign: { deformations: [{}], revision: i } }
    await publishSettled()
  }
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(broadcastFingerprint).not.toHaveBeenCalled()
})

it('still republishes overlay geometry and transitions back to the canonical scene', async () => {
  await publishSettled()
  document.querySelector('[data-vt="sequences"]').classList.add('active')
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(2)
  state = { ...state, currentGeometry: [{ x: 4 }] }
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(broadcastFingerprint).toHaveBeenCalled()
  document.querySelector('[data-vt="sequences"]').classList.remove('active')
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(4)
  state = { ...state, currentDesign: { deformations: [{}], revision: 8 } }
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(4)
})

it('publishes explicit tablet acknowledgements and a new viewer after reset', async () => {
  await publishSettled()
  await controller.activate(0, 7)
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(2)
  controller.reset()
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(3)
})

it('exports surface normals with inverse transpose and keeps lines unlit',async()=>{
  document.querySelector('[data-vt="lengthHeatmap"]').classList.add('active')
  const scene=new THREE.Scene(),geometry=new THREE.BufferGeometry()
  geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0,0,1,0],3))
  geometry.setAttribute('normal',new THREE.Float32BufferAttribute([1,1,0,1,1,0,1,1,0],3))
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial())
  mesh.scale.set(2,1,1);mesh.position.set(8,9,10);scene.add(mesh)
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(),new THREE.Vector3(1,0,0)]),new THREE.LineBasicMaterial());scene.add(line)
  const view=await captureVRView(scene,document)
  expect(view.schema).toBe(5)
  const normal=new THREE.Vector3(...view.triangles.slice(9,12))
  expect(normal.length()).toBeCloseTo(1,5)
  expect(normal.x/normal.y).toBeCloseTo(.5,5)
  expect([...view.lines.slice(9,12)]).toEqual([0,0,0])
})

it('negotiates transform updates, and resets to full snapshots for new viewers or changed colors',async()=>{
 const {Blob}=await import('node:buffer');vi.stubGlobal('Blob',Blob)
 const scene=new THREE.Scene(),mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial(),1)
 mesh.setMatrixAt(0,new THREE.Matrix4());scene.add(mesh)
 document.querySelector('[data-vt="lengthHeatmap"]').classList.add('active')
 document.documentElement.dataset.vrSimulationTrajectory='true'
 const headers=[]
 fetch.mockImplementation(async(_url,{body})=>{
  const buffer=await body.arrayBuffer();headers.push([...new Uint32Array(buffer,8,10)])
  return {ok:true,json:async()=>({transform_updates:true})}
 })
 controller=createVRViewTools({scene,getState:()=>state})
 try{
  await publishSettled()
  mesh.setMatrixAt(0,new THREE.Matrix4().makeTranslation(1,2,3));controller.refresh();await vi.runAllTimersAsync()
  expect(headers.map(h=>h[0])).toEqual([5,7])
  mesh.setColorAt(0,new THREE.Color(.1,.2,.3));controller.refresh();await vi.runAllTimersAsync()
  expect(headers.at(-1)[0]).toBe(6)
  controller.reset();await publishSettled();expect(headers.at(-1)[0]).toBe(5)
 }finally{delete document.documentElement.dataset.vrSimulationTrajectory}
})


it('reports completed delivery cost for smooth pacing and clears it on reset',async()=>{
 vi.mocked(fetch).mockImplementation(async()=>{await new Promise(resolve=>setTimeout(resolve,80));return {ok:true}})
 const pending=controller.publish()
 await vi.advanceTimersByTimeAsync(1)
 expect(controller.delivery.busy).toBe(true)
 await vi.runAllTimersAsync();await pending
 expect(controller.delivery.busy).toBe(false)
 expect(controller.delivery.milliseconds).toBeGreaterThanOrEqual(80)
 controller.reset()
 expect(controller.delivery.milliseconds).toBe(0)
})

it('publishes a simple click without the debounce or browser animation frames',async()=>{
  await publishSettled()
  vi.stubGlobal('requestAnimationFrame',()=>{throw new Error('Occluded browser frame')})
  const before=performance.now()
  await controller.activate(3,12)
  await vi.advanceTimersByTimeAsync(10)
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(performance.now()-before).toBeLessThan(50)
})

it('waits for actual deform readiness and then publishes without a fixed delay',async()=>{
  let ready
  const activateDeform=vi.fn(()=>new Promise(resolve=>{ready=resolve}))
  controller=createVRViewTools({scene:new THREE.Scene(),getState:()=>state,activateDeform})
  await publishSettled()
  const pending=controller.activate(7,13)
  await vi.advanceTimersByTimeAsync(2000);await controller.publish()
  expect(fetch).toHaveBeenCalledTimes(1)
  ready();await pending;await vi.advanceTimersByTimeAsync(10)
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('batches real loop/skip annotations without losing posed positions or visibility',async()=>{
  const {initLoopSkipHighlight}=await import('./loop_skip_highlight.js')
  const scene=new THREE.Scene(),overlay=initLoopSkipHighlight(scene)
  const design={helices:Array.from({length:100},(_,i)=>({id:String(i),bp_start:0,length_bp:10,axis_start:{x:i,y:0,z:0},axis_end:{x:i,y:0,z:3.4},loop_skips:[{bp_index:2,delta:1},{bp_index:4,delta:-1}]}))}
  overlay.rebuild(design,[],{});overlay.setVisible(true)
  document.querySelector('[data-vt="loopSkips"]').classList.add('active')
  const view=await captureVRView(scene)
  expect(view.triangles).toHaveLength(0)
  expect(view.batches.reduce((n,b)=>n+b.vertices.length/12,0)).toBe(12)
  // One shared billboard per marker kind, including its procedural halo.
  expect(view.batches).toHaveLength(2)
  for(const b of view.batches)for(let k=0;k<b.vertices.length;k+=12){
    expect([...b.vertices.slice(k+7,k+12)]).toEqual([b===view.batches[0]?-3:-4,b===view.batches[0]?-3:-4,0,0,0])
  }
  const loop=view.batches[0]
  expect(loop.instances.length/20).toBe(100)
  expect(loop.instances[99*20+12]).toBe(99)
  overlay.getEntries()[0].setHighlight(true)
  const highlighted=await captureVRView(scene)
  expect(highlighted.batches.some(b=>b.vertices[3]===1&&b.vertices[4]===1&&b.vertices[5]===1)).toBe(true)
  overlay.setVisible(false)
  expect((await captureVRView(scene)).batches).toHaveLength(0)
})

it('does not acknowledge an asynchronous overlay until its report is applied',async()=>{
 let ready
 const waitForTool=vi.fn(()=>new Promise(resolve=>{ready=resolve}))
 controller=createVRViewTools({scene:new THREE.Scene(),getState:()=>state,waitForTool})
 await publishSettled()
 const pending=controller.activate(6,14)
 await vi.advanceTimersByTimeAsync(2000);await controller.publish()
 expect(fetch).toHaveBeenCalledTimes(1)
 ready();await pending;await vi.advanceTimersByTimeAsync(10)
 expect(waitForTool).toHaveBeenCalledWith('clashes')
 expect(fetch).toHaveBeenCalledTimes(2)
})

it('publishes cold state and subscribed geometry edits immediately',async()=>{
 let changed
 controller=createVRViewTools({scene:new THREE.Scene(),getState:()=>state,subscribe:fn=>{changed=fn}})
 document.querySelector('[data-vt="loopSkips"]').classList.add('active')
 const initial=controller.publish();await vi.advanceTimersByTimeAsync(10);await initial
 expect(fetch).toHaveBeenCalledTimes(1)
 const previous=state;state={...state,currentGeometry:[{}]};changed(state,previous)
 await vi.advanceTimersByTimeAsync(10)
 expect(fetch).toHaveBeenCalledTimes(2)
 expect(performance.now()).toBeLessThan(50)
})

it('negotiates atlas reuse and sends only the panel for unchanged canonical geometry',async()=>{
 const {Blob}=await import('node:buffer');vi.stubGlobal('Blob',Blob)
 const packets=[]
 fetch.mockImplementation(async(_url,{body})=>{
  const a=await body.arrayBuffer();packets.push({header:[...new Uint32Array(a,8,10)],bytes:a.byteLength})
  return {ok:true,json:async()=>({atlas_patches:true,transform_updates:true})}
 })
 await publishSettled()
 await controller.activate(7,15);await vi.runAllTimersAsync()
 expect(packets.map(p=>p.header[0])).toEqual([5,9])
 expect(packets[1].bytes).toBe(52+768*768*4)
 expect(packets[1].header[9]).toBe(15)
 document.querySelector('[data-vt="grid"]').classList.add('active')
 await controller.activate(4,16);await vi.runAllTimersAsync()
 expect(packets.at(-1).header[0]).toBe(8)
})

it('refreshes changed texture contents and reclaims an atlas when texture dimensions change',async()=>{
 document.querySelector('[data-vt="sequences"]').classList.add('active')
 const scene=new THREE.Scene(),canvas=document.createElement('canvas');canvas.width=16;canvas.height=16
 const texture=new THREE.CanvasTexture(canvas),sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture}));scene.add(sprite)
 const first=await captureVRView(scene)
 expect((await captureVRView(scene,document,'',false,first.atlasState)).schema).toBe(6)
 texture.needsUpdate=true
 expect((await captureVRView(scene,document,'',false,first.atlasState)).schema).toBe(5)
 canvas.width=32
 const resized=await captureVRView(scene,document,'',false,first.atlasState)
 expect(resized.schema).toBe(5);expect(resized.atlasState).not.toBe(first.atlasState)
})
