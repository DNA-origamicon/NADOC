import { it,expect,vi } from 'vitest'
import * as THREE from 'three'
import { createTracePreview } from './path_trace_preview.js'
import { createGeometryLoads } from '../geometry_loads.js'
const flush=()=>new Promise(resolve=>setTimeout(resolve,0))
function setup(load,buffer=[100,100],maxTextureSize=8192,prepare=()=>{},realFingerprint=false){
  let clock=0,key='a'
  const settings={pathTracing:true,pathTraceSamples:2},scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera()
  const renderer={capabilities:{maxTextureSize},domElement:{width:buffer[0],height:buffer[1]},getDrawingBufferSize:v=>v.set(...buffer),getSize:v=>v.set(100,100)}
  const geometry=createGeometryLoads()
  const mode=createTracePreview({scene,camera,renderer,settings,isActive:()=>true,load,now:()=>clock,fingerprint:realFingerprint?undefined:()=>key,geometry,prepare})
  const raster={render:vi.fn()},pass=mode.pass(raster),render=()=>pass.render(renderer,null,{})
  return {mode,render,raster,geometry,scene,camera,settings,advance(ms=250){clock+=ms},change(){key+='x'}}
}
const engine=()=>({samples:0,emSamples:8,step(){this.samples++},draw:vi.fn(),dispose:vi.fn()})
it('synchronizes new mesh materials before fingerprinting the tracing snapshot',async()=>{
  const e=engine(),create=vi.fn(async()=>e),prepare=vi.fn(()=>d.change())
  const d=setup(async()=>create,[100,100],8192,prepare)
  const done=d.geometry.begin('atoms');d.render();d.advance();d.render()
  expect(prepare).not.toHaveBeenCalled()
  done();d.render();d.advance();d.render();await flush();d.render();d.render()
  expect(prepare).toHaveBeenCalledOnce();expect(create).toHaveBeenCalledOnce()
  expect(d.mode.getStatus()).toMatchObject({state:'tracing',samples:2})
  d.mode.stop()
})
it('stops tracing through staged geometry loads and resumes only after every owner finishes',async()=>{
  const first=engine(),second=engine(),create=vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second)
  const d=setup(async()=>create)
  d.render();d.advance();d.render();await flush();d.render()
  const atoms=d.geometry.begin('atoms'),positions=d.geometry.begin('positions')
  d.render();expect(first.dispose).toHaveBeenCalledOnce()
  for(let i=0;i<5;i++){d.advance();d.change();d.render()}
  expect(d.mode.getStatus()).toMatchObject({state:'loading',samples:0})
  atoms();d.advance();d.render();expect(create).toHaveBeenCalledOnce()
  positions();d.render();d.advance();d.render();await flush();d.render()
  expect(create).toHaveBeenCalledTimes(2);expect(second.draw).toHaveBeenCalledOnce()
  d.mode.stop()
})
it('rejects a late tracer build even if a geometry load starts and finishes between render frames',async()=>{
  const old=engine();let finish
  const d=setup(async()=>()=>new Promise(resolve=>{finish=resolve}))
  d.render();d.advance();d.render();await flush()
  const done=d.geometry.begin('atoms');done();finish(old);await flush()
  expect(old.dispose).toHaveBeenCalledOnce();expect(old.draw).not.toHaveBeenCalled()
  expect(d.mode.getStatus().samples).toBe(0)
  d.mode.stop()
})
it('disabling while geometry loads prevents an automatic restart',async()=>{
  const create=vi.fn(async()=>engine()),d=setup(async()=>create),done=d.geometry.begin('atoms')
  d.render();d.advance();d.render();d.mode.setEnabled(false);done()
  d.render();d.advance();d.render()
  expect(create).not.toHaveBeenCalled();expect(d.mode.getStatus().state).toBe('off')
})
it('refines a stationary view, discards old frames on changes and releases the GPU on disable',async()=>{
  const e=engine(),create=vi.fn(async()=>e),d=setup(async()=>create)
  d.render();d.advance();d.render();await flush();d.render();d.render();d.render()
  expect(d.mode.getStatus()).toMatchObject({samples:2,emSamples:8})
  d.change();d.render();expect(e.dispose).toHaveBeenCalledOnce()
  expect(d.mode.getStatus().samples).toBe(0)
  d.mode.setEnabled(false);d.render();expect(d.mode.getStatus().state).toBe('off')
})
it('traces every viewport pixel and bounds tile area instead of enlarging a low-resolution image',async()=>{
  const create=vi.fn(async()=>engine()),d=setup(async()=>create,[3764,2370])
  d.render();d.advance();d.render();await flush()
  const options=create.mock.calls[0][0]
  expect([options.width,options.height]).toEqual([3764,2370])
  expect(options.width/options.tileCount).toBeLessThanOrEqual(256)
  expect(options.viewHeight).toBe(100)
  d.mode.stop()
})
it('keeps raster sharp when the viewport exceeds the hardware limit',async()=>{
  const create=vi.fn(),d=setup(async()=>create,[4000,2000],2048)
  d.render();d.advance();d.render();await flush();d.render()
  expect(create).not.toHaveBeenCalled()
  expect(d.mode.getStatus().error).toContain('render-target limit')
  expect(d.raster.render).toHaveBeenCalledTimes(3)
})
it('resizes retained tracing tiles along with the drawing buffer',async()=>{
  const buffer=[100,100],e=engine();e.update=vi.fn(async()=>{});e.reset=vi.fn()
  const create=vi.fn(async()=>e),d=setup(async()=>create,buffer)
  d.render();d.advance();d.render();await flush();d.render()
  buffer[0]=3764;buffer[1]=2370;d.change();d.render();d.advance();d.render();await flush()
  expect(create).toHaveBeenCalledOnce()
  expect(e.reset).toHaveBeenLastCalledWith(expect.any(THREE.PerspectiveCamera),3764,2370,15)
  d.mode.stop()
})
it('disposes a late build after cancellation and never displays stale tracing',async()=>{
  const e=engine();let finish
  const d=setup(async()=>()=>new Promise(resolve=>{finish=resolve}))
  d.render();d.advance();d.render();await flush();d.mode.setEnabled(false)
  finish(e);await flush();d.render()
  expect(e.dispose).toHaveBeenCalledOnce();expect(e.draw).not.toHaveBeenCalled()
})
it('reports an unavailable GPU and keeps raster preview without retry loops',async()=>{
  const load=vi.fn(async()=>{throw new Error('Unsupported GPU')});const d=setup(load)
  d.render();d.advance();d.render();await flush();d.render();d.render()
  expect(d.mode.getStatus()).toMatchObject({state:'error',error:'Unsupported GPU'})
  expect(load).toHaveBeenCalledOnce();expect(d.raster.render).toHaveBeenCalledTimes(4)
})
it('retains an updateable engine across changes and never displays its stale frame',async()=>{
  const e=engine();e.update=vi.fn(async()=>{});e.reset=vi.fn(()=>{e.samples=0})
  const create=vi.fn(async()=>e),d=setup(async()=>create)
  d.render();d.advance();d.render();await flush();d.render()
  d.change();d.render();expect(d.mode.getStatus().samples).toBe(0)
  expect(e.dispose).not.toHaveBeenCalled()
  d.advance();d.render();await flush();d.render()
  expect(create).toHaveBeenCalledOnce();expect(e.update).toHaveBeenCalledOnce()
  d.mode.setEnabled(false);expect(e.dispose).toHaveBeenCalledOnce()
})
it('pauses and reuses only a completed, exact camera/resolution/backend match',async()=>{
  const e=engine();e.ready=()=>true;e.readPixels=vi.fn(()=>new Float32Array(4))
  const d=setup(async()=>async()=>e),camera=new THREE.PerspectiveCamera()
  d.render();d.advance();d.render();await flush();d.render();d.render()
  const release=d.mode.beginExport();d.render();expect(e.dispose).not.toHaveBeenCalled()
  const options={camera,width:100,height:100,backend:'webgl',samples:2}
  expect(d.mode.completedFrame(options)).toMatchObject({samples:2})
  for(const patch of [{width:200},{backend:'optix'},{samples:4}])expect(d.mode.completedFrame({...options,...patch})).toBeNull()
  camera.position.x=1;camera.updateMatrixWorld();expect(d.mode.completedFrame(options)).toBeNull()
  camera.position.x=0;camera.updateMatrixWorld();d.change();expect(d.mode.completedFrame(options)).toBeNull()
  release();release();d.mode.stop();expect(e.dispose).toHaveBeenCalledOnce()
})

