import * as THREE from 'three'
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'

/** Capture the same studio used by raster Photo mode, as a linear equirect map. */
export function traceEnvironment(renderer, scene, settings) {
  const width=256,height=128, data=new Float32Array(width*height*4)
  const ambient=new THREE.Color(0,0,0)
  scene.traverseVisible(o=>{if(o.isAmbientLight)ambient.add(o.color.clone().multiplyScalar(o.intensity))})
  if(settings.studioEnvironment) {
    const previous=renderer.getRenderTarget(), tone=renderer.toneMapping
    const cube=new THREE.WebGLCubeRenderTarget(128,{type:THREE.HalfFloatType})
    const target=new THREE.WebGLRenderTarget(width,height,{type:THREE.FloatType})
    const room=new RoomEnvironment(), capture=new THREE.CubeCamera(.1,100,cube)
    const material=new THREE.ShaderMaterial({toneMapped:false,uniforms:{map:{value:cube.texture}},
      vertexShader:'varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }',
      fragmentShader:`uniform samplerCube map; varying vec2 vUv;
        void main(){float theta=(vUv.x-.5)*6.28318530718; float phi=(1.-vUv.y)*3.14159265359;
        gl_FragColor=textureCube(map,vec3(sin(phi)*sin(theta),cos(phi),sin(phi)*cos(theta)));}`})
    const quad=new FullScreenQuad(material)
    try {
      renderer.toneMapping=THREE.NoToneMapping
      capture.update(renderer,room);renderer.setRenderTarget(target);quad.render(renderer)
      renderer.readRenderTargetPixels(target,0,0,width,height,data)
    } finally {renderer.setRenderTarget(previous);renderer.toneMapping=tone;quad.dispose();material.dispose();room.dispose();cube.dispose();target.dispose()}
  }
  for(let i=0;i<data.length;i+=4) {
    data[i]=data[i]*(settings.studioEnvironmentIntensity??1)+ambient.r
    data[i+1]=data[i+1]*(settings.studioEnvironmentIntensity??1)+ambient.g
    data[i+2]=data[i+2]*(settings.studioEnvironmentIntensity??1)+ambient.b;data[i+3]=1
  }
  const texture=new THREE.DataTexture(data,width,height,THREE.RGBAFormat,THREE.FloatType)
  texture.mapping=THREE.EquirectangularReflectionMapping;texture.needsUpdate=true
  return texture
}
