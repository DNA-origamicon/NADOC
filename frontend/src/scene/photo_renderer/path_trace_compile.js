import * as THREE from 'three'

/** Compile the same fullscreen shader variant used by PathTracingRenderer.
 * KHR_parallel_shader_compile lets the UI keep drawing/status polling while
 * the driver compiles. Do not hold the live renderer's target across an await. */
export async function compileTraceMaterial({renderer,material,camera,target,signal,onStatus=()=>{}}){
  signal?.throwIfAborted()
  onStatus({stage:'compile',label:'Compiling GPU tracing shader…',fraction:null})
  // compileAsync does not call material.onBeforeRender; the tracer uses it to
  // select fog/background/DOF defines immediately before its first draw.
  material.setDefine('CAMERA_TYPE',camera.isEquirectCamera?2:camera.projectionMatrix.elements[15]>0?1:0)
  material.onBeforeRender()
  const geometry=new THREE.PlaneGeometry(2,2),scene=new THREE.Scene()
  scene.add(new THREE.Mesh(geometry,material))
  const view=new THREE.OrthographicCamera(-1,1,1,-1,0,1),previous=renderer.getRenderTarget()
  let compilation
  try{
    try{renderer.setRenderTarget(target);compilation=renderer.compileAsync(scene,view)}
    finally{renderer.setRenderTarget(previous)}
    await compilation
    signal?.throwIfAborted()
  }finally{geometry.dispose()}
}
