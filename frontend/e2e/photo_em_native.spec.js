import {test,expect} from '@playwright/test'

// Generic display primitives only. No molecular documents, jobs, or downloads.
// All render scratch belongs to the API lease/lifespan; finally and API shutdown
// release workers on failure. Standard Playwright reporter cleans test outputs.
test('compact EM transport matches legacy native pixels and scales to dense clouds',async({page})=>{
  test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit native GPU check')
  test.setTimeout(180000)
  await page.route('**/em-native-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/em-native-check')
  const result=await page.evaluate(async()=>{
    const T=await import('/node_modules/.vite/deps/three.js')
    const {traceSnapshot}=await import('/src/scene/photo_renderer/path_trace_snapshot.js')
    const {nativeTracePayload}=await import('/src/scene/photo_renderer/path_trace_native_payload.js')
    const {nativeJSONSize}=await import('/src/scene/photo_renderer/path_trace_native_upload.js')
    const {requestOptix}=await import('/src/scene/photo_renderer/path_trace_errors.js')
    const {createNativeSession}=await import('/src/scene/photo_renderer/path_trace_native_session.js')
    const scene=new T.Scene(),camera=new T.PerspectiveCamera(45,1,.1,100);camera.position.z=8
    const geometry=new T.BufferGeometry(),material=new T.PointsMaterial({size:2,opacity:.24})
    const cloud=new T.Points(geometry,material);cloud.userData.emSamples=true;scene.add(cloud)
    const receiver=new T.Mesh(new T.SphereGeometry(.8,24,16),new T.MeshStandardMaterial({color:0xcccccc,metalness:.7,roughness:.15}))
    receiver.position.z=-1;scene.add(receiver)
    const environment=new T.DataTexture(new Float32Array([.05,.05,.05,1]),1,1,T.RGBAFormat,T.FloatType)
    const lease=await createNativeSession(),measurements=[]
    const frame={width:96,height:96,samples:16,camera:{matrix:camera.matrixWorld.toArray(),projection:camera.projectionMatrix.toArray(),orthographic:false}}
    async function render(payload){
      camera.updateMatrixWorld(true);frame.camera.matrix=camera.matrixWorld.toArray()
      const start=performance.now(),response=await requestOptix(`/${lease.id}/frame`,{...payload,...frame})
      return {pixels:new Float32Array(await response.arrayBuffer()),ms:performance.now()-start,stats:JSON.parse(response.headers.get('X-NADOC-Render-Stats'))}
    }
    try{
      let comparison
      for(const count of [1000,10000]){
        const positions=new Float32Array(count*3),colors=new Float32Array(count*3)
        for(let i=0;i<count;i++){
          positions.set([(i%25-12)*.12,(Math.floor(i/25)%20-9.5)*.12,Math.floor(i/500)*.04],i*3)
          colors.set(i%2?[1,.02,0]:[0,.02,1],i*3)
        }
        geometry.setAttribute('position',new T.BufferAttribute(positions,3));geometry.setAttribute('color',new T.BufferAttribute(colors,3))
        const start=performance.now(),compact=traceSnapshot(scene,camera,96,{compactEM:true}),prepareMs=performance.now()-start
        try{
          const payload=nativeTracePayload(compact,environment,scene,{bgColor:'#000000'})
          const rendered=await render(payload)
          const updated=await render({reuse_scene:true,emitters:payload.emitters})
          measurements.push({count,prepareMs,bytes:nativeJSONSize(payload),cold:rendered.stats,warm:updated.stats})
          if(count===1000){
            const start=performance.now(),legacy=traceSnapshot(scene,camera,96)
            try{
              const legacyPrepareMs=performance.now()-start,oldPayload=nativeTracePayload(legacy,environment,scene,{bgColor:'#000000'})
              const old=await render(oldPayload)
              let max=0,sum=0
              for(let i=0;i<old.pixels.length;i++){const d=Math.abs(old.pixels[i]-rendered.pixels[i]);max=Math.max(max,d);sum+=d*d}
              comparison={max,rmse:Math.sqrt(sum/old.pixels.length),legacyBytes:nativeJSONSize(oldPayload),legacyPrepareMs}
            }finally{legacy.dispose()}
          }
        }finally{compact.dispose()}
      }
      const cleared=await render({reuse_scene:true,emitters:[]})
      receiver.visible=false
      geometry.setAttribute('position',new T.Float32BufferAttribute([0,0,0],3))
      geometry.setAttribute('color',new T.Float32BufferAttribute([1,.2,.1],3))
      material.opacity=1;material.size=10
      const dot=traceSnapshot(scene,camera,96,{compactEM:true})
      try{
        const dto=nativeTracePayload(dot,environment,scene,{bgColor:'#000000'})
        const original=await render(dto)
        dto.emitters[0].power=new Float32Array([.3,.06,.03])
        const normalized=await render({...dto})
        let markerDifference=0
        for(let i=0;i<original.pixels.length;i++)markerDifference=Math.max(markerDifference,Math.abs(original.pixels[i]-normalized.pixels[i]))
        const plane=new T.Mesh(new T.PlaneGeometry(6,6),new T.MeshStandardMaterial({color:0xffffff,roughness:1}))
        scene.add(plane);cloud.position.set(2.7,0,2)
        environment.image.data.set([0,0,0,1]);frame.samples=512
        const lit=traceSnapshot(scene,camera,96,{compactEM:true})
        try{
          const lighting=nativeTracePayload(lit,environment,scene,{bgColor:'#000000'})
          const emitter=lighting.emitters[0]
          emitter.power=new Float32Array([.3,.3,.3]);emitter.radii.fill(.08)
          emitter.power.fill(0)
          const dark=await render(lighting)
          emitter.power.fill(.3)
          const small=await render({reuse_scene:true,emitters:lighting.emitters})
          emitter.radii.fill(.16)
          const large=await render({reuse_scene:true,emitters:lighting.emitters})
          emitter.power=new Float32Array([.6,.6,.6])
          const doubled=await render({reuse_scene:true,emitters:lighting.emitters})
          const energy=image=>{let sum=0;for(let y=32;y<64;y++)for(let x=32;x<64;x++)sum+=image.pixels[(y*96+x)*4];return sum/1024}
          return {measurements,comparison,capabilities:lease.capabilities,cleared:cleared.stats,
            normalization:{markerDifference,dark:energy(dark),small:energy(small)-energy(dark),large:energy(large)-energy(dark),doubled:energy(doubled)-energy(dark),attributes:doubled.stats}}
        }finally{lit.dispose();plane.geometry.dispose();plane.material.dispose()}
      }finally{dot.dispose()}
    }finally{await lease.close();geometry.dispose();material.dispose();receiver.geometry.dispose();receiver.material.dispose();environment.dispose()}
  })
  console.log('EM_NATIVE_SCALING',JSON.stringify(result))
  expect(result.measurements).toHaveLength(2)
  expect(result.measurements[0].bytes).toBeLessThan(result.comparison.legacyBytes/10)
  // Identical deterministic sampling; tolerate float32 normal rounding.
  expect(result.comparison.rmse).toBeLessThan(.0001)
  for(const row of result.measurements){expect(row.warm.scene_reused).toBe(true);expect(row.warm.em_clouds).toBe(1);expect(row.warm.em_updates.unchanged).toBe(1)}
  expect(result.cleared.em_clouds).toBe(0)
  expect(result.normalization.markerDifference).toBeLessThan(.00001)
  expect(result.normalization.small).toBeGreaterThan(.00001)
  expect(result.normalization.large/result.normalization.small).toBeCloseTo(1,1)
  expect(result.normalization.dark).toBeLessThan(.000001)
  // Power changes alter MIS probabilities; allow 3% Monte Carlo error in the
  // 32x32 receiver mean at 512 samples, rather than demanding pixel identity.
  expect(Math.abs(result.normalization.doubled/result.normalization.large/2-1)).toBeLessThan(.03)
  expect(result.normalization.attributes.em_updates.attributes).toBe(1)
})