it('reuses geometry while orbiting, waits for GPU completion, and restores native resolution when still',async()=>{
  let ready=true
  const e=engine();e.emSamples=0;e.ready=()=>ready
  e.setView=vi.fn(()=>{e.samples=0});e.update=vi.fn(async()=>{});e.reset=vi.fn(()=>{e.samples=0})
  const create=vi.fn(async()=>e),d=setup(async()=>create,[1280,720],8192,()=>{},true)
  d.scene.add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()))
  const rig=new THREE.Group();rig.userData.photoLightRig=true;rig.add(new THREE.DirectionalLight());d.scene.add(rig)
  d.render();d.advance();d.render();await flush();d.render();d.render()
  ready=false;d.camera.position.x=2;rig.rotation.y=.1;d.advance(16);d.render()
  expect(e.setView).not.toHaveBeenCalled();expect(d.mode.getStatus().state).toBe('interactive')
  ready=true;d.advance(16);d.render()
  expect(e.setView).toHaveBeenCalledOnce();expect(e.setView.mock.calls[0].slice(2)).toEqual([832,468,1])
  expect(create).toHaveBeenCalledOnce();expect(e.update).not.toHaveBeenCalled()
  expect(d.mode.completedFrame({camera:d.camera,width:1280,height:720,backend:'webgl',samples:1})).toBeNull()
  d.advance();d.render()
  expect(e.setView.mock.calls.at(-1).slice(2)).toEqual([1280,720,5])
  expect(d.mode.getStatus().state).toBe('tracing')
  d.scene.children[0].position.x=3;d.render();expect(d.mode.getStatus().state).toBe('waiting')
  d.advance();d.render();await flush();expect(e.update).toHaveBeenCalledOnce()
  d.mode.stop()
})
it('does not credit queued GPU samples as completed traced frames',async()=>{
  let ready=true;const e=engine();e.ready=()=>ready
  const d=setup(async()=>async()=>e)
  d.render();d.advance();d.render();await flush();d.advance(16);d.render()
  ready=false;d.advance(16);d.render()
  expect(d.mode.getStatus().metrics.tracedFPS).toBe(0)
  ready=true;d.advance(16);d.render()
  expect(d.mode.getStatus().metrics.tracedFPS).toBeGreaterThan(0)
  d.mode.stop()
})

