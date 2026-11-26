import * as THREE from 'three'
import {createTraceEngine} from '../../src/scene/photo_renderer/path_trace_engine.js'
import {createTracePreview} from '../../src/scene/photo_renderer/path_trace_preview.js'
import {compareTraceImages} from '../../src/scene/photo_renderer/trace_metrics.js'

// Optical graphics benchmark, not an authored NADOC structure. Bare reflective
// spheres with a colored rough surface, no EM data, no molecular document/API.
export async function runTraceBenchmark({width=1280,height=720,samples=128,motionSeconds=4,instances=0,bvhOptions,denoise=true,capture=false}={}){
  const renderer=new THREE.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(width,height);document.body.append(renderer.domElement)
  const gl=renderer.getContext(),extension=gl.getExtension('WEBGL_debug_renderer_info')
  const adapter=extension?gl.getParameter(extension.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,width/height,.1,1000)
  camera.position.set(0,15,95);camera.lookAt(0,0,0)
  const material=new THREE.MeshStandardMaterial({color:0xffce65,metalness:1,roughness:.16})
  const geometry=new THREE.SphereGeometry(15,48,32)
  for(const x of [-16,16]){const mesh=new THREE.Mesh(geometry,material);mesh.position.x=x;scene.add(mesh)}
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(120,100),new THREE.MeshStandardMaterial({color:0x337799,roughness:.65}));floor.rotation.x=-Math.PI/2;floor.position.y=-17;scene.add(floor)
  // Optional dense optical stress scene: generic colored spheres, not DNA or
  // a saved NADOC structure. Measures BVH traversal beyond a two-sphere toy.
  let dense=null
  if(instances){
    dense=new THREE.InstancedMesh(new THREE.SphereGeometry(.3,12,8),new THREE.MeshStandardMaterial({roughness:.4}),instances)
    const matrix=new THREE.Matrix4(),color=new THREE.Color()
    for(let i=0;i<instances;i++){
      matrix.makeTranslation((i%150-74.5)*.45,-16+Math.floor(i/9000)*.75,(Math.floor(i/150)%60-29.5)*.45)
      dense.setMatrixAt(i,matrix);dense.setColorAt(i,color.setHSL((i%17)/17,.7,.5))
    }
    scene.add(dense)
  }
  scene.add(new THREE.AmbientLight(0xffffff,.12))
  const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(-30,45,50);scene.add(key)
  const settings={pathTracing:true,pathTraceDenoise:denoise,pathTraceSamples:1,studioEnvironment:true,studioEnvironmentIntensity:1.2,bgColor:'#101520',bgType:'solid'}
  let engine
  const preview=createTracePreview({scene,camera,renderer,settings,isActive:()=>true,load:async()=>async options=>engine=await createTraceEngine({...options,bvhOptions})})
  preview.setMetricsEnabled(true)
  const pass=preview.pass({render(){renderer.render(scene,camera)}});pass.renderToScreen=true
  const tick=()=>new Promise(requestAnimationFrame)
  async function settle(target){
    settings.pathTraceSamples=target
    const deadline=performance.now()+180000
    while(performance.now()<deadline){
      pass.render(renderer)
      const status=preview.getStatus();if(status.error)throw new Error(status.error)
      if(status.samples>=target&&engine.ready()){pass.render(renderer);return}
      await tick()
    }
    throw new Error('Trace benchmark timed out')
  }
  try{
    const images=[],filtered=[],captures={},checkpoints=[],start=performance.now()
    for(const n of [...new Set([1,8,32,samples])].filter(n=>n<=samples)){
      await settle(n);images.push(engine.readPixels())
      const out=engine.denoisedTarget(),pixels=new Float32Array(width*height*4)
      renderer.readRenderTargetPixels(out,0,0,width,height,pixels);filtered.push(pixels)
      if(capture&&n===32){
        engine.draw(null);captures.raw=renderer.domElement.toDataURL()
        engine.draw(null,{denoise:true});captures.denoised=renderer.domElement.toDataURL()
      }
      checkpoints.push({samples:n,ms:performance.now()-start,status:preview.getStatus()})
    }
    const reference=images.at(-1)
    const errors=images.map((pixels,i)=>({samples:checkpoints[i].samples,...compareTraceImages(pixels,reference,{width,peak:1})}))
    const denoisedErrors=filtered.map((pixels,i)=>({samples:checkpoints[i].samples,...compareTraceImages(pixels,reference,{width,peak:1})}))
    preview.setMetricsEnabled(false)
    // Warm throughput separates sampling from compilation, readback and
    // diagnostic probes. Offline cadence exercises the shared export engine.
    const throughputSamples=Math.min(samples,32),throughput={samples:throughputSamples}
    engine.reset(camera.clone(),width,height,Math.max(4,Math.ceil(Math.max(width,height)/256)))
    let timed=performance.now();await settle(throughputSamples);throughput.previewMs=performance.now()-timed
    engine.reset(camera.clone(),width,height,2);timed=performance.now()
    while(engine.samples<throughputSamples || !engine.ready()){
      if(performance.now()-timed>120000)throw new Error('Offline throughput timed out')
      engine.advance(throughputSamples);await new Promise(resolve=>setTimeout(resolve,0))
    }
    throughput.offlineMs=performance.now()-timed
    const orbitStart=performance.now()
    while(performance.now()-orbitStart<motionSeconds*1000){
      const angle=(performance.now()-orbitStart)/1000*.22
      camera.position.set(95*Math.sin(angle),15,95*Math.cos(angle));camera.lookAt(0,0,0)
      pass.render(renderer);await tick()
    }
    const moving=preview.getStatus()
    await settle(Math.min(samples,32))
    return {adapter,width,height,instances,triangles:engine.triangles,emSamples:engine.emSamples,referenceSamples:samples,
      metricDomain:'linear HDR RGB, PSNR peak=1; luminance SSIM in non-overlapping 8x8 windows. Finite-sample reference, not ground truth.',
      checkpoints,errors,denoisedErrors,denoise,captures,throughput,moving,settled:preview.getStatus()}
  }finally{preview.stop();dense?.geometry.dispose();dense?.material.dispose();geometry.dispose();material.dispose();floor.geometry.dispose();floor.material.dispose();renderer.dispose();renderer.domElement.remove()}
}
