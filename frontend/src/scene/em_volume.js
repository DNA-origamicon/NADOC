import * as THREE from 'three'
import {normalizeEMColors,emColorRGB} from './em_colors.js'
import {prepareVolumeCells} from './em_volume_data.js'
import {volumeVertex,volumeFragment} from './em_volume_shader.js'
import {volumeViewKey} from './em_volume_cache.js'

export function updateVolumeColors(mesh,options){
 const colors=normalizeEMColors(options),u=mesh.material.uniforms,data=u.palette.value.image.data
 for(let i=0;i<256;i++){const value=colors.colorMinimum*(colors.maximum/colors.colorMinimum)**(i/255);data.set([...emColorRGB(value,colors),1],i*4)}
 u.palette.value.needsUpdate=true;u.colorLow.value=colors.colorMinimum;u.colorHigh.value=colors.maximum
 // Include transfer settings in output/cache fingerprints, independently of GL uniforms.
 mesh.userData.emVolumeColors=JSON.stringify(colors)
}
/** One instanced hull per retained tetrahedron. Hulls only bound ray intervals;
 * they are never drawn as colored surfaces or exported into a tracing BVH. */
export function createEMVolume(result,grid,options={}){
 const cells=prepareVolumeCells(result,grid,options.minimum??3)
 if(!cells.count)return []
 const geometry=new THREE.InstancedBufferGeometry()
 geometry.setAttribute('position',new THREE.Float32BufferAttribute(new Float32Array(36),3))
 geometry.setAttribute('corner',new THREE.Float32BufferAttribute([0,1,2,0,3,1,0,2,3,1,3,2],1))
 for(const [name,array]of Object.entries(cells.arrays))geometry.setAttribute(name,new THREE.InstancedBufferAttribute(array,name.startsWith('p')?3:4))
 geometry.instanceCount=cells.count;geometry.boundingBox=cells.bounds;geometry.boundingSphere=cells.bounds.getBoundingSphere(new THREE.Sphere())
 const palette=new THREE.DataTexture(new Float32Array(1024),256,1,THREE.RGBAFormat,THREE.FloatType)
 palette.minFilter=palette.magFilter=THREE.LinearFilter
 const integrationMaterial=new THREE.ShaderMaterial({vertexShader:volumeVertex,fragmentShader:volumeFragment,
  uniforms:{sceneDepth:{value:null},palette:{value:palette},inverseProjection:{value:new THREE.Matrix4()},cameraWorld:{value:new THREE.Matrix4()},viewportSize:{value:new THREE.Vector2()},cutoff:{value:options.minimum??3},colorLow:{value:.1},colorHigh:{value:100},weight:{value:1}},
  transparent:true,depthWrite:false,depthTest:false,side:THREE.BackSide,toneMapped:false,
  blending:THREE.CustomBlending,blendEquation:THREE.AddEquation,blendSrc:THREE.OneFactor,blendDst:THREE.OneFactor})
 const material=new THREE.ShaderMaterial({
  uniforms:{...integrationMaterial.uniforms,volumeMap:{value:null},opacity:{value:1}},
  vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}',
  fragmentShader:`uniform sampler2D volumeMap;uniform float opacity;varying vec2 vUv;
   void main(){gl_FragColor=texture2D(volumeMap,vUv)*opacity;
   #include <colorspace_fragment>
   }`,
  transparent:true,depthWrite:false,depthTest:false,toneMapped:false,
  blending:THREE.CustomBlending,blendEquation:THREE.AddEquation,blendSrc:THREE.OneFactor,blendDst:THREE.OneFactor})
 const screenGeometry=new THREE.PlaneGeometry(2,2)
 screenGeometry.boundingBox=cells.bounds;screenGeometry.boundingSphere=geometry.boundingSphere
 const mesh=new THREE.Mesh(screenGeometry,material);mesh.frustumCulled=false;mesh.renderOrder=1000;mesh.raycast=()=>{}
 mesh.userData.emSmooth=true;mesh.userData.emVolume=true;mesh.userData.emOpacity=1;mesh.userData.emCellCount=cells.count
 // Renderer-owned adaptive data, not document state or a serialized scene tag.
 mesh.emVolumeCells=cells.arrays
 updateVolumeColors(mesh,options)
 const hull=new THREE.Mesh(geometry,integrationMaterial),integrationScene=new THREE.Scene();hull.frustumCulled=false;integrationScene.add(hull)
 const targets=new WeakMap(),ownedTargets=new Set()
 const disposeEntry=entry=>{entry.depth.dispose();entry.image.dispose();ownedTargets.delete(entry)}
 mesh.releaseEMVolumeRenderer=renderer=>{const entry=targets.get(renderer);if(entry){disposeEntry(entry);targets.delete(renderer)}}
 mesh.onBeforeRender=(renderer,renderScene,camera)=>{
  // Figure normal/depth passes must not see the screen-space composition quad.
  if(renderScene.overrideMaterial){screenGeometry.setDrawRange(0,0);return}
  let scene=mesh;while(scene.parent)scene=scene.parent
  const previous=renderer.getRenderTarget(),size=previous?new THREE.Vector2(previous.width,previous.height):renderer.getDrawingBufferSize(new THREE.Vector2())
  let entry=targets.get(renderer)
  if(!entry){entry={depth:new THREE.WebGLRenderTarget(size.x,size.y,{depthTexture:new THREE.DepthTexture(size.x,size.y)}),image:new THREE.WebGLRenderTarget(size.x,size.y,{type:THREE.HalfFloatType,depthBuffer:false}),key:null};targets.set(renderer,entry);ownedTargets.add(entry)}
  const key=volumeViewKey(scene,camera,size,palette,renderer)
  if(entry.key!==key){
   const {depth,image}=entry
   if(depth.width!==size.x||depth.height!==size.y){depth.setSize(size.x,size.y);image.setSize(size.x,size.y)}
   const hidden=[],background=scene.background,autoClear=renderer.autoClear,viewport=renderer.getViewport(new THREE.Vector4()),scissor=renderer.getScissor(new THREE.Vector4()),scissorTest=renderer.getScissorTest(),clearColor=renderer.getClearColor(new THREE.Color()),clearAlpha=renderer.getClearAlpha()
   scene.traverseVisible(o=>{if(o.userData.emVolume){hidden.push(o);o.visible=false}})
   try{
    scene.background=null;renderer.autoClear=true;renderer.setRenderTarget(depth);renderer.setScissorTest(false);renderer.render(scene,camera)
    const u=integrationMaterial.uniforms;u.sceneDepth.value=depth.depthTexture;u.viewportSize.value.copy(size)
    u.inverseProjection.value.copy(camera.projectionMatrixInverse);u.cameraWorld.value.copy(camera.matrixWorld);u.weight.value=1
    renderer.setRenderTarget(image);renderer.setClearColor(0x000000,0);renderer.render(integrationScene,camera)
    entry.key=key;mesh.userData.emVolumeIntegrations=(mesh.userData.emVolumeIntegrations??0)+1
   }finally{
    hidden.forEach(o=>o.visible=true);scene.background=background;renderer.autoClear=autoClear;renderer.setClearColor(clearColor,clearAlpha)
    renderer.setRenderTarget(previous);renderer.setViewport(viewport);renderer.setScissor(scissor);renderer.setScissorTest(scissorTest)
   }
  }
  material.uniforms.volumeMap.value=entry.image.texture;material.uniforms.opacity.value=material.opacity
 }
 mesh.onAfterRender=()=>screenGeometry.setDrawRange(0,Infinity)
 material.addEventListener('dispose',()=>{palette.dispose();geometry.dispose();integrationMaterial.dispose();for(const entry of ownedTargets)disposeEntry(entry)})

 return [mesh]
}
/** Camera-volume composition shared by every tracing backend, before grading.
 * The depth pass uses the original scene's display shaders and opaque surfaces.
 * This intentionally models emitted camera radiance, not multiple scattering. */
export function drawEMVolumes(renderer,scene,camera,target){
 const volumes=[];scene.traverseVisible(o=>{if(o.userData.emVolume&&o.material.visible&&o.material.opacity>0)volumes.push(o)})
 if(!volumes.length)return
 const projection=new THREE.Scene(),previous=renderer.getRenderTarget(),autoClear=renderer.autoClear
 for(const source of volumes){const mesh=new THREE.Mesh(source.geometry,source.material);mesh.frustumCulled=false;mesh.onBeforeRender=source.onBeforeRender;mesh.onAfterRender=source.onAfterRender;projection.add(mesh)}
 try{renderer.setRenderTarget(target);renderer.autoClear=false;renderer.render(projection,camera)}
 finally{renderer.setRenderTarget(previous);renderer.autoClear=autoClear;projection.clear()}
}

export function releaseEMVolumeRenderer(scene,renderer){
 scene.traverse(o=>o.releaseEMVolumeRenderer?.(renderer))
}
