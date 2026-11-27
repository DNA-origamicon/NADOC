import * as THREE from 'three'
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js'
import { DynamicPathTracingSceneGenerator, PathTracingRenderer, PhysicalPathTracingMaterial, RenderTarget2DArray } from 'three-gpu-pathtracer'
import { compileTraceMaterial } from './path_trace_compile.js'
import { SAH } from 'three-mesh-bvh'
import { GenerateMeshBVHWorker } from 'three-mesh-bvh/src/workers/GenerateMeshBVHWorker.js'
import { traceSnapshotAsync, traceLights } from './path_trace_snapshot.js'
import { traceEnvironment } from './path_trace_environment.js'
import { reuseTraceGeometry } from './path_trace_reuse.js'
import { createTraceProbe } from './trace_probe.js'
import { createTraceDenoiser } from './trace_denoise.js'
import { createTraceSchedule } from './path_trace_schedule.js'
import { checkTraceBVH, checkTraceGeometry } from './path_trace_limits.js'

/** One context-local tracer. Only disposable geometry enters the BVH worker. */
export async function createTraceEngine({renderer,scene,camera,width,height,viewHeight,settings,signal,tileCount=2,onProgress=()=>{},onStatus=()=>{},bvhOptions={}}) {
  if(!renderer.capabilities.isWebGL2 || !renderer.extensions.has('EXT_color_buffer_float'))
    throw new Error('GPU path tracing needs WebGL 2 and floating-point render targets.')
  if(renderer.clippingPlanes?.length)throw new Error('Disable section clipping before GPU path tracing.')
  let worker=null, bvh=null, geometry=null, originalIndex=null, env=null, environmentKey=null, disposed=false
  const material=new PhysicalPathTracingMaterial(), textures=new RenderTarget2DArray()
  // In tracer 0.0.20 the stratified texture is depth-by-dimension, but its
  // shader indexes dimension-by-depth. With 5+5 bounces its width is 15:
  // rand(15), the diffuse/specular choice, reads out of bounds and stays fixed
  // per pixel across samples. Use the supported, frame-seeded PCG sampler;
  // unlike Sobol it also avoids the library's documented macOS compiler issue.
  material.setDefine('RANDOM_TYPE',0)
  material.textures.dispose();material.textures=textures.texture
  const background=new THREE.DataTexture(new Float32Array(4),1,1,THREE.RGBAFormat,THREE.FloatType)
  material.backgroundMap=background;material.bounces=5;material.transmissiveBounces=5;material.filterGlossyFactor=.5
  const tracer=new PathTracingRenderer(renderer);tracer.material=material;tracer.camera=camera
  tracer.alpha=settings.bgType==='transparent';tracer.tiles.set(tileCount,tileCount);tracer.setSize(width,height)
  // The legacy alpha renderer exposes a fixed ping-pong slot, one sample
  // behind on even passes. Select the slot it actually wrote this iteration.
  const currentTarget=()=>tracer.alpha&&tracer.samples>0?tracer._blendTargets[Math.ceil(tracer.samples)%2]:tracer.target
  const schedule=createTraceSchedule(renderer)
  const quad=new FullScreenQuad(new THREE.MeshBasicMaterial({toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending}))
  // SAH spends more preparation work to reduce repeated ray traversal. Four
  // triangles per leaf keeps the dense-scene tree substantially smaller than
  // a one-triangle tree; retain it/refit it across subsequent frames.
  const treeOptions={strategy:SAH,maxLeafSize:4,...bvhOptions}
  const stats={bvhStrategy:['CENTER','AVERAGE','SAH'][treeOptions.strategy],bvhLeafSize:treeOptions.maxLeafSize,builds:0,refits:0,updates:0,environmentBuilds:0,prepareMs:0}
  let compiling=null,closing=null
  let triangles=0,emSamples=0,refitsSinceBuild=0,checkAllocation=true,probe=null,denoiser=null,revision=0
  function dispose(){
    if(disposed)return closing;disposed=true
    worker?.dispose();worker=null
    const release=()=>{
      geometry?.dispose();geometry=null
      denoiser?.dispose();probe?.dispose();schedule.dispose();tracer.dispose();quad.dispose();quad.material.dispose();textures.dispose()
      for(const value of Object.values(material.uniforms))value.value?.dispose?.()
      material.dispose();env?.dispose();background.dispose()
    }
    // Three's async compiler still polls material/program state. Keep that
    // state alive until it settles, even when a view update is cancelled.
    if(compiling)closing=compiling.catch(()=>{}).then(release)
    else release()
    return closing
  }
  async function update({scene,camera,settings,viewHeight,signal,onProgress=()=>{},onStatus=()=>{}}){
    const started=performance.now();signal?.throwIfAborted()
    onStatus({stage:'snapshot',label:'Preparing tracing geometry…',fraction:null})
    if(disposed)throw new Error('Path tracer disposed.')
    if(renderer.clippingPlanes?.length)throw new Error('Disable section clipping before GPU path tracing.')
    let snapshot=null,generator=null,abort
    const copies=[]
    const cancelled=new Promise((_,reject)=>{abort=()=>{worker?.dispose();worker=null;reject(signal.reason??new DOMException('Cancelled','AbortError'))}})
    signal?.addEventListener('abort',abort,{once:true})
    try{
      snapshot=await traceSnapshotAsync(scene,camera,viewHeight,{maxTextureSize:renderer.capabilities.maxTextureSize,signal,onProgress:fraction=>onStatus({stage:'snapshot',fraction,label:'Preparing scene snapshot'})})
      material.transmissiveBounces=snapshot.smoothEM?160:5
      if(!snapshot.triangles)throw new Error('There are no visible surfaces or EM samples to path trace.')
      onStatus({stage:'geometry',fraction:null,label:'Preparing tracing geometry and acceleration'})
      generator=new DynamicPathTracingSceneGenerator(snapshot.root.children);generator.prepScene()
      checkTraceGeometry({vertices:generator.geometry.attributes.position.count,triangles:generator.geometry.index.count/3},renderer.capabilities.maxTextureSize)
      // Rebuild periodically to avoid a degraded tree after large trajectory motion.
      const reused=refitsSinceBuild<32 && reuseTraceGeometry(geometry,generator.geometry,originalIndex)
      if(reused){
        onStatus({reused:['geometry']})
        if(reused.moved){bvh.refit();material.bvh.updateFrom(bvh);stats.refits++;refitsSinceBuild++}
      }else{
        const nextIndex=generator.geometry.index.array.slice()
        worker??=new GenerateMeshBVHWorker()
        const next=await Promise.race([worker.generate(generator.geometry,{...treeOptions,onProgress}),cancelled])
        signal?.throwIfAborted();if(disposed)throw new Error('Path tracer disposed.')
        geometry?.dispose();geometry=generator.geometry;generator.geometry=null
        bvh=next;originalIndex=nextIndex;checkTraceBVH(bvh,renderer.capabilities.maxTextureSize);material.bvh.updateFrom(bvh);stats.builds++;refitsSinceBuild=0
      }
      onStatus({stage:'environment',fraction:null,label:'Preparing GPU materials and environment'})
      const attributes=geometry.attributes
      material.attributesArray.updateFrom(attributes.normal,attributes.tangent,attributes.uv,attributes.color)
      material.materialIndexAttribute.updateFrom(attributes.materialIndex)
      // Clone wrappers: texture atlas preparation changes matrices temporarily.
      for(const texture of generator.textures){const copy=texture.clone();copy.needsUpdate=true;copies.push(copy)}
      const gl=renderer.getContext(),layers=gl.getParameter(gl.MAX_ARRAY_TEXTURE_LAYERS)
      if(copies.length>layers)throw new Error(`WebGL needs ${copies.length} texture layers; this device reports a limit of ${layers}.`)
      const textureSize=Math.min(renderer.capabilities.maxTextureSize,Math.max(1,...copies.map(t=>Math.max(t.image?.width??1,t.image?.height??1))))
      textures.setTextures(renderer,textureSize,textureSize,copies)
      material.materials.updateFrom(generator.materials,generator.textures);material.lights.updateFrom(generator.lights)
      const ambient=[];scene.traverseVisible(o=>{if(o.isAmbientLight)ambient.push(o.color.toArray(),o.intensity)})
      const key=JSON.stringify([settings.studioEnvironment,settings.studioEnvironmentIntensity,ambient])
      if(key!==environmentKey){env?.dispose();env=traceEnvironment(renderer,scene,settings);material.envMapInfo.updateFrom(env);environmentKey=key;stats.environmentBuilds++}
      material.environmentRotation.makeRotationFromEuler(scene.environmentRotation)
      new THREE.Color(settings.bgColor??'#ffffff').toArray(background.image.data);background.image.data[3]=1;background.needsUpdate=true
      material.backgroundAlpha=settings.bgType==='transparent'?0:1
      tracer.alpha=settings.bgType==='transparent';tracer.camera=camera;tracer.reset();revision++;checkAllocation=true
      triangles=snapshot.triangles;emSamples=snapshot.emSamples;stats.updates++;stats.prepareMs=performance.now()-started
      const compileStart=performance.now()
      compiling=compileTraceMaterial({renderer,material,camera,target:tracer.target,signal,onStatus})
      try{await compiling}finally{compiling=null}
      stats.compileMs=performance.now()-compileStart
    }finally{signal?.removeEventListener('abort',abort);snapshot?.dispose();generator?.geometry?.dispose();copies.forEach(t=>t.dispose())}
  }
  const api={
    get triangles(){return triangles},get emSamples(){return emSamples},get samples(){return tracer.samples},
    get diagnostics(){return {...stats,...schedule.diagnostics,denoiseRuns:denoiser?.runs??0,width:tracer.target.width,height:tracer.target.height,tilesX:tracer.tiles.x,tilesY:tracer.tiles.y,gpuBatchMs:schedule.gpuMs}},
    update,
    setView(camera,scene,w,h,tiles=1){
      scene.updateMatrixWorld(true)
      material.lights.updateFrom(traceLights(scene));material.environmentRotation.makeRotationFromEuler(scene.environmentRotation)
      tracer.camera=camera;tracer.tiles.set(tiles,tiles);tracer.setSize(w,h);tracer.reset();revision++;checkAllocation=true
    },
    step(){
      if(renderer.getContext().isContextLost())throw new Error('WebGL device/context was lost while tracing. GPU memory is shared with other applications.')
      const previous=renderer.debug.onShaderError;let failure=''
      renderer.debug.onShaderError=(gl,program)=>{failure=gl.getProgramInfoLog(program)||'GPU shader compilation failed'}
      try{tracer.update()}finally{renderer.debug.onShaderError=previous}
      if(failure)throw new Error(`GPU path tracing is unavailable: ${failure}`)
      if(checkAllocation){
        checkAllocation=false
        const gl=renderer.getContext(),code=gl.getError()
        if(gl.isContextLost() || code!==gl.NO_ERROR)
          throw new Error(`WebGL could not allocate or use this scene on the current device (${gl.isContextLost()?'context lost':code===gl.OUT_OF_MEMORY?'out of GPU memory':`GPU error ${code}`}). Other applications also share GPU memory.`)
      }
    },
    advance(target){return schedule.run(api,target)},ready:()=>schedule.ready(),
    reset(camera,w,h,tiles=tileCount){tracer.camera=camera;tracer.tiles.set(tiles,tiles);tracer.setSize(w,h);tracer.reset();revision++;checkAllocation=true},
    drawRaw(target){const previous=renderer.getRenderTarget();try{renderer.setRenderTarget(target);quad.material.map=currentTarget().texture;quad.render(renderer)}finally{renderer.setRenderTarget(previous)}},
    draw(target,{denoise=false}={}){
      if(!denoise){api.drawRaw(target);return}
      denoiser??=createTraceDenoiser(renderer)
      denoiser.draw(api.denoisedTarget(),target)
    },
    denoisedTarget(){
      denoiser??=createTraceDenoiser(renderer)
      return denoiser.render(api.drawRaw,tracer.target.width,tracer.target.height,`${revision}:${tracer.samples}`)
    },
    readProbe(){probe??=createTraceProbe(renderer);return probe.read(currentTarget().texture)},
    readPixels(){
      const target=currentTarget(),pixels=new Float32Array(target.width*target.height*4)
      renderer.readRenderTargetPixels(target,0,0,target.width,target.height,pixels)
      return pixels
    },
    dispose,
  }
  try{await update({scene,camera,settings,viewHeight,signal,onProgress,onStatus});return api}catch(error){dispose();throw error}
}