it('keeps a completion that arrives between the first poll and a moving-view reset',async()=>{
  const e=engine();e.emSamples=0;e.diagnostics={width:100,height:100};e.ready=()=>true
  e.setView=()=>{e.samples=0}
  const d=setup(async()=>async()=>e,[100,100],8192,()=>{},true)
  d.render();d.advance();d.render();await flush();d.render();d.render()
  d.camera.position.x=1;d.advance(16);d.render()
  const before=d.mode.getStatus().metrics.totalCameraPaths
  let polls=0;e.ready=()=>++polls>1
  d.camera.position.x=2;d.advance(70);d.render()
  expect(d.mode.getStatus().metrics.totalCameraPaths-before).toBe(10000)
  d.mode.stop()
})

it('compares raw and denoised views without discarding samples or rebuilding geometry',async()=>{
  const e=engine(),create=vi.fn(async()=>e),d=setup(async()=>create,[100,100],8192,()=>{},true)
  d.render();d.advance();d.render();await flush();d.render();d.render()
  expect(e.samples).toBe(2);expect(e.draw).toHaveBeenLastCalledWith({}, {denoise:true})
  d.mode.setDenoise(false);d.render()
  expect(e.samples).toBe(2);expect(e.draw).toHaveBeenLastCalledWith({}, {denoise:false})
  d.mode.setDenoise(true);d.render()
  expect(create).toHaveBeenCalledOnce();expect(e.dispose).not.toHaveBeenCalled()
  d.mode.stop()
})

