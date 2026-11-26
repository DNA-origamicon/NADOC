import * as THREE from 'three'
import {FullScreenQuad} from 'three/addons/postprocessing/Pass.js'

// Two edge-stopping à-trous passes, strides 1 and 2, radius 2 each.
// This is a spatial reconstruction of beauty RGB, not a physical estimator or
// a temporal/geometry-guided denoiser. Never feed it back into accumulation.
export const TRACE_DENOISE_HALO=6

/** Core tiles plus real neighbouring pixels: no filter clamping at tile seams. */
export function traceDenoiseTile(x,y,width,height,tileWidth,tileHeight,halo=0){
  const left=x*tileWidth,top=y*tileHeight,w=Math.min(tileWidth,width-left),h=Math.min(tileHeight,height-top)
  const ox=Math.max(0,left-halo),oy=Math.max(0,top-halo)
  return {x:ox,y:oy,width:Math.min(width,left+w+halo)-ox,height:Math.min(height,top+h+halo)-oy,
    cropX:left-ox,cropY:top-oy,coreWidth:w,coreHeight:h,left,top}
}

export function createTraceDenoiser(renderer){
  const targets=Array.from({length:3},()=>new THREE.WebGLRenderTarget(1,1,{
    type:THREE.FloatType,format:THREE.RGBAFormat,minFilter:THREE.NearestFilter,magFilter:THREE.NearestFilter,depthBuffer:false,stencilBuffer:false,
  }))
  const material=new THREE.ShaderMaterial({
    toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending,
    uniforms:{map:{value:null},rawMap:{value:null},stride:{value:1}},
    vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}`,
    fragmentShader:`
      uniform sampler2D map,rawMap;uniform float stride;varying vec2 vUv;
      vec3 edgeColor(vec3 c){c=max(c,vec3(0.));return c/(1.+max(c.r,max(c.g,c.b)));}
      float brightness(vec3 c){return log(1.+dot(max(c,vec3(0.)),vec3(.2126,.7152,.0722)));}
      float kernel(int i){return i==0?6.:abs(i)==1?4.:1.;}
      float lineEvidence(float c,float a,float b,float n,float m){
        // A connected contour has support along its tangent and contrast
        // across it. Accept a plateau on one side (two-pixel lines/step edges).
        // An isolated bright/dark noise sample has no tangential support.
        if((n-c)*(m-c)<0.)return 0.;
        return max(abs(n-c),abs(m-c))-4.*max(abs(a-c),abs(b-c));
      }
      void main(){
        ivec2 size=textureSize(map,0),p=clamp(ivec2(vUv*vec2(size)),ivec2(0),size-1);
        vec4 center=texelFetch(map,p,0);
        if(center.a<=0.){gl_FragColor=center;return;}
        vec4 original=texelFetch(rawMap,p,0);
        vec3 guide=edgeColor(original.rgb),sum=vec3(0.);float total=0.;
        for(int y=-2;y<=2;y++)for(int x=-2;x<=2;x++){
          ivec2 q=clamp(p+ivec2(vec2(x,y)*stride),ivec2(0),size-1);
          vec4 c=texelFetch(map,q,0);
          // Never use the first pass's blurred colors to decide where edges
          // are: that progressively widens and erases narrow contours.
          vec4 raw=stride==1.?c:texelFetch(rawMap,q,0);
          vec3 delta=edgeColor(raw.rgb)-guide;
          float lightDelta=brightness(raw.rgb)-brightness(original.rgb);
          // Preserve silhouette coverage exactly, and reject neighbours across
          // alpha edges. HDR compression is used only for weights, never RGB.
          float weight=kernel(x)*kernel(y)*exp(-dot(delta,delta)/.045-lightDelta*lightDelta/.02-abs(c.a-center.a)*80.);
          sum+=weight*c.rgb;total+=weight;
        }
        vec3 filtered=sum/max(total,1e-20);
        if(stride>1.){
          float l[9];
          for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++){
            vec4 raw=texelFetch(rawMap,clamp(p+ivec2(x,y),ivec2(0),size-1),0);
            // Missing transparent coverage must not invent a line guide.
            l[(y+1)*3+x+1]=brightness(mix(original.rgb,raw.rgb,min(raw.a,1.)));
          }
          float c=l[4];
          float evidence=max(max(lineEvidence(c,l[3],l[5],l[1],l[7]),lineEvidence(c,l[1],l[7],l[3],l[5])),
            max(lineEvidence(c,l[0],l[8],l[2],l[6]),lineEvidence(c,l[2],l[6],l[0],l[8])));
          // Rasterized curves also contain 135-degree joins, not just straight
          // horizontal/vertical/diagonal runs. Reuse the same eight neighbours.
          float ring[8];ring[0]=l[5];ring[1]=l[2];ring[2]=l[1];ring[3]=l[0];
          ring[4]=l[3];ring[5]=l[6];ring[6]=l[7];ring[7]=l[8];
          for(int i=0;i<8;i++)evidence=max(evidence,lineEvidence(c,ring[i],ring[(i+3)%8],ring[(i+2)%8],ring[(i+6)%8]));
          // Restore coherent fine detail only; this is not a global sharpening
          // pass, so it cannot overshoot radiance or create ringing halos.
          filtered=mix(filtered,original.rgb,smoothstep(.02,.055,evidence));
        }
        gl_FragColor=vec4(filtered,original.a);
      }`,
  })
  const filter=new FullScreenQuad(material)
  const copy=new FullScreenQuad(new THREE.MeshBasicMaterial({toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending}))
  let cached=null,runs=0,disposed=false
  return {
    render(drawRaw,width,height,key){
      if(disposed)throw new Error('Denoiser disposed.')
      if(renderer.getContext().isContextLost())throw new Error('GPU context lost while denoising.')
      if(cached===key&&targets[0].width===width&&targets[0].height===height)return targets[2]
      const previous=renderer.getRenderTarget()
      const resized=!runs||targets[0].width!==width||targets[0].height!==height
      const shaderError=renderer.debug.onShaderError;let failure=''
      renderer.debug.onShaderError=(gl,program)=>{failure=gl.getProgramInfoLog(program)||'Shader compilation failed'}
      try{
        for(const target of targets)target.setSize(width,height)
        drawRaw(targets[0])
        material.uniforms.rawMap.value=targets[0].texture
        for(let i=0;i<2;i++){
          material.uniforms.map.value=targets[i].texture;material.uniforms.stride.value=2**i
          renderer.setRenderTarget(targets[i+1]);filter.render(renderer)
        }
        if(failure)throw new Error(`Denoising failed: ${failure}`)
        if(resized){
          const gl=renderer.getContext(),code=gl.getError()
          if(gl.isContextLost()||code!==gl.NO_ERROR)throw new Error(`GPU denoising could not allocate or render this image (${code}). Disable Denoise path tracing to reduce GPU memory use.`)
        }
        cached=key;runs++;return targets[2]
      }finally{renderer.debug.onShaderError=shaderError;renderer.setRenderTarget(previous)}
    },
    draw(source,target){
      const previous=renderer.getRenderTarget()
      try{renderer.setRenderTarget(target);copy.material.map=source.texture;copy.render(renderer)}finally{renderer.setRenderTarget(previous)}
    },
    get runs(){return runs},
    dispose(){if(disposed)return;disposed=true;targets.forEach(t=>t.dispose());filter.dispose();material.dispose();copy.dispose();copy.material.dispose()},
  }
}
