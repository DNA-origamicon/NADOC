import {test,expect} from '@playwright/test'

// GPU image fixtures only. No documents, API writes, downloads or disk images.
// Browser disposal and the standard reporter/global teardown own all cleanup.
test('denoising reduces noise, preserves alpha/thin color edges and matches tiled output',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/denoise-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/denoise-check')
  const result=await page.evaluate(async()=>{
    const T=await import('/node_modules/three/build/three.module.js')
    const {FullScreenQuad}=await import('/node_modules/three/examples/jsm/postprocessing/Pass.js')
    const {createTraceDenoiser,traceDenoiseTile}=await import('/src/scene/photo_renderer/trace_denoise.js')
    const renderer=new T.WebGLRenderer(),filter=createTraceDenoiser(renderer),w=65,h=49
    const material=new T.MeshBasicMaterial({toneMapped:false,depthTest:false,depthWrite:false,blending:T.NoBlending}),quad=new FullScreenQuad(material)
    const truth=new Float32Array(w*h*4),raw=truth.slice();let seed=1729
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const i=(y*w+x)*4,color=x===32?[1.5,.01,.01]:x<32?[.12,.55,.9]:[.12,.9,.25]
      for(let k=0;k<3;k++){
        seed=(Math.imul(seed,1664525)+1013904223)>>>0
        truth[i+k]=color[k];raw[i+k]=color[k]*(.75+.5*seed/4294967296)
      }
      truth[i+3]=raw[i+3]=y===0?0:y===1?.25:1
    }
    const textures=[]
    const source=(data,width,height)=>{
      const t=new T.DataTexture(data,width,height,T.RGBAFormat,T.FloatType);t.needsUpdate=true;textures.push(t)
      return target=>{renderer.setRenderTarget(target);material.map=t;quad.render(renderer)}
    }
    const read=target=>{const p=new Float32Array(target.width*target.height*4);renderer.readRenderTargetPixels(target,0,0,target.width,target.height,p);return p}
    try{
      const draw=source(raw,w,h),full=read(filter.render(draw,w,h,'full'))
      filter.render(()=>{throw new Error('Unchanged image should reuse the cached filter')},w,h,'full')
      let rawError=0,filteredError=0,alphaError=0,lineRed=0,seamError=0
      for(let i=0;i<raw.length;i+=4){
        alphaError=Math.max(alphaError,Math.abs(full[i+3]-raw[i+3]))
        if(i/(4*w)<4)continue
        for(let k=0;k<3;k++){rawError+=(raw[i+k]-truth[i+k])**2;filteredError+=(full[i+k]-truth[i+k])**2}
      }
      for(let y=4;y<h;y++)lineRed+=full[(y*w+32)*4]/(h-4)
      const compareTiles=(input,expected,key)=>{
        for(let y=0;y<2;y++)for(let x=0;x<2;x++){
          const t=traceDenoiseTile(x,y,w,h,33,25,6),data=new Float32Array(t.width*t.height*4)
          for(let j=0;j<t.height;j++)data.set(input.subarray(((t.y+j)*w+t.x)*4,((t.y+j)*w+t.x+t.width)*4),j*t.width*4)
          const tile=read(filter.render(source(data,t.width,t.height),t.width,t.height,`${key}:${x}:${y}`))
          for(let j=0;j<t.coreHeight;j++)for(let i=0;i<t.coreWidth;i++)for(let k=0;k<4;k++){
            seamError=Math.max(seamError,Math.abs(tile[((j+t.cropY)*t.width+i+t.cropX)*4+k]-expected[((j+t.top)*w+i+t.left)*4+k]))
          }
        }
      }
      compareTiles(raw,full,'color')
      // Same chromaticity, radically different HDR radiance: compressed
      // color alone must not bleed bright reflections into their neighbours.
      const hdr=new Float32Array(w*h*4)
      for(let i=0;i<w*h;i++){const scale=i%w<32?30:3;hdr.set([scale,scale*.5,scale*.1,1],i*4)}
      const hdrOut=read(filter.render(source(hdr,w,h),w,h,'hdr'));let hdrError=0
      for(let i=0;i<hdr.length;i++)hdrError=Math.max(hdrError,Math.abs(hdrOut[i]-hdr[i]))
      // Weak achromatic silhouettes, including diagonal and stair-step edges.
      // Unlike the saturated red line above, their color distance is small.
      const lines=new Float32Array(w*h*4),linePixels=[]
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){
        const line=x===12||x===20||x===21||y===12||x===y||x===Math.floor(y/2)+35||Math.abs(Math.hypot(x-47,y-29)-8)<.55
        const value=line?.5:.6;lines.set([value,value,value,1],(y*w+x)*4)
        if(line&&x>3&&x<w-4&&y>3&&y<h-4)linePixels.push((y*w+x)*4)
      }
      // A lone dark sample is noise, not a connected contour.
      const isolated=(35*w+28)*4;lines.set([.5,.5,.5,1],isolated)
      const linesOut=read(filter.render(source(lines,w,h),w,h,'lines'))
      const contrastRetention=linePixels.reduce((s,i)=>s+(.6-linesOut[i])/.1,0)/linePixels.length
      compareTiles(lines,linesOut,'contour')
      const bright=lines.map((v,i)=>i%4===3?v:1.2-v)
      const brightOut=read(filter.render(source(bright,w,h),w,h,'bright'))
      const brightRetention=linePixels.reduce((s,i)=>s+(brightOut[i]-.6)/.1,0)/linePixels.length
      return {contrastRetention,brightRetention,isolatedResidual:(.6-linesOut[isolated])/.1,hdrError,rmseRatio:Math.sqrt(filteredError/rawError),alphaError,lineRed,seamError,finite:full.every(Number.isFinite),runs:filter.runs}
    }finally{filter.dispose();textures.forEach(t=>t.dispose());quad.dispose();material.dispose();renderer.dispose()}
  })
  console.log('DENOISE_GPU',JSON.stringify(result))
  expect(result.rmseRatio).toBeLessThan(.6);expect(result.alphaError).toBe(0)
  expect(result.lineRed).toBeGreaterThan(1.35);expect(result.seamError).toBeLessThan(1e-5)
  expect(result.contrastRetention).toBeGreaterThan(.85);expect(result.isolatedResidual).toBeLessThan(.5)
  expect(result.brightRetention).toBeGreaterThan(.85)
  expect(result.finite).toBe(true);expect(result.runs).toBe(12);expect(result.hdrError).toBeLessThan(1e-5);expect(errors).toEqual([])
})
