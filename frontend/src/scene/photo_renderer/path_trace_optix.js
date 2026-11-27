import * as THREE from 'three'
import {FullScreenQuad} from 'three/addons/postprocessing/Pass.js'
import {traceSnapshotAsync} from './path_trace_snapshot.js'
import {traceEnvironment} from './path_trace_environment.js'
import {nativeTracePayload,nativeTraceLighting} from './path_trace_native_payload.js'
import {requestOptix} from './path_trace_errors.js'
import {pollNativeTrace} from './path_trace_native_progress.js'
import {createTraceDenoiser} from './trace_denoise.js'
import {traceOutputKey} from './path_trace_output.js'
import {readNativeImage} from './path_trace_native_image.js'
import {createNativeSession} from './path_trace_native_session.js'

/** Persistent native renderer shared by offline output and the async preview adapter. */
export async function createOptixTraceEngine(options){
  const controller=new AbortController(),signal=options.signal
  const abort=()=>controller.abort(signal?.reason);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort()
  let id=null,payload=null,camera=null,width=options.width,height=options.height,samples=0,image=null,disposed=false
  let onStatus=options.onStatus,sequence=0,stopProgress=null,uploaded=false,capacity=null,pixels=null,filter=null,revision=0
  let accumulationTarget=null,emVolumeCells=0
  let stats={},device='',lease=null,closing=null,triangles=0,emSamples=0,sceneKey=null,startupMs=0,lightingUpdate=null,lightingKey=null
  const identityCamera=new THREE.Camera()
  const keyFor=next=>{ let smooth=false;next.scene.traverseVisible(o=>{if(o.userData.emSmooth)smooth=true})
    return traceOutputKey({scene:next.scene,camera:identityCamera,
    settings:Object.fromEntries(Object.entries(next.settings).filter(([k])=>!k.startsWith('pathTrace')&&k!=='pathTracing')),
    width:next.width,height:next.height,viewHeight:next.viewHeight,ignoreTraceLighting:true,ignoreEM:!smooth}) }
  const renderer=options.renderer,quad=new FullScreenQuad(new THREE.MeshBasicMaterial({toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending}))
  const request=(path,body,extra)=>requestOptix(path,body,controller.signal,extra)
  async function update(next){
    onStatus=next.onStatus
    if(sceneKey!==null)onStatus?.({reused:['device']})
    if(sceneKey!==null&&sceneKey===keyFor(next)){
      onStatus?.({reused:['environment']})
      const snapshot=await traceSnapshotAsync(next.scene,next.camera,next.viewHeight,{compactEM:true,onlyEM:true,
        signal:controller.signal,onProgress:fraction=>onStatus?.({stage:'snapshot',fraction,label:'Preparing EM emitters; retaining molecular geometry'})})
      try{
        const hasEM=emSamples>0||snapshot.emSamples>0||lightingUpdate?.emitters!==undefined
        if(!hasEM)onStatus?.({reused:['snapshot','upload','decode','geometry']})
        triangles+=snapshot.triangles-emSamples*20;emSamples=snapshot.emSamples
        const lighting=nativeTraceLighting(next.scene)
        const key=JSON.stringify(lighting),update={...(key!==lightingKey?lighting:{}),...(hasEM?{emitters:snapshot.emitters}:{})}
        if(uploaded)lightingUpdate={...lightingUpdate,...update}
        else Object.assign(payload,update)
        lightingKey=key
      }finally{snapshot.dispose()}
      camera=next.camera;samples=0;revision++;return
    }
    const snapshot=await traceSnapshotAsync(next.scene,next.camera,next.viewHeight,{compactEM:true,signal:controller.signal,onProgress:fraction=>onStatus?.({stage:'snapshot',fraction,label:'Preparing scene snapshot'})});let env
    onStatus?.({stage:'environment',fraction:null,label:'Preparing materials and environment'})
    try{env=traceEnvironment(renderer,next.scene,next.settings);payload=nativeTracePayload(snapshot,env,next.scene,next.settings);triangles=snapshot.triangles;emSamples=snapshot.emSamples
      emVolumeCells=payload.volumes.reduce((sum,v)=>sum+v.values.byteLength/16,0)}
    finally{snapshot.dispose();env?.dispose()}
    lightingUpdate=null;lightingKey=JSON.stringify({lights:payload.lights,rotation:payload.rotation})
    sceneKey=keyFor(next);camera=next.camera;samples=0;uploaded=false;revision++
  }
  function drawRaw(target){const previous=renderer.getRenderTarget();try{renderer.setRenderTarget(target);quad.render(renderer)}finally{renderer.setRenderTarget(previous)}}
  const api={update,get samples(){return samples},get triangles(){return triangles},get emSamples(){return emSamples},get emVolumeCells(){return emVolumeCells},
    get diagnostics(){return {...stats,startupMs,backend:'optix',device,experimental:true,width,height,denoiseRuns:filter?.runs??0}},
    reset(c,w,h){camera=c;width=w;height=h;samples=0;revision++},ready:()=>true,
    async advance(count,{quick=false,sampleTarget=count}={}){
      const base=accumulationTarget===sampleTarget?samples:0,batch=count-base
      if(batch<=0)return
      const started=performance.now(),requestId=String(++sequence)
      const report=info=>{
        if(info.stage==='complete')info={stage:'readback',fraction:1,label:'Native image ready for transfer'}
        if(info.stage==='tracing')info={...info,samples:base+info.samples,target:sampleTarget,fraction:(base+info.samples)/sampleTarget,
          label:`OptiX · ${base+info.samples}/${sampleTarget} samples`}
        if(quick&&['acceleration','tracing','readback','delivery'].includes(info.stage))info={...info,stage:`quick-${info.stage}`}
        else if(count<sampleTarget&&['acceleration','readback','delivery'].includes(info.stage))info={...info,stage:'tracing',fraction:base/sampleTarget}
        onStatus?.(info)
      }
      report({stage:uploaded?'acceleration':'upload',label:uploaded?'Updating OptiX camera and lighting':'Encoding / uploading OptiX scene',fraction:uploaded?null:0})
      stopProgress=pollNativeTrace(id,requestId,report)
      try{
        const response=await request(`/${id}/frame`,{...(uploaded?{reuse_scene:true,...lightingUpdate}:payload),width,height,samples:batch,sample_offset:base,sample_total:sampleTarget,
          camera:{matrix:camera.matrixWorld.toArray(),projection:camera.projectionMatrix.toArray(),orthographic:!!camera.isOrthographicCamera}},
        {maxBytes:capacity.upload_limit_bytes,requestId,onProgress:uploaded?undefined:report})
        stopProgress?.();stopProgress=null
        const next=new Float32Array(await readNativeImage(response,width*height*16,controller.signal,report));controller.signal.throwIfAborted()
        if(next.length!==width*height*4)throw new Error('OptiX returned an incomplete frame.')
        stats=JSON.parse(response.headers.get('X-NADOC-Render-Stats')??'{}');stats.requestMs=performance.now()-started
        stats.chunkSamples=batch;stats.sampleOffset=base;stats.samples=count
        if(base&&pixels)for(let i=0;i<next.length;i++)next[i]=pixels[i]+(next[i]-pixels[i])*(batch/count)
        pixels=next;accumulationTarget=sampleTarget;uploaded=true;payload=null;lightingUpdate=null
        image?.dispose();image=new THREE.DataTexture(pixels,width,height,THREE.RGBAFormat,THREE.FloatType);image.needsUpdate=true;quad.material.map=image;samples=count;revision++
        if(count<sampleTarget&&!quick)onStatus?.({stage:'tracing',fraction:count/sampleTarget,samples:count,target:sampleTarget,label:`OptiX · ${count}/${sampleTarget} samples displayed`})
      }finally{stopProgress?.();stopProgress=null}
    },
    readPixels:()=>pixels?.slice(),
    denoisedTarget(){filter??=createTraceDenoiser(renderer);return filter.render(drawRaw,width,height,revision)},
    draw(target,{denoise=false}={}){if(denoise){const result=api.denoisedTarget();filter.draw(result,target)}else drawRaw(target)},
    dispose(){
      if(disposed)return closing;disposed=true;stopProgress?.();controller.abort();signal?.removeEventListener('abort',abort)
      filter?.dispose();image?.dispose();quad.dispose();quad.material.dispose()
      closing=lease?.close()??Promise.resolve()
      return closing
    },
  }
  try{
    const started=performance.now()
    onStatus?.({stage:'device',fraction:null,label:'Starting native OptiX device'})
    lease=await createNativeSession({signal:controller.signal});id=lease.id;device=lease.device
    startupMs=performance.now()-started
    capacity=lease.capacity
    await update(options);return api
  }catch(e){await api.dispose();throw e}
}
