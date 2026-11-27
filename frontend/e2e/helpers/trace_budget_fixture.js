import * as THREE from 'three'
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js'
import {compareTraceImages} from '../../src/scene/photo_renderer/trace_metrics.js'
import {traceSnapshot} from '../../src/scene/photo_renderer/path_trace_snapshot.js'

/** Quality/time experiment, no documents or authoring. Each trial starts with
 * zero accumulated samples. Timed through GPU completion of denoise + ACES/sRGB
 * presentation, including native upload/HTTP/download. Quality readback/scoring
 * follows the timed interval. Reference uses this same backend without denoise. */
export async function measureTraceBudget({scene,camera,renderer,settings,width=1280,height=720,backend='webgl',budgetMs=200,referenceSamples=256,counts=[1,2,4,8,16,32],repeats=3,onMeasurement=()=>{}}){
  const create=backend==='optix'?(await import('../../src/scene/photo_renderer/path_trace_optix.js')).createOptixTraceEngine:
    (await import('../../src/scene/photo_renderer/path_trace_engine.js')).createTraceEngine
  renderer.setSize(width,height,false);renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1
  const gl=renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info')
  const adapter=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)
  if(/swiftshader|llvmpipe|software/i.test(adapter))throw new Error('Quality/time benchmark requires a hardware browser GPU')
  const input=new THREE.WebGLRenderTarget(width,height,{type:THREE.FloatType,depthBuffer:false,stencilBuffer:false})
  const output=new OutputPass();output.renderToScreen=true
  // An independently rasterized primary-visibility mask keeps empty background
  // from making the foreground error look artificially small. Same disposable
  // geometry as the tracer, including expanded instances; one-pixel edge halo.
  const maskPixels=new Uint8Array(width*height*4),mask=new Uint8Array(width*height)
  const snapshot=traceSnapshot(scene,camera,height),maskScene=new THREE.Scene(),maskTarget=new THREE.WebGLRenderTarget(width,height)
  const maskMaterial=new THREE.MeshBasicMaterial({color:0xffffff,toneMapped:false,side:THREE.DoubleSide})
  const previousTarget=renderer.getRenderTarget(),clear=renderer.getClearColor(new THREE.Color()),alpha=renderer.getClearAlpha()
  try{
    maskScene.add(snapshot.root);maskScene.overrideMaterial=maskMaterial;renderer.setRenderTarget(maskTarget);renderer.setClearColor(0,0);renderer.clear();renderer.render(maskScene,camera)
    renderer.readRenderTargetPixels(maskTarget,0,0,width,height,maskPixels)
    for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(maskPixels[(y*width+x)*4+3]){
      for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)if(x+dx>=0&&x+dx<width&&y+dy>=0&&y+dy<height)mask[(y+dy)*width+x+dx]=1
    }
  }finally{renderer.setRenderTarget(previousTarget);renderer.setClearColor(clear,alpha);snapshot.dispose();maskTarget.dispose();maskMaterial.dispose()}
  const foregroundPixels=mask.reduce((s,v)=>s+v,0)
  if(!foregroundPixels)throw new Error('No traced geometry is visible in the benchmark camera')
  const start=performance.now();let engine
  async function render(samples,denoise,capture){
    const begin=performance.now();engine.reset(camera.clone(),width,height,2)
    while(engine.samples<samples||!engine.ready()){
      if(performance.now()-begin>180000)throw new Error('Bounded quality benchmark timed out rendering one frame')
      if(engine.ready()&&engine.samples<samples)await engine.advance(samples)
      if(!engine.ready())await new Promise(r=>setTimeout(r,0))
    }
    engine.draw(input,{denoise});output.render(renderer,null,input);gl.finish()
    const ms=performance.now()-begin,diagnostics={...engine.diagnostics}
    let pixels
    if(capture){pixels=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels)}
    return {ms,diagnostics,pixels}
  }
  const normalized=bytes=>Float32Array.from(bytes,v=>v/255)
  try{
    engine=await create({scene,camera:camera.clone(),renderer,settings,width,height,viewHeight:height,tileCount:2})
    const prepareMs=performance.now()-start
    await render(1,true,false);const coldReadyMs=performance.now()-start
    const trials=[]
    for(const samples of counts){
      const times=[];let image,diagnostics
      for(let i=0;i<repeats;i++){
        const result=await render(samples,true,i===0);times.push(result.ms);diagnostics=result.diagnostics
        if(result.pixels)image=result.pixels
      }
      const row={samples,timesMs:times,medianMs:[...times].sort((a,b)=>a-b)[Math.floor(times.length/2)],maxMs:Math.max(...times),diagnostics}
      trials.push({...row,pixels:image});onMeasurement(row)
    }
    const reference=await render(referenceSamples,false,true),truth=normalized(reference.pixels)
    const results=trials.map(({pixels,...row})=>{
      const image=normalized(pixels);let squared=0
      for(let i=0;i<mask.length;i++)if(mask[i])for(let k=0;k<3;k++)squared+=(image[i*4+k]-truth[i*4+k])**2
      return {...row,quality:{...compareTraceImages(image,truth,{width,peak:1}),foregroundRmse:foregroundPixels?Math.sqrt(squared/(3*foregroundPixels)):null}}
    })
    const within=results.filter(r=>r.maxMs<=budgetMs)
    return {backend,adapter,width,height,budgetMs,triangles:engine.triangles,foregroundFraction:foregroundPixels/(width*height),prepareMs,coldReadyMs,referenceSamples,referenceMs:reference.ms,
      metricDomain:'ACES/sRGB display RGB, peak=1; finite same-backend raw reference; quality readback/scoring excluded from timed display delivery',
      results,bestWithinBudget:within.length?within.reduce((a,b)=>a.quality.rmse<b.quality.rmse?a:b):null,
      deadlineMet:within.length>0,denoise:true}
  }finally{await engine?.dispose();input.dispose();output.dispose()}
}

export function budgetOpticalScene({instances=0}={}){
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1280/720,.1,1000)
  camera.position.set(0,15,95);camera.lookAt(0,0,0);camera.updateMatrixWorld()
  const material=new THREE.MeshStandardMaterial({color:0xffce65,metalness:1,roughness:.16}),geometry=new THREE.SphereGeometry(15,48,32)
  for(const x of [-16,16]){const mesh=new THREE.Mesh(geometry,material);mesh.position.x=x;scene.add(mesh)}
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(120,100),new THREE.MeshStandardMaterial({color:0x337799,roughness:.65}));floor.rotation.x=-Math.PI/2;floor.position.y=-17;scene.add(floor)
  let dense
  if(instances){
    dense=new THREE.InstancedMesh(new THREE.SphereGeometry(.3,12,8),new THREE.MeshStandardMaterial({roughness:.4}),instances)
    const matrix=new THREE.Matrix4(),color=new THREE.Color()
    for(let i=0;i<instances;i++){matrix.makeTranslation((i%150-74.5)*.45,-16+Math.floor(i/9000)*.75,(Math.floor(i/150)%60-29.5)*.45);dense.setMatrixAt(i,matrix);dense.setColorAt(i,color.setHSL((i%17)/17,.7,.5))}
    scene.add(dense)
  }
  scene.add(new THREE.AmbientLight(0xffffff,.12));const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(-30,45,50);scene.add(key)
  const settings={studioEnvironment:true,studioEnvironmentIntensity:1.2,bgColor:'#101520',bgType:'solid'}
  return {scene,camera,settings,dispose(){dense?.geometry.dispose();dense?.material.dispose();geometry.dispose();material.dispose();floor.geometry.dispose();floor.material.dispose()}}
}
