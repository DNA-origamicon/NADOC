import * as THREE from 'three'
import { Pass } from 'three/addons/postprocessing/Pass.js'
import { traceOutputKey, createTraceOutputCache } from './path_trace_output.js'
import { createTraceMotion } from './trace_motion.js'
import { createTraceMetrics } from './trace_metrics.js'
import { createTraceWorkProgress } from './trace_work_progress.js'
import { geometryLoads } from '../geometry_loads.js'

export const TRACE_DEFAULTS=Object.freeze({pathTracing:false,pathTraceInteractive:true,pathTraceDenoise:true,pathTraceSamples:64,pathTraceExportBackend:'webgl',pathTracePreviewBackend:'webgl'})
export const traceSamples=value=>Math.max(1,Math.min(512,Math.round(Number(value)||64)))
const loadEngine=backend=>backend==='optix'?import('./path_trace_native_preview.js').then(m=>m.createNativeTracePreviewEngine):import('./path_trace_engine.js').then(m=>m.createTraceEngine)

export function createTracePreview({scene,camera,renderer,settings,isActive,load=loadEngine,now=()=>performance.now(),fingerprint,geometry=geometryLoads,prepare=()=>{}}) {
  let engine=null,controller=null,pending=false,valid=false,stamp=null,changedAt=0,error='',exporting=0,progress=0,phase=null,phaseRevision=0
  let work=createTraceWorkProgress(settings.pathTracePreviewBackend,traceSamples(settings.pathTraceSamples))
  let disposal=Promise.resolve(),buildFinished=Promise.resolve()
  let geometryRevision=geometry.getState().revision
  const outputCache=createTraceOutputCache(),metrics=createTraceMetrics({now})
  let completedSamples=0,lastCpuMs=0
  let metricsEnabled=false,moving=false,sceneStamp=null,viewStamp=null,motionChangedAt=0
  const motion=createTraceMotion(),identityCamera=new THREE.Camera()
  const tracingSettings=()=>Object.fromEntries(Object.entries(settings).filter(([key])=>!['pathTraceSamples','pathTraceExportBackend','pathTraceDenoise'].includes(key)))
  const sceneSignature=()=>fingerprint?fingerprint():traceOutputKey({scene,camera:identityCamera,settings:tracingSettings(),
    width:renderer.domElement.width,height:renderer.domElement.height,viewHeight:renderer.getSize(new THREE.Vector2()).y,ignoreTraceLighting:true})
  function completed(){
    const ready=engine.ready?.()??true
    if(ready&&valid){
      completedSamples=engine.samples
      const d=engine.diagnostics
      metrics.completeSamples({samples:completedSamples,width:d?.width,height:d?.height})
    }
    return ready
  }
  function probe(){
    if(metricsEnabled&&!moving&&valid&&engine.readProbe&&metrics.wantsProbe(engine.samples)&&completed()){
      const before=now(),pixels=engine.readProbe();metrics.probe(engine.samples,pixels,now()-before)
    }
  }
  const signature=fingerprint??(()=>traceOutputKey({scene,camera,settings:tracingSettings(),width:renderer.domElement.width,height:renderer.domElement.height,viewHeight:renderer.getSize(new THREE.Vector2()).y}))
  function clear(){phaseRevision++;phase=null;controller?.abort();controller=null;if(engine)disposal=Promise.resolve(engine.dispose()).catch(e=>console.warn(e));engine=null;pending=false;valid=false}
  function stop(){work=createTraceWorkProgress(settings.pathTracePreviewBackend,traceSamples(settings.pathTraceSamples));outputCache.clear();clear();valid=false;stamp=null;sceneStamp=null;moving=false;error='';progress=0;completedSamples=0;metrics.reset()}
  async function build(key){
    const previousBuild=buildFinished;let finishBuild
    buildFinished=new Promise(resolve=>{finishBuild=resolve})
    work=createTraceWorkProgress(settings.pathTracePreviewBackend,traceSamples(settings.pathTraceSamples))
    const own=new AbortController();controller=own;pending=true;progress=0
    const revision=geometryRevision,ownPhase=++phaseRevision
    try {
      await previousBuild;await disposal;own.signal.throwIfAborted()
      // Match the actual drawing buffer, including device pixel ratio. More
      // samples cannot recover detail lost by tracing a downscaled viewport.
      const size=renderer.getDrawingBufferSize(new THREE.Vector2())
      if(Math.max(size.x,size.y)>(renderer.capabilities?.maxTextureSize??Infinity))
        throw new Error('The viewport exceeds the GPU render-target limit. Reduce the window size to path trace.')
      const options={scene,camera:camera.clone(),renderer,settings:{...settings},
        width:Math.max(1,Math.ceil(size.x)),height:Math.max(1,Math.ceil(size.y)),viewHeight:renderer.getSize(new THREE.Vector2()).y,
        signal:own.signal,tileCount:Math.max(4,Math.ceil(Math.max(size.x,size.y)/256)),onProgress:value=>{if(controller===own){progress=value;phase={stage:'geometry',fraction:value,label:`Building tracing geometry · ${Math.round(value*100)}%`};work.event(phase)}},
        onStatus:info=>{if(phaseRevision===ownPhase){phase=info;work.event(info)}}}
      let next=engine
      if(next?.update){await next.update(options);next.reset(options.camera,options.width,options.height,options.tileCount)}
      else {const create=await load(settings.pathTracePreviewBackend??'webgl');own.signal.throwIfAborted();next=await create(options)}
      if(own.signal.aborted || stamp!==key || !isActive() || !settings.pathTracing ||
        geometry.getState().busy || geometry.getState().revision!==revision){await next.dispose();if(engine===next)engine=null;return}
      if(settings.pathTracePreviewBackend!=='optix')work.event({stage:'tracing',fraction:0})
      engine=next;valid=true;sceneStamp=sceneSignature();viewStamp=stamp;moving=false;completedSamples=0;metrics.reset()
    }catch(e){if(!own.signal.aborted){clear();error=e.message}}
    finally{finishBuild();if(controller===own){pending=false;controller=null}}
  }
  function frame(){
    if(!isActive() || !settings.pathTracing){if(engine||pending)stop();return false}
    if(exporting)return false
    const loading=geometry.getState()
    if(loading.revision!==geometryRevision){
      geometryRevision=loading.revision;stop();changedAt=now()
    }
    if(loading.busy)return false
    scene.updateMatrixWorld(true);camera.updateMatrixWorld(true)
    const key=signature()
    if(key!==stamp){
      if(settings.pathTraceInteractive!==false&&valid&&!pending&&engine?.setView&&!engine.emSamples&&sceneSignature()===sceneStamp){
        if(!moving){moving=true;motion.begin(now())}
        motionChangedAt=now();stamp=key
      }else{
        if(pending || !engine?.update)clear()
        work=createTraceWorkProgress(settings.pathTracePreviewBackend,traceSamples(settings.pathTraceSamples))
        moving=false;valid=false;stamp=key;changedAt=now();error='';return false
      }
    }
    if(error)return false
    if(!valid){
      if(!pending && now()-changedAt>=200){
        try{
          // A native frame cannot be resumed after cancelling its request.
          // Keep the worker alive, hide the obsolete frame and coalesce view
          // changes until that in-flight work finishes before updating it.
          if(engine&&!(engine.ready?.()??true))return false
          // Install Appearance materials/bounds before taking the final snapshot,
          // rather than waiting for its periodic mesh-change check mid-render.
          prepare();scene.updateMatrixWorld(true);camera.updateMatrixWorld(true)
          stamp=signature();void build(stamp)
        }catch(e){error=e.message}
      }
      return false
    }
    try{
      if(moving&&completed()){
        if(engine.samples>=1)motion.complete(now())
        const size=renderer.getDrawingBufferSize(new THREE.Vector2())
        if(now()-motionChangedAt>=200){
          engine.setView(camera.clone(),scene,size.x,size.y,Math.max(4,Math.ceil(Math.max(size.x,size.y)/256)))
          moving=false;viewStamp=stamp;completedSamples=0;metrics.reset()
        }else if(viewStamp!==stamp&&motion.due(now())){
          const sizeNext=motion.submit(now(),size.x,size.y)
          engine.setView(camera.clone(),scene,sizeNext.width,sizeNext.height,1);viewStamp=stamp;completedSamples=0;metrics.reset()
        }
      }
      probe()
      let target=moving?1:traceSamples(settings.pathTraceSamples)
      // Visit exact doubling counts when measuring, so independent half-blocks
      // have equal size even when adaptive batches cross whole samples.
      if(metricsEnabled&&!moving&&engine.readProbe)target=Math.min(target,2**Math.ceil(Math.log2(Math.max(1,engine.samples+1e-6))))
      if(engine.samples<target&&completed()){if(engine.advance)engine.advance(target);else engine.step()}
      return engine.samples>=1
    }
    catch(e){clear();error=e.message;return false}
  }
  class TracePass extends Pass {
    constructor(raster){super();this.raster=raster;this.needsSwap=false}
    render(r,w,read,...rest){
      // Count GPU-completed work before submitting/resetting the next view.
      // Submitted samples alone would report a fictitious FPS on a busy GPU.
      try{if(valid&&(engine.ready?.()??true))completedSamples=engine.samples}
      catch(e){clear();valid=false;error=e.message}
      const diagnostics=engine?.diagnostics
      metrics.frame({samples:valid?completedSamples:0,width:diagnostics?.width,height:diagnostics?.height,cpuMs:lastCpuMs,traced:valid&&completedSamples>=1})
      const start=now();let traced=frame()
      if(traced){
        try{
          engine.draw(this.renderToScreen?null:read,{denoise:settings.pathTraceDenoise!==false})
          if(engine.ready?.()??true){
            if(settings.pathTracePreviewBackend!=='optix')work.event({stage:'tracing',fraction:engine.samples/traceSamples(settings.pathTraceSamples),label:`Sampling · ${Math.floor(engine.samples)} / ${traceSamples(settings.pathTraceSamples)}`})
            if(engine.samples>=traceSamples(settings.pathTraceSamples))work.event({stage:'display',fraction:1,label:'Image ready'})
          }
        }
        catch(e){clear();error=e.message;traced=false}
      }
      if(!traced){this.raster.renderToScreen=this.renderToScreen;this.raster.render(r,w,read,...rest)}
      lastCpuMs=now()-start
    }
  }
  return {
    pass:raster=>new TracePass(raster), stop,
    setMetricsEnabled(value){metricsEnabled=!!value},
    setDenoise(value){settings.pathTraceDenoise=!!value;outputCache.clear();if(error)stop()},
    setInteractive(value){settings.pathTraceInteractive=!!value;stop()},
    setEnabled(value){settings.pathTracing=!!value;stop()},
    setSamples(value){
      const target=traceSamples(value)
      if(target===settings.pathTraceSamples)return
      settings.pathTraceSamples=target
      // Let an in-flight native request finish, then reuse its scene for the
      // changed target. Never label still-uploading geometry as prewarmed.
      if(valid&&settings.pathTracePreviewBackend==='optix'&&engine?.diagnostics?.pending){
        phaseRevision++;phase=null;valid=false;stamp=null
      }
      if(pending)return // startup's measured work remains valid for either target
      work=createTraceWorkProgress(settings.pathTracePreviewBackend,target)
      if(valid)work.event({reused:settings.pathTracePreviewBackend==='optix'
        ?['device','snapshot','environment','upload','decode','geometry','quick-acceleration','quick-tracing','quick-readback','quick-delivery']
        :['snapshot','geometry','environment','compile']})
    },
    setPreviewBackend(value){settings.pathTracePreviewBackend=value==='optix'?'optix':'webgl';stop()},
    setExportBackend(value){settings.pathTraceExportBackend=['webgl','webgpu','optix'].includes(value)?value:'webgl'},
    outputCache,
    // Pause accumulation without throwing away a stationary, already solved view.
    beginExport(){exporting++;if(pending){clear();valid=false}let released=false;return()=>{if(!released){released=true;exporting--}}},
    async releaseEngineForExport(){clear();valid=false;await buildFinished;await disposal},
    completedFrame({camera:requested,width,height,backend,samples}){
      scene.updateMatrixWorld(true);camera.updateMatrixWorld(true)
      if(geometry.getState().busy || geometry.getState().revision!==geometryRevision ||
        moving || backend!==(settings.pathTracePreviewBackend??'webgl') || !valid || pending || error || !engine?.readPixels ||
        engine.samples<samples || !Number.isInteger(engine.samples) || !engine.ready() || signature()!==stamp ||
        width!==renderer.domElement.width || height!==renderer.domElement.height ||
        !requested.matrixWorld.equals(camera.matrixWorld) || !requested.projectionMatrix.equals(camera.projectionMatrix) ||
        requested.layers.mask!==camera.layers.mask)return null
      return {pixels:engine.readPixels(),samples:engine.samples}
    },
    getStatus(){return {enabled:settings.pathTracing,backend:settings.pathTracePreviewBackend??'webgl',samples:valid?Math.floor(engine?.samples??0):0,target:traceSamples(settings.pathTraceSamples),
      state:!settings.pathTracing?'off':geometry.getState().busy?'loading':error?'error':exporting?'exporting':pending?'building':!valid&&engine?.diagnostics?.pending?'updating':moving?'interactive':valid?'tracing':'waiting',
      progress,phase,work:work.get(),emSamples:engine?.emSamples??0,triangles:engine?.triangles??0,diagnostics:engine?.diagnostics,metrics:{...metrics.get(),...motion.state,interactive:moving},error}},
  }
}