it('reports a denoiser/display failure and falls back without breaking the render loop',async()=>{
  const e=engine(),d=setup(async()=>async()=>e)
  e.draw.mockImplementation(()=>{throw new Error('GPU denoising allocation failed')})
  d.render();d.advance();d.render();await flush();d.render()
  expect(d.mode.getStatus().error).toContain('denoising allocation failed')
  expect(e.dispose).toHaveBeenCalledOnce();expect(d.raster.render).toHaveBeenCalled()
  d.mode.setDenoise(false);expect(d.mode.getStatus().error).toBe('')
  d.render();d.mode.stop()
})

it('selects the native factory explicitly and awaits async resource release',async()=>{
  let release
  const e=engine();e.dispose=vi.fn(()=>new Promise(r=>release=r))
  const load=vi.fn(async()=>async()=>e),d=setup(load)
  d.mode.setPreviewBackend('optix');d.render();d.advance();d.render();await flush();d.render()
  expect(load).toHaveBeenCalledWith('optix');expect(d.mode.getStatus().backend).toBe('optix')
  let finished=false
  const closing=d.mode.releaseEngineForExport().then(()=>finished=true)
  await flush();expect(finished).toBe(false);release();await closing;expect(finished).toBe(true)
})

it('reports asynchronous startup and native rendering progress without accepting disposed callbacks',async()=>{
  let options
  const e=engine(),d=setup(async()=>async o=>{options=o;o.onStatus({stage:'compile',label:'Compiling GPU tracing shader…'});return e})
  d.render();d.advance();d.render();await flush()
  options.onStatus({stage:'tracing',label:'Sample 16/64',samples:16})
  expect(d.mode.getStatus().phase).toMatchObject({samples:16})
  d.mode.stop();options.onStatus({stage:'tracing',label:'Old worker'})
  expect(d.mode.getStatus().phase).toBeNull()
})

it('coalesces view changes behind an in-flight native image without restarting its worker',async()=>{
  let ready=true
  const e=engine();e.ready=()=>ready;e.update=vi.fn(async()=>{});e.reset=()=>{e.samples=0}
  const create=vi.fn(async()=>e),d=setup(async()=>create)
  d.render();d.advance();d.render();await flush();d.render()
  ready=false;e.diagnostics={pending:true}
  for(let i=0;i<4;i++){d.change();d.render();d.advance();d.render();await flush()}
  expect(e.update).not.toHaveBeenCalled();expect(e.dispose).not.toHaveBeenCalled()
  expect(d.mode.getStatus()).toMatchObject({state:'updating',samples:0})
  ready=true;e.diagnostics.pending=false;d.render();await flush();d.render()
  expect(e.update).toHaveBeenCalledOnce();expect(create).toHaveBeenCalledOnce()
  d.mode.stop()
})

it.each([false,true])('uses doubling checkpoints only for renderers with a noise probe (%s)',async hasProbe=>{
  const e=engine();e.advance=vi.fn();if(hasProbe)e.readProbe=vi.fn()
  const d=setup(async()=>async()=>e);d.settings.pathTraceSamples=64;d.mode.setMetricsEnabled(true)
  d.render();d.advance();d.render();await flush();d.render()
  expect(e.advance).toHaveBeenCalledWith(hasProbe?1:64)
  d.mode.stop()
})
it('does not claim unfinished native scene work is reused when samples change during upload',async()=>{
  let ready=true
  const e=engine();e.ready=()=>ready;e.update=vi.fn(async()=>{});e.reset=()=>{e.samples=0}
  const d=setup(async()=>async()=>e);d.settings.pathTracePreviewBackend='optix'
  d.render();d.advance();d.render();await flush();d.render()
  ready=false;e.diagnostics={pending:true};d.mode.setSamples(8)
  d.render();d.advance();d.render()
  expect(d.mode.getStatus().work.stages.some(row=>row.state==='reused')).toBe(false)
  expect(e.update).not.toHaveBeenCalled();expect(e.dispose).not.toHaveBeenCalled()
  ready=true;e.diagnostics.pending=false;d.render();await flush()
  expect(e.update).toHaveBeenCalledOnce();expect(d.mode.getStatus().target).toBe(8)
  d.mode.stop()
})
