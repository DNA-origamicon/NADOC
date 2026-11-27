import * as THREE from 'three'
import {FullScreenQuad} from 'three/addons/postprocessing/Pass.js'
import {traceSnapshot} from './path_trace_snapshot.js'
import {traceEnvironment} from './path_trace_environment.js'

/** Experimental export-only bridge. Float readback preserves the shared NADOC
 * tone mapping, figure effects and grading in the existing WebGL composer. */
export async function createWebGPUTraceEngine(options){
  const {createWebGPUExport}=await import('../../../trace_webgpu/index.js')
  const backend=await createWebGPUExport(),renderer=options.renderer
  let image=null,width=options.width,height=options.height,triangles=0,emSamples=0
  const quad=new FullScreenQuad(new THREE.MeshBasicMaterial({toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending}))
  async function update({scene,camera,settings,viewHeight,signal}){
    const snapshot=traceSnapshot(scene,camera,viewHeight),projection=new THREE.Scene()
    let env
    try{
      projection.add(snapshot.root);env=traceEnvironment(renderer,scene,settings);projection.environment=env
      projection.environmentRotation.copy(scene.environmentRotation)
      projection.background=settings.bgType==='transparent'?null:new THREE.Color(settings.bgColor??'#ffffff')
      await backend.update(projection.toJSON(),camera.toJSON(),signal,{smoothEM:snapshot.smoothEM})
      triangles=snapshot.triangles;emSamples=snapshot.emSamples
    }finally{snapshot.dispose();env?.dispose()}
  }
  const api={update,get samples(){return backend.samples},get triangles(){return triangles},get emSamples(){return emSamples},
    get diagnostics(){return {backend:'webgpu',experimental:true}},
    reset(camera,w,h){width=w;height=h;backend.reset(camera.toJSON(),w,h)},
    advance:target=>backend.advance(target),ready:()=>true,
    async prepareDraw(){
      const pixels=await backend.pixels()
      image?.dispose();image=new THREE.DataTexture(pixels,width,height,THREE.RGBAFormat,THREE.FloatType)
      // WebGPU readback rows are top-down; WebGL texture rows are bottom-up.
      image.flipY=true;image.needsUpdate=true;quad.material.map=image
    },
    draw(target){const previous=renderer.getRenderTarget();try{renderer.setRenderTarget(target);quad.render(renderer)}finally{renderer.setRenderTarget(previous)}},
    dispose(){backend.dispose();image?.dispose();quad.dispose();quad.material.dispose()},
  }
  try{await update(options);return api}catch(e){try{api.dispose()}catch(cleanup){console.warn('WebGPU cleanup failed',cleanup)}throw e}
}
