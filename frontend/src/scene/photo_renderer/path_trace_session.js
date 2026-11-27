import {drawEMVolumes,releaseEMVolumeRenderer} from '../em_volume.js'
import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { FigurePass } from './figure_pass.js'
import { createTraceDenoiser, traceDenoiseTile, TRACE_DENOISE_HALO } from './trace_denoise.js'
import { traceSamples } from './path_trace_preview.js'
import { traceOutputKey } from './path_trace_output.js'
import { traceSampleProgress } from './path_trace_progress.js'
import { settleEMExport } from '../em_export.js'
import { settleZoomVolumes, drawZoomVolumes } from '../zoom_volume_export.js'
import { syncSceneAnnotations, drawSceneAnnotations } from '../annotation_overlay.js'
import { assertPlacementExportSafe } from '../../viewer/placement_scene_guard.js'
import { traceExportError } from './path_trace_errors.js'

const nextTask=()=>new Promise(resolve=>setTimeout(resolve,0))
/** Offline accumulation, with exact-match reuse of completed output/preview. */
export function createTraceFrameSession({scene,camera,renderer:liveRenderer,settings,width,height,grading,preview,syncFrame,figureParams,cueRange,signal,onProgress}) {
  const canvas=Object.assign(document.createElement('canvas'),{width,height}),ctx=canvas.getContext('2d',{willReadFrequently:true})
  const renderer=new THREE.WebGLRenderer({alpha:true,preserveDrawingBuffer:true})
  renderer.toneMapping=THREE.ACESFilmicToneMapping
  const denoise=settings.pathTraceDenoise!==false,halo=denoise?TRACE_DENOISE_HALO:0
  const filter=denoise?createTraceDenoiser(renderer):null
  let drawRevision=0
  const tileMax=Math.min(renderer.capabilities.maxTextureSize-2*halo,1024),nx=Math.ceil(width/tileMax),ny=Math.ceil(height/tileMax)
  const tw=Math.ceil(width/nx),th=Math.ceil(height/ny)
  renderer.setPixelRatio(1);renderer.setSize(tw,th,false)
  const frameCamera=camera.clone(),composer=new EffectComposer(renderer)
  let engine=null,drawable=null,disposed=false,busy=false,closing=null,diagnostics=null,report=onProgress
  const backend=settings.pathTraceExportBackend??'webgl'
  class TracePass extends Pass {
    constructor(){super();this.needsSwap=false}
    render(r,w,read){
      const target=this.renderToScreen?null:read
      if(filter){
        const size=renderer.getDrawingBufferSize(new THREE.Vector2())
        filter.draw(filter.render(t=>drawable.draw(t),size.x,size.y,++drawRevision),target)
      }else drawable.draw(target)
      drawEMVolumes(r,scene,frameCamera,target)
    }
  }
  composer.addPass(new TracePass())
  const figure=new FigurePass(scene,frameCamera);composer.addPass(figure)
  composer.addPass(new OutputPass())
  const grade=grading.create();composer.addPass(grade);composer.setSize(tw,th)
  const controller=new AbortController(),release=preview.beginExport()
  const abort=()=>controller.abort(signal?.reason)
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort()
  function check(){controller.signal.throwIfAborted();if(disposed || !settings.pathTracing)throw new Error('GPU path-traced export cancelled.')}
  function draw(){figure.setParams(figureParams());cueRange(figure);figure.enabled=figure.hasEffect();composer.render()}
  async function renderFrameToCanvas(){
    check();if(busy)throw new Error('A path-traced frame is already rendering.')
    busy=true
    let stage='preparing EM data'
    const phase=async(label,key='prepare',fraction=null)=>{stage=label[0].toLowerCase()+label.slice(1);report?.({stage:key,label,fraction});await nextTask();check()}
    try {
      await phase('Preparing EM data');await settleEMExport(scene)
      await phase('Preparing zoom insets');await settleZoomVolumes(scene);check()
      await phase('Preparing the scene')
      assertPlacementExportSafe(scene);syncSceneAnnotations(scene);syncFrame()
      frameCamera.copy(camera);frameCamera.aspect=width/height;frameCamera.clearViewOffset();frameCamera.updateProjectionMatrix();frameCamera.updateMatrixWorld(true)
      renderer.toneMappingExposure=settings.exposure
      const viewHeight=liveRenderer.getSize(new THREE.Vector2()).y,target=traceSamples(settings.pathTraceSamples)
      const keyOptions={scene,camera:frameCamera,settings:{...settings,pathTraceExportBackend:backend,pathTraceDenoise:denoise},width,height,viewHeight}
      const key=traceOutputKey(keyOptions),cached=preview.outputCache?.get(key)
      const solved=!cached && preview.completedFrame?.({camera:frameCamera,width,height,backend,samples:target})
      ctx.clearRect(0,0,width,height)
      if(cached){
        report?.({stage:'reused',label:'Reusing completed export',fraction:1})
        ctx.drawImage(cached,0,0);diagnostics={reused:'export'}
      }else if(solved){
        report?.({stage:'reused',label:`Reusing ${solved.samples} completed viewport samples`,fraction:1})
        const texture=new THREE.DataTexture(solved.pixels,width,height,THREE.RGBAFormat,THREE.FloatType);texture.needsUpdate=true
        const material=new THREE.MeshBasicMaterial({map:texture,toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending}),quad=new FullScreenQuad(material)
        try{
          drawable={draw(target){const previous=renderer.getRenderTarget();try{renderer.setRenderTarget(target);quad.render(renderer)}finally{renderer.setRenderTarget(previous)}}}
          renderer.setSize(width,height,false);composer.setSize(width,height);if(denoise)await phase('Denoising completed samples','denoise',1);draw();ctx.drawImage(renderer.domElement,0,0)
          diagnostics={reused:'preview',samples:solved.samples}
        }finally{texture.dispose();quad.dispose();material.dispose();drawable=null;renderer.setSize(tw,th,false);composer.setSize(tw,th)}
      }else{
        await preview.releaseEngineForExport?.()
        await phase('Loading the renderer')
        const createTraceEngine=backend==='webgpu'?(await import('./path_trace_webgpu.js')).createWebGPUTraceEngine:
          backend==='optix'?(await import('./path_trace_optix.js')).createOptixTraceEngine:
          (await import('./path_trace_engine.js')).createTraceEngine
        await phase('Initializing the renderer and scene')
        let tile=0
        const options={scene,camera:frameCamera,renderer,width:tw,height:th,viewHeight,settings:{...settings},signal:controller.signal,
          onProgress:fraction=>report?.({stage:'geometry',label:`Building tracing geometry · ${Math.round(fraction*100)}%`,fraction}),
          onStatus:info=>report?.(info.stage==='tracing'?{...traceSampleProgress(tile,nx*ny,info.samples,target),native:true}:info)}
        if(engine)await engine.update(options)
        else engine=await createTraceEngine(options)
        drawable=engine
        for(let y=0;y<ny;y++)for(let x=0;x<nx;x++) {
          tile=y*nx+x;stage=`rendering tile ${tile+1} of ${nx*ny}`
          check();const tileView=traceDenoiseTile(x,y,width,height,tw,th,halo)
          const {width:rw,height:rh}=tileView
          renderer.setSize(rw,rh,false);composer.setSize(rw,rh)
          frameCamera.setViewOffset(width,height,tileView.x,tileView.y,rw,rh);frameCamera.updateProjectionMatrix()
          engine.reset(frameCamera,rw,rh)
          report?.(traceSampleProgress(tile,nx*ny,0,target))
          while(engine.samples<target) {check();await engine.advance(target);report?.(traceSampleProgress(tile,nx*ny,engine.samples,target));await nextTask()}
          while(!engine.ready()){check();await nextTask()}
          await engine.prepareDraw?.();check()
          if(denoise)await phase(`Denoising tile ${tile+1} of ${nx*ny}`,'denoise',(tile+1)/(nx*ny))
          draw();ctx.drawImage(renderer.domElement,tileView.cropX,tileView.cropY,tileView.coreWidth,tileView.coreHeight,
            tileView.left,tileView.top,tileView.coreWidth,tileView.coreHeight)
        }
        diagnostics={...engine.diagnostics,reused:false}
      }
      frameCamera.clearViewOffset();frameCamera.updateProjectionMatrix()
      // The cache excludes annotations/insets: these may change independently of
      // the molecular scene and must be drawn anew even when rays are reused.
      if(!cached && traceOutputKey({...keyOptions,settings:{...settings,pathTraceExportBackend:backend,pathTraceDenoise:denoise}})===key)preview.outputCache?.put(key,canvas)
      await phase('Compositing the image','composite',1)
      drawSceneAnnotations(scene,ctx,width,height,frameCamera);drawZoomVolumes(scene,ctx,width,height,frameCamera)
      assertPlacementExportSafe(scene);check()
      report?.({stage:'complete',label:'Image rendered',fraction:1})
      return canvas
    }catch(error){
      try{await engine?.dispose()}catch(cleanupError){console.warn('Path-tracer cleanup failed',cleanupError)}finally{engine=null;drawable=null}
      throw traceExportError(error,backend,stage)
    }finally{busy=false}
  }
  return {
    renderFrameToCanvas,
    setProgressCallback(callback){report=callback},
    getDiagnostics:()=>diagnostics??engine?.diagnostics,
    async renderFrame(){
      await renderFrameToCanvas();report?.({stage:'encode',label:'Encoding PNG',fraction:null});await nextTask();check()
      const blob=await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG capture failed')),'image/png'))
      check();return blob
    },
    requiresFreshPalette:()=>true,
    dispose(){if(disposed)return closing;disposed=true;controller.abort();signal?.removeEventListener('abort',abort);
      closing=(async()=>{
        while(busy)await nextTask()
        try{await engine?.dispose()}finally{engine=null;filter?.dispose();composer.dispose();figure.dispose();grade.dispose();releaseEMVolumeRenderer(scene,renderer);renderer.dispose();release()}
      })();return closing},
    tiles:nx*ny,
  }
}
