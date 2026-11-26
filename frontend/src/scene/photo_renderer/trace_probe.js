import * as THREE from 'three'
import {FullScreenQuad} from 'three/addons/postprocessing/Pass.js'
// Gather exact pixels into a tiny diagnostic buffer, without averaging away
// noise. This is opt-in, at doubling sample counts, after the GPU fence signals.
export function createTraceProbe(renderer,size=32){
  const target=new THREE.WebGLRenderTarget(size,size,{type:THREE.FloatType,depthBuffer:false})
  const material=new THREE.ShaderMaterial({depthTest:false,depthWrite:false,toneMapped:false,uniforms:{source:{value:null},grid:{value:size}},
    vertexShader:'void main(){gl_Position=vec4(position.xy,0.,1.);}',
    fragmentShader:`uniform sampler2D source;uniform float grid;
      void main(){ivec2 dims=textureSize(source,0);ivec2 p=ivec2(gl_FragCoord.xy*vec2(dims)/grid);gl_FragColor=texelFetch(source,min(p,dims-1),0);}`})
  const quad=new FullScreenQuad(material)
  return {read(texture){
    const previous=renderer.getRenderTarget(),pixels=new Float32Array(size*size*4)
    try{material.uniforms.source.value=texture;renderer.setRenderTarget(target);quad.render(renderer);renderer.readRenderTargetPixels(target,0,0,size,size,pixels);return pixels}
    finally{renderer.setRenderTarget(previous)}
  },dispose(){target.dispose();quad.dispose();material.dispose()}}
}
