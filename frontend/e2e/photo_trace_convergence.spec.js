import {test,expect} from '@playwright/test'

// Generic planar graphics, never a NADOC structure. No API writes, documents,
// jobs or downloads. All pixel buffers stay in browser memory. Standard global
// teardown/reporter remove the isolated bridge credential and test reports.
test('live tracing converges without persistent dark speckles on a glossy surface',async({page})=>{
  test.setTimeout(180000)
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/trace-convergence-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/trace-convergence-check')
  const result=await page.evaluate(async()=>{
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createTracePreview}=await import('/src/scene/photo_renderer/path_trace_preview.js')
    const {createTraceEngine}=await import('/src/scene/photo_renderer/path_trace_engine.js')
    const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-1,1,1,-1,.1,100)
    camera.position.z=5;camera.updateMatrixWorld()
    // Infinite-looking plane, parallel camera and constant illumination: every
    // interior pixel has the same radiance. Spatial variance measures noise.
    const surface=new THREE.Mesh(new THREE.PlaneGeometry(4,4),new THREE.MeshPhysicalMaterial({color:0x3399dd,roughness:.25,metalness:.25,clearcoat:1,clearcoatRoughness:.15}))
    // Same compiler used by the editor's opaque instance materials.
    surface.material.onBeforeCompile=(await import('/src/scene/instance_alpha.js')).instanceAlphaOnBeforeCompile
    scene.add(surface,new THREE.AmbientLight(0xffffff,1))
    const renderer=new THREE.WebGLRenderer();renderer.setSize(64,64);document.body.append(renderer.domElement)
    const settings={pathTracing:true,pathTraceSamples:128,studioEnvironment:false,bgColor:'#000000',bgType:'solid'}
    let engine
    const preview=createTracePreview({scene,camera,renderer,settings,isActive:()=>true,load:async()=>async options=>engine=await createTraceEngine(options)})
    const pass=preview.pass({render(){renderer.render(scene,camera)}});pass.renderToScreen=true
    const measurements=[];let opaque16,denoised16
    function measure(){
      const pixels=engine.readPixels(),values=[]
      for(let y=8;y<56;y++)for(let x=8;x<56;x++)values.push(pixels[(y*64+x)*4+2])
      const mean=values.reduce((a,b)=>a+b,0)/values.length
      const cv=Math.sqrt(values.reduce((sum,v)=>sum+(v-mean)**2,0)/values.length)/mean
      return {samples:engine.samples,mean,cv,nonfinite:values.filter(v=>!Number.isFinite(v)).length,dark:values.filter(v=>v<mean*.5).length}
    }
    try{
      for(const target of [16,128]){
        settings.pathTraceSamples=target
        const deadline=performance.now()+120000
        while(performance.now()<deadline){
          pass.render(renderer)
          const status=preview.getStatus()
          if(status.error)throw new Error(status.error)
          if(status.samples>=target&&engine.ready())break
          await new Promise(requestAnimationFrame)
        }
        if(engine?.samples<target)throw new Error('Preview did not converge before deadline')
        measurements.push(measure());if(target===16){
          opaque16=engine.readPixels();denoised16=new Float32Array(64*64*4)
          renderer.readRenderTargetPixels(engine.denoisedTarget(),0,0,64,64,denoised16)
        }
      }
      // An even transparent sample count must expose the latest ping-pong
      // image, not the previous odd sample. Fresh engines share PCG seeds.
      const transparent=await createTraceEngine({renderer,scene,camera,width:64,height:64,viewHeight:64,
        settings:{...settings,bgType:'transparent'},tileCount:4})
      try{
        const deadline=performance.now()+60000
        while(transparent.samples<16 || !transparent.ready()){
          if(performance.now()>deadline)throw new Error('Transparent convergence timed out')
          transparent.advance(16);await new Promise(requestAnimationFrame)
        }
        const pixels=transparent.readPixels();let maxDifference=0
        for(let y=8;y<56;y++)for(let x=8;x<56;x++)for(let k=0;k<3;k++){
          const i=(y*64+x)*4+k;maxDifference=Math.max(maxDifference,Math.abs(pixels[i]-opaque16[i]))
        }
        if(maxDifference>1e-4)throw new Error(`Even alpha accumulation differs from opaque reference: ${maxDifference}`)
      }finally{transparent.dispose()}
      const reference=engine.readPixels();let rawError=0,filteredError=0
      for(let y=8;y<56;y++)for(let x=8;x<56;x++)for(let k=0;k<3;k++){
        const i=(y*64+x)*4+k;rawError+=(opaque16[i]-reference[i])**2;filteredError+=(denoised16[i]-reference[i])**2
      }
      measurements[0].denoiseRmseRatio=Math.sqrt(filteredError/rawError)
      return measurements
    }finally{preview.stop();surface.geometry.dispose();surface.material.dispose();renderer.dispose()}
  })
  console.log('TRACE_CONVERGENCE',JSON.stringify(result))
  expect(result[0].denoiseRmseRatio).toBeLessThan(.6)
  expect(result[1].nonfinite).toBe(0)
  expect(result[1].cv).toBeLessThan(.06)
  expect(result[1].dark).toBe(0)
  expect(result[1].cv).toBeLessThan(result[0].cv*.6)
  expect(errors).toEqual([])
})
