// This module resolves Three.js exclusively from its own pinned dependency tree.
// Transfer rendering snapshots as JSON, never editor Three.js objects.
import * as THREE from 'three/webgpu'
import {WebGPUPathTracer,RenderToScreenNodeMaterial} from 'three-gpu-pathtracer/webgpu'
import {GenerateMeshBVHWorker} from 'three-mesh-bvh/src/workers/GenerateMeshBVHWorker.js'
import {checkWebGPUStorage,traceDeviceLimits} from '../src/scene/photo_renderer/path_trace_limits.js'

export async function createWebGPUExport() {
  if(!navigator.gpu)throw new Error('WebGPU is unavailable in this browser. Use WebGL export.')
  const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'})
  if(!adapter)throw new Error('A WebGPU adapter is required. Use WebGL or OptiX export.')
  // Request the adapter's actual capacities instead of WebGPU's smaller defaults.
  const device=await adapter.requestDevice({requiredFeatures:[...adapter.features],requiredLimits:traceDeviceLimits(adapter.limits)})
  const renderer=new THREE.WebGPURenderer({alpha:true,trackTimestamp:true,device})
  try{await renderer.init()}catch(error){renderer.dispose();device.destroy();throw error}
  if(!renderer.backend.isWebGPUBackend){renderer.dispose();throw new Error('A WebGPU adapter is required; WebGL fallback is disabled.')}
  renderer.toneMapping=THREE.NoToneMapping;renderer.outputColorSpace=THREE.LinearSRGBColorSpace
  const tracer=new WebGPUPathTracer(renderer)
  let buildSignal=null
  class CancellableBVHWorker extends GenerateMeshBVHWorker {
    async generate(...args){
      const signal=buildSignal;signal?.throwIfAborted()
      let abort
      try{
        return await Promise.race([
          this.runTask(this.worker,...args),
          new Promise((_,reject)=>{abort=()=>{this.dispose();reject(signal.reason)};signal?.addEventListener('abort',abort,{once:true})}),
        ])
      }finally{signal?.removeEventListener('abort',abort)}
    }
    dispose(){if(this.worker)super.dispose()}
  }
  tracer.setBVHWorker(CancellableBVHWorker)
  tracer.maxBounces=5;tracer.maxTransparentBounces=5;tracer.filterGlossyFactor=.5
  tracer.renderDelay=0;tracer.fadeDuration=0;tracer.minSamples=0;tracer.dynamicLowRes=false
  tracer.synchronizeRenderSize=false;tracer.renderToCanvas=false
  tracer.frameBudget=8192;tracer.adaptiveFrameBudget=false
  const target=new THREE.RenderTarget(1,1,{type:THREE.FloatType})
  const display=new RenderToScreenNodeMaterial();display.toneMapping=THREE.NoToneMapping;display.transition=1;display.opacity=1
  // Match the tracer's blit UV convention: the material already converts its
  // top-down storage rows, but QuadMesh also has top-origin UVs. Normalize an
  // owned copy (never the shared QuadMesh geometry) to avoid inverting each tile.
  const quad=new THREE.QuadMesh(display)
  quad.geometry=quad.geometry.clone()
  const uv=quad.geometry.attributes.uv
  for(let i=0;i<uv.count;i++)uv.setY(i,1-uv.getY(i))
  let scene=null,camera=null,samples=0,disposed=false
  let lost=''
  device.lost.then(info=>{if(!disposed)lost=info.message||'device lost'})
  async function checked(operation){
    if(lost)throw new Error(`WebGPU device lost: ${lost}`)
    device.pushErrorScope('out-of-memory');device.pushErrorScope('validation')
    let result,failure
    try{result=await operation()}catch(error){failure=error}
    const validation=await device.popErrorScope(),memory=await device.popErrorScope()
    if(failure)throw failure
    if(validation||memory||lost)throw new Error(`WebGPU ${memory?'memory allocation':validation?'device validation':'device lost'} failed: ${(memory??validation)?.message??lost}`)
    return result
  }
  function releaseScene(){scene?.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material??[])){for(const v of Object.values(m))if(v?.isTexture)v.dispose();m.dispose()}});scene?.environment?.dispose();scene=null}
  return {
    async update(sceneJSON,cameraJSON,signal,{smoothEM=false}={}){
      tracer.maxTransparentBounces=smoothEM?160:5
      signal?.throwIfAborted();releaseScene()
      scene=new THREE.ObjectLoader().parse(sceneJSON);camera=new THREE.ObjectLoader().parse(cameraJSON)
      buildSignal=signal
      try{await checked(async()=>{await tracer.setSceneAsync(scene,camera);checkWebGPUStorage(tracer._bvhData.storage,device.limits)});signal?.throwIfAborted();samples=0}finally{buildSignal=null}
    },
    reset(cameraJSON,w,h){camera=new THREE.ObjectLoader().parse(cameraJSON);tracer.setCamera(camera);tracer.setSize(w,h);target.setSize(w,h);tracer.reset();samples=0},
    get samples(){return samples},
    async advance(count){
      if(disposed)throw new Error('WebGPU export disposed.')
      await checked(async()=>{
        tracer.maxSamples=count;tracer.renderSample()
        // Completion/readback prevents unbounded compute queues and shares the GPU.
        const counts=await tracer.getSampleCountsAsync();samples=counts.min
      })
    },
    async pixels(){
      display.texture=tracer.target;renderer.setRenderTarget(target);quad.render(renderer)
      return renderer.readRenderTargetPixelsAsync(target,0,0,target.width,target.height)
    },
    dispose(){
      if(disposed)return;disposed=true
      try{tracer.dispose()}finally{releaseScene();target.dispose();quad.geometry.dispose();display.dispose();renderer.dispose();device.destroy()}
    },
  }
}
