import {test,expect} from '@playwright/test'

// Optional real native-GPU check. Only generic graphics primitives; no documents
// or jobs. The API owns nadoc-optix-* scratch and kills its exact worker PID on
// DELETE, cancellation, expiry or server teardown (including test failure).
// No downloads/captures outside Playwright's automatically cleaned output.
test('OptiX exports changed EM fields through one persistent native worker',async({page})=>{
  test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit optional native GPU check')
  test.setTimeout(180000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  page.on('requestfailed',r=>!(/\/progress$/.test(r.url())&&r.failure()?.errorText==='net::ERR_ABORTED')&&errors.push(`${r.method()} ${r.url()}: ${r.failure()?.errorText}`))
  await page.route('**/optix-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/optix-fixture')
  const large=process.env.NADOC_TEST_TRACE_LARGE==='1'
  const result=await page.evaluate(async ({large,size,samples})=>{
    const raw=[],uploads=[],stats=[],fetchOriginal=window.fetch
    window.fetch=async(...args)=>{
      if(String(args[0]).endsWith('/frame'))uploads.push(Number(args[1]?.headers?.['X-NADOC-Upload-Bytes'])||args[1]?.body?.size||0)
      const response=await fetchOriginal(...args)
      if(String(args[0]).endsWith('/frame')&&response.ok){
        stats.push(JSON.parse(response.headers.get('X-NADOC-Render-Stats')))
        const pixels=new Float32Array(await response.clone().arrayBuffer());let red=0,blue=0,min=Infinity,max=-Infinity
        for(let i=0;i<pixels.length;i+=4){min=Math.min(min,pixels[i],pixels[i+1],pixels[i+2]);max=Math.max(max,pixels[i],pixels[i+1],pixels[i+2]);if(pixels[i]>pixels[i+1]+.1&&pixels[i]>pixels[i+2]+.1)red++;if(pixels[i+2]>pixels[i]+.1)blue++}
        raw.push({red,blue,min,max})
      }
      return response
    }
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100)
    const {addTraceGraphics}=await import('/e2e/helpers/trace_graphics_fixture.js')
    const disposeGraphics=addTraceGraphics(THREE,scene,large?18000:512)
    camera.position.z=8
    const renderer=new THREE.WebGLRenderer({alpha:true});renderer.setSize(96,96)
    const surface=new THREE.Mesh(new THREE.SphereGeometry(.7,12,8),new THREE.MeshStandardMaterial({color:0xcccccc,metalness:1,roughness:.1}))
    surface.position.z=-1;scene.add(surface)
    const overlay=createEMFieldOverlay(scene),data={shape:[2,2,2],lower_nm:[-1,-1,0],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:Array(8).fill(100),outside:Array(8).fill(true)}
    const options={mode:'volume',minimum:0,dotSize:16,opacity:1}
    overlay.show(data,options)
    const cloud=scene.getObjectByName('experimental-em-field').children.find(o=>o.isPoints);cloud.material.opacity=1
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    mode.activate();mode.setPathTracing(true);mode.setPathTraceSamples(samples);mode.setPathTraceExportBackend('optix')
    const progress=[]
    const session=mode.beginFrameSession(size,size,{onProgress:p=>progress.push(p)})
    try{
      const capture=async()=>{
        const start=performance.now(),canvas=await session.renderFrameToCanvas(),pixels=canvas.getContext('2d').getImageData(0,0,size,size).data
        let red=0,blue=0
        for(let i=0;i<pixels.length;i+=4){if(pixels[i]>pixels[i+1]+15&&pixels[i]>pixels[i+2]+15)red++;if(pixels[i+2]>pixels[i]+15)blue++}
        return {red,blue,ms:performance.now()-start}
      }
      const red=await capture()
      overlay.show({...data,intensity:Array(8).fill(.2)},options);cloud.material.opacity=1
      const blue=await capture()
      return {red,blue,raw,uploads,stats,samples,progress:progress.filter((p,i,a)=>JSON.stringify(p)!==JSON.stringify(a[i-1])),instances:large?18000:512}
    }finally{await session.dispose();mode.deactivate();overlay.dispose();disposeGraphics();renderer.dispose();window.fetch=fetchOriginal}
  },{large,size:large?64:Number(process.env.NADOC_TEST_TRACE_SIZE??1024),samples:large?4:Number(process.env.NADOC_TEST_TRACE_SAMPLES??512)})
  console.log('OPTIX_BACKEND_CHECK',JSON.stringify(result))
  // Short fixtures can finish between native progress polls. Require both
  // returned float images and completed sample progress; the long default
  // fixture additionally exercises intermediate native progress.
  expect(result.raw).toHaveLength(2)
  expect(result.progress.filter(p=>p.stage==='tracing'&&p.samples===result.samples).length).toBeGreaterThanOrEqual(2)
  if(!process.env.NADOC_TEST_TRACE_SAMPLES)expect(result.progress.some(p=>p.native&&p.samples>0)).toBe(true)
  expect(result.progress.some(p=>p.stage==='denoise')).toBe(true)
  expect(result.red.red).toBeGreaterThan(10);expect(result.blue.blue).toBeGreaterThan(10)
  expect(result.blue.red).toBeLessThan(result.red.red)
  expect(result.stats[0].compact_em).toBe(true)
  expect(result.stats[1].scene_reused).toBe(true)
  expect(result.stats[1].em_updated).toBe(true)
  expect(result.stats[1].em_clouds).toBe(1)
  expect(result.uploads[1]).toBeLessThan(result.uploads[0]/10)
  if(large)expect(result.uploads[0]).toBeGreaterThan(128*1048576)
  expect(errors).toEqual([])
})
